from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import apply_workflow, commands


def setup(tmp_path):
    root = tmp_path / "project"; work = root / "csa-work"; root.mkdir(); work.mkdir()
    doc = root / "assessment.docx"; doc.write_bytes(b"document")
    project = {"key": "test", "label": "Test System", "project_root": str(root), "work_dir": str(work)}
    proposal = {"section": {"visible_number": "3.1", "stable_key": "ASSET", "heading": "Assets"},
                "lane": "revise", "file": "ChangesCSA_Test_Section3.md", "etag": '"hash"',
                "records": [{"edit_id": "S3-E1"}, {"edit_id": "S3-E2"}]}
    validator = lambda _section, _payload: {"valid": True, "file_hash": '"hash"', "errors": 0}
    checks = {"proposal_loader": lambda _: proposal, "validator": validator,
              "document_resolver": lambda _: {"state": "ready", "path": doc},
              "word_lock_check": lambda _: None, "framework_lock_check": lambda _: False}
    return project, proposal, checks


def test_apply_operation_is_mutating_locked_and_until_done():
    operation = commands.OPERATIONS["apply"]
    assert operation.mutating and operation.lock == "docx" and "until_done" in operation.options


def test_preflight_resolves_exact_identity_hash_document_and_edits(tmp_path):
    project, proposal, checks = setup(tmp_path)
    result = apply_workflow.preflight(Path(".agents"), project, "ASSET",
                                      {"file": proposal["file"], "file_hash": proposal["etag"]}, **checks)
    assert result["edit_count"] == 2 and result["edit_ids"] == ["S3-E1", "S3-E2"]
    assert result["document"] == "assessment.docx" and result["confirmation_required"]


@pytest.mark.parametrize("change", ["stale", "document", "word", "framework", "validation"])
def test_preflight_blocks_every_unsafe_state(tmp_path, change):
    project, proposal, checks = setup(tmp_path)
    request = {"file": proposal["file"], "file_hash": proposal["etag"]}
    if change == "stale": request["file_hash"] = '"old"'
    if change == "document": checks["document_resolver"] = lambda _: {"state": "blocked"}
    if change == "word": checks["word_lock_check"] = lambda _: Path("~$assessment.docx")
    if change == "framework": checks["framework_lock_check"] = lambda _: True
    if change == "validation": checks["validator"] = lambda *_: {"valid": False, "file_hash": '"hash"'}
    with pytest.raises(HTTPException) as error:
        apply_workflow.preflight(Path(".agents"), project, "3.1", request, **checks)
    assert error.value.status_code == 409


def test_submit_requires_separate_confirmation_and_records_safe_audit(tmp_path):
    project, proposal, checks = setup(tmp_path)
    class Manager:
        calls = []
        def submit(self, project, operation, request):
            self.calls.append((operation, request)); return SimpleNamespace(id="job-1", model_dump=lambda: {"id": "job-1", "state": "queued"})
    manager = Manager(); request = {"file": proposal["file"], "file_hash": proposal["etag"]}
    with pytest.raises(HTTPException):
        apply_workflow.submit(Path(".agents"), manager, project, "3.1", request, **checks)
    request["confirmed"] = True
    result = apply_workflow.submit(Path(".agents"), manager, project, "3.1", request, **checks)
    assert result["job"]["id"] == "job-1" and manager.calls[0][0] == "apply"
    assert manager.calls[0][1].options == {"until_done": True}
    audit = (Path(project["work_dir"]) / "evidence-browser-audit.jsonl").read_text()
    assert "apply_requested" in audit and "S3-E1" not in audit


@pytest.mark.parametrize("job,state", [
    ({"state": "succeeded", "stdout_tail": '{"applied":["S3-E1"],"already_applied":["S3-E0"],"backup":"copy.bak"}'}, "succeeded"),
    ({"state": "succeeded", "stdout_tail": '{"applied":["S3-E1"],"blocked":["S3-E2"],"next_edit_id":"S3-E2"}'}, "partial"),
    ({"state": "failed", "stdout_tail": "failure"}, "failed"),
    ({"state": "succeeded", "stdout_tail": '{"already_applied":["S3-E1"]}'}, "succeeded"),
])
def test_outcome_preserves_success_partial_failure_resume_and_already_applied(job, state):
    assert apply_workflow.outcome(job)["state"] == state
