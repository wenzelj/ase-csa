"""S268 – Review workflow: submit, track, and report the framework review agent run."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import commands, documents, jobs, word_review
from .models import CommandRequest, ReviewReport


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_review_output(job: dict[str, Any]) -> dict[str, Any]:
    """Extract review-significant fields from the job's stdout JSON."""
    stdout = str(job.get("stdout_tail") or "")
    parsed, _ = commands.parse_json_output(stdout)
    data = parsed if isinstance(parsed, dict) else {}
    return {
        "review_signoff": data.get("verdict") or data.get("review_signoff") or data.get("section_verdict"),
        "section_breakdown": data.get("section_breakdown") or data.get("sections") or [],
        "findings": data.get("findings") or data.get("blocked") or [],
        "breaking": data.get("breaking") or {"area": "none", "detail": ""},
        "report_path": str(data.get("report_path") or data.get("report") or data.get("report_file")) or None,
        "raw": data,
    }


def _latest_review_dir(work_dir: Path) -> Path | None:
    reviews = work_dir / "reviews"
    if not reviews.is_dir():
        return None
    reports = sorted(reviews.glob("**/*ChangeReviewReport*.md"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if not reports:
        return None
    # The report lives at project/versions/vN/.../reviews/ or similar;
    # we return the report's own directory for path context.
    return reports[0].parent


def submit(agents_dir: Path, manager: jobs.JobManager, project: dict[str, str], section: str, request: dict[str, Any]) -> dict[str, Any]:
    """Submit a review job. Returns the job record and preflight info."""
    if request.get("confirmed") is not True:
        raise HTTPException(422, "Explicit review confirmation is required.")

    # Pre-flight: document must exist.
    doc = documents.resolve(project)
    if doc.get("state") != "ready" or not doc.get("path"):
        raise HTTPException(409, "The authoritative working document is unavailable.")

    # Word lock check (JobManager also enforces, but fail fast for the UI).
    lock = jobs.word_lock(project)
    if lock is not None:
        raise HTTPException(409, f"The working document is open in Word ({lock.name}). Close it before running review.")

    approval = word_review.build_review(agents_dir, project)
    if approval.get("gate") != "ready_for_review":
        raise HTTPException(409, approval.get("reason") or "Save and close the Word document before review.")

    job = manager.submit(project, "review", CommandRequest(target=section))
    document_hash = hashlib.sha256(Path(doc["path"]).read_bytes()).hexdigest()
    context = Path(project["work_dir"]).expanduser() / "ui-jobs" / job.id / "review-context.json"
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text(json.dumps({"section": section, "document": str(doc["path"]),
                                   "document_hash": document_hash, "word_gate_hash": approval.get("sha256")}, indent=2) + "\n",
                       encoding="utf-8")

    # Audit entry
    audit = Path(project["work_dir"]).expanduser() / "evidence-browser-audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "event": "review_requested", "project": project["key"],
            "section": section, "job_id": job.id,
        }, separators=(",", ":")) + "\n")

    return {"job": job.model_dump(), "section": section, "document": doc["path"], "document_name": Path(doc["path"]).name,
            "document_hash": document_hash}


def outcome(job: dict[str, Any], project: dict[str, str] | None = None) -> dict[str, Any]:
    """Summarize a completed (or terminal) review job."""
    parsed = _parse_review_output(job)
    state = job.get("state", "")
    if state == "failed" and not parsed.get("review_signoff"):
        parsed["failure_reason"] = str(job.get("stderr_tail") or job.get("message") or "Review job failed.")
    elif state == "cancelled" and not parsed.get("review_signoff"):
        parsed["failure_reason"] = "Cancelled by operator."
    return {"state": state, "review_signoff": parsed.get("review_signoff"),
            "section_breakdown": parsed.get("section_breakdown"), "findings": parsed.get("findings"),
            "breaking": parsed.get("breaking"), "report_path": parsed.get("report_path"),
            "failure_reason": parsed.get("failure_reason"), "raw": parsed.get("raw")}


def latest(agents_dir: Path, project: dict[str, str], section: str) -> dict[str, Any] | None:
    """Find the most recent review job for a section in this project. Returns None if none."""
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
        if data.get("operation") != "review":
            continue
        if data.get("project_key") != project["key"]:
            continue
        # Target is the section number
        if data.get("target") != section and str(section) not in str(data.get("display_args", "")):
            continue
        created = data.get("created_at", "")
        if created and created > best_time:
            best_time = created
            best = data

    if best is None:
        return None

    report_dir = _latest_review_dir(work_dir)
    folder = Path(project["work_dir"]).expanduser() / "ui-jobs" / str(best.get("id"))
    try:
        context = json.loads((folder / "review-context.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        context = {}
    job = dict(best)
    try:
        job["stdout_tail"] = (folder / "stdout.log").read_text(encoding="utf-8")[-65536:]
        job["stderr_tail"] = (folder / "stderr.log").read_text(encoding="utf-8")[-65536:]
    except OSError:
        pass
    summary = outcome(job)
    return {
        "job_id": best.get("id"),
        "state": best.get("state"),
        "section": section,
        "created_at": best.get("created_at"),
        "finished_at": best.get("finished_at"),
        "exit_code": best.get("exit_code"),
        "report_dir": str(report_dir) if report_dir else None,
        "document_hash": context.get("document_hash"),
        "review_signoff": summary.get("review_signoff"),
        "findings": summary.get("findings") or [],
    }
