"""Pure preview/validation for registering a new CSA application.

This layer validates a new project's configuration and returns the exact registry,
project-context and knowledge metadata values that would be written -- it writes
nothing itself. Registration happens through the framework (S514); this module only
decides what would be written and whether each field is acceptable.

Conventions kept here:

- discovery defaults to ``<root>/Discovery`` and knowledge to ``<root>/00 Knowlege`` exactly
  (the browser contract spells the knowledge folder "Knowlege");
- all project paths stay inside the new root, except paths explicitly identified as
  existing template or legacy material;
- optional fields (estate, sites, spec mode, application skills, legacy/working
  documents, extra context fields) may be omitted.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

DISCOVERY_DEFAULT = "Discovery"
KNOWLEDGE_DEFAULT = "00 Knowlege"
LANES = ("build", "revise")
SPEC_MODES = ("on", "off", "shadow")
CONTEXT_TEMPLATE_FIELDS = (
    "assessment_name", "assessment_type", "program", "environment", "application",
    "organisation", "as_of_date", "scope_in", "scope_out", "authoritative_sources",
    "terminology", "known_constraints", "stakeholders", "required_deliverables",
    "application_skills",
)
KEY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SITE_ENTRY = re.compile(r"^[A-Z0-9]+=[^\s=,]+$")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _path(value: Any) -> Path | None:
    if value is None or _text(value) == "":
        return None
    return Path(str(value))


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _field(errors: list[dict[str, Any]], field: str, code: str, message: str) -> None:
    errors.append({"field": field, "code": code, "message": message})


def _default_context_fields() -> dict[str, Any]:
    """The default project-context values: the csa-context template, verbatim."""
    template = (Path(__file__).resolve().parents[2] / "csa-templates" / "PROJECT_CONTEXT_TEMPLATE.yaml")
    return {
        "assessment_name": "",
        "assessment_type": "Current State Assessment",
        "program": "",
        "environment": "",
        "application": "",
        "organisation": "",
        "as_of_date": "",
        "scope_in": [],
        "scope_out": [],
        "authoritative_sources": [],
        "terminology": {},
        "known_constraints": [],
        "stakeholders": [],
        "required_deliverables": ["detailed_current_state_assessment", "consumable_summary"],
        "application_skills": [],
        "template_file": str(template),
    }


def preview_project_setup(payload: dict[str, Any], *, agents_dir: Path, base_dir: Path | None = None,
                          existing_keys: list[str] | None = None,
                          existing_project_roots: list[str | Path] | None = None) -> dict[str, Any]:
    """Validate a new project's configuration and return the exact values to be written.

    ``agents_dir`` is the folder that holds ``csa-context/PROJECTS.yaml`` and the
    project-context files. ``base_dir`` is the folder the destination is placed under
    (the CurrentStateAssessments root); it is only used to resolve relative paths and
    never written. ``existing_keys`` and ``existing_project_roots`` are the registry's
    current projects, supplied so this function stays pure and testable.

    Returns a dict with ``status`` (``"READY"`` or ``"BLOCKED"``), ``errors`` (one
    ``{"field", "code", "message"}`` per problem), and ``values`` holding the exact
    ``registry``, ``project_context`` and ``knowledge`` payloads plus the derived
    paths, written as-is when a writer is added. Nothing is written here.
    """
    errors: list[dict[str, Any]] = []
    agents_dir = Path(agents_dir)
    base_dir = Path(base_dir) if base_dir else agents_dir.parent
    existing_keys = [str(k) for k in (existing_keys or [])]
    existing_roots = [Path(r) for r in (existing_project_roots or [])]

    key = _text(payload.get("key"))
    label = _text(payload.get("label"))
    if not key:
        _field(errors, "key", "BLANK_KEY", "The project key is required and cannot be blank.")
    elif not KEY.match(key):
        _field(errors, "key", "BAD_KEY",
               "The project key must start with a lowercase letter and use lowercase letters, digits and hyphens only.")
    if key in existing_keys:
        _field(errors, "key", "DUPLICATE_KEY", f"A project with key \"{key}\" is already registered.")
    if not label:
        _field(errors, "label", "BLANK_LABEL", "The project label is required and cannot be blank.")

    destination = _path(payload.get("destination"))
    if destination is None:
        destination = _path(payload.get("project_root"))
    if destination is None:
        _field(errors, "destination", "MISSING_DESTINATION",
               "A destination folder for the new project is required.")
        destination = base_dir / key if key else base_dir / "new-project"
    try:
        if destination.is_absolute():
            root = destination.expanduser().resolve()
        else:
            root = (base_dir / destination).resolve()
    except (OSError, RuntimeError) as error:
        _field(errors, "destination", "BAD_DESTINATION", f"The destination folder cannot be resolved ({error}).")
        root = base_dir / "new-project"

    if destination.exists():
        _field(errors, "destination", "DESTINATION_EXISTS",
               "The destination folder already exists; choose a new folder name.")
    else:
        for existing in existing_roots:
            if root == existing.resolve() or _is_inside(root, existing.resolve()) or _is_inside(existing.resolve(), root):
                _field(errors, "destination", "DESTINATION_CONFLICTS",
                       "The destination overlaps an existing project folder.")
                break

    def project_path(field: str, value: Any, *, allow_existing: bool = False) -> Path | None:
        path = _path(value)
        if path is None:
            return None
        resolved = path.expanduser()
        if not resolved.is_absolute():
            resolved = (base_dir / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if not allow_existing and not _is_inside(resolved, root):
            _field(errors, field, "PATH_OUTSIDE_ROOT",
                   f"{_text(value)} is not inside the new project root.")
        return resolved

    discovery_path = project_path("discovery", payload.get("discovery"))
    if discovery_path is None:
        discovery_path = root / DISCOVERY_DEFAULT

    knowledge_path = project_path("knowledge", payload.get("knowledge"))
    if knowledge_path is None:
        knowledge_path = root / KNOWLEDGE_DEFAULT

    knowledge_metadata: dict[str, Any] = {"documents": [], "system_terms": []}
    raw_knowledge = payload.get("knowledge_sources")
    if raw_knowledge is None:
        raw_knowledge = payload.get("knowledge_metadata")
    if isinstance(raw_knowledge, str):
        try:
            raw_knowledge = json.loads(raw_knowledge)
        except json.JSONDecodeError as error:
            _field(errors, "knowledge_sources", "BAD_JSON",
                   f"The knowledge sources metadata is not valid JSON ({error}).")
            raw_knowledge = {}
    if raw_knowledge is not None:
        if not isinstance(raw_knowledge, dict):
            _field(errors, "knowledge_sources", "BAD_SHAPE",
                   "The knowledge sources metadata must be a JSON object with \"documents\" and \"system_terms\".")
        else:
            if "documents" in raw_knowledge and not isinstance(raw_knowledge["documents"], list):
                _field(errors, "knowledge_sources", "BAD_SHAPE", "\"documents\" must be a list.")
            if "system_terms" in raw_knowledge and not isinstance(raw_knowledge["system_terms"], list):
                _field(errors, "knowledge_sources", "BAD_SHAPE", "\"system_terms\" must be a list.")
            for index, document in enumerate(raw_knowledge.get("documents") or []):
                if not isinstance(document, dict) or not _text(document.get("file")):
                    _field(errors, "knowledge_sources", "BAD_DOCUMENT",
                           f"Document {index + 1} needs at least a \"file\" name.")
            knowledge_metadata = {
                "documents": copy.deepcopy(list(raw_knowledge.get("documents") or [])),
                "system_terms": copy.deepcopy(list(raw_knowledge.get("system_terms") or [])),
            }
            if "about" in raw_knowledge:
                knowledge_metadata["about"] = raw_knowledge["about"]

    lane = _text(payload.get("lane")).lower()
    if not lane:
        lane = "build"
    if lane not in LANES:
        _field(errors, "lane", "BAD_LANE", f"The assessment lane must be one of: {', '.join(LANES)}.")

    stage = _text(payload.get("stage")).lower()
    if not stage:
        stage = "draft"
    if stage not in ("draft", "v1"):
        _field(errors, "stage", "BAD_STAGE", 'The assessment stage must be "draft" or "v1".')

    spec_mode = _text(payload.get("spec_mode")).lower()
    if not spec_mode:
        spec_mode = "off"
    if spec_mode not in SPEC_MODES:
        _field(errors, "spec_mode", "BAD_SPEC_MODE", f"Spec mode must be one of: {', '.join(SPEC_MODES)}.")

    estate = _text(payload.get("estate"))

    sites = _text(payload.get("sites"))
    if sites:
        for entry in [e.strip() for e in sites.split(",") if e.strip()]:
            if not SITE_ENTRY.match(entry):
                _field(errors, "sites", "BAD_SITES",
                       f"\\\"{entry}\\\" is not a valid site entry (use PREFIX=Name, comma separated).")
                break

    template_path = project_path("template_docx", payload.get("template_docx"), allow_existing=True)
    legacy_docx = project_path("legacy_docx", payload.get("legacy_docx"), allow_existing=True)
    working_docx = project_path("working_docx", payload.get("working_docx"), allow_existing=True)
    index_extra_sources = project_path("index_extra_sources", payload.get("index_extra_sources"), allow_existing=True)

    context = _default_context_fields()
    raw_context = payload.get("context")
    if raw_context is not None:
        if not isinstance(raw_context, dict):
            _field(errors, "context", "BAD_SHAPE", "The project-context fields must be an object.")
        else:
            for field, value in raw_context.items():
                if field not in CONTEXT_TEMPLATE_FIELDS:
                    _field(errors, "context", "UNKNOWN_FIELD", f"\"{field}\" is not a project-context template field.")
                else:
                    context[field] = copy.deepcopy(value)
    application = _text(payload.get("application"))
    if application:
        context["application"] = application

    registry: dict[str, Any] = {
        "key": key,
        "label": label,
        "project_root": str(root),
        "project_context": str(agents_dir / "csa-context" / f"{key.upper().replace('-', '_')}_PROJECT_CONTEXT.yaml"),
        "work_dir": str(root / "csa-work"),
        "default_source_set": str(discovery_path),
    }
    if estate:
        registry["estate"] = estate
    if sites:
        registry["sites"] = sites
    if spec_mode != "off":
        registry["spec_mode"] = spec_mode
    if lane == "revise":
        registry["stage"] = "v1"
    if template_path is not None:
        registry["template_docx"] = str(template_path)
    if legacy_docx is not None:
        registry["legacy_docx"] = str(legacy_docx)
    if working_docx is not None:
        registry["working_docx"] = str(working_docx)
    if index_extra_sources is not None:
        registry["index_extra_sources"] = str(index_extra_sources)

    return {
        "status": "READY" if not errors else "BLOCKED",
        "errors": errors,
        "values": {
            "paths": {
                "project_root": str(root),
                "discovery": str(discovery_path),
                "knowledge": str(knowledge_path),
                "work_dir": str(root / "csa-work"),
            },
            "registry": registry,
            "project_context": context,
            "knowledge": knowledge_metadata,
            "lane": lane,
            "stage": stage,
            "spec_mode": spec_mode,
        },
    }
