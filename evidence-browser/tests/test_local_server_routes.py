from pathlib import Path


def test_dependency_free_server_keeps_section_workflow_route_parity() -> None:
    source = (Path(__file__).resolve().parents[1] / "backend" / "local_server.py").read_text(encoding="utf-8")
    for handler in (
        "api.get_section(", "api.get_section_proposal(", "api.save_section_proposal(",
        "api.validate_section_proposal(", "api.apply_preflight(", "api.apply_section(",
        "api.get_apply_job(",
    ):
        assert handler in source
    assert 'if path.startswith("/api/")' in source
    assert 'self.send_json({"detail": "Route not found"}, 404)' in source


def test_intake_errors_route_returns_runs_and_warnings(tmp_path, monkeypatch) -> None:
    import json

    import pytest
    from fastapi import HTTPException

    from backend import app as workspace
    from backend.models import IntakeErrorsResponse

    work = tmp_path / "csa-work"
    jobs = (
        ("a", "gap_check", "failed", 1, "csa: failed to read the gap file\n"),
        ("b", "ingest", "succeeded", 0, ""),
    )
    for job_id, operation, state, code, err in jobs:
        folder = work / "ui-jobs" / job_id
        folder.mkdir(parents=True)
        meta = dict(
            id=job_id, project_key="tetra-reveloc", operation=operation, state=state,
            created_at="2026-01-01T00:00:0" + ("1" if job_id == "a" else "2") + "+00:00",
            started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:00:05+00:00",
            exit_code=code,
        )
        (folder / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (folder / "stdout.log").write_text("", encoding="utf-8")
        (folder / "stderr.log").write_text(err, encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text(
        "projects:\n  - key: tetra-reveloc\n    label: T\n"
        "    project_root: " + str(tmp_path) + "\n    work_dir: " + str(work) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    parsed = IntakeErrorsResponse.model_validate(workspace.get_intake_errors("tetra"))
    by = {r.id: r for r in parsed.runs}
    assert set(by) == {"a", "b"}
    assert by["a"].has_problems is True and by["a"].problems[0].stream == "stderr"
    assert by["b"].has_problems is False
    assert parsed.warnings == [] and parsed.generated_at
    with pytest.raises(HTTPException) as exc:
        workspace.get_intake_errors("nope")
    assert exc.value.status_code == 404
