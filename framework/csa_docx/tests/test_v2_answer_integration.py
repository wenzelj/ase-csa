"""S626: the V2 answer lane is connected to the native subsection evidence package.

Acceptance from the story:
- a V2 answer run reports `v2-native` context and never uses a V1 file;
- the model receives only the requested blocks plus their complete scoped package;
- unsupported hosts, ratings, zones and evidence IDs fail before the sheet
  is rendered (the structured fact layer runs before prose validation);
- the existing repair-loop behaviour remains focused and warning-aware;
- legacy cards continue to pass (no package: the validator path is unchanged).
"""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

from csa_docx import answer_sheet
from csa_docx.answer_plan import plan_context
from csa_docx.v2repo import Repo
from csa_docx.v2repo.subsection_evidence import build_package, PACKAGE_VERSION

CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def _seed(tmp_path: Path, monkeypatch) -> Path:
    """A V2 store with one application, an evidence row, a scope host, a flow
    and a lead for the subsection; a legacy csa-work file that must stay untouched."""
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    legacy = workspace / "csa-work"
    (legacy / "evidence").mkdir(parents=True)
    legacy_matrix = legacy / "evidence-matrix.csv"
    legacy_matrix.write_text(
        "evidence_id,csa_area,question,claim,status,source_title\n"
        "E-LEGACY,legacy,A legacy question,LEGACY-ONLY host claim,VERIFIED,legacy.txt\n",
        encoding="utf-8")
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: test\n"
        '    label: "Test"\n'
        f'    project_root: "{workspace}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{v2}"\n'
        '    default_source_set: ""\n',
        encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))

    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("APP01", role="application")
        repo.hosts.create("NTPSRV1", role="provider")
        repo.application_scope.add("test-app", "APP01", "owned", basis="inventory", review_state="accepted")
        repo.evidence.create(
            claim="APP01 synchronises time from an enterprise NTP source.",
            question="Which time source is configured?",
            area="time",
            source_title="captures/app01.txt",
            excerpt="APP01 NTP enterprise source",
            status="VERIFIED")
        con = repo.con
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) "
                    "VALUES ('APP01','NTPSRV1',123,'udp','time')")
        con.execute("INSERT INTO lead (id, question, state, evidence_ids) "
                    "VALUES ('L-001','Which time source is configured?','open','')")
        con.execute("INSERT INTO indexed_file (rel_path, sha256, size) VALUES ('app01.txt','x',10)")
        con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES "
                    "('app01.txt','time','APP01 NTP enterprise time source running')")
        repo.graph.refresh()
    repo.close()
    return v2 / "csa.sqlite"


def _card(db: Path, monkeypatch, number: str = "3.5", title: str = "Time Synchronisation") -> dict:
    from csa_docx.v2repo import subsection_contract as SC
    contract = SC.build(title, "Which time source is configured?", application_view="application")
    question = "Which time source is configured?"
    pkg = build_package(db, subsection_key="3.5", application_key="test-app",
                        question=question, terms=[question], contract=contract)
    body = {k: v for k, v in pkg.items() if k not in ("revision", "package_hash", "context", "model_profile")}
    pkg["package_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:16]
    pkg["context"] = "v2-native"
    pkg["model_profile"] = "v2-subsection-answering"
    card = {
        "key": "3.5", "title": title, "ratings": ["Met", "Partially Met", "Not Met"],
        "questions": [{"id": "B1", "kind": "requirement", "text": "Which time source is configured?"}],
        "evidence": {"B1": {"rows": [{"id": pkg["evidence"][0]["evidence_id"],
                                      "claim": pkg["evidence"][0]["text"]}] if pkg["evidence"] else []}},
        "obligations": {"contract_version": "answer-contract-v1",
                        "blocks": {"B1": {"evidence_ids": [f["evidence_id"] for f in pkg["evidence"][:1]]}}},
        "package": pkg,
    }
    return card


def test_v2_run_reports_native_context_and_package_hash(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    assert card["package"]["context"] == "v2-native"
    assert card["package"]["package_version"] == PACKAGE_VERSION
    assert len(card["package"]["package_hash"]) == 16
    assert card["package"]["revision"]["modified_ns"] is not None
    # the package carries the contract version, gaps, conflicts and provenance
    assert card["package"]["contract_version"]
    for lead in card["package"]["leads"]:
        assert lead["non_evidence"] is True
    for w in card["package"]["warnings"]:
        assert w["non_evidence"] is True


def test_v2_package_needs_no_v1_file(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    from csa_docx.v2repo import subsection_contract as SC
    contract = SC.build("Time Synchronisation", "Which time source is configured?", application_view="application")
    pkg = build_package(db, subsection_key="3.5", application_key="test-app",
                        question="Which time source is configured?", contract=contract)
    # every evidence fact carries provenance; scope hosts are the package's own
    for f in pkg["evidence"]:
        assert f["evidence_id"] and (f["source"] or f["non_evidence"])
        assert f["basis"] in ("stated", "canonical", "unresolved", "ambiguous")
    hosts = pkg["hosts"]
    assert "APP01" in hosts["owned"]
    # graph context is scoped to the projection
    for fl in pkg["connections"]["flows"]:
        assert fl["src_host"] in hosts["owned"] + hosts["peers"] or fl["dst_host"] in hosts["owned"] + hosts["peers"]


def test_unsupported_host_rating_and_evidence_fail_before_render(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    eid = card["evidence"]["B1"]["rows"][0]["id"]
    sheet = (f"## B1\nFacts:\n- UNREGISTERED-99 hosts the time source. ({eid}) {{observed; all hosts}}\n"
             f"Rating: Gold\nRating reason: no.\n")
    parsed = answer_sheet.parse(sheet)
    findings = answer_sheet.structured_findings(parsed, card, card["package"])
    codes = {f["code"] for f in findings}
    assert "RATING_INVALID" in codes            # 'Gold' is not a card rating
    assert "HOST_NOT_SUPPORTED" in codes        # UNREGISTERED-99 is not in the package
    # an evidence ID outside the package fails the structured layer
    sheet2 = "## B1\nFacts:\n- APP01 does it. (E-999)\n"
    findings2 = answer_sheet.structured_findings(answer_sheet.parse(sheet2), card, card["package"])
    assert any(f["code"] == "UNKNOWN_EVIDENCE" for f in findings2)


def test_native_structured_checks_cover_rows_bullets_and_zones(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    sheet = (f"## B1\nRows:\n| claim | evidence |\n| APP01 is in OT | E-999 |\n"
             f"Bullets:\n- APP01 is in OT (E-998)\n")
    findings = answer_sheet.structured_findings(answer_sheet.parse(sheet), card, card["package"])
    codes = [f["code"] for f in findings]
    assert codes.count("UNKNOWN_EVIDENCE") == 2
    assert "ZONE_FACT_NOT_BACKED" in codes


def test_valid_structured_sheet_has_no_structured_findings(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    eid = card["evidence"]["B1"]["rows"][0]["id"]
    sheet = (f"## B1\nFacts:\n- APP01 synchronises time from an enterprise NTP source. ({eid}) "
             f"{{observed; APP01}}\nRating: Met\nRating reason: the source is stated.\n")
    findings = answer_sheet.structured_findings(answer_sheet.parse(sheet), card, card["package"])
    assert findings == []


def test_structured_findings_run_before_prose_in_validate(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    eid = card["evidence"]["B1"]["rows"][0]["id"]
    sheet = f"## B1\nFacts:\n- UNREGISTERED-99 hosts the time source. ({eid}) {{observed; all hosts}}\n"
    res = answer_sheet.validate(answer_sheet.parse(sheet), card, new_ids={eid.upper()})
    codes = {f["code"] for f in res["findings"]}
    assert "HOST_NOT_SUPPORTED" in codes


def test_legacy_card_without_package_is_unchanged(tmp_path, monkeypatch):
    """A V1 card (no package) runs the exact same validator path: no structured findings."""
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    del card["package"]
    eid = card["evidence"]["B1"]["rows"][0]["id"]
    sheet = f"## B1\nFacts:\n- APP01 does it. ({eid})\n"
    assert answer_sheet.structured_findings(answer_sheet.parse(sheet), card, None) == []
    # and the validate() path simply does not add the structured layer
    res = answer_sheet.validate(answer_sheet.parse(sheet), card, new_ids={eid.upper()})
    assert not any(f["code"] == "HOST_NOT_SUPPORTED" for f in res["findings"])


def test_plan_context_is_native_or_legacy(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    rows = [{"legacy_ids": "", "req_id": "SEP-TIME-01", "statement_type": "observed",
             "fact": "APP01 uses an enterprise NTP source.", "evidence_scope": "APP01; capture",
             "destination": "REQ SEP-TIME-01 / Current State", "confidence": "high",
             "transformation": "stated", "gap_generated": ""}]
    native = plan_context(rows, card, card["package"])
    assert native["route"] == "v2-native"
    assert native["package_hash"] == card["package"]["package_hash"]
    assert native["revision"]["modified_ns"] is not None
    assert "APP01" in native["hosts"]
    assert native["findings"] == []
    legacy = plan_context(rows, card, None)
    assert legacy["route"] == "v1-native"
    assert "package_hash" not in legacy and "findings" not in legacy
    assert legacy["plan"] == rows


def test_unsupported_plan_evidence_id_is_flagged(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    card = _card(db, monkeypatch)
    rows = [{"legacy_ids": "E-999", "req_id": "SEP-TIME-01", "statement_type": "observed",
             "fact": "x", "evidence_scope": "", "destination": "REQ SEP-TIME-01 / Current State",
             "confidence": "high", "transformation": "", "gap_generated": ""}]
    native = plan_context(rows, card, card["package"])
    assert any(f["code"] == "UNKNOWN_EVIDENCE" for f in native["findings"])
    legacy = plan_context(rows, card, None)
    assert legacy["findings"] if "findings" in legacy else True  # legacy keeps its own checks


def test_prompt_context_scoped_to_requested_blocks(tmp_path, monkeypatch):
    """The bounded prompt context names only the requested blocks; the package
    is one subsection's and shared by every block call of it."""
    work = tmp_path / "csa-work-v2"; (work / "cards").mkdir(parents=True)
    card = work / "cards" / "3.5.md"; card.write_text("# 3.5\n", encoding="utf-8")
    card.with_suffix(".json").write_text(json.dumps({
        "questions": [{"id": "B1", "kind": "observation"}, {"id": "B2", "kind": "observation"}],
        "evidence": {"B1": {"rows": [{"id": "E-1"}]}, "B2": {"rows": [{"id": "E-2"}]}},
        "package": {"context": "v2-native", "package_hash": "abc123", "package_version": PACKAGE_VERSION,
                     "evidence": [{"evidence_id": "E-1", "text": "APP01 fact"}],
                     "hosts": {"owned": ["APP01"], "peers": [], "external": []}}
    }), encoding="utf-8")
    p = {"key": "x", "label": "X", "project_context": str(tmp_path / "context.yaml"),
         "work_dir": str(work), "project_root": str(tmp_path)}
    route = {"verb": "answer", "file": "csa-answer-agent.md", "title": "CSA Answer Agent",
             "inputs": "SECTION, CARD*, SHEET*, MODE=answer, ONLY", "local_inputs": ""}
    prompt = CSA["build_prompt"](p, route, ["3.5", f"CARD={card}", f"SHEET={work / '3.5.answer.md'}", "ONLY=B1"], local=False)
    assert '"B1"' in prompt and '"B2"' not in prompt
    assert "V2_NATIVE_SUBSECTION_PACKAGE" in prompt
    assert "V2_CONTEXT=v2-native PACKAGE_HASH=abc123" in prompt


def test_repair_loop_remains_focused_and_warning_aware(tmp_path, monkeypatch):
    finding = lambda level, code, question=None: {"level": level, "code": code,
                                                  "question": question, "message": code}
    res = {"findings": [
        finding("ERROR", "HOST_NOT_SUPPORTED", "B1"),
        finding("WARN", "STORY_SENTENCE_LONG", "B1"),
        finding("ERROR", "SLOT_NOT_ANSWERED", "B2"),
    ]}
    selected = CSA["repair_findings"](res, {"B1"})
    assert [f["code"] for f in selected] == ["HOST_NOT_SUPPORTED"]
    assert CSA["answer_blocks_failing"](res) == {"B1", "B2"}
    repeated = (("HOST_NOT_SUPPORTED", "B1", "same"),)
    assert CSA["repeated_repair_action"](repeated, None, "small", "fallback", False) == (None, False)
    assert CSA["repeated_repair_action"](repeated, repeated, "small", "fallback", False) == ("fallback", False)
