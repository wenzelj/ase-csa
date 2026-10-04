from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import commands, proposals
from .models import CommandRequest


Executor = Callable[[str, CommandRequest], Any]
Loader = Callable[[str], dict[str, Any]]
ANCHOR = re.compile(r"@H\d+(?:\.\d+)*(?:-(?:P|T)\d+(?:-R\d+)?)?")
EVIDENCE = re.compile(r"\bE-\d{2,}\b")

FIELD_BY_CODE = {
    "BAD_ID": "edit_id", "DUPLICATE_ID": "edit_id", "WHERE_NOT_STABLE_ID": "target",
    "ANCHOR_UNRESOLVED": "target", "ANCHOR_CHECK_UNAVAILABLE": "target", "BAD_ACTION": "operation",
    "MISSING_TEXT": "replacement", "MISSING_EVIDENCE": "evidence_ids", "UNKNOWN_EVIDENCE": "evidence_ids",
    "EVIDENCE_PENDING": "evidence_ids", "BAD_RATING": "rating", "RATING": "rating",
    "UNTAGGED_FACT": "facts", "FACT_NO_EVIDENCE": "facts", "IP_IN_TEXT": "replacement",
}


def operation_for(lane: str) -> str:
    try:
        return commands.validation_operation(lane).key
    except HTTPException as error:
        raise HTTPException(409, "The section lane is unresolved; validation cannot choose a framework gate") from error


def _normalise(item: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("code") or "UNKNOWN")
    message = str(item.get("message") or "Validation finding")
    severity = str(item.get("level") or item.get("severity") or "INFO").lower()
    edit_id = item.get("edit_id") or item.get("record_id")
    return {"severity": severity, "code": code, "edit_id": edit_id, "record_id": edit_id,
            "field": item.get("field") or FIELD_BY_CODE.get(code),
            "stable_anchor": item.get("stable_anchor") or next(iter(ANCHOR.findall(message)), None),
            "evidence_ids": item.get("evidence_ids") or EVIDENCE.findall(message), "message": message,
            "raw": item}


def validate(agents_dir: Path, project: dict[str, str], section: str, request: dict[str, Any], *,
             loader: Loader | None = None, executor: Executor | None = None) -> dict[str, Any]:
    load = loader or (lambda target: proposals.load(agents_dir, project, target))
    proposal = load(section)
    if request.get("etag") != proposal.get("etag") or request.get("file") != proposal.get("file"):
        raise HTTPException(409, "Proposal identity or file hash changed. Reload before validating.")
    operation = operation_for(str(proposal.get("lane") or ""))
    target = section if operation == "check_change" else str(proposal["file"])
    execute = executor or (lambda key, command: commands.execute(agents_dir, project, key, command))
    result = execute(operation, CommandRequest(target=target))
    parsed = result.parsed if hasattr(result, "parsed") else result.get("parsed", result)
    exit_code = result.exit_code if hasattr(result, "exit_code") else int(result.get("exit_code", 0))
    if not isinstance(parsed, dict):
        raise HTTPException(502, "The framework validator did not return a machine-readable report")
    findings = [_normalise(item) for item in parsed.get("findings", []) if isinstance(item, dict)]
    errors = sum(1 for finding in findings if finding["severity"] == "error")
    warnings = sum(1 for finding in findings if finding["severity"] == "warn" or finding["severity"] == "warning")
    return {"section": proposal["section"], "lane": proposal["lane"], "file": proposal["file"],
            "file_hash": proposal["etag"], "operation": operation, "valid": errors == 0 and exit_code == 0,
            "stale": False, "errors": errors, "warnings": warnings, "findings": findings,
            "raw_report": parsed, "exit_code": exit_code}
