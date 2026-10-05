"""Controlled build-lane preview and document generation for S271."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import commands, documents, jobs, pipeline
from .models import BuildGate, BuildSetup, CommandRequest


def _lane(project: dict[str, str]) -> str:
    return str(project.get("assessment_lane") or project.get("workflow_lane") or "revise").strip().lower()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(agents_dir: Path, project: dict[str, str], *, runner: Callable[[str], Any] | None = None) -> dict[str, Any]:
    if _lane(project) != "build":
        raise HTTPException(409, "This project is registered for the revise lane, not assessment generation.")
    snap = pipeline.snapshot(agents_dir, project, runner=runner)
    template = Path(project["template_docx"]).expanduser() if project.get("template_docx") else None
    output = Path(project["build_output_docx"]).expanduser() if project.get("build_output_docx") else None
    section_rows: list[dict[str, Any]] = []
    for section in snap.sections:
        if section.lane != "build":
            continue
        valid = section.validation_result in {"valid", "pass", "passed", "ready"}
        section_rows.append({"stable_key": section.stable_key, "number": section.visible_number,
                             "heading": section.heading, "file": section.section_file,
                             "valid": valid, "issues": [issue.model_dump() for issue in section.issues]})
    gaps = [{"section": row["stable_key"], "reason": "Section source is missing or has not passed validation."}
            for row in section_rows if not row["file"] or not row["valid"]]
    gates = [
        BuildGate(key="registered_build_lane", satisfied=True, detail="Registry explicitly selects the build lane"),
        BuildGate(key="template", satisfied=bool(template and template.is_file()), detail=str(template or "No template registered")),
        BuildGate(key="sections", satisfied=bool(section_rows) and not gaps,
                  detail=f"{len(section_rows) - len(gaps)} of {len(section_rows)} section sources ready"),
        BuildGate(key="output_registered", satisfied=output is not None, detail=str(output or "No output registered")),
        BuildGate(key="output_absent", satisfied=bool(output and not output.exists()),
                  detail="Output is clear" if output and not output.exists() else "Refusing to overwrite an existing document"),
    ]
    ready_preview = all(g.satisfied for g in gates if g.key not in {"output_absent"})
    ready_build = all(g.satisfied for g in gates)
    return BuildSetup(project_key=project["key"], template=str(template) if template else None,
                      template_version=project.get("template_version"), output=str(output) if output else None,
                      document_properties={"title": project.get("label", project["key"]),
                                           "version": project.get("initial_document_version", "0.1")},
                      sections=section_rows, gaps=gaps, gates=gates,
                      ready_for_preview=ready_preview, ready_for_build=ready_build).model_dump()


def submit(agents_dir: Path, manager: jobs.JobManager, project: dict[str, str], *, preview: bool,
           confirmed: bool, setup_runner: Callable[[str], Any] | None = None) -> dict[str, Any]:
    plan = setup(agents_dir, project, runner=setup_runner)
    ready = plan["ready_for_preview"] if preview else plan["ready_for_build"]
    if not ready:
        raise HTTPException(409, "Build preflight has unresolved blockers.")
    if not preview and not confirmed:
        raise HTTPException(422, "Explicit build confirmation is required.")
    operation = "build_preview" if preview else "build"
    job = manager.submit(project, operation, CommandRequest())
    return {"job": job.model_dump(), "preflight": plan, "preview": preview}


def outcome(job: dict[str, Any], *, preview: bool) -> dict[str, Any]:
    parsed, _ = commands.parse_json_output(str(job.get("stdout_tail") or ""))
    data = parsed if isinstance(parsed, dict) else {}
    document = data.get("document") or data.get("output") or data.get("path")
    path = Path(document).expanduser() if document else None
    digest = _sha(path) if path and path.is_file() else data.get("document_hash")
    return {"state": job.get("state", "unknown"), "preview": preview, "document": str(path) if path else None,
            "document_hash": digest, "backup": data.get("backup"),
            "section_map": data.get("section_map") or data.get("sections") or [],
            "warnings": data.get("warnings") or [], "integrity": data.get("integrity") or {}, "raw": data}
