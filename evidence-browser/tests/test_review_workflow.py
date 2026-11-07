from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import commands, review_workflow


def setup(tmp_path):
    root = tmp_path / "project"
    work = root / "csa-work"
    root.mkdir()
    work.mkdir()
    doc = root / "assessment.docx"
    doc.write_bytes(b"document")
    project = {"key": "test", "label": "Test System", "project_root": str(root), "work_dir": str(work)}
    return project, doc


def test_review_operation_is_mutating_locked():
    operation = commands.OPERATIONS["review"]
    assert operation.mutating
    assert operation.lock == "docx"


def test_submit_requires_confirmation(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    class Manager:
        calls = []

        def submit(self, project, operation, request):
            self.calls.append((operation, request))
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.review_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "name": "assessment.docx"})
    monkeypatch.setattr("backend.review_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.review_workflow.word_review.build_review", lambda a, p: {"gate": "ready_for_review", "sha256": "abc"})

    manager = Manager()
    with pytest.raises(HTTPException) as error:
        review_workflow.submit(Path(".agents"), manager, project, "3.1", {"confirmed": False})
    assert error.value.status_code in (409, 422)


def test_submit_records_audit(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    class Manager:
        calls = []

        def submit(self, project, operation, request):
            self.calls.append((operation, request))
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.review_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "name": "assessment.docx"})
    monkeypatch.setattr("backend.review_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.review_workflow.word_review.build_review", lambda a, p: {"gate": "ready_for_review", "sha256": "abc"})

    manager = Manager()
    result = review_workflow.submit(Path(".agents"), manager, project, "3.1", {"confirmed": True})
    assert result["job"]["id"] == "job-1"
    assert manager.calls[0][0] == "review"
    audit_file = Path(project["work_dir"]) / "evidence-browser-audit.jsonl"
    assert "review_requested" in audit_file.read_text()
    assert "3.1" in audit_file.read_text()


def test_submit_blocks_when_document_unavailable(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    class Manager:
        def submit(self, project, operation, request):
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.review_workflow.documents.resolve", lambda p: {"state": "blocked"})
    monkeypatch.setattr("backend.review_workflow.jobs.word_lock", lambda p: None)

    with pytest.raises(HTTPException) as error:
        review_workflow.submit(Path(".agents"), Manager(), project, "3.1", {"confirmed": True})
    assert error.value.status_code == 409


def test_submit_blocks_when_word_locked(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    class Manager:
        def submit(self, project, operation, request):
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.review_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "name": "assessment.docx"})
    monkeypatch.setattr("backend.review_workflow.jobs.word_lock", lambda p: Path("~$locked.docx"))

    with pytest.raises(HTTPException) as error:
        review_workflow.submit(Path(".agents"), Manager(), project, "3.1", {"confirmed": True})
    assert error.value.status_code == 409


def test_outcome_success():
    job = {"state": "succeeded",
           "stdout_tail": '{"verdict":"approved","section_breakdown":[{"key":"3.1","heading":"Sub-process","verdict":"approved","findings":[]}],"breaking":{"area":"none","detail":""}}'}
    outcome = review_workflow.outcome(job)
    assert outcome["state"] == "succeeded"
    assert outcome["review_signoff"] == "approved"
    assert outcome["section_breakdown"][0]["verdict"] == "approved"
    assert outcome["breaking"]["area"] == "none"


def test_outcome_failure():
    job = {"state": "failed", "stdout_tail": "some error", "stderr_tail": "traceback"}
    outcome = review_workflow.outcome(job)
    assert outcome["state"] == "failed"
    assert "failure_reason" in outcome
    assert outcome["failure_reason"]


def test_outcome_cancelled():
    job = {"state": "cancelled"}
    outcome = review_workflow.outcome(job)
    assert outcome["state"] == "cancelled"


def test_latest_no_review_returns_none(tmp_path):
    project, doc = setup(tmp_path)
    result = review_workflow.latest(Path(".agents"), project, "3.1")
    assert result is None


def test_latest_finds_review_job(tmp_path):
    import json
    project, doc = setup(tmp_path)
    ui_jobs = Path(project["work_dir"]) / "ui-jobs"
    job_dir = ui_jobs / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(json.dumps({
        "id": "job-1",
        "operation": "review",
        "project_key": "test",
        "target": "3.1",
        "state": "succeeded",
        "created_at": "2026-10-04T10:00:00Z",
        "finished_at": "2026-10-04T10:02:00Z",
        "exit_code": 0,
    }))

    result = review_workflow.latest(Path(".agents"), project, "3.1")
    assert result is not None
    assert result["job_id"] == "job-1"
    assert result["state"] == "succeeded"
    assert result["section"] == "3.1"


def test_latest_filters_by_operation(tmp_path):
    import json
    project, doc = setup(tmp_path)
    ui_jobs = Path(project["work_dir"]) / "ui-jobs"
    job_dir = ui_jobs / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(json.dumps({
        "id": "job-1",
        "operation": "apply",
        "project_key": "test",
        "target": "3.1",
        "state": "succeeded",
        "created_at": "2026-10-04T10:00:00Z",
    }))

    result = review_workflow.latest(Path(".agents"), project, "3.1")
    assert result is None
