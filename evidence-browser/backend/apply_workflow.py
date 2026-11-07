from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import documents, jobs, proposals, validation
from .models import CommandRequest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _framework_locked(project: dict[str, str]) -> bool:
    lock = Path(project["work_dir"]).expanduser() / ".csa-place.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = lock.open("a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
    finally:
        handle.close()


def preflight(agents_dir: Path, project: dict[str, str], section: str, request: dict[str, Any], *,
              proposal_loader: Callable | None = None, validator: Callable | None = None,
              document_resolver: Callable | None = None, word_lock_check: Callable | None = None,
              framework_lock_check: Callable | None = None) -> dict[str, Any]:
    load = proposal_loader or (lambda target: proposals.load(agents_dir, project, target))
    proposal = load(section)
    if request.get("file") != proposal.get("file") or request.get("file_hash") != proposal.get("etag"):
        raise HTTPException(409, "Proposal identity or hash is stale. Reload and validate again.")
    validate = validator or (lambda target, payload: validation.validate(agents_dir, project, target, payload))
    report = validate(section, {"file": proposal["file"], "etag": proposal["etag"]})
    if not report.get("valid") or report.get("file_hash") != proposal["etag"]:
        raise HTTPException(409, "A fresh successful validation for this proposal hash is required.")
    selected = (document_resolver or documents.resolve)(project)
    if selected.get("state") != "ready" or not selected.get("path"):
        raise HTTPException(409, "The authoritative working document is ambiguous or unavailable.")
    document = Path(selected["path"])
    lock = (word_lock_check or jobs.word_lock)(project)
    if lock is not None:
        raise HTTPException(409, f"The working document is open in Word ({lock.name}).")
    if (framework_lock_check or _framework_locked)(project):
        raise HTTPException(409, "Another framework document operation holds the project lock.")
    records = proposal.get("records") or []
    return {"system": project.get("label") or project["key"], "project_key": project["key"],
            "section": proposal["section"], "proposal": proposal["file"], "proposal_hash": proposal["etag"],
            "document": document.name, "document_path": str(document), "document_hash": _sha(document),
            "edit_count": len(records) if proposal.get("lane") == "revise" else 1,
            "edit_ids": [row.get("edit_id") for row in records], "validation": report,
            "confirmation_required": True}


def submit(agents_dir: Path, manager: Any, project: dict[str, str], section: str, request: dict[str, Any], **checks) -> dict[str, Any]:
    if request.get("confirmed") is not True:
        raise HTTPException(422, "Explicit application confirmation is required.")
    plan = preflight(agents_dir, project, section, request, **checks)
    job = manager.submit(project, "apply", CommandRequest(target=plan["section"]["visible_number"],
                                                            options={"until_done": True}))
    audit = Path(project["work_dir"]).expanduser() / "evidence-browser-audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "apply_requested", "project": project["key"],
                                 "section": plan["section"]["visible_number"], "proposal": plan["proposal"],
                                 "proposal_hash": plan["proposal_hash"], "edit_count": plan["edit_count"],
                                 "job_id": job.id}, separators=(",", ":")) + "\n")
    return {"job": job.model_dump(), "preflight": plan}


def outcome(job: dict[str, Any]) -> dict[str, Any]:
    text = str(job.get("stdout_tail") or "")
    parsed, _ = __import__("backend.commands", fromlist=["parse_json_output"]).parse_json_output(text)
    data = parsed if isinstance(parsed, dict) else {}
    applied = data.get("applied") or []
    already = data.get("already_applied") or []
    blocked = data.get("blocked") or []
    state = "partial" if applied and (blocked or data.get("next_edit_id")) else job.get("state")
    return {"state": state, "applied": applied, "already_applied": already,
            "skipped": data.get("skipped") or [], "blocked": blocked, "backup": data.get("backup"),
            "warnings": data.get("warnings") or [], "next_edit_id": data.get("next_edit_id"), "raw": data}
