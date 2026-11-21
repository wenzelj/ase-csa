"""Evidence Browser adapter for the framework answered-document import lane."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import HTTPException

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))

from csa_docx import section_state

from . import commands
from .jobs import JobManager, TERMINAL_STATES
from .models import CommandRequest


def _work(project: dict[str, str]) -> Path:
    return Path(project["work_dir"]).expanduser()


def _sections(project: dict[str, str], rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        key = str(item.get("section_key") or item.get("key") or "")
        if key:
            # This is the shared projection used by Draft and Improve.  The
            # Browser does not infer readiness from import output itself.
            readiness = section_state.project(_work(project), key)
            item["readiness"] = readiness
            item["eligible_for_improve"] = bool(readiness.get("eligible_for_improve"))
        result.append(item)
    return result


def _payload(project: dict[str, str], parsed: Any, *, preview: bool = False,
             job: dict[str, Any] | None = None, exit_code: int | None = None) -> dict[str, Any]:
    data = parsed if isinstance(parsed, dict) else {}
    rows = _sections(project, data.get("sections", []))
    warnings = list(data.get("warnings") or [])
    blockers = list(data.get("blockers") or [])
    for row in rows:
        warnings.extend(row.get("warnings") or [])
        blockers.extend(row.get("blockers") or [])
    state = str((job or {}).get("state") or ("preview" if preview else "unknown"))
    failed = exit_code not in (None, 0) or state in {"failed", "cancelled", "interrupted"}
    framework_status = str(data.get("status") or "")
    status = "FAILED" if failed else framework_status or ("PREVIEW" if preview else state.upper())
    if not failed and framework_status in {"PARTIAL", "BLOCKED", "DRY_RUN"}:
        status = framework_status
    return {
        "status": status,
        "state": state,
        "terminal": preview or state in TERMINAL_STATES,
        "preview": preview,
        "project_key": project["key"],
        "sections": rows,
        "warnings": list(dict.fromkeys(str(value) for value in warnings)),
        "blockers": list(dict.fromkeys(str(value) for value in blockers)),
        "resumable": not preview and status not in {"OK", "SUCCEEDED"},
        "raw": data,
        **({"job": job} if job is not None else {}),
    }


def _request(section: str | None = None, *, dry_run: bool = False, resume: bool = False,
             on_source_change: str = "block", force_source_change: bool = False) -> CommandRequest:
    options: dict[str, str | bool] = {"dry_run": dry_run, "resume": resume,
                                      "on_source_change": on_source_change,
                                      "force_source_change": force_source_change}
    return CommandRequest(target=section or None, options=options)


def preview(agents_dir: Path, project: dict[str, str], section: str | None = None,
            *, on_source_change: str = "block") -> dict[str, Any]:
    if on_source_change not in {"block", "reimport"}:
        raise HTTPException(422, "on_source_change must be block or reimport")
    result = commands.execute(agents_dir, project, "import_answers",
                              _request(section, dry_run=True, on_source_change=on_source_change))
    return _payload(project, result.parsed, preview=True, exit_code=result.exit_code)


def submit(agents_dir: Path, manager: JobManager, project: dict[str, str], section: str | None = None,
           *, resume: bool = True, on_source_change: str = "block",
           force_source_change: bool = False) -> dict[str, Any]:
    if on_source_change not in {"block", "reimport"}:
        raise HTTPException(422, "on_source_change must be block or reimport")
    job = manager.submit(project, "import_answers", _request(
        section, resume=resume, on_source_change=on_source_change,
        force_source_change=force_source_change))
    return _payload(project, {}, job=job.model_dump())


def outcome(project: dict[str, str], job: dict[str, Any]) -> dict[str, Any]:
    parsed, _ = commands.parse_json_output(str(job.get("stdout_tail") or ""))
    return _payload(project, parsed, job=job, exit_code=job.get("exit_code"))
