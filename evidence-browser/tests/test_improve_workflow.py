from pathlib import Path

from backend import improve_workflow


AGENTS = Path(__file__).resolve().parents[2]


def project(tmp_path):
    return {"key": "test", "work_dir": str(tmp_path / "csa-work"), "stage": "draft"}


def test_snapshot_marks_answered_and_unanswered_sections_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(improve_workflow.draft_workflow, "snapshot", lambda *a, **k: {
        "sections": [
            {"key": "TIME", "number": "3.4", "title": "Time", "state": "answered"},
            {"key": "DNS", "number": "3.5", "title": "DNS", "state": "not-answered"},
        ]
    })
    result = improve_workflow.snapshot(AGENTS, project(tmp_path))
    assert result["eligible_count"] == 1
    rows = {row["key"]: row for row in result["sections"]}
    assert rows["TIME"]["improve"]["state"] == "not-started"
    assert rows["DNS"]["improve"]["state"] == "unavailable"
    assert rows["DNS"]["improve"]["reason"] == "no answer has reached the working document"


def test_section_reads_current_context_and_pending_proposal(tmp_path, monkeypatch):
    work = tmp_path / "csa-work"
    root = work / "improve" / "TIME"
    root.mkdir(parents=True)
    (root / "context.json").write_text('{"heading":"3.4 Time","answer_text":"Current answer.","document_hash":"sha256:x","provenance":"legacy/unknown","supporting_evidence_ids":["E-001"],"findings":["Missing fallback"],"open_questions":[]}', encoding="utf-8")
    (root / "proposal.json").write_text('{"status":"improve","section_key":"TIME"}', encoding="utf-8")
    monkeypatch.setattr(improve_workflow.draft_workflow, "snapshot", lambda *a, **k: {
        "sections": [{"key": "TIME", "number": "3.4", "title": "Time", "state": "answered", "rating": {"latest": 6.0}}]
    })
    result = improve_workflow.section(AGENTS, project(tmp_path), "TIME")
    assert result["status"] == "OK"
    assert result["current"]["text"] == "Current answer."
    assert result["findings"] == ["Missing fallback"]
    assert result["proposal"]["status"] == "improve"


def test_section_reports_missing_spec_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(improve_workflow.draft_workflow, "snapshot", lambda *a, **k: {"sections": []})
    result = improve_workflow.section(AGENTS, project(tmp_path), "TIME")
    assert result["status"] == "NOT_FOUND"
