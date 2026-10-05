from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands
from backend.jobs import JobManager
from backend.models import CommandRequest


def project(tmp_path: Path, key: str = "iamps-08") -> dict[str, str]:
    root = tmp_path / key
    work = root / "csa-work"
    work.mkdir(parents=True)
    return {"key": key, "project_root": str(root), "work_dir": str(work)}


def operation(monkeypatch: pytest.MonkeyPatch, script: str, *, mutating: bool = False,
              lock: str = "none") -> None:
    item = commands.Operation("stub", "Stub", "Test operation", ("stub",))
    object.__setattr__(item, "mutating", mutating)
    object.__setattr__(item, "lock", lock)
    monkeypatch.setitem(commands.OPERATIONS, "stub", item)
    monkeypatch.setattr(commands, "build_argv", lambda *_args: (item, [sys.executable, "-c", script]))


def test_success_persists_metadata_and_complete_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operation(monkeypatch, "import sys; print('done'); print('warning', file=sys.stderr)")
    item = project(tmp_path)
    manager = JobManager(tmp_path / ".agents")
    created = manager.submit(item, "stub", CommandRequest())
    result = manager.wait(item, created.id)
    assert result.state == "succeeded" and result.exit_code == 0
    folder = Path(item["work_dir"]) / "ui-jobs" / created.id
    assert (folder / "stdout.log").read_text() == "done\n"
    assert (folder / "stderr.log").read_text() == "warning\n"
    assert json.loads((folder / "metadata.json").read_text())["state"] == "succeeded"


def test_read_only_jobs_run_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operation(monkeypatch, "import time; time.sleep(.25)")
    item = project(tmp_path)
    manager = JobManager(tmp_path / ".agents")
    start = time.monotonic()
    first = manager.submit(item, "stub", CommandRequest())
    second = manager.submit(item, "stub", CommandRequest())
    manager.wait(item, first.id); manager.wait(item, second.id)
    assert time.monotonic() - start < .48


def test_mutating_jobs_serialize_per_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operation(monkeypatch, "import time; time.sleep(.2)", mutating=True, lock="docx")
    item = project(tmp_path)
    manager = JobManager(tmp_path / ".agents")
    first = manager.submit(item, "stub", CommandRequest())
    second = manager.submit(item, "stub", CommandRequest())
    time.sleep(.08)
    assert {manager.get(item, first.id).state, manager.get(item, second.id).state} == {"running", "queued"}
    manager.wait(item, first.id); manager.wait(item, second.id)


def test_workspace_writes_reject_same_section_but_allow_another(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = commands.Operation("stub", "Stub", "Test operation", ("stub",), "required", "section",
                              mutation_class="workspace_write", lock="section")
    monkeypatch.setitem(commands.OPERATIONS, "stub", item)
    monkeypatch.setattr(commands, "build_argv", lambda agents, key, op, req:
                        (item, [sys.executable, "-c", "import time; time.sleep(.2)", req.target]))
    project_row = project(tmp_path)
    manager = JobManager(tmp_path / ".agents")
    manager.submit(project_row, "stub", CommandRequest(target="3.6"))
    with pytest.raises(HTTPException) as caught:
        manager.submit(project_row, "stub", CommandRequest(target="3.6"))
    assert caught.value.status_code == 409
    other = manager.submit(project_row, "stub", CommandRequest(target="3.7"))
    assert other.resource == "section:3.7"


def test_restart_marks_abandoned_job_interrupted(tmp_path: Path) -> None:
    item = project(tmp_path)
    job_id = "67f8a560-4865-4eb8-8b69-97b5c66e4bcc"
    folder = Path(item["work_dir"]) / "ui-jobs" / job_id
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(json.dumps({
        "id": job_id, "project_key": item["key"], "operation": "status", "display_args": [],
        "classification": "read_only", "lock": "none", "state": "running",
        "created_at": "2026-10-04T00:00:00+00:00", "started_at": "2026-10-04T00:00:01+00:00",
    }), encoding="utf-8")
    recovered = JobManager(tmp_path / ".agents").get(item, job_id)
    assert recovered.state == "interrupted" and recovered.finished_at


def test_cancel_only_running_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operation(monkeypatch, "import time; time.sleep(10)")
    item = project(tmp_path)
    manager = JobManager(tmp_path / ".agents")
    created = manager.submit(item, "stub", CommandRequest())
    deadline = time.monotonic() + 2
    while manager.get(item, created.id).state != "running" and time.monotonic() < deadline:
        time.sleep(.01)
    manager.cancel(item, created.id)
    assert manager.wait(item, created.id).state == "cancelled"
    with pytest.raises(HTTPException) as caught:
        manager.cancel(item, created.id)
    assert caught.value.status_code == 409


def test_word_lock_rejects_docx_job_before_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operation(monkeypatch, "raise SystemExit('must not launch')", mutating=True, lock="docx")
    item = project(tmp_path)
    lock = Path(item["project_root"]) / "~$assessment.docx"
    lock.write_text("open", encoding="utf-8")
    manager = JobManager(tmp_path / ".agents", word_lock_check=lambda _project: lock)
    created = manager.submit(item, "stub", CommandRequest())
    result = manager.wait(item, created.id)
    assert result.state == "failed"
    assert "open in Word" in (result.message or "")
