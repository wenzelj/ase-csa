from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from fastapi import HTTPException

from .models import CommandDescriptor, CommandRequest, CommandResult


ALLOWED_PROJECTS = frozenset({"iamps-08", "utcdtc", "tetra-reveloc"})
SAFE_SECTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,139}\.md$")
SAFE_HEADING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &()_.,/+-]{0,119}$")


@dataclass(frozen=True)
class Operation:
    key: str
    title: str
    description: str
    argv: tuple[str, ...]
    target: Literal["none", "optional", "required"] = "none"
    target_kind: Literal["section", "file", "heading"] | None = None
    options: dict[str, Literal["boolean", "identifier"]] = field(default_factory=dict)
    timeout: int = 45
    mutating: bool = False
    lock: Literal["none", "docx"] = "none"

    def descriptor(self) -> CommandDescriptor:
        return CommandDescriptor(
            key=self.key, title=self.title, description=self.description, target=self.target,
            options=self.options, timeout_seconds=self.timeout, mutating=self.mutating, lock=self.lock,
        )


OPERATIONS: dict[str, Operation] = {
    "status": Operation("status", "Section status", "Read the live state of all sections or one section.",
                        ("status",), "optional", "section"),
    "next": Operation("next", "Next action", "Read the framework's next safe pipeline action.", ("next",)),
    "report": Operation("report", "Pipeline report", "Read approval, apply and review metrics.", ("report",)),
    "sections": Operation("sections", "Build sections", "Read build-lane section files and readiness.", ("sections",)),
    "spec_status": Operation("spec_status", "Document structure", "Read the live document specification.",
                             ("spec", "status"), timeout=90),
    "comments": Operation("comments", "Word comments", "Read reviewer comments from the authoritative DOCX.",
                          ("comments",), "optional", "heading", timeout=90),
    "check_change": Operation(
        "check_change", "Validate proposal", "Run the existing change-record validator without applying edits.",
        ("check-change",), "required", "section",
        {"file": "identifier", "no_lint": "boolean", "no_anchors": "boolean"}, timeout=120,
    ),
    "check_section": Operation(
        "check_section", "Validate build section", "Run the existing build-section validator without placing it.",
        ("check-section",), "required", "file", {"no_lint": "boolean"}, timeout=120,
    ),
    "review": Operation(
        "review", "Review section", "Run the framework review agent: verify applied edits, comments and DOCX integrity.",
        ("review",), "required", "section",
        {}, timeout=900, mutating=True, lock="docx",
    ),
    "apply": Operation(
        "apply", "Apply validated proposal", "Apply through the framework with tracked changes and backups.",
        ("apply",), "required", "section", {"until_done": "boolean"}, timeout=900,
        mutating=True, lock="docx",
    ),
    "cleanup": Operation(
        "cleanup", "Cleanup section", "Finalise a reviewed section: accept signed-off changes and remove framework scaffolding.",
        ("cleanup",), "required", "section",
        {}, timeout=900, mutating=True, lock="docx",
    ),
    "author": Operation(
        "author", "Author proposal", "Draft an evidence-grounded proposal for one section (no-apply; routed to validation, never applied).",
        ("author",), "required", "section",
        {"cards": "boolean", "no_apply": "boolean"}, timeout=1800, mutating=False, lock="none",
    ),
    "build_preview": Operation(
        "build_preview", "Preview assessment build", "Generate a throwaway candidate from validated build-lane section sources.",
        ("build", "--preview"), timeout=900,
    ),
    "build": Operation(
        "build", "Build assessment", "Generate the registered assessment document from validated section sources.",
        ("build",), timeout=900, mutating=True, lock="docx",
    ),
    "audit": Operation(
        "audit", "Audit assessment", "Run the framework's read-only assessment audit and preserve its report artifacts.",
        ("audit",), timeout=900,
    ),
}


def catalogue() -> list[dict[str, Any]]:
    return [operation.descriptor().model_dump() for operation in OPERATIONS.values()]


def validation_operation(lane: str) -> Operation:
    """The one authoritative validation gate for a framework section lane."""
    key = {"revise": "check_change", "build": "check_section"}.get(lane)
    if key is None:
        raise HTTPException(409, "The section lane is unresolved")
    return OPERATIONS[key]


def _validate_identifier(value: str, kind: str) -> str:
    value = value.strip()
    if not value or ".." in value or "/" in value or "\\" in value:
        raise HTTPException(422, f"Invalid {kind} identifier")
    pattern = SAFE_FILE if kind == "file" else SAFE_HEADING if kind == "heading" else SAFE_SECTION
    if not pattern.fullmatch(value):
        raise HTTPException(422, f"Invalid {kind} identifier")
    return value


def build_argv(agents_dir: Path, project_key: str, operation_key: str, request: CommandRequest) -> tuple[Operation, list[str]]:
    if project_key not in ALLOWED_PROJECTS:
        raise HTTPException(403, "Project is not exposed by the CSA editing workspace")
    operation = OPERATIONS.get(operation_key)
    if operation is None:
        raise HTTPException(404, "Unknown editing operation")
    unknown = set(request.options) - set(operation.options)
    if unknown:
        raise HTTPException(422, f"Unsupported option(s): {', '.join(sorted(unknown))}")
    if operation.target == "required" and not request.target:
        raise HTTPException(422, "This operation requires a target")
    if operation.target == "none" and request.target:
        raise HTTPException(422, "This operation does not accept a target")

    argv = [str((agents_dir / "bin" / "csa").resolve()), "--project", project_key, *operation.argv]
    if request.target:
        target = _validate_identifier(request.target, operation.target_kind or "section")
        if operation.key == "comments":
            argv += ["--heading", target]
        else:
            argv.append(target)
    for name, value in request.options.items():
        kind = operation.options[name]
        flag = "--" + name.replace("_", "-")
        if kind == "boolean":
            if not isinstance(value, bool):
                raise HTTPException(422, f"Option {name} must be true or false")
            if value:
                argv.append(flag)
        else:
            if not isinstance(value, str):
                raise HTTPException(422, f"Option {name} must be an identifier")
            argv += [flag, _validate_identifier(value, "section")]
    if operation.key not in {"author", "review", "cleanup", "build_preview", "build", "audit"}:
        argv.append("--json")
    return operation, argv


def _minimal_environment(agents_dir: Path) -> dict[str, str]:
    allowed = ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "USER")
    env = {name: os.environ[name] for name in allowed if os.environ.get(name)}
    env["CSA_AGENTS_DIR"] = str(agents_dir.resolve())
    if os.environ.get("CSA_PROJECTS_FILE"):
        env["CSA_PROJECTS_FILE"] = os.environ["CSA_PROJECTS_FILE"]
    return env


def parse_json_output(output: str) -> tuple[Any | None, bool]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"(?m)^[\[{]", output):
        try:
            parsed, _ = decoder.raw_decode(output[match.start():])
            return parsed, True
        except json.JSONDecodeError:
            continue
    return None, False


def _audit(work_dir: Path, event: dict[str, Any]) -> None:
    path = work_dir / "evidence-browser-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")


def execute(agents_dir: Path, project: dict[str, str], operation_key: str,
            request: CommandRequest) -> CommandResult:
    project_key = project["key"]
    operation, argv = build_argv(agents_dir, project_key, operation_key, request)
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    clock = monotonic()
    try:
        process = subprocess.run(
            argv, cwd=str(agents_dir.parent), env=_minimal_environment(agents_dir), shell=False,
            capture_output=True, text=True, timeout=operation.timeout,
        )
        exit_code, stdout, stderr = process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        stderr = (stderr + f"\nCommand timed out after {operation.timeout} seconds").strip()
    finished = datetime.now(timezone.utc)
    duration_ms = round((monotonic() - clock) * 1000)
    parsed, parsed_json = parse_json_output(stdout)
    result = CommandResult(
        correlation_id=correlation_id, operation=operation.key, project_key=project_key,
        started_at=started.isoformat(), finished_at=finished.isoformat(), duration_ms=duration_ms,
        exit_code=exit_code, stdout=stdout, stderr=stderr, parsed=parsed, parsed_json=parsed_json,
    )
    _audit(Path(project["work_dir"]).expanduser(), {
        "correlation_id": correlation_id, "operation": operation.key, "project_key": project_key,
        "classification": "read_only", "started_at": result.started_at, "finished_at": result.finished_at,
        "duration_ms": duration_ms, "exit_code": exit_code, "parsed_json": parsed_json,
    })
    return result
