"""Read-only audit inventory and explicit gap recording for S272."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import jobs
from .models import AuditFinding, AuditSnapshot, CommandRequest

ALLOWED_DISPOSITIONS = {"OPEN", "PARTIAL", "CONFLICT", "NOT_FOUND", "DISCOVERY_REQUIRED", "ANSWERED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_dirs(project: dict[str, str]) -> list[Path]:
    root = Path(project["work_dir"]).expanduser() / "audit"
    return sorted([path for path in root.glob("2*") if (path / "audit.json").is_file()]) if root.is_dir() else []


def _finding_rows(data: dict[str, Any]) -> list[AuditFinding]:
    rows: list[AuditFinding] = []
    counter = 0
    for requirement in data.get("requirements", {}).get("rows", []):
        issues = requirement.get("issues") or []
        if not issues:
            continue
        counter += 1
        rows.append(AuditFinding(id=f"AUD-{counter:03d}", section=str(requirement.get("section") or ""),
                                 severity="high", requirement=str(requirement.get("req") or ""),
                                 claim="; ".join(map(str, issues)), location=str(requirement.get("section") or ""),
                                 disposition="OPEN", action="Find matrix evidence first; search the discovery index only if needed."))
    for section, unknowns in (data.get("unknowns") or {}).items():
        for unknown in unknowns if isinstance(unknowns, list) else [unknowns]:
            counter += 1
            rows.append(AuditFinding(id=f"AUD-{counter:03d}", section=str(section), severity="medium",
                                     claim=str(unknown), location=str(section), disposition="DISCOVERY_REQUIRED",
                                     action="Confirm scope and collect the named source from the application owner."))
    for placeholder in data.get("placeholders") or []:
        counter += 1
        rows.append(AuditFinding(id=f"AUD-{counter:03d}", section=str(placeholder.get("section") or ""),
                                 severity="medium", claim=str(placeholder.get("text") or "Placeholder"),
                                 location=str(placeholder.get("section") or ""), disposition="OPEN",
                                 action="Replace the placeholder with evidence-supported current-state text or an explicit gap."))
    return rows


def snapshot(project: dict[str, str]) -> dict[str, Any]:
    dirs = _audit_dirs(project)
    history = []
    for folder in reversed(dirs):
        try:
            row = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        history.append({"audit_id": row.get("audit_id") or folder.name, "generated_at": row.get("generated_at"),
                        "document": row.get("docx"), "path": str(folder)})
    if not dirs:
        return AuditSnapshot(state="not_started", history=[]).model_dump()
    folder = dirs[-1]
    data = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
    document = Path(str(data.get("docx") or "")).expanduser()
    digest = hashlib.sha256(document.read_bytes()).hexdigest() if document.is_file() else None
    reports = sorted(folder.glob("Audit Report*.md"))
    return AuditSnapshot(state="ready", audit_id=str(data.get("audit_id") or folder.name),
                         document=str(document) if str(document) else None, document_hash=digest,
                         generated_at=data.get("generated_at"), report=str(reports[-1]) if reports else None,
                         findings=_finding_rows(data), history=history).model_dump()


def submit(agents_dir: Path, manager: jobs.JobManager, project: dict[str, str]) -> dict[str, Any]:
    job = manager.submit(project, "audit", CommandRequest())
    return {"job": job.model_dump(), "read_only": True}


def outcome(job: dict[str, Any], project: dict[str, str]) -> dict[str, Any]:
    return {"state": job.get("state", "unknown"), "snapshot": snapshot(project) if job.get("state") == "succeeded" else None,
            "failure_reason": job.get("stderr_tail") or job.get("message")}


def record_gap(project: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    required = {"finding_id", "section", "disposition", "scope", "searched_locations", "recommended_action"}
    missing = [name for name in required if not str(payload.get(name) or "").strip()]
    if missing:
        raise HTTPException(422, f"Gap record is missing: {', '.join(sorted(missing))}")
    disposition = str(payload["disposition"]).upper()
    if disposition not in ALLOWED_DISPOSITIONS - {"ANSWERED"}:
        raise HTTPException(422, "Invalid gap disposition")
    record = {name: payload.get(name) for name in sorted(required)}
    record.update({"disposition": disposition, "recorded_at": _now(), "project_key": project["key"],
                   "statement": "This records an evidence gap, not proof that the capability does not exist."})
    root = Path(project["work_dir"]).expanduser() / "gaps"
    root.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(payload["finding_id"]))
    path = root / f"{safe_id}.json"
    if path.exists():
        raise HTTPException(409, "A gap record already exists for this finding; create a new audit finding instead of rewriting history.")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (Path(project["work_dir"]).expanduser() / "proposal-validation-invalidated").write_text(_now() + "\n", encoding="utf-8")
    return {"state": "recorded", "path": str(path), "record": record}
