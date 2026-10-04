from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from . import commands
from .models import CommandRequest, JobRecord


TAIL_LIMIT = 64 * 1024
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(value: str) -> str:
    return value[-TAIL_LIMIT:]


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _working_docx(project: dict[str, str]) -> Path | None:
    explicit = project.get("working_docx")
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    root = Path(project["project_root"]).expanduser()
    change_files = [path for path in root.rglob("reviews/ChangesCSA_*.md")
                    if not any("archive" in part.lower() or part.lower().startswith("backup")
                               for part in path.relative_to(root).parts[:-1])]
    version_dirs = sorted({path.parent.parent for path in change_files})
    for folder in version_dirs:
        documents = [path for path in folder.glob("*.docx") if not path.name.startswith("~$")]
        if documents:
            return max(documents, key=lambda path: (path.stat().st_mtime_ns, path.name))
    return None


def word_lock(project: dict[str, str]) -> Path | None:
    document = _working_docx(project)
    if document is None:
        return None
    locks = [document.with_name(f"~${document.name}")]
    if len(document.name) > 2:
        locks.append(document.with_name(f"~${document.name[2:]}"))
    return next((path for path in locks if path.exists()), None)


class JobManager:
    """Local process manager. It deliberately creates no filesystem lock protocol.

    The catalogue's framework lock class is used as the scheduling resource, matching
    ``csa fleet`` semantics. The invoked CSA command remains responsible for its own
    backups and mutation transaction.
    """

    def __init__(self, agents_dir: Path, *, popen: Callable = subprocess.Popen,
                 word_lock_check: Callable[[dict[str, str]], Path | None] = word_lock) -> None:
        self.agents_dir = agents_dir
        self._popen = popen
        self._word_lock_check = word_lock_check
        self._jobs: dict[str, JobRecord] = {}
        self._projects: dict[str, dict[str, str]] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._cancel_requested: set[str] = set()
        self._held: set[tuple[str, str]] = set()
        self._condition = threading.Condition()

    @staticmethod
    def _folder(project: dict[str, str], job_id: str) -> Path:
        return Path(project["work_dir"]).expanduser() / "ui-jobs" / job_id

    def _persist(self, project: dict[str, str], job: JobRecord, stdout: str | None = None,
                 stderr: str | None = None) -> None:
        folder = self._folder(project, job.id)
        folder.mkdir(parents=True, exist_ok=True)
        if stdout is not None:
            _atomic_text(folder / "stdout.log", stdout)
        if stderr is not None:
            _atomic_text(folder / "stderr.log", stderr)
        _atomic_json(folder / "metadata.json", job.model_dump())

    def _load_project(self, project: dict[str, str]) -> None:
        project_key = project["key"]
        with self._condition:
            if project_key in self._projects:
                return
            self._projects[project_key] = dict(project)
        root = Path(project["work_dir"]).expanduser() / "ui-jobs"
        if not root.is_dir():
            return
        for metadata in root.glob("*/metadata.json"):
            try:
                job = JobRecord.model_validate_json(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if job.project_key != project_key:
                continue
            if job.state in {"queued", "running"}:
                job.state = "failed" if job.started_at is None else "interrupted"
                job.finished_at = _now()
                if job.started_at is None:
                    job.message = "The evidence workspace restarted before this job started."
                else:
                    job.message = "The evidence workspace restarted before this job completed."
                self._persist(project, job)
            with self._condition:
                self._jobs[job.id] = job

    def submit(self, project: dict[str, str], operation_key: str, request: CommandRequest) -> JobRecord:
        self._load_project(project)
        operation, argv = commands.build_argv(self.agents_dir, project["key"], operation_key, request)
        classification = "mutating" if getattr(operation, "mutating", False) else "read_only"
        lock_class = str(getattr(operation, "lock", "none"))
        job = JobRecord(
            id=str(uuid.uuid4()), project_key=project["key"], operation=operation.key,
            display_args=argv[3:], classification=classification, lock=lock_class,
            state="queued", created_at=_now(),
        )
        with self._condition:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(dict(project), job.id, operation, argv), daemon=True).start()
        return job.model_copy(deep=True)

    def _resource(self, job: JobRecord) -> tuple[str, str] | None:
        if job.classification == "mutating":
            return (job.project_key, "mutating")
        return None

    def _run(self, project: dict[str, str], job_id: str, operation, argv: list[str]) -> None:
        with self._condition:
            job = self._jobs[job_id]
            resource = self._resource(job)
        self._persist(project, job)
        with self._condition:
            while resource is not None and resource in self._held:
                self._condition.wait()
            if resource is not None:
                self._held.add(resource)

        stdout = ""
        stderr = ""
        try:
            if job.lock == "docx":
                lock = self._word_lock_check(project)
                if lock is not None:
                    raise RuntimeError(
                        f"Working DOCX is open in Word ({lock.name}). Close it before running this operation."
                    )
            process = self._popen(
                argv, cwd=str(self.agents_dir.parent), env=commands._minimal_environment(self.agents_dir),
                shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            with self._condition:
                self._processes[job_id] = process
                job = self._jobs[job_id]
                job.state = "running"
                job.started_at = _now()
                self._persist(project, job)
            stdout, stderr = process.communicate()
            exit_code = process.returncode
            with self._condition:
                cancelled = job_id in self._cancel_requested
                job = self._jobs[job_id]
                job.exit_code = exit_code
                job.stdout_tail = _tail(stdout or "")
                job.stderr_tail = _tail(stderr or "")
                job.state = "cancelled" if cancelled else ("succeeded" if exit_code == 0 else "failed")
        except Exception as error:
            with self._condition:
                job = self._jobs[job_id]
                job.exit_code = None
                job.state = "failed"
                job.message = str(error)
                job.stderr_tail = _tail(str(error))
        finally:
            with self._condition:
                job = self._jobs[job_id]
                job.finished_at = _now()
                self._processes.pop(job_id, None)
                self._cancel_requested.discard(job_id)
                resource = self._resource(job)
                if resource is not None:
                    self._held.discard(resource)
                self._persist(project, job, stdout, stderr)
                self._condition.notify_all()

    def list(self, project: dict[str, str]) -> list[JobRecord]:
        self._load_project(project)
        with self._condition:
            rows = [job.model_copy(deep=True) for job in self._jobs.values()
                    if job.project_key == project["key"]]
        return sorted(rows, key=lambda job: job.created_at, reverse=True)

    def get(self, project: dict[str, str], job_id: str) -> JobRecord:
        self._load_project(project)
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.project_key != project["key"]:
                raise HTTPException(404, "Job not found")
            return job.model_copy(deep=True)

    def cancel(self, project: dict[str, str], job_id: str) -> JobRecord:
        self._load_project(project)
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.project_key != project["key"]:
                raise HTTPException(404, "Job not found")
            process = self._processes.get(job_id)
            if job.state != "running" or process is None:
                raise HTTPException(409, "Only a running child process can be cancelled")
            self._cancel_requested.add(job_id)
            process.terminate()
            snapshot = job.model_copy(deep=True)
        threading.Thread(target=self._kill_after_grace, args=(job_id, process), daemon=True).start()
        return snapshot

    def _kill_after_grace(self, job_id: str, process: subprocess.Popen) -> None:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with self._condition:
                if self._processes.get(job_id) is process:
                    process.kill()

    def wait(self, project: dict[str, str], job_id: str, timeout: float = 5) -> JobRecord:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                job = self._jobs[job_id]
                if job.state in TERMINAL_STATES:
                    return job.model_copy(deep=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return job.model_copy(deep=True)
                self._condition.wait(remaining)
