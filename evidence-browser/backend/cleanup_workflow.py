"""S269 – Cleanup workflow: gate, submit, track, and report the framework cleanup agent run.

Cleanup is irreversible. It is blocked unless the latest review is a complete
pass on the current authoritative document hash and no Word/framework lock is
active. It runs the existing ``csa cleanup`` command through the S259 job
runner and must not accept/reject tracked changes itself — the framework agent
owns that decision based on the review sign-off.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import commands, documents, jobs
from .models import CleanupGate, CleanupPreflight, CommandRequest
from .review_workflow import latest as _latest_review


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _framework_locked(project: dict[str, str]) -> bool:
    """Return True if another process holds the framework cleanup lock.

    Uses a non-creating, non-acquiring probe so that merely reading preflight
    has no side effect.
    """
    lock = Path(project["work_dir"]).expanduser() / ".csa-cleanup.lock"
    if not lock.exists():
        return False
    handle = lock.open("r")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        except (BlockingIOError, OSError, PermissionError):
            return True
    finally:
        handle.close()


def _count_unresolved_revisions(document: Path) -> tuple[int, str]:
    """Heuristic: count Word tracked-change marks still present in document.xml.

    Word tracks insertions/deletions in two ways: wrapping the modified content
    in ``<w:ins>``/``<w:del>`` elements, or annotating run properties with
    ``<w:ins .../>``/``<w:del .../>`` inside ``<w:rPr>``. A non-zero count
    means the document still carries tracked changes the operator has not
    yet accepted or rejected in Word, and cleanup is blocked.
    Returns (count, label).
    """
    import zipfile
    try:
        with zipfile.ZipFile(document) as archive:
            member = "word/document.xml"
            if member not in archive.namelist():
                return 0, "none"
            xml = archive.read(member).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile) as exc:
        return -1, f"unreadable ({exc})"
    # Count both attribute-form (`<w:ins ...>`) and self-closing property
    # markers (`<w:ins .../>`). Each tracked change usually contributes one
    # of these per affected run or paragraph; we de-dupe on the pair.
    ins_open = len(re.findall(r"<w:ins[ >]", xml))
    ins_clsd = len(re.findall(r"<w:ins\s/", xml))
    del_open = len(re.findall(r"<w:del[ >]", xml))
    del_clsd = len(re.findall(r"<w:del\s/", xml))
    total = ins_open + ins_clsd + del_open + del_clsd
    if total == 0:
        return 0, "none"
    return total, f"{total} open revision(s)"


def preflight(
    agents_dir: Path,
    project: dict[str, str],
    section: str,
    request: dict[str, Any],
    *,
    document_resolver: Callable | None = None,
    word_lock_check: Callable | None = None,
    framework_lock_check: Callable | None = None,
    review_state_check: Callable | None = None,
    revision_counter: Callable | None = None,
    hash_check: Callable | None = None,
) -> dict[str, Any]:
    """Evaluate all cleanup gates before allowing a submit.

    A gate failing produces a 409 with the specific reason. On success, returns
    the preflight payload that the UI renders before asking for confirmation.
    """
    resolve = document_resolver or documents.resolve
    doc = resolve(project)
    if doc.get("state") != "ready" or not doc.get("path"):
        raise HTTPException(409, "The authoritative working document is ambiguous or unavailable.")
    document = Path(doc["path"])
    if not document.exists():
        raise HTTPException(409, f"The working document is missing: {document.name}.")

    word_lock = (word_lock_check or jobs.word_lock)(project)
    if word_lock is not None:
        raise HTTPException(409, f"The working document is open in Word ({word_lock.name}). Close it before running cleanup.")

    if (framework_lock_check or _framework_locked)(project):
        raise HTTPException(409, "Another framework operation holds the project lock. Wait for it to finish.")

    review_latest = (review_state_check or _latest_review)(agents_dir, project, section)
    review_signoff = "none"
    review_hash: str | None = None
    if review_latest:
        verdict = str(review_latest.get("review_signoff") or "").upper()
        review_signoff = "approved" if review_latest.get("state") == "succeeded" and verdict in {"PASS", "PASSED", "APPROVED"} else verdict.lower() or str(review_latest.get("state", "unknown"))
        # The review job's outcome may carry the document hash at review time;
        # we don't have it from the job metadata alone, so we re-compare against
        # the current document hash using the hash recorded in the review report
        # if available — but the safest check is to require re-review once the
        # current document hash differs from the review-time hash.
        # We approximate by reading the review's Change Review Report if it
        # records the hash; otherwise we require the review to be recent.
        review_hash = review_latest.get("document_hash")
    if review_signoff != "approved":
        raise HTTPException(409, "The latest review has not signed off. Run the review agent and approve before cleanup.")

    # Hash staleness: the story requires the review to be for the *current*
    # document hash. If the review record carries a hash, compare it directly.
    current_hash = ""
    try:
        current_hash = _sha(document)
    except OSError:
        pass
    if not review_hash:
        raise HTTPException(409, "The latest review has no document-hash record. Run a fresh review before cleanup.")
    if review_hash != current_hash:
        raise HTTPException(409, "The review was performed on an older version of the document. Re-run the review after your latest edits.")

    revisions, revision_label = (revision_counter or _count_unresolved_revisions)(document)
    if revisions > 0:
        raise HTTPException(409, f"Unresolved tracked changes remain ({revision_label}). Accept or reject them in Word, then run the review agent again.")

    backup_dest = document.with_name(f"{document.name}.before_section_{section.replace('.', '_')}_cleanup.bak")

    gates = [
        CleanupGate(key="review_signoff", required=True, satisfied=True,
                    detail=f"Latest review approved for section {section}"),
        CleanupGate(key="hash_current", required=True, satisfied=review_hash == current_hash,
                    detail="Review is on the current document hash" if review_hash == current_hash else "Review is on an older document hash"),
        CleanupGate(key="word_locked", required=True, satisfied=word_lock is None,
                    detail="No Word lock" if word_lock is None else f"Word lock: {word_lock.name}"),
        CleanupGate(key="framework_locked", required=True, satisfied=True,
                    detail="No framework lock"),
        CleanupGate(key="unresolved_revisions", required=True, satisfied=revisions <= 0,
                    detail=revision_label),
    ]

    preflight_payload = CleanupPreflight(
        system=project.get("label") or project["key"],
        project_key=project["key"],
        section=section,
        document=document.name,
        document_hash=current_hash,
        review_signoff=review_signoff,
        review_signoff_satisfied=True,
        word_locked=False,
        framework_locked=False,
        unresolved_revisions=revision_label,
        unresolved_revisions_satisfied=revisions <= 0,
        gates=gates,
        backup_destination=str(backup_dest),
        confirmation_required=True,
    )
    return preflight_payload.model_dump()


def submit(
    agents_dir: Path,
    manager: jobs.JobManager,
    project: dict[str, str],
    section: str,
    request: dict[str, Any],
    **checks: Any,
) -> dict[str, Any]:
    """Submit a cleanup job through the S259 runner after every gate passes."""
    if request.get("confirmed") is not True:
        raise HTTPException(422, "Explicit cleanup confirmation is required.")
    plan = preflight(agents_dir, project, section, request, **checks)
    job = manager.submit(project, "cleanup", CommandRequest(target=section))
    audit = Path(project["work_dir"]).expanduser() / "evidence-browser-audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "event": "cleanup_requested", "project": project["key"],
            "section": section, "job_id": job.id,
            "document_hash": plan["document_hash"],
            "backup_destination": plan["backup_destination"],
        }, separators=(",", ":")) + "\n")
    return {
        "job": job.model_dump(),
        "section": section,
        "document": plan["document"],
        "document_hash": plan["document_hash"],
        "backup_destination": plan["backup_destination"],
        "preflight": plan,
    }


def _parse_cleanup_output(job: dict[str, Any]) -> dict[str, Any]:
    """Extract cleanup-significant fields from the job's stdout JSON."""
    stdout = str(job.get("stdout_tail") or "")
    parsed, _ = commands.parse_json_output(stdout)
    data = parsed if isinstance(parsed, dict) else {}
    result = data.get("cleanup_result") or data.get("result") or data.get("finalized") or ""
    if isinstance(result, bool):
        result = "FINALISED" if result else "STOPPED"
    result = str(result).upper()
    if result not in {"FINALISED", "STOPPED", "UNKNOWN"}:
        if job.get("state") == "succeeded":
            result = "FINALISED"
        elif job.get("state") == "failed":
            result = "STOPPED"
    validation = data.get("validation") or {}
    if isinstance(validation, dict):
        validation = {str(k): bool(v) for k, v in validation.items()}
    removed = data.get("removed") or data.get("removed_artifacts") or []
    if not isinstance(removed, list):
        removed = [str(removed)]
    retained = data.get("retained") or data.get("retained_artifacts") or []
    if not isinstance(retained, list):
        retained = [str(retained)]
    return {
        "result": result,
        "backup": data.get("backup") or data.get("backup_path"),
        "document_hash": data.get("document_hash"),
        "revisions_before": _as_int(data.get("revisions_before")),
        "revisions_after": _as_int(data.get("revisions_after")),
        "accepted_revisions": _as_int(data.get("accepted_revisions") or data.get("accepted")),
        "removed": removed,
        "retained": retained,
        "section_state": str(data.get("section_state") or data.get("section") or "unknown"),
        "validation": validation,
        "stop_reason": data.get("stop_reason"),
        "raw": data,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def outcome(job: dict[str, Any]) -> dict[str, Any]:
    """Summarize a completed (or terminal) cleanup job for the UI."""
    parsed = _parse_cleanup_output(job)
    state = job.get("state", "")
    failure_reason: str | None = None
    if state == "failed":
        failure_reason = str(job.get("stderr_tail") or job.get("message") or parsed.get("stop_reason") or "Cleanup job failed.")
        if parsed["result"] not in {"STOPPED", "FINALISED"}:
            parsed["result"] = "STOPPED"
    elif state == "interrupted":
        failure_reason = "Cleanup interrupted — document left in a recoverable state."
        parsed["result"] = "STOPPED"
    elif state == "cancelled":
        failure_reason = "Cancelled by operator."
        parsed["result"] = "STOPPED"

    # Recovery instructions: the framework keeps a backup; we surface that path
    # and the documented restore path.
    recovery: list[str] = []
    if parsed["backup"]:
        recovery.append("A pre-cleanup backup was created.")
    recovery.append("To restore: close Word, copy the backup back over the working document, then re-run review to re-approve.")
    recovery.append("Re-run the review agent after restoring to re-approve the section before attempting cleanup again.")

    return {
        "state": state,
        "result": parsed["result"],
        "backup": parsed["backup"],
        "document_hash": parsed["document_hash"],
        "revisions_before": parsed["revisions_before"],
        "revisions_after": parsed["revisions_after"],
        "accepted_revisions": parsed["accepted_revisions"],
        "removed_artifacts": parsed["removed"],
        "retained_artifacts": parsed["retained"],
        "section_state": parsed["section_state"],
        "validation": parsed["validation"],
        "recovery_instructions": recovery,
        "failure_reason": failure_reason,
        "raw": parsed["raw"],
    }


def latest(agents_dir: Path, project: dict[str, str], section: str) -> dict[str, Any] | None:
    """Find the most recent cleanup job for a section in this project. Returns None if none."""
    work_dir = Path(project["work_dir"]).expanduser()
    ui_jobs = work_dir / "ui-jobs"
    if not ui_jobs.is_dir():
        return None

    best: dict[str, Any] | None = None
    best_time = ""
    for metadata in ui_jobs.glob("*/metadata.json"):
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("operation") != "cleanup":
            continue
        if data.get("project_key") != project["key"]:
            continue
        if data.get("target") != section and str(section) not in str(data.get("display_args", "")):
            continue
        created = data.get("created_at", "")
        if created and created > best_time:
            best_time = created
            best = data

    if best is None:
        return None

    return {
        "job_id": best.get("id"),
        "state": best.get("state"),
        "section": section,
        "created_at": best.get("created_at"),
        "finished_at": best.get("finished_at"),
        "exit_code": best.get("exit_code"),
    }
