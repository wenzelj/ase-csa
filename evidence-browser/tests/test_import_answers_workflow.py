from pathlib import Path
from types import SimpleNamespace

from backend import commands, import_answers_workflow
from backend.models import CommandResult


def project(tmp_path: Path) -> dict[str, str]:
    work = tmp_path / "work"
    (work / "cards").mkdir(parents=True)
    return {"key": "tetra-reveloc", "work_dir": str(work)}


def test_preview_delegates_to_framework_and_projects_readiness(tmp_path, monkeypatch):
    row = project(tmp_path)
    monkeypatch.setattr(commands, "execute", lambda *_args: CommandResult(
        correlation_id="c", operation="import_answers", project_key=row["key"],
        started_at="", finished_at="", duration_ms=1, exit_code=0, stdout="",
        stderr="", parsed={"status": "DRY_RUN", "sections": [{"section_key": "NET"}]}, parsed_json=True))
    monkeypatch.setattr(import_answers_workflow.section_state, "project",
                        lambda _work, key: {"state": "ready-for-improve", "eligible_for_improve": key == "NET"})
    result = import_answers_workflow.preview(Path(".agents"), row)
    assert result["status"] == "DRY_RUN"
    assert result["sections"][0]["readiness"]["state"] == "ready-for-improve"
    assert result["sections"][0]["eligible_for_improve"] is True


def test_submit_uses_import_operation_and_keeps_job_resumable(tmp_path):
    row = project(tmp_path)
    calls = []

    class Manager:
        def submit(self, _project, operation, request):
            calls.append((operation, request))
            return SimpleNamespace(model_dump=lambda: {"id": "j1", "state": "queued", "operation": operation})

    result = import_answers_workflow.submit(Path(".agents"), Manager(), row)
    assert calls[0][0] == "import_answers"
    assert calls[0][1].options["resume"] is True
    assert result["terminal"] is False and result["resumable"] is True


def test_outcome_does_not_report_success_for_partial_import(tmp_path, monkeypatch):
    row = project(tmp_path)
    monkeypatch.setattr(import_answers_workflow.section_state, "project", lambda *_: {"eligible_for_improve": False})
    result = import_answers_workflow.outcome(row, {
        "state": "succeeded", "exit_code": 1,
        "stdout_tail": '{"status":"PARTIAL","sections":[{"section_key":"NET","blockers":["rating missing"]}]}'})
    assert result["status"] == "FAILED"
    assert result["terminal"] is True
    assert result["resumable"] is True
