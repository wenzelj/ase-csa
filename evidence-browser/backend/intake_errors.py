"""Classify a step run's log into a short list of grouped problems.

Pure function: no file or network access. A run can print dozens of identical failures; this turns the raw
output into distinct problems with counts so the page can show them.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))
from csa_docx import leads as lead_store

MAX_GROUPS = 25
SAMPLE_CHARS = 300
WITHHELD = "[withheld: looked like a credential]"

_TRACEBACK = "Traceback (most recent call last):"
_CLI_ERROR = re.compile(r"^[\w.\-/ ]+: error: (.+)$")
_CSA_START = ("csa:", "Error:", "ERROR:")
_CSA_WORDS = ("error", "failed", "cannot", "could not", "not found", "refused")
_NO_TERMINAL = "csa: no terminal here, so the agent runs headless (no interactive UI)"
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_ABS_PATH = re.compile(r"(?<![\w.~])/(?:[^\s'\"/:]+/)+([^\s'\"/:]+)")
_DIGITS = re.compile(r"\d+")


def _normalise(text: str) -> str:
    text = _QUOTED.sub("'…'", text.strip())
    text = _ABS_PATH.sub(r"\1", text)
    text = _DIGITS.sub("N", text)
    return re.sub(r"\s+", " ", text)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _sample(text: str) -> str:
    text = text[:SAMPLE_CHARS]
    if lead_store._looks_secret(text):
        return WITHHELD
    return text


def classify_log(text: str) -> list[dict[str, Any]]:
    """Return grouped problems: {kind, signature, count, first_line, last_line, sample}."""
    if not text:
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    partial = len(lines) - 1 if lines and lines[-1] != "" else -1  # last line still being written
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, signature: str, line_no: int, sample: str) -> None:
        group = groups.get((kind, signature))
        if group is None:
            groups[(kind, signature)] = {
                "kind": kind, "signature": signature, "count": 1,
                "first_line": line_no, "last_line": line_no, "sample": _sample(sample),
            }
            return
        group["count"] += 1
        group["first_line"] = min(group["first_line"], line_no)
        group["last_line"] = max(group["last_line"], line_no)

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == _TRACEBACK:
            base = _indent(line)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base):
                j += 1
            if j < len(lines) and j != partial:
                block = "\n".join(lines[i:j + 1])
                add("traceback", _normalise(lines[j]), i + 1, block)
                i = j + 1
            else:
                i = len(lines)  # cut off before its final line: not counted
            continue
        stripped = line.strip()
        number = i + 1
        if _CLI_ERROR.match(line):
            add("cli_error", _normalise(line), number, stripped)
        elif stripped == _NO_TERMINAL:
            pass
        elif line.startswith(_CSA_START) and any(w in line.lower() for w in _CSA_WORDS):
            add("csa_error", _normalise(line), number, stripped)
        elif "hit(s) skipped" in line or "hit(s) withheld" in line:
            add("skipped", _normalise(line), number, stripped)
        i += 1

    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["first_line"]))
    return ordered[:MAX_GROUPS]


RUN_OPERATIONS = {"ingest": "ingest", "intake": "documents", "gap_check": "gaps", "resolve_gaps": "settle"}
MAX_LOG_BYTES = 8 * 1024 * 1024
_FAILED_STATES = {"failed", "interrupted", "cancelled"}
_cache: dict[str, tuple[tuple, tuple[list[dict[str, Any]], bool]]] = {}
_cache_lock = threading.Lock()


def _read_log(path: Path, max_bytes: int = MAX_LOG_BYTES) -> tuple[str, bool]:
    """Return (text, truncated). A log over max_bytes is read from its end, starting at a whole line."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            truncated = size > max_bytes
            handle.seek(size - max_bytes if truncated else 0)
            data = handle.read(max_bytes)
    except OSError:
        return "", False
    if truncated:
        newline = data.find(b"\n")
        data = data[newline + 1:] if newline >= 0 else b""
    return data.decode("utf-8", errors="replace"), truncated


def _stat_key(path: Path) -> tuple[int, int]:
    try:
        info = path.stat()
    except OSError:
        return (-1, -1)
    return (info.st_size, info.st_mtime_ns)


def _classify_job(job_id: str, folder: Path) -> tuple[list[dict[str, Any]], bool]:
    stdout_path, stderr_path = folder / "stdout.log", folder / "stderr.log"
    key = (_stat_key(stdout_path), _stat_key(stderr_path))
    with _cache_lock:
        hit = _cache.get(job_id)
        if hit is not None and hit[0] == key:
            return hit[1]
    problems: list[dict[str, Any]] = []
    truncated = False
    for stream, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        text, cut = _read_log(path)
        truncated = truncated or cut
        for group in classify_log(text):
            problems.append({**group, "stream": stream})
    result = (problems, truncated)
    with _cache_lock:
        _cache[job_id] = (key, result)
    return result


def _seconds(started: str | None, finished: str | None) -> float | None:
    if not started:
        return None
    try:
        begin = datetime.fromisoformat(started)
        end = datetime.fromisoformat(finished) if finished else datetime.now(timezone.utc)
        return max(0.0, round((end - begin).total_seconds(), 3))
    except ValueError:
        return None


def intake_runs(project: dict[str, str], limit: int = 10) -> list[dict[str, Any]]:
    """Recent runs of the four intake steps, newest first, each with the problems found in its logs."""
    root = Path(project["work_dir"]).expanduser() / "ui-jobs"
    if not root.is_dir() or limit <= 0:
        return []
    metas: list[dict[str, Any]] = []
    for path in root.glob("*/metadata.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("operation") not in RUN_OPERATIONS or not meta.get("id"):
            continue
        if meta.get("project_key") not in (None, project.get("key")):
            continue
        metas.append(meta)
    metas.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
    runs: list[dict[str, Any]] = []
    for meta in metas[:limit]:
        job_id = str(meta["id"])
        problems, truncated = _classify_job(job_id, root / job_id)
        state = str(meta.get("state") or "")
        reason = meta.get("message") or ""
        if not reason and problems:
            reason = max(problems, key=lambda g: g["count"])["signature"]
        runs.append({
            "id": job_id, "operation": meta["operation"], "step": RUN_OPERATIONS[meta["operation"]],
            "state": state, "exit_code": meta.get("exit_code"),
            "started_at": meta.get("started_at"), "finished_at": meta.get("finished_at"),
            "elapsed_seconds": _seconds(meta.get("started_at"), meta.get("finished_at")),
            "reason": reason, "problems": problems, "problem_count": len(problems),
            "has_problems": state in _FAILED_STATES or bool(problems), "log_truncated": truncated,
        })
    return runs
