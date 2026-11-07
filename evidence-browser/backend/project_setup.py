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
import os
import re
import shutil
import time
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
    registry["knowledge_dir"] = Path(knowledge_path).name

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


# ---------------------------------------------------------------------------
# Confirmed commit (S514: atomic project registration)
# ---------------------------------------------------------------------------

#: Fixed registry key order for the always-present fields (key and label first).
_ALWAYS_KEY_ORDER = ("key", "label", "project_root", "project_context",
                     "work_dir", "default_source_set")

#: Optional registry fields, in the order they are written (only when selected).
_OPTIONAL_KEY_ORDER = ("estate", "sites", "spec_mode", "stage", "template_docx",
                       "legacy_docx", "working_docx", "index_extra_sources",
                       "knowledge_dir")

#: Top-level folders the commit creates when the upload did not include them.
#: ``csa-work`` is always (re)created empty by the commit; the knowledge folder
#: name is the project's (``00 Knowlege`` for new projects).
_FRAMEWORK_DIRS = ("csa-work", "Discovery")


class _CommitLock:
    """Exclusive lock for one agents directory; holds an open file for its lifetime.

    Uses ``fcntl.flock`` on a file in the agents directory so two commits (or a
    commit and another registry writer) for the same workspace cannot interleave.
    """

    def __init__(self, agents_dir: Path):
        self._path = Path(agents_dir) / ".commit.lock"
        self._handle = None

    def acquire(self) -> bool:
        import fcntl
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+")
        try:
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._handle.close()
            self._handle = None
            return False

    def release(self) -> None:
        import fcntl
        if self._handle is not None:
            try:
                fcntl.flock(self._handle, fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


def _existing_project_keys(registry_file: Path) -> list[str]:
    """Keys of the projects already in the registry (flat, first-key form)."""
    if not registry_file.is_file():
        return []
    keys: list[str] = []
    for raw in registry_file.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s.startswith("- key:"):
            keys.append(s[len("- key:"):].strip().strip("\"'"))
    return keys


def _project_root_overlap(registry_file: Path, root: Path) -> str | None:
    """Return the key of an existing project whose project_root overlaps ``root``."""
    if not registry_file.is_file():
        return None
    text = registry_file.read_text(encoding="utf-8")
    entries = text.split("  - key: ")[1:]
    for entry in entries:
        key = entry.split(":", 1)[0].strip().strip("\"'")
        for line in entry.splitlines():
            t = line.strip()
            if t.startswith("project_root:"):
                value = t[len("project_root:"):].strip().strip("\"'")
                if not value:
                    break
                try:
                    existing = Path(value).expanduser().resolve()
                except OSError:
                    break
                if root == existing or _is_inside(root, existing) or _is_inside(existing, root):
                    return key
                break
    return None


def _registry_entry_text(registry: dict[str, Any]) -> str:
    """Render one project entry for PROJECTS.yaml (two-space list indent)."""
    lines = []
    for i, field in enumerate(_ALWAYS_KEY_ORDER):
        prefix = "  - " if i == 0 else "    "
        lines.append(f"{prefix}{field}: {json.dumps(str(registry[field]))}")
    for field in _OPTIONAL_KEY_ORDER:
        if field in registry:
            lines.append(f"    {field}: {json.dumps(str(registry[field]))}")
    return "\n".join(lines)


def _context_file_text(context: dict[str, Any]) -> str:
    """Render the project-context file from the template's fixed field order."""
    lines = ["project:"]
    for field in ("assessment_name", "assessment_type", "program", "environment",
                  "application", "organisation", "as_of_date", "scope_in", "scope_out",
                  "authoritative_sources", "terminology", "known_constraints",
                  "stakeholders", "required_deliverables"):
        if field in context:
            lines.append(f"  {field}: {json.dumps(context[field], ensure_ascii=False)}")
    if context.get("application_skills"):
        lines.append(f"  application_skills: {json.dumps(context['application_skills'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _staged_tree_ok(source: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Revalidate a staged upload tree: symlinks, byte counts, exact manifest."""
    errors: list[dict[str, Any]] = []
    if not source.is_dir():
        return [{"field": "staging", "code": "STAGING_MISSING",
                 "message": "The staged upload folder is missing."}]
    manifest_files = {e["path"] for e in entries if e["kind"] == "file"}
    manifest_dirs = {e["path"] for e in entries if e["kind"] == "dir"}
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(source):
        rel = Path(dirpath).relative_to(source)
        for name in dirnames:
            p = Path(dirpath) / name
            if p.is_symlink():
                errors.append({"field": "staging", "code": "SYMLINK_FOUND",
                               "message": f"Symlink found at {(rel / name).as_posix()}."})
        for name in filenames:
            p = Path(dirpath) / name
            rel_path = (rel / name).as_posix()
            seen.add(rel_path)
            if p.is_symlink():
                errors.append({"field": "staging", "code": "SYMLINK_FOUND",
                               "message": f"Symlink found at {rel_path}."})
            elif rel_path not in manifest_files:
                errors.append({"field": "staging", "code": "UNEXPECTED_FILE",
                               "message": f"File {rel_path} is not in the manifest."})
    for entry in entries:
        rel = entry["path"]
        if entry["kind"] == "dir":
            if not (source / rel).is_dir():
                errors.append({"field": "staging", "code": "DIR_MISSING",
                               "message": f"Directory {rel} is missing from the staged tree."})
        else:
            target = source / rel
            if not target.is_file():
                errors.append({"field": "staging", "code": "FILE_MISSING",
                               "message": f"File {rel} is missing from the staged tree."})
            else:
                declared = entry.get("size", 0)
                actual = target.stat().st_size
                if actual != declared:
                    errors.append({"field": "staging", "code": "SIZE_MISMATCH",
                                   "message": f"{rel}: expected {declared} bytes, got {actual}."})
    return errors


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _sessions_map(staging_root: Path) -> dict[str, dict[str, Any]]:
    """The upload session map from ``sessions.json`` ({} when absent or corrupt)."""
    sessions_file = staging_root / "sessions.json"
    if not sessions_file.is_file():
        return {}
    try:
        data = json.loads(sessions_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_sessions(staging_root: Path, sessions: dict[str, dict[str, Any]]) -> None:
    sessions_file = staging_root / "sessions.json"
    sessions_file.parent.mkdir(parents=True, exist_ok=True)
    sessions_file.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


def commit_project_setup(
    payload: dict[str, Any],
    *,
    agents_dir: Path,
    staging_root: Path,
    session_id: str,
    base_dir: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Register a completed upload as one project, atomically.

    Revalidates the staged manifest and the configuration, moves the staged
    top-level folder under ``base_dir`` (the CurrentStateAssessments root),
    creates ``csa-work`` and the ``Discovery`` and knowledge folders when absent
    (the upload content itself is not changed), writes the project-context file
    from the template fields, writes optional knowledge ``sources.json``
    metadata, and appends the project's entry -- with ``knowledge_dir`` and the
    other selected fields -- to ``PROJECTS.yaml``, preserving every other
    registry line. Nothing is indexed and no DOCX is created.

    The destination folder, the key and the context file must not already exist.
    The commit holds an exclusive lock for the whole agents directory while it
    writes; any failure before registration completes rolls back every write it
    made (registry restored from its backup, context file and moved tree
    removed) and reports the recoverable staging state, so the caller can offer
    ``cancel_commit`` or retry.

    Returns ``{"status": "READY", ...}`` on success, or
    ``{"status": "BLOCKED", "errors": [...], "staging": {...}}`` /
    ``{"status": "ERROR", ...}`` otherwise.
    """
    agents_dir = Path(agents_dir)
    staging_root = Path(staging_root)
    base_dir = Path(base_dir) if base_dir else agents_dir.parent
    now = now if now is not None else time.time()
    session_dir = staging_root / session_id
    staging = {"session_id": session_id, "staging_root": str(staging_root),
               "session_dir": str(session_dir), "state": "staged", "recoverable": True}
    registry_file = agents_dir / "csa-context" / "PROJECTS.yaml"

    # --- session state ---------------------------------------------------
    sessions = _sessions_map(staging_root)
    session = sessions.get(session_id)
    if session is None:
        return {"status": "BLOCKED",
                "errors": [{"field": "session_id", "code": "UNKNOWN_SESSION",
                            "message": "Session not found."}],
                "staging": {**staging, "recoverable": False}}
    if session.get("status") == "cancelled":
        return {"status": "BLOCKED",
                "errors": [{"field": "session_id", "code": "SESSION_CANCELLED",
                            "message": "Session has been cancelled."}],
                "staging": {**staging, "recoverable": False}}
    if session.get("status") == "committed":
        return {"status": "BLOCKED",
                "errors": [{"field": "session_id", "code": "ALREADY_COMMITTED",
                            "message": "Session is already committed; its project exists."}],
                "staging": {**staging, "recoverable": False}}
    expires_at = session.get("expires_at")
    if expires_at is not None and now > expires_at and session.get("status") == "uploading":
        return {"status": "BLOCKED",
                "errors": [{"field": "session_id", "code": "SESSION_EXPIRED",
                            "message": "Session has expired."}],
                "staging": staging}

    # --- revalidate configuration ---------------------------------------
    # The destination is the final registered folder, not the staging area:
    # resolve it relative to the base dir when the payload gives a relative path.
    preview_payload = dict(payload)
    for dest_field in ("destination", "project_root"):
        raw = preview_payload.get(dest_field)
        if isinstance(raw, str) and raw.strip():
            p = Path(raw)
            if not p.is_absolute():
                preview_payload[dest_field] = str(base_dir / p)
    preview = preview_project_setup(
        preview_payload, agents_dir=agents_dir, base_dir=base_dir,
        existing_keys=_existing_project_keys(registry_file))
    if preview["status"] != "READY":
        return {"status": "BLOCKED", "errors": preview["errors"], "staging": staging}

    values = preview["values"]
    key = str(preview["values"]["registry"]["key"])
    context = values["project_context"]
    knowledge = values["knowledge"]
    root = Path(values["paths"]["project_root"])
    context_file = Path(values["registry"]["project_context"])

    if root.exists():
        return {"status": "BLOCKED",
                "errors": [{"field": "destination", "code": "DESTINATION_EXISTS",
                            "message": "The destination folder already exists; choose a new folder name."}],
                "staging": staging}
    if context_file.exists():
        return {"status": "BLOCKED",
                "errors": [{"field": "project_context", "code": "CONTEXT_EXISTS",
                            "message": "A project-context file already exists for this key."}],
                "staging": staging}
    overlap = _project_root_overlap(registry_file, root)
    if overlap:
        return {"status": "BLOCKED",
                "errors": [{"field": "destination", "code": "DESTINATION_CONFLICTS",
                            "message": f"The destination overlaps the existing project \"{overlap}\"."}],
                "staging": staging}

    # --- revalidate the staged tree --------------------------------------
    tree_errors = _staged_tree_ok(session_dir, session.get("manifest", []))
    if tree_errors:
        return {"status": "BLOCKED", "errors": tree_errors, "staging": staging}

    # --- lock, then write -------------------------------------------------
    lock = _CommitLock(agents_dir)
    if not lock.acquire():
        return {"status": "BLOCKED",
                "errors": [{"field": "commit", "code": "COMMIT_LOCKED",
                            "message": "Another commit holds the registration lock; try again."}],
                "staging": staging}
    backup_path = None
    context_written = False
    moved_root = False
    try:
        # double-check under the lock (another commit may have finished meanwhile)
        if key in _existing_project_keys(registry_file):
            return {"status": "BLOCKED",
                    "errors": [{"field": "key", "code": "DUPLICATE_KEY",
                                "message": f"A project with key \"{key}\" is already registered."}],
                    "staging": staging}
        if root.exists() or context_file.exists():
            return {"status": "BLOCKED",
                    "errors": [{"field": "destination", "code": "DESTINATION_EXISTS",
                                "message": "The destination folder already exists."}],
                    "staging": staging}
        if _project_root_overlap(registry_file, root):
            return {"status": "BLOCKED",
                    "errors": [{"field": "destination", "code": "DESTINATION_CONFLICTS",
                                "message": "The destination overlaps an existing project folder."}],
                    "staging": staging}

        # 1. move the uploaded tree into place (content is not changed)
        os.replace(session_dir, root)
        moved_root = True

        # 2. framework folders, created when the upload did not include them
        (root / "csa-work").mkdir(parents=True, exist_ok=True)
        (root / "Discovery").mkdir(parents=True, exist_ok=True)
        knowledge_dir = Path(values["paths"]["knowledge"])
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        # 3. project-context file from the template fields
        context_file.parent.mkdir(parents=True, exist_ok=True)
        context_file.write_text(_context_file_text(context), encoding="utf-8")
        context_written = True

        # 4. optional knowledge sources.json (only when the upload carried it)
        if knowledge.get("documents") or knowledge.get("system_terms"):
            sources = {"documents": list(knowledge.get("documents") or []),
                       "system_terms": list(knowledge.get("system_terms") or [])}
            if "about" in knowledge:
                sources["about"] = knowledge["about"]
            (knowledge_dir / "sources.json").write_text(
                json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 5. append the registry entry, preserving every other line
        if not registry_file.is_file():
            return {"status": "ERROR",
                    "errors": [{"field": "registry", "code": "REGISTRY_MISSING",
                                "message": f"The project registry is missing: {registry_file}"}],
                    "staging": staging}
        original = registry_file.read_text(encoding="utf-8")
        backup_path = registry_file.with_name(f"PROJECTS.yaml.commit-{int(now * 1000)}.bak")
        shutil.copy2(registry_file, backup_path)
        entry = _registry_entry_text(values["registry"])
        if original.endswith("\n"):
            merged = original.rstrip("\n") + "\n" + entry + "\n"
        elif original:
            merged = original.rstrip("\n") + "\n" + entry + "\n"
        else:
            merged = entry + "\n"
        registry_file.write_text(merged, encoding="utf-8")

        # 6. mark the session committed (its staging area is gone -- it was moved)
        sessions[session_id]["status"] = "committed"
        sessions[session_id]["committed_at"] = now
        _save_sessions(staging_root, sessions)

        return {
            "status": "READY",
            "project_key": key,
            "project_root": str(root),
            "project_context": str(context_file),
            "registry": str(registry_file),
            "staging": {"session_id": session_id, "state": "committed", "recoverable": False},
        }
    except Exception as error:  # rollback: restore registry, remove partial writes
        if backup_path is not None and backup_path.exists() and registry_file.is_file():
            shutil.copy2(backup_path, registry_file)
        if backup_path is not None and backup_path.exists():
            backup_path.unlink(missing_ok=True)
        if context_written:
            context_file.unlink(missing_ok=True)
        if moved_root:
            _remove_tree(root)
        return {"status": "ERROR",
                "errors": [{"field": "commit", "code": "COMMIT_FAILED",
                            "message": f"Registration failed and was rolled back ({error})."}],
                "staging": staging}
    finally:
        lock.release()


def cancel_commit(
    session_id: str,
    *,
    agents_dir: Path,
    staging_root: Path,
) -> dict[str, Any]:
    """Discard a staged session whose commit failed or was refused. Idempotent.

    Removes the session's staging area and marks it cancelled. The registry and
    context file are never touched here: a failed commit has already rolled its
    own writes back, and a committed session cannot be cancelled.
    """
    agents_dir = Path(agents_dir)
    staging_root = Path(staging_root)
    sessions = _sessions_map(staging_root)
    session = sessions.get(session_id)
    if session is None:
        return {"status": "OK", "cancelled": False}
    if session.get("status") == "cancelled":
        return {"status": "OK", "cancelled": True}
    if session.get("status") == "committed":
        return {"status": "BLOCKED",
                "errors": [{"field": "session_id", "code": "ALREADY_COMMITTED",
                            "message": "Session is already committed; its project exists."}]}
    lock = _CommitLock(agents_dir)
    acquired = lock.acquire()
    try:
        sessions[session_id]["status"] = "cancelled"
        _save_sessions(staging_root, sessions)
    finally:
        if acquired:
            lock.release()
    _remove_tree(staging_root / session_id)
    return {"status": "OK", "cancelled": True}
