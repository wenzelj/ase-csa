"""Gap check: every open question in draft/open-questions.md is looked up in the matrix and the index."""
import json

from csa_docx import gap_lookup as gl
from csa_docx import gap_sweep as gs

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
    (tmp_path / "csa-work" / "draft").mkdir(parents=True)
    (tmp_path / "csa-work" / "draft" / "open-questions.md").write_text(OPEN, encoding="utf-8")
    return tmp_path


def test_sweep_writes_affected_sections(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)

    def lookup(workspace, dr_id, text, exclude=()):
        if dr_id == "DR-BAK-B1":
            return {"verdict": "CANDIDATES", "evidence_ids": ["E-510"], "matrix": [], "index": ["E-510"], "searched": "x"}
        if dr_id == "DR-EXECUTIVE_SUMMARY-F01":
            return {"verdict": "ANSWERED", "evidence_ids": ["E-495"], "matrix": ["E-495"], "index": [], "searched": "x"}
        return {"verdict": "NOT_FOUND", "evidence_ids": [], "matrix": [], "index": [], "searched": "x"}
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lookup)
    res = gs.sweep(ws)
    assert res["affected"] == [
        {"number": "3.11", "key": "BAK", "title": "Backup & Recovery", "answered": 0, "candidates": 1},
        {"number": "2.1", "key": "EXECUTIVE_SUMMARY", "title": "Executive Summary", "answered": 1, "candidates": 0}]
    saved = json.loads((ws / "csa-work" / "intake" / "gap-check-latest.json").read_text(encoding="utf-8"))
    assert saved == res and len(saved["questions"]) == 5 and saved["checked_at"]
    assert {q["dr_id"]: q["verdict"] for q in saved["questions"]}["DR-INET-B2"] == "NOT_FOUND"
    only = gs.sweep(ws, section_key="BAK")
    assert [q["dr_id"] for q in only["questions"]] == ["DR-BAK-B1"]


HIT = {"rel_path": "src/IS-REVELOC.pdf", "page_or_location": "line 40", "source_title": "src/IS-REVELOC.pdf",
       "source_version": "", "evidence_excerpt": "MOTPRDLOG103 OT Tetra Log Server WIN2019 (Virtual)"}


def _stateful_run(appended):
    """A matrix that writes a candidate once and reports the same row as a duplicate afterwards."""
    def run(cmd):
        if "lookup" in cmd:
            return {"status": "OK", "matches": []}
        if "search" in cmd:
            return {"status": "OK", "results": [HIT]}
        if "append" in cmd:
            if appended:
                return {"status": "NOTHING_TO_WRITE", "skipped_duplicates": [{"duplicate_of": "E-600"}]}
            appended.append(cmd)
            return {"status": "APPENDED", "written": [{"evidence_id": "E-600"}]}
        return None
    return run


def test_sweep_is_idempotent(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    appended: list = []
    monkeypatch.setattr(gl, "_run", _stateful_run(appended))
    first = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    second = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    f01 = lambda r: next(q for q in r["questions"] if q["dr_id"] == "DR-EXECUTIVE_SUMMARY-F01")
    assert f01(first)["evidence_ids"] == f01(second)["evidence_ids"] == ["E-600"]
    assert len(appended) == 1


def test_sweep_skips_rejected(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setattr(gl, "_run", _stateful_run([]))
    assert {q["dr_id"]: q["verdict"] for q in gs.sweep(ws, "EXECUTIVE_SUMMARY")["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "CANDIDATES"
    (ws / "csa-work" / "evidence-reviews.jsonl").write_text(
        json.dumps({"evidence_id": "E-600", "state": "rejected"}) + "\n", encoding="utf-8")
    again = gs.sweep(ws, "EXECUTIVE_SUMMARY")
    assert {q["dr_id"]: q["verdict"] for q in again["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "NOT_FOUND"
    assert again["affected"] == []


def test_sweep_carries_pending_candidate_by_exact_dr_id(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    matrix = ws / "csa-work" / "evidence-matrix.csv"
    matrix.write_text(
        "evidence_id,csa_area,question,claim,status,review_state\n"
        'E-700,gap_lookup,q,"Possible answer to DR-BAK-B1: the source reads: backup",UNCONFIRMED,pending\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda *args, **kwargs:
                        {"verdict": "NOT_FOUND", "evidence_ids": []})
    result = gs.sweep(ws, "BAK")
    assert result["questions"][0]["verdict"] == "CANDIDATES"
    assert result["questions"][0]["evidence_ids"] == ["E-700"]
    assert result["affected"][0]["candidates"] == 1


def test_csa_has_gap_check_and_resolve_commands():
    import subprocess
    import sys
    from pathlib import Path
    csa = Path(__file__).resolve().parents[3] / "bin" / "csa"
    r = subprocess.run([sys.executable, str(csa), "gap-check", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "open question" in r.stdout
    r = subprocess.run([sys.executable, str(csa), "resolve-gaps", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "resolve-gaps" in r.stdout and "section" in r.stdout
