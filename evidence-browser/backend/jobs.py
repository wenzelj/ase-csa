from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import signal
import sys
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
from .terminal_sessions import TerminalSession

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))
from csa_docx import leads as lead_store


TAIL_LIMIT = 64 * 1024
LOG_PAGE_MAX = 500
LOG_LINE_MAX = 2000
LOG_WITHHELD = "[withheld: looked like a credential]"
_JOB_ID = re.compile(r"^[0-9a-f-]{36}$")
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
INTERACTIVE_OPERATIONS = frozenset({"intake", "resolve_gaps", "answer", "refresh_draft",
                                    "figure_wording", "figure_design", "author", "review", "audit"})
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")


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
    change_files = [path for path in change_files if "csa-work" not in path.relative_to(root).parts]
    version_dirs = sorted({path.parent.parent for path in change_files}) + [root / "01 Current State AS Built" / "01 Final Version"]
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
        self._terminals: dict[str, TerminalSession] = {}
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

    def _append_log(self, project: dict[str, str], job: JobRecord, name: str, text: str) -> None:
        folder = self._folder(project, job.id)
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{name}.log", "a", encoding="utf-8") as handle:
            handle.write(text)
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
                if job.terminal and job.pid:
                    self._stop_abandoned_terminal(job)
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
        classification = str(getattr(operation, "mutation_class", "read_only"))
        if classification == "read_only" and getattr(operation, "mutating", False):
            classification = "document_write"
        lock_class = str(getattr(operation, "lock", "none"))
        resource = f"section:{request.target}" if lock_class == "section" and request.target else (
            "document" if lock_class == "docx" else "evidence" if lock_class == "evidence" else None)
        terminal = operation.key in INTERACTIVE_OPERATIONS
        job = JobRecord(
            id=str(uuid.uuid4()), project_key=project["key"], operation=operation.key,
            display_args=argv[3:], classification=classification, lock=lock_class, resource=resource,
            state="queued", created_at=_now(), terminal=terminal,
        )
        with self._condition:
            if lock_class in ("section", "evidence") and resource and any(row.project_key == project["key"] and row.resource == resource and
                                row.state in {"queued", "running"} for row in self._jobs.values()):
                raise HTTPException(409, f"Another operation is already working on {resource.replace(':', ' ')}.")
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(dict(project), job.id, operation, argv), daemon=True).start()
        return job.model_copy(deep=True)

    def _resource(self, job: JobRecord) -> tuple[str, str] | None:
        if job.resource:
            return (job.project_key, job.resource)
        if job.classification == "document_write":
            return (job.project_key, "document")
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
        process: subprocess.Popen | None = None
        try:
            if job.lock == "docx" and not getattr(operation, "closes_word", False):
                lock = self._word_lock_check(project)
                if lock is not None:      # save and close it in Word (or clear a stale owner file), then check again
                    try:
                        subprocess.run([str(self.agents_dir / "bin" / "csa"), "--project", project["key"], "close-word"],
                                       cwd=str(self.agents_dir.parent), env=commands._minimal_environment(self.agents_dir),
                                       capture_output=True, text=True, timeout=90)
                    except (OSError, subprocess.SubprocessError):
                        pass
                    lock = self._word_lock_check(project)
                if lock is not None:
                    raise RuntimeError(
                        f"Working DOCX is open in Word ({lock.name}). Close it before running this operation."
                    )
            terminal = None
            if job.terminal:
                # The agent's window stays open after its work; csa closes it when an answer turn ends (turn_end_args).
                terminal = TerminalSession.start(argv, self.agents_dir.parent,
                                                 dict(commands._minimal_environment(self.agents_dir),
                                                      CSA_CLOSE_ON_TURN_END="1"))
                process = terminal.process
            else:
                process = self._popen(
                    argv, cwd=str(self.agents_dir.parent), env=commands._minimal_environment(self.agents_dir),
                    shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                )
            with self._condition:
                self._processes[job_id] = process
                if terminal is not None:
                    self._terminals[job_id] = terminal
                job = self._jobs[job_id]
                job.state = "running"
                job.started_at = _now()
                job.pid = getattr(process, "pid", None)
                self._persist(project, job)
                self._condition.notify_all()
            chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}

            def drain(name: str, stream) -> None:
                if stream is None:
                    return
                for text in iter(stream.readline, ""):
                    with self._condition:
                        chunks[name].append(text)
                        current = self._jobs[job_id]
                        current.stdout_tail = _tail("".join(chunks["stdout"]))
                        current.stderr_tail = _tail("".join(chunks["stderr"]))
                        self._append_log(project, current, name, text)
                stream.close()

            if terminal is not None:
                terminal.drain()
                process.wait()
                if job.operation == "review":
                    clean = _ANSI.sub("", terminal.snapshot().decode("utf-8", errors="replace")).replace("\r", "\n")
                    parsed, valid = commands.parse_json_output(clean)
                    if valid and isinstance(parsed, dict):
                        stdout = json.dumps(parsed, ensure_ascii=True)
            else:
                readers = [threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
                           threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True)]
                for reader in readers:
                    reader.start()
                process.wait()
                for reader in readers:
                    reader.join()
                stdout, stderr = "".join(chunks["stdout"]), "".join(chunks["stderr"])
            exit_code = process.returncode
            with self._condition:
                cancelled = job_id in self._cancel_requested
                job = self._jobs[job_id]
                job.exit_code = exit_code
                job.stdout_tail = _tail(stdout or "")
                job.stderr_tail = _tail(stderr or "")
                job.state = "cancelled" if cancelled else ("succeeded" if exit_code == 0 else "failed")
                if terminal is not None and exit_code != 0 and not cancelled:
                    job.message = f"Command exited with code {exit_code}; inspect the in-page terminal."
        except Exception as error:
            if process is not None and process.poll() is None:
                self._signal_process_tree(process, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._signal_process_tree(process, signal.SIGKILL)
                    process.wait()
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
                completed = sorted((self._jobs[key] for key in self._terminals
                                    if self._jobs[key].state in TERMINAL_STATES),
                                   key=lambda row: row.finished_at or "", reverse=True)
                for old in completed[10:]:
                    self._terminals.pop(old.id, None)
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

    def read_log(self, project: dict[str, str], job_id: str, stream: str, start: int = 1,
                 limit: int = 200) -> dict:
        if stream not in ("stdout", "stderr"):
            raise HTTPException(400, "stream must be stdout or stderr")
        self._load_project(project)
        with self._condition:
            known = job_id in self._jobs
        if not known and not _JOB_ID.match(str(job_id)):
            raise HTTPException(404, "Job not found")
        self.get(project, job_id)
        start = max(1, int(start))
        limit = max(1, min(int(limit), LOG_PAGE_MAX))
        path = self._folder(project, job_id) / (stream + ".log")
        lines: list[dict] = []
        total = 0
        truncated = False
        if path.is_file():
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                while True:
                    text = handle.readline(LOG_LINE_MAX + 1)
                    if not text:
                        break
                    cut = False
                    if len(text) > LOG_LINE_MAX and not text.endswith("\n"):
                        cut = True
                        while True:                      # discard the rest of an over-long line
                            rest = handle.readline(65536)
                            if not rest or rest.endswith("\n"):
                                break
                    total += 1
                    if total < start or len(lines) >= limit:
                        continue
                    text = text.rstrip("\r\n")
                    if len(text) > LOG_LINE_MAX:
                        text, cut = text[:LOG_LINE_MAX], True
                    truncated = truncated or cut
                    if lead_store._looks_secret(text):
                        text = LOG_WITHHELD
                    lines.append(dict(n=total, text=text))
        return dict(stream=stream, total_lines=total, start=start, lines=lines, truncated=truncated)

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
            self._signal_process_tree(process, signal.SIGINT if job.terminal else signal.SIGTERM)
            snapshot = job.model_copy(deep=True)
        threading.Thread(target=self._kill_after_grace, args=(job_id, process, job.terminal), daemon=True).start()
        return snapshot

    def _kill_after_grace(self, job_id: str, process: subprocess.Popen, interactive: bool = False) -> None:
        if interactive:
            for delay, value in ((3, signal.SIGTERM), (2, signal.SIGKILL)):
                time.sleep(delay)
                with self._condition:
                    if self._processes.get(job_id) is not process:
                        return
                    try:
                        os.killpg(process.pid, value)
                    except (ProcessLookupError, PermissionError):
                        if process.poll() is None:
                            self._signal_process_tree(process, value)
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with self._condition:
                if self._processes.get(job_id) is process:
                    self._signal_process_tree(process, signal.SIGKILL)

    @staticmethod
    def _signal_process_tree(process: subprocess.Popen, value: signal.Signals) -> None:
        """Signal the job's process group, falling back to the direct child for injected/fake processes.

        Jobs start in their own process session solely so cancellation cannot leave ordinary descendants behind.
        Terminal models remain tracked children of the browser job.
        """
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, value)
        except (AttributeError, ProcessLookupError, PermissionError):
            if value == signal.SIGKILL:
                process.kill()
            elif value == signal.SIGINT:
                process.send_signal(value)
            else:
                process.terminate()

    def _stop_abandoned_terminal(self, job: JobRecord) -> bool:
        """Stop only the exact old CSA process, avoiding a reused PID after restart."""
        pid = job.pid
        if not pid or pid <= 1:
            return False
        expected = str(self.agents_dir / "bin" / "csa")
        names = {expected, expected.removeprefix("/private") if expected.startswith("/private/") else expected}
        matches = lambda command: any(name in command for name in names) and f"--project {job.project_key}" in command
        try:
            command = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="],
                                     capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        if not matches(command):
            return False
        try:
            if "terminal_exec.py" in command:
                # Startup race: the helper has not created its process group yet.
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return False
        for _ in range(20):
            time.sleep(.1)
            if not Path(f"/proc/{pid}").exists() and sys.platform.startswith("linux"):
                return True
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        try:
            current = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="],
                                     capture_output=True, text=True, timeout=2).stdout
            if matches(current):
                os.killpg(pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError, ProcessLookupError, PermissionError):
            pass
        return True

    def _terminal(self, project: dict[str, str], job_id: str) -> TerminalSession:
        self.get(project, job_id)
        with self._condition:
            self._condition.wait_for(lambda: job_id in self._terminals or
                                     self._jobs[job_id].state in TERMINAL_STATES, timeout=5)
            terminal = self._terminals.get(job_id)
        if terminal is None:
            raise HTTPException(404, "Interactive terminal not found")
        return terminal

    def terminal_output(self, project: dict[str, str], job_id: str, after: int) -> dict:
        return self._terminal(project, job_id).output(after)

    def terminal_input(self, project: dict[str, str], job_id: str, data: str, capability: str) -> dict:
        terminal = self._terminal(project, job_id)
        if not secrets.compare_digest(terminal.capability, capability):
            raise HTTPException(403, "Invalid terminal capability")
        if len(data) > 4 * 4096 // 3 + 8:
            raise HTTPException(413, "Terminal input is too large")
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise HTTPException(422, "Invalid terminal input encoding") from error
        terminal.input(raw)
        return {"ok": True}

    def terminal_resize(self, project: dict[str, str], job_id: str, rows: int, cols: int,
                        capability: str) -> dict:
        terminal = self._terminal(project, job_id)
        if not secrets.compare_digest(terminal.capability, capability):
            raise HTTPException(403, "Invalid terminal capability")
        terminal.resize(rows, cols)
        return {"ok": True}

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
