"""Gap check: every open question in draft/open-questions.md is looked up in the matrix and the index."""
import json

from csa_docx import gap_lookup as gl
from csa_docx import gap_sweep as gs
from csa_docx import leads

OPEN = """# Open questions (draft lane, 2026-10-10 20:56)

## 3.11 Backup & Recovery (BAK)

- [B1] the exact backup product and service could be confirmed by the backup owner.

## 3.17 Internet Access & Communications (Proxy / SMTP) (INET)

- [B2] which hosts actually send SMTP alerts.

## 2.1 Executive Summary (EXECUTIVE_SUMMARY)

- [B1] whether ROKPRDOPS112 is in scope.

## Figure for 2.1 Executive Summary

- [DR-EXECUTIVE_SUMMARY-F01] MOTPRDLOG103: role not recorded

## Figure for 3.4 Time Synchronisation

- [DR-TIME-F01] ROTPRDREV101: time source not known
"""


def test_parse_open_questions():
    qs = gs.parse_open_questions(OPEN)
    got = [(q["number"], q["key"], q["qid"], q["dr_id"]) for q in qs]
    assert got == [("3.11", "BAK", "B1", "DR-BAK-B1"), ("3.17", "INET", "B2", "DR-INET-B2"),
                   ("2.1", "EXECUTIVE_SUMMARY", "B1", "DR-EXECUTIVE_SUMMARY-B1"),
                   ("2.1", "EXECUTIVE_SUMMARY", "F01", "DR-EXECUTIVE_SUMMARY-F01"),
                   ("3.4", "FIGURE-3.4", "F01", "DR-TIME-F01")]
    assert qs[1]["title"] == "Internet Access & Communications (Proxy / SMTP)"
    assert qs[3]["text"] == "MOTPRDLOG103: role not recorded"


def test_parse_skips_malformed():
    text = "## Notes without a number\n\n- [B1] orphan line\n\n## 3.5 DNS (DNS)\n\n- no id here\n- [B3] fallback\n"
    qs = gs.parse_open_questions(text)
    assert [(q["key"], q["qid"]) for q in qs] == [("DNS", "B3")]
    assert gs.parse_open_questions("") == []


def _workspace(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "csa-work" / "draft").mkdir(parents=True)
    (ws / "csa-work" / "draft" / "open-questions.md").write_text(OPEN, encoding="utf-8")
    return ws


def test_sweep_writes_affected_sections(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)

    def lookup(workspace, dr_id, text, exclude=()):
        if dr_id == "DR-BAK-B1":
            return {"verdict": "CANDIDATES", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": ["L-000510"], "searched": "x"}
        if dr_id == "DR-EXECUTIVE_SUMMARY-F01":
            return {"verdict": "ANSWERED", "answer_evidence_ids": ["E-495"], "related_evidence_ids": [], "lead_ids": [], "searched": "x"}
        return {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": [], "searched": "x"}
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lookup)
    res = gs.sweep(ws)
    assert res["affected"] == [
        {"number": "3.11", "key": "BAK", "title": "Backup & Recovery", "answered": 0, "candidates": 1},
        {"number": "2.1", "key": "EXECUTIVE_SUMMARY", "title": "Executive Summary", "answered": 1, "candidates": 0}]
    saved = json.loads((ws / "csa-work" / "intake" / "gap-check-latest.json").read_text(encoding="utf-8"))
    assert saved == res and saved["schema_version"] == 2 and len(saved["questions"]) == 5 and saved["checked_at"]
    candidate = next(q for q in saved["questions"] if q["dr_id"] == "DR-BAK-B1")
    assert candidate["lead_ids"] == ["L-000510"] and candidate["evidence_ids"] == []
    assert {q["dr_id"]: q["verdict"] for q in saved["questions"]}["DR-INET-B2"] == "NOT_FOUND"
    only = gs.sweep(ws, section_key="BAK")
    assert [q["dr_id"] for q in only["questions"]] == ["DR-BAK-B1"]


HIT = {"rel_path": "src/IS-REVELOC.pdf", "page_or_location": "line 40", "source_title": "src/IS-REVELOC.pdf",
       "source_version": "", "evidence_excerpt": "MOTPRDLOG103 OT Tetra Log Server WIN2019 (Virtual)"}


def _stateful_run(appended):
    def run(cmd):
        if "lookup" in cmd:
            return {"status": "OK", "matches": []}
        if "search" in cmd:
            return {"status": "OK", "results": [HIT]}
        if "append" in cmd:
            appended.append(cmd)
        return None
    return run


def test_sweep_is_idempotent(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    appended: list = []
    monkeypatch.setattr(gl, "_run", _stateful_run(appended))
    first = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    second = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    f01 = lambda r: next(q for q in r["questions"] if q["dr_id"] == "DR-EXECUTIVE_SUMMARY-F01")
    assert f01(first)["lead_ids"] == f01(second)["lead_ids"] == ["L-000001"]
    assert not appended
    assert len((ws / "csa-work" / "intake" / "leads.jsonl").read_text().splitlines()) == 1


def test_sweep_skips_terminal_leads(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setattr(gl, "_run", _stateful_run([]))
    assert {q["dr_id"]: q["verdict"] for q in gs.sweep(ws, "EXECUTIVE_SUMMARY")["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "CANDIDATES"
    lead_id = leads.open_leads(ws, "DR-EXECUTIVE_SUMMARY-F01")[0]["lead_id"]
    leads.review(ws, [lead_id], "not_an_answer", "tester", "read")
    again = gs.sweep(ws, "EXECUTIVE_SUMMARY")
    assert {q["dr_id"]: q["verdict"] for q in again["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "NOT_FOUND"
    assert again["affected"] == []


def test_sweep_carries_open_lead_by_exact_dr_id(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-BAK-B1", "B1", "the exact backup product", [HIT])[0]
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda *args, **kwargs:
                        {"verdict": "CANDIDATES", "answer_evidence_ids": [], "related_evidence_ids": [],
                         "lead_ids": [lead_id], "searched": "x"})
    result = gs.sweep(ws, "BAK")
    assert result["questions"][0]["verdict"] == "CANDIDATES"
    assert result["questions"][0]["lead_ids"] == [lead_id]
    assert result["questions"][0]["evidence_ids"] == []
    assert result["affected"][0]["candidates"] == 1


def test_successful_scoped_sweep_retires_only_absent_questions_in_that_section(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    old_bak = leads.add_leads(ws, "DR-BAK-B9", "B9", "old backup question", [HIT])[0]
    other = leads.add_leads(ws, "DR-INET-B9", "B9", "old internet question", [dict(HIT, page_or_location="line 50")])[0]
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda *args, **kwargs:
                        {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [],
                         "lead_ids": [], "searched": "x"})
    result = gs.sweep(ws, "BAK")
    assert result["retired_lead_ids"] == [old_bak]
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [other]


def test_missing_or_malformed_question_input_never_retires_leads(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-BAK-B9", "B9", "old backup question", [HIT])[0]
    source = ws / "csa-work" / "draft" / "open-questions.md"
    source.write_text("## malformed\n\n- [B1] orphan\n", encoding="utf-8")
    assert gs.sweep(ws)["retired_lead_ids"] == []
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [lead_id]
    source.unlink()
    assert gs.sweep(ws)["retired_lead_ids"] == []
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [lead_id]


def test_csa_has_gap_check_and_resolve_commands():
    import subprocess
    import sys
    from pathlib import Path
    csa = Path(__file__).resolve().parents[3] / "bin" / "csa"
    r = subprocess.run([sys.executable, str(csa), "gap-check", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "open question" in r.stdout
    r = subprocess.run([sys.executable, str(csa), "resolve-gaps", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "resolve-gaps" in r.stdout and "section" in r.stdout


def test_the_run_report_counts_what_the_lookup_did():
    results = [
        {"verdict": "NOT_FOUND", "lead_ids": [], "kind": "document", "owners": ["backup service owner"], "related": [], "searches": 12},
        {"verdict": "NOT_FOUND", "lead_ids": [], "kind": "document", "owners": ["backup service owner", "application owner"], "related": ["E-1"], "searches": 12},
        {"verdict": "CANDIDATES", "lead_ids": ["L-000009", "L-000010"], "kind": "system", "owners": [], "related": [], "searches": 4},
    ]
    s = gs.summarise(results)
    assert s["gaps"] == 3 and s["by_kind"] == {"document": 2, "system": 1} and s["searches"] == 28
    assert s["candidates_to_read"] == 2 and s["gaps_with_related_rows"] == 1
    assert s["to_ask"] == {"backup service owner": 2, "application owner": 1}
    text = " ".join(gs.report_lines(s))
    assert "3 open question(s)" in text and "28 search(es)" in text and "backup service owner (2)" in text
