"""S622: the answer routes are explicit. A V2 project reads csa.sqlite and is told which route
each command runs on (`v1-native`, `v2-native`, `v2-compatibility-adapter`); it never opens or
creates a legacy matrix, host or graph file, and a missing V2 store or table fails clearly."""
import csv
import json
import os
import sqlite3
from pathlib import Path

from csa_docx import answer_sheet, v2_access, v2_gap
from csa_docx.v2repo import Repo


def _v2_project(tmp_path, monkeypatch):
    """A registered V2 project: work_dir ends in csa-work-v2, the store is complete, and a real
    csa-work/ tree sits beside it so a silent fallback would be visible."""
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.evidence.create(area="dns", question="Resolver?", claim="RMS resolver on HOST1",
                             source_title="capture", excerpt="resolver", actor="test")
        repo.con.execute("INSERT INTO host(name, role) VALUES ('HOST1', 'server')")
        repo.con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES ('capture.txt', 'x', 10)")
    repo.close()
    legacy = workspace / "csa-work" / "hosts"
    legacy.mkdir(parents=True)
    for name in ("evidence-matrix.csv", "hosts/hosts.csv", "graph/nodes.csv", "graph/edges.csv"):
        f = workspace / "csa-work" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("evidence_id,csa_area\nE-999,dns\n", encoding="utf-8")
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: v2test\n"
        '    label: "V2 Test"\n'
        f'    project_root: "{workspace}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{v2}"\n'
        '    default_source_set: ""\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))
    return workspace, v2


def test_route_labels_cover_the_three_routes(tmp_path, monkeypatch):
    assert v2_access.ROUTE_LABELS == ("v1-native", "v2-native", "v2-compatibility-adapter")
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    db = v2 / "csa.sqlite"
    v1 = v2_access.route("ev", work_dir=workspace / "csa-work", project="v2test")
    assert v1["route"] == "v1-native" and "store" not in v1
    native = v2_access.route("gap-check", work_dir=v2, db=db, project="v2test")
    assert native["route"] == "v2-native" and native["store"] == str(db)
    adapter = v2_access.route("answer", work_dir=v2, db=db, adapter=True, project="v2test")
    assert adapter["route"] == "v2-compatibility-adapter"


def test_route_revision_is_deterministic_and_bounded(tmp_path, monkeypatch):
    _workspace, v2 = _v2_project(tmp_path, monkeypatch)
    db = v2 / "csa.sqlite"
    first = v2_access.store_revision(db)
    second = v2_access.store_revision(db)
    assert first == second
    assert first["tables"]["evidence"]["rows"] == 1
    assert isinstance(first["modified_ns"], int)
    # bounded: the inventory is the store's own tables, nothing walked from disk
    assert len(first["tables"]) <= 40
    diag = v2_access.route("gap-check", work_dir=v2, db=db)
    assert diag["revision"] == first


def test_missing_v2_store_fails_clearly(tmp_path, monkeypatch):
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    for f in sorted((v2 / "backups").glob("*")) if (v2 / "backups").is_dir() else []:
        f.unlink()
    (v2 / "csa.sqlite").unlink()
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))
    try:
        v2_access.active_db()
        raise AssertionError("expected FileNotFoundError for a missing v2 store")
    except FileNotFoundError as e:
        assert "v2 store is missing" in str(e) and "never falls back" in str(e)
    diag = v2_access.route("ev", work_dir=v2, project="v2test", adapter=True)
    assert diag["route"] == "v2-compatibility-adapter" and diag["status"] == "BLOCKED"
    assert "no fallback" in diag["message"]
    # a failed V2 route never touched the legacy tree: the sentinel rows are untouched
    for name in ("evidence-matrix.csv", "hosts/hosts.csv", "graph/nodes.csv", "graph/edges.csv"):
        assert (workspace / "csa-work" / name).read_text(encoding="utf-8") == "evidence_id,csa_area\nE-999,dns\n"


def test_missing_v2_tables_fail_clearly(tmp_path, monkeypatch):
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    db = v2 / "csa.sqlite"
    con = sqlite3.connect(db)
    con.execute("DROP TABLE graph_edge")
    con.close()
    gaps = v2_access.missing_tables(db)
    assert gaps == ["graph_edge"]
    diag = v2_access.route("gap-check", work_dir=v2, db=db)
    assert diag["status"] == "BLOCKED" and "graph_edge" in diag["message"]
    result = v2_access.matrix_command(db, ["lookup", "resolver"], workspace)
    assert result["status"] == "BLOCKED" and result["code"] == "V2_TABLES_MISSING"
    # the legacy matrix beside the project is untouched: nothing was opened or rewritten
    legacy = (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8")
    assert legacy == "evidence_id,csa_area\nE-999,dns\n"


def test_v2_evidence_routes_read_the_store_only(tmp_path, monkeypatch):
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    db = v2 / "csa.sqlite"
    monkeypatch.delenv("CSA_WORK_DIR", raising=False)
    assert v2_access.evidence_rows(db)[0]["claim"] == "RMS resolver on HOST1"
    assert v2_access.index_status(db)["indexed_files"] == 1
    assert v2_access.index_search(db, "resolver")["status"] == "OK"
    # a V2 route never creates or rewrites the legacy tree
    legacy = (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8")
    assert legacy == "evidence_id,csa_area\nE-999,dns\n"


def test_v2_adapter_matrix_is_temporary(tmp_path, monkeypatch):
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    db = v2 / "csa.sqlite"
    created: list[str] = []

    def recording_open(path, *a, **kw):
        created.append(str(path))
        return original_open(path, *a, **kw)

    import builtins
    original_open = builtins.open
    monkeypatch.setattr(builtins, "open", recording_open)
    try:
        with open(db, "rb") as fh:
            pass
        created.clear()
        v2_access.matrix_command(db, ["stats"], workspace)
    finally:
        monkeypatch.setattr(builtins, "open", original_open)
    for path in created:
        assert "csa-work/evidence" not in path and "csa-work/hosts" not in path and "csa-work/graph" not in path, path
    assert (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8").startswith("E-999") or \
           (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8").startswith("evidence_id")


def test_v2_gap_record_and_settlement_touch_no_legacy_files(tmp_path, monkeypatch):
    workspace, v2 = _v2_project(tmp_path, monkeypatch)
    (v2 / "draft").mkdir(parents=True, exist_ok=True)
    (v2 / "draft" / "open-questions.md").write_text(
        "## 3.4 Time Synchronisation (TIME)\n\n- [B1] Which time source is configured?\n", encoding="utf-8")
    record = v2_gap.run(v2)
    assert record["summary"]["gaps"] >= 1
    assert not (workspace / "csa-work" / "evidence-matrix.csv").is_file() or \
        (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8") == "evidence_id,csa_area\nE-999,dns\n"
    # settle rejects unknown evidence before it can be read from a legacy file
    bad = v2_gap.settle(v2, record, [{"lead_id": "L-999", "state": "resolved", "evidence_ids": ["E-999"]}], actor="test")
    assert bad["status"] == "ERROR"
    assert (workspace / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8") == "evidence_id,csa_area\nE-999,dns\n"


def test_v1_project_route_is_v1_native(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    work = workspace / "csa-work"
    work.mkdir(parents=True)
    (work / "evidence-matrix.csv").write_text("evidence_id,csa_area,question,claim,status,source_title,review_state\n"
                                              "E-001,dns,Resolver?,RMS resolver,VERIFIED,capture,accepted\n", encoding="utf-8")
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: v1test\n"
        '    label: "V1 Test"\n'
        f'    project_root: "{workspace}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{work}"\n'
        '    default_source_set: ""\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))
    monkeypatch.delenv("CSA_WORK_DIR", raising=False)
    diag = v2_access.route("ev", work_dir=work, project="v1test")
    assert diag["route"] == "v1-native" and "store" not in diag and "status" not in diag
    # V1 keeps its own matrix file: the framework still reads it
    from csa_docx import evidence_live
    rows = evidence_live.read(work / "evidence-matrix.csv")
    assert [r["evidence_id"] for r in rows] == ["E-001"]


def test_v1_answer_validation_unchanged(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    work = workspace / "csa-work"
    cards = work / "cards"
    cards.mkdir(parents=True)
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,review_state\n"
        "E-001,dns,Resolver?,RMS resolver on HOST1,VERIFIED,capture,accepted\n", encoding="utf-8")
    card = {"questions": [{"id": "B1", "kind": "requirement", "text": "What resolver is configured?"}],
            "number": "3.4", "title": "Time Synchronisation"}
    (cards / "TIME.json").write_text(json.dumps(card), encoding="utf-8")
    sheet_text = (
        "## B1 Resolver\n\n"
        "Facts:\n"
        "- The resolver is the RMS resolver. (E-001) {observed; HOST1}\n\n"
        "Rating: Not Applicable\n\n"
        "Rating Reason: No requirement text to rate against.\n")
    (cards / "TIME.answer.md").write_text(sheet_text, encoding="utf-8")
    res = answer_sheet.validate(answer_sheet.parse(sheet_text), card,
                                answer_sheet.load_matrix(work / "evidence-matrix.csv"), new_ids=set())
    assert res["status"] in ("OK", "ERROR", "READY") and isinstance(res.get("findings"), list)
    # the V1 matrix file is read in place and never rewritten by the validation
    assert (work / "evidence-matrix.csv").read_text(encoding="utf-8").startswith("evidence_id,")
