"""S269 – Cleanup workflow tests.

Covers:
- the ``cleanup`` operation is registered as mutating, docx-locked, requires a target
- preflight gates: document-ready, review-signoff, word-lock, framework-lock, unresolved-revisions
- submit: confirmation required, audit entry, backup destination surfaced
- outcome parsing from stdout JSON (FINALISED / STOPPED)
- latest() finds the most recent cleanup job and filters by operation
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import cleanup_workflow, commands


def setup(tmp_path):
    root = tmp_path / "project"
    work = root / "csa-work"
    root.mkdir()
    work.mkdir()
    doc = root / "assessment.docx"
    doc.write_bytes(b"document")
    project = {"key": "test", "label": "Test System", "project_root": str(root), "work_dir": str(work)}
    return project, doc


def passing_review(doc, section="3.1"):
    return {"job_id": "r-1", "state": "succeeded", "section": section,
            "review_signoff": "PASS", "document_hash": hashlib.sha256(doc.read_bytes()).hexdigest(),
            "created_at": "2026-10-04T09:00:00Z"}


def test_cleanup_operation_registered():
    operation = commands.OPERATIONS["cleanup"]
    assert operation.mutating
    assert operation.lock == "docx"
    assert operation.target == "required"
    assert operation.argv == ("cleanup",)


def test_preflight_requires_ready_document(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)
    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "blocked"})
    with pytest.raises(HTTPException) as error:
        cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert error.value.status_code == 409


def test_preflight_requires_review_signoff(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)
    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: False)
    # No completed review at all -> latest returns None -> signoff gate fails.
    monkeypatch.setattr("backend.cleanup_workflow._latest_review", lambda a, p, s: None)

    with pytest.raises(HTTPException) as error:
        cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert error.value.status_code == 409
    assert "review" in error.value.detail.lower()


def test_preflight_blocks_when_word_locked(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)
    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: Path("~$locked.docx"))

    with pytest.raises(HTTPException) as error:
        cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert error.value.status_code == 409
    assert "word" in error.value.detail.lower()


def test_preflight_blocks_when_framework_locked(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)
    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: True)

    with pytest.raises(HTTPException) as error:
        cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert error.value.status_code == 409


def test_preflight_blocks_unresolved_revisions(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    def _passing_review(a, p, s):
        return passing_review(doc, s)

    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: False)
    monkeypatch.setattr("backend.cleanup_workflow._latest_review", _passing_review)
    monkeypatch.setattr("backend.cleanup_workflow._count_unresolved_revisions", lambda d: (7, "7 open revision(s)"))

    with pytest.raises(HTTPException) as error:
        cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert error.value.status_code == 409
    assert "revision" in error.value.detail.lower()


def test_preflight_returns_gates_when_all_pass(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    def _passing_review(a, p, s):
        return passing_review(doc, s)

    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: False)
    monkeypatch.setattr("backend.cleanup_workflow._latest_review", _passing_review)
    monkeypatch.setattr("backend.cleanup_workflow._count_unresolved_revisions", lambda d: (0, "none"))

    plan = cleanup_workflow.preflight(Path(".agents"), project, "3.1", {})
    assert plan["confirmation_required"] is True
    assert plan["review_signoff"] == "approved"
    assert all(gate["satisfied"] for gate in plan["gates"])
    assert plan["backup_destination"].endswith(".bak")
    assert plan["document_hash"]  # sha256 present


def test_submit_requires_confirmation(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    class Manager:
        def submit(self, project, operation, request):
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: False)
    monkeypatch.setattr("backend.cleanup_workflow._latest_review", lambda a, p, s: passing_review(doc, s))
    monkeypatch.setattr("backend.cleanup_workflow._count_unresolved_revisions", lambda d: (0, "none"))

    with pytest.raises(HTTPException) as error:
        cleanup_workflow.submit(Path(".agents"), Manager(), project, "3.1", {"confirmed": False})
    assert error.value.status_code == 422


def test_submit_sends_cleanup_and_records_audit(tmp_path, monkeypatch):
    project, doc = setup(tmp_path)

    calls = []

    class Manager:
        def submit(self, project, operation, request):
            calls.append(operation)
            return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})

    monkeypatch.setattr("backend.cleanup_workflow.documents.resolve", lambda p: {"state": "ready", "path": doc, "candidates": [str(doc)]})
    monkeypatch.setattr("backend.cleanup_workflow.jobs.word_lock", lambda p: None)
    monkeypatch.setattr("backend.cleanup_workflow._framework_locked", lambda p: False)
    monkeypatch.setattr("backend.cleanup_workflow._latest_review", lambda a, p, s: passing_review(doc, s))
    monkeypatch.setattr("backend.cleanup_workflow._count_unresolved_revisions", lambda d: (0, "none"))

    result = cleanup_workflow.submit(Path(".agents"), Manager(), project, "3.1", {"confirmed": True})
    assert result["job"]["id"] == "job-1"
    assert calls == ["cleanup"]
    audit_file = Path(project["work_dir"]) / "evidence-browser-audit.jsonl"
    content = audit_file.read_text()
    assert "cleanup_requested" in content
    assert "3.1" in content


def test_outcome_finalised():
    job = {
        "state": "succeeded",
        "stdout_tail": json.dumps({
            "cleanup_result": "FINALISED",
            "backup": "/tmp/assessment.before_cleanup.bak",
            "revisions_before": 12,
            "revisions_after": 0,
            "accepted_revisions": 12,
            "removed": ["comments/section_3_1"],
            "retained": ["backups/assessment.bak"],
            "section_state": "finalised",
            "validation": {"no_tracked_changes": True, "no_comments": True},
        }),
    }
    outcome = cleanup_workflow.outcome(job)
    assert outcome["result"] == "FINALISED"
    assert outcome["revisions_before"] == 12
    assert outcome["revisions_after"] == 0
    assert outcome["removed_artifacts"] == ["comments/section_3_1"]
    assert outcome["validation"]["no_tracked_changes"] is True
    assert outcome["recovery_instructions"]


def test_outcome_stopped_on_failure():
    job = {"state": "failed", "stdout_tail": "garbage", "stderr_tail": "boom"}
    outcome = cleanup_workflow.outcome(job)
    assert outcome["result"] == "STOPPED"
    assert outcome["state"] == "failed"
    assert outcome["failure_reason"]


def test_outcome_stopped_on_cancel():
    outcome = cleanup_workflow.outcome({"state": "cancelled"})
    assert outcome["result"] == "STOPPED"
    assert outcome["failure_reason"]


def test_latest_none_when_no_jobs(tmp_path):
    project, doc = setup(tmp_path)
    assert cleanup_workflow.latest(Path(".agents"), project, "3.1") is None


def test_latest_finds_cleanup_job(tmp_path):
    project, doc = setup(tmp_path)
    job_dir = Path(project["work_dir"]) / "ui-jobs" / "job-9"
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(json.dumps({
        "id": "job-9", "operation": "cleanup", "project_key": "test",
        "target": "3.1", "state": "succeeded",
        "created_at": "2026-10-04T11:00:00Z", "finished_at": "2026-10-04T11:02:00Z", "exit_code": 0,
    }))
    found = cleanup_workflow.latest(Path(".agents"), project, "3.1")
    assert found is not None
    assert found["job_id"] == "job-9"
    assert found["state"] == "succeeded"
    assert found["section"] == "3.1"


def test_latest_ignores_non_cleanup(tmp_path):
    project, doc = setup(tmp_path)
    job_dir = Path(project["work_dir"]) / "ui-jobs" / "job-1"
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(json.dumps({
        "id": "job-1", "operation": "review", "project_key": "test",
        "target": "3.1", "state": "succeeded", "created_at": "2026-10-04T10:00:00Z",
    }))
    # Only a review job exists -> latest cleanup must be None.
    assert cleanup_workflow.latest(Path(".agents"), project, "3.1") is None
