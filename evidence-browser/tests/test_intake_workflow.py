"""Evidence intake page: the jobs it can start and the snapshot it reads (index, intake record, matrix, gaps, graph)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import commands, intake_workflow
from backend import app as workspace
from backend.models import CommandRequest

AGENTS = Path(__file__).resolve().parents[2]
HEADER = "evidence_id,csa_area,question,claim,status,source_title,source_version,section,page_or_location,evidence_excerpt,inference_reason,confidence,gap_or_action,review_state\n"


def _row(eid: str, status: str = "VERIFIED", claim: str = "a claim", source: str = "src/a.txt") -> str:
    return f'{eid},general_asset_inventory,q,"{claim}",{status},{source},,,line 1,quote,,high,,pending\n'


def _work(tmp_path: Path, rows: list[str] | None = None) -> dict[str, str]:
    work = tmp_path / "csa-work"
    work.mkdir()
    (work / "evidence-matrix.csv").write_text(HEADER + "".join(rows or []), encoding="utf-8")
    return {"key": "tetra-reveloc", "work_dir": str(work), "project_root": str(tmp_path)}


def _record(work: Path, **kw) -> dict:
    rec = {"id": "20261012T030000Z", "built_at_utc": "2026-10-12T03:00:00Z", "matrix_last_id": "E-002",
           "added": [], "changed": [], "removed": [], "unreadable": [], **kw}
    (work / "intake").mkdir(exist_ok=True)
    (work / "intake" / "latest.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


def test_gap_check_and_intake_argv():
    op, argv = commands.build_argv(AGENTS, "tetra-reveloc", "intake", CommandRequest(options={"cli": "evo"}))
    assert argv[3:] == ["intake", "--cli", "evo"] and op.mutation_class == "workspace_write"
    with pytest.raises(HTTPException):
        commands.build_argv(AGENTS, "tetra-reveloc", "intake", CommandRequest(options={"cli": "gpt"}))
    op, argv = commands.build_argv(AGENTS, "tetra-reveloc", "gap_check", CommandRequest(target="3.11"))
    assert argv[3:] == ["gap-check", "3.11"]
    _, argv = commands.build_argv(AGENTS, "tetra-reveloc", "gap_check", CommandRequest())
    assert argv[3:] == ["gap-check"]
    op, argv = commands.build_argv(AGENTS, "tetra-reveloc", "resolve_gaps", CommandRequest(options={"cli": "evo"}))
    assert argv[3:] == ["resolve-gaps", "--latest", "--cli", "evo"]
    assert op.mutation_class == "document_write" and op.lock == "docx" and op.closes_word is True


def _audit(work: Path, *entries: tuple[str, list[str]]) -> None:
    (work / "evidence-matrix-audit.jsonl").write_text(
        "".join(json.dumps({"agent": "x", "context": c, "action": "append", "ids": ids}) + "\n" for c, ids in entries),
        encoding="utf-8")


def test_new_evidence_counts_only_rows_the_agent_appended_for_this_intake(tmp_path):
    project = _work(tmp_path, [_row(f"E-00{i}") for i in range(1, 7)])
    work = Path(project["work_dir"])
    _record(work, carried_from=["20261011T010000Z"])
    _audit(work, ("intake 20261012T030000Z", ["E-003", "E-004"]), ("TETRA/06 REVELOC TETRA", ["E-005"]),
           ("DR-BAK-B1", ["E-006"]), ("intake 20261011T010000Z", ["E-002"]), ("intake 20261001T000000Z", ["E-001"]))
    snap = intake_workflow.snapshot(project)
    assert [r["evidence_id"] for r in snap["matrix"]["added_since_intake"]] == ["E-002", "E-003", "E-004"]
    assert snap["matrix"]["rows"] == 6 and snap["matrix"]["by_status"] == {"VERIFIED": 6}


def test_nothing_new_needs_a_complete_index(tmp_path):
    project = _work(tmp_path)
    work = Path(project["work_dir"])
    db = sqlite3.connect(work / "discovery-index.sqlite")
    db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE files(status TEXT);"
                     "INSERT INTO meta VALUES('built_at_utc','2026-10-12T04:00:00Z'),('complete','0');")
    db.commit(); db.close()
    _record(work)
    assert intake_workflow.snapshot(project)["nothing_new_since"] is None


def test_evidence_jobs_share_one_lock():
    for key in ("ingest", "intake", "gap_check"):
        assert commands.OPERATIONS[key].lock == "evidence", key


def test_snapshot_flags_unreadable(tmp_path):
    project = _work(tmp_path)
    png = {"rel_path": "src/b.png", "ext": ".png", "status": "skipped", "reason": "binary type .png",
           "source_class": "other", "host": None}
    _record(Path(project["work_dir"]), added=[png], unreadable=[png])
    snap = intake_workflow.snapshot(project)
    assert snap["intake"]["unreadable"][0]["reason"] == "binary type .png"


def test_snapshot_lists_only_open_leads_and_counts_terminal_states(tmp_path):
    project = _work(tmp_path, [_row("E-001"), _row("E-002", "NOT_FOUND")])
    intake = Path(project["work_dir"]) / "intake"
    intake.mkdir()
    base = {"qid": "B1", "question": "q", "question_fingerprint": "sha256:q", "source_title": "src/a.txt",
            "source_ref": "src/a.txt", "rel_path": "src/a.txt", "source_version": "v1", "source_class": "other",
            "page_or_location": "line 1", "excerpt": "a sufficiently long source excerpt", "excerpt_hash": "sha256:x",
            "terms": ["source"], "found_at": "2026-10-29T00:00:00Z"}
    leads = [{**base, "lead_id": f"L-{n:06d}", "dr_id": f"DR-X-B{n}"} for n in range(1, 5)]
    (intake / "leads.jsonl").write_text("".join(json.dumps(r) + "\n" for r in leads), encoding="utf-8")
    states = ["not_an_answer", "resolved", "retired"]
    reviews = [{"lead_id": f"L-{n:06d}", "state": state, "evidence_ids": ["E-001"] if state == "resolved" else [],
                "by": "test", "at": "2026-10-29T01:00:00Z", "note": "done"} for n, state in zip(range(2, 5), states)]
    (intake / "leads-reviews.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reviews), encoding="utf-8")
    snap = intake_workflow.snapshot(project)
    assert [(c["lead_id"], c["dr_id"]) for c in snap["open_leads"]] == [("L-000001", "DR-X-B1")]
    assert snap["leads"]["by_state"] == {"open": 1, "not_an_answer": 1, "resolved": 1, "retired": 1}
    assert snap["matrix"]["evidence_rows"] == 1 and snap["matrix"]["not_found"] == 1


def test_snapshot_counts_legacy_candidate_tombstones_but_not_as_evidence(tmp_path):
    candidate = _row("E-001", "UNCONFIRMED", "Possible answer to DR-BAK-B1: the source reads: x").replace(",general_asset_inventory,", ",gap_lookup,", 1)
    project = _work(tmp_path, [candidate, _row("E-002")])
    (Path(project["work_dir"]) / "evidence-reviews.jsonl").write_text(
        json.dumps({"evidence_id": "E-001", "state": "rejected", "note": "migrated to lead L-000001; not an evidence row"}) + "\n",
        encoding="utf-8")
    snap = intake_workflow.snapshot(project)
    assert snap["matrix"]["legacy_candidate_tombstones"] == 1
    assert snap["matrix"]["evidence_rows"] == 1 and snap["matrix"]["by_status"] == {"VERIFIED": 1}


def test_snapshot_without_intake(tmp_path):
    snap = intake_workflow.snapshot(_work(tmp_path))
    assert snap["intake"] is None and snap["gap_check"] is None and snap["agent_summary"] is None
    assert snap["index"] == {"built_at_utc": None, "files_by_status": {}, "complete": False} and snap["stale"] == 0


def test_snapshot_reads_index_gaps_graph_stale_and_summary(tmp_path):
    project = _work(tmp_path, [_row("E-001"), _row("E-002"), _row("E-003")])
    work = Path(project["work_dir"])
    db = sqlite3.connect(work / "discovery-index.sqlite")
    db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE files(status TEXT);"
                     "INSERT INTO meta VALUES('built_at_utc','2026-10-12T04:00:00Z'),('complete','1');"
                     "INSERT INTO files VALUES('indexed'),('indexed'),('skipped');")
    db.commit(); db.close()
    _record(work)
    (work / "intake" / "20261012T030000Z.evidence.md").write_text("# Intake\n- E-003 added\n", encoding="utf-8")
    gaps = {"checked_at": "2026-10-12T05:00:00Z", "section": "", "questions": [], "affected": [{"key": "BAK"}]}
    (work / "intake" / "gap-check-latest.json").write_text(json.dumps(gaps), encoding="utf-8")
    (work / "graph").mkdir()
    (work / "graph" / "nodes.csv").write_text("node_id\nN-001\nN-002\n", encoding="utf-8")
    (work / "graph" / "edges.csv").write_text("edge_id\nR-001\n", encoding="utf-8")
    (work / "draft").mkdir()
    (work / "draft" / "stale.json").write_text(json.dumps({"sections": [{"status": "STALE"}, {"status": "REUSE"}]}),
                                               encoding="utf-8")
    snap = intake_workflow.snapshot(project)
    assert snap["index"] == {"built_at_utc": "2026-10-12T04:00:00Z", "files_by_status": {"indexed": 2, "skipped": 1}, "complete": True}
    assert snap["nothing_new_since"] == "2026-10-12T03:00:00Z"
    assert snap["graph"] == {"nodes": 2, "edges": 1} and snap["stale"] == 1
    assert snap["gap_check"]["affected"] == [{"key": "BAK"}]
    assert snap["agent_summary"]["text"].startswith("# Intake") and snap["agent_summary"]["modified_at"]


def test_review_route_refuses_other_states():
    with pytest.raises(ValidationError):
        workspace.EvidenceReviewRequest(state="accepted", note="x")
    assert workspace.EvidenceReviewRequest(state="rejected", note="not an answer").state == "rejected"


def test_lead_review_route_settles_a_lead_and_evidence_route_refuses_it(tmp_path, monkeypatch):
    project = _work(tmp_path, [_row("E-001")])
    intake = Path(project["work_dir"]) / "intake"
    intake.mkdir()
    lead = {"lead_id": "L-000001", "dr_id": "DR-BAK-B1", "qid": "B1", "question": "q",
            "question_fingerprint": "sha256:q", "source_title": "src/a.txt", "source_ref": "src/a.txt",
            "rel_path": "src/a.txt", "source_version": "v1", "source_class": "other", "page_or_location": "line 1",
            "excerpt": "a sufficiently long source excerpt", "excerpt_hash": "sha256:x", "terms": [],
            "found_at": "2026-10-29T00:00:00Z"}
    (intake / "leads.jsonl").write_text(json.dumps(lead) + "\n", encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text("projects:\n  - key: tetra-reveloc\n    label: \"T\"\n"
                   f"    project_root: \"{tmp_path}\"\n    work_dir: \"{project['work_dir']}\"\n", encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    res = workspace.review_lead("tetra", "L-000001", workspace.LeadReviewRequest(state="not_an_answer", note="not an answer"))
    assert res["status"] == "OK" and res["reviewed"] == ["L-000001"] and res["state"] == "not_an_answer"
    log = (intake / "leads-reviews.jsonl").read_text(encoding="utf-8")
    assert '"not_an_answer"' in log and "L-000001" in log
    assert intake_workflow.snapshot(project)["open_leads"] == []
    with pytest.raises(HTTPException):
        workspace.review_evidence("tetra", "L-000001", workspace.EvidenceReviewRequest(state="rejected"))
    with pytest.raises(HTTPException):
        workspace.review_lead("tetra", "E-001", workspace.LeadReviewRequest(state="not_an_answer"))
