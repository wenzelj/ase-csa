"""Classify a step run's log into a short list of grouped problems.

Pure function: no file or network access. A run can print dozens of identical failures; this turns the raw
output into distinct problems with counts so the page can show them.
"""
from __future__ import annotations

import json
import re
import sqlite3
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
# Only errors raised by the framework itself are reported. A traceback counts when one of its frames is in the
# framework tree; the agent's own throwaway scripts (`<string>`, `<stdin>`, stdlib) and a mistyped command line
# are not framework errors.
_AGENTS_DIR = Path(__file__).resolve().parents[2]
_FRAME = re.compile(r'^\s*File "([^"]+)"')


def _normalise(text: str) -> str:
    text = _QUOTED.sub("'…'", text.strip())
    text = _ABS_PATH.sub(r"\1", text)
    text = _DIGITS.sub("N", text)
    return re.sub(r"\s+", " ", text)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_framework_traceback(block: str) -> bool:
    root = str(_AGENTS_DIR) + "/"
    for line in block.split("\n"):
        m = _FRAME.match(line)
        if m and m.group(1).startswith(root) and "/.venv/" not in m.group(1) and "/node_modules/" not in m.group(1):
            return True
    return False


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
                if _is_framework_traceback(block):
                    add("traceback", _normalise(lines[j]), i + 1, block)
                i = j + 1
            else:
                i = len(lines)  # cut off before its final line: not counted
            continue
        stripped = line.strip()
        number = i + 1
        if _CLI_ERROR.match(line):
            pass  # argparse usage error from a command the agent typed, not a framework fault
        elif stripped == _NO_TERMINAL:
            pass
        elif line.startswith(_CSA_START) and any(w in line.lower() for w in _CSA_WORDS):
            add("csa_error", _normalise(line), number, stripped)
        elif "hit(s) skipped" in line or "hit(s) withheld" in line:
            add("skipped", _normalise(line), number, stripped)
        i += 1

    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["first_line"]))
    return ordered[:MAX_GROUPS]


RUN_OPERATIONS = {"ingest": "ingest", "model_build": "ingest", "intake": "documents", "gap_check": "gaps", "resolve_gaps": "settle"}
MAX_LOG_BYTES = 8 * 1024 * 1024
_FAILED_STATES = {"failed", "interrupted"}  # a run the user cancelled is not an error
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
    """Recent Evidence Intake jobs, newest first, with the problems found in their logs."""
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
    # A later clean finished run of the same step answers an earlier failure, so the old one is no longer shown.
    cleared: set[str] = set()
    for run in runs:  # newest first
        finished = run["state"] in ("succeeded", "failed", "interrupted", "cancelled")
        if run["step"] in cleared and run["has_problems"]:
            run.update(problems=[], problem_count=0, has_problems=False, superseded=True)
        elif finished and not run["has_problems"] and run["state"] == "succeeded":
            cleared.add(run["step"])
    return runs


GAP_SCHEMA_VERSION = 4
_REASON_LIMIT = 3


def _record(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _entry(step: str, severity: str, code: str, message: str, count: int = 1) -> dict[str, Any]:
    return {"step": step, "severity": severity, "code": code, "message": message, "count": count}


def _gap_warnings(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for text in record.get("input_warnings") or []:
        out.append(_entry("gaps", "warning", "input_warning", str(text)))
    questions = [q for q in record.get("questions") or [] if isinstance(q, dict)]
    incomplete = sum(1 for q in questions if q.get("verdict") == "INCOMPLETE")
    if incomplete:
        reasons: dict[str, int] = {}
        for q in questions:
            if q.get("verdict") != "INCOMPLETE":
                continue
            coverage = q.get("coverage") if isinstance(q.get("coverage"), dict) else {}
            for reason in coverage.get("incomplete_reasons") or []:
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
        top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:_REASON_LIMIT]
        message = f"{incomplete} question(s) have an incomplete search"
        if top:
            message += ": " + "; ".join(f"{reason} ({n})" for reason, n in top)
        out.append(_entry("gaps", "warning", "incomplete_questions", message, incomplete))
    version = record.get("schema_version")
    if version != GAP_SCHEMA_VERSION:
        out.append(_entry("gaps", "warning", "old_schema",
                          f"The gap-check record uses schema version {version}, not {GAP_SCHEMA_VERSION}"))
    return out


def intake_warnings(work: Path) -> list[dict[str, Any]]:
    """Problems the saved records already hold: [{step, severity, code, message, count}]. A missing or
    unreadable record adds nothing."""
    out: list[dict[str, Any]] = []
    work = Path(work)
    if work.name == "csa-work-v2" and (work / "csa.sqlite").is_file():
        # V2 has no legacy graph-audit.jsonl, host CSVs or gap-check JSON.
        # Read the equivalent durable state from SQLite instead.
        try:
            con = sqlite3.connect(f"file:{work / 'csa.sqlite'}?mode=ro", uri=True)
            pending = con.execute("""
                WITH latest AS (
                    SELECT f.status,
                           ROW_NUMBER() OVER (
                               PARTITION BY f.rel_path
                               ORDER BY r.started_at DESC, r.id DESC
                           ) AS rn
                    FROM intake_file f
                    JOIN intake_record r ON r.id = f.record_id
                )
                SELECT COUNT(*) FROM latest WHERE rn=1 AND status='pending'
            """).fetchone()[0]
            # A failed historical attempt is cleared when a later intake record
            # processes the same source file. Count only the latest durable state
            # per path, otherwise successful retries leave a permanent warning.
            failed = con.execute("""
                WITH latest AS (
                    SELECT f.status,
                           ROW_NUMBER() OVER (
                               PARTITION BY f.rel_path
                               ORDER BY r.started_at DESC, r.id DESC
                           ) AS rn
                    FROM intake_file f
                    JOIN intake_record r ON r.id = f.record_id
                )
                SELECT COUNT(*) FROM latest WHERE rn=1 AND status='failed'
            """).fetchone()[0]
            if pending:
                out.append(_entry("ingest", "warning", "pending_intake_files",
                                  f"{pending} intake file(s) are still pending", pending))
            if failed:
                out.append(_entry("ingest", "error", "failed_intake_files",
                                  f"{failed} intake file(s) failed processing", failed))
            if con.execute("SELECT COUNT(*) FROM gap_check").fetchone()[0] == 0:
                out.append(_entry("gaps", "warning", "no_gap_check", "No V2 open-question check has been recorded"))
            con.close()
        except sqlite3.Error:
            out.append(_entry("ingest", "error", "v2_store_unreadable", "The V2 SQLite store could not be read"))
        return out
    gap = _record(work / "intake" / "gap-check-latest.json")
    if gap is not None:
        out.extend(_gap_warnings(gap))
    try:
        from backend.intake_workflow import _sync_health
        health = _sync_health(work)
    except Exception:  # an unreadable register must not break the page
        health = {}
    if health.get("failed"):
        status = (health.get("last") or {}).get("status", "")
        out.append(_entry("ingest", "error", "sync_failed", f"The last host rebuild did not finish (status {status})"))
    if health.get("behind"):
        out.append(_entry("ingest", "warning", "sync_behind", "The host register is older than the evidence"))
    latest = _record(work / "intake" / "latest.json")
    unreadable = latest.get("unreadable") if latest else None
    if isinstance(unreadable, list) and unreadable:
        out.append(_entry("documents", "warning", "unreadable_files",
                          f"{len(unreadable)} file(s) could not be read", len(unreadable)))
    return out
