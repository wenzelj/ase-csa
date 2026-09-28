"""The function factory: a small, fixed set of high-level operations a
tool-calling model (including a small one, e.g. qwen3-4b) can call directly,
instead of reading the long natural-language agent definitions and
constructing CLI invocations/paths itself.

Every function here takes a handful of primitive arguments and returns a
plain JSON-serializable dict. None of them raise outward on ordinary
failure modes (missing section, ambiguous manifest, validation failure) —
those come back as ``{"status": "ERROR", "message": "..."}`` in the same
shape as a success result, so a caller (model or MCP client) never has to
parse a traceback. There is deliberately no "run an arbitrary command" tool
here: everything the small model can do is one of these named operations.

``apply_next_batch`` is the same logic ``cli_apply_section.py`` runs, pulled
out into an importable function so the CLI and the MCP server
(:mod:`csa_docx.mcp`) share one implementation. See qwen-mcp-factory-plan.md
for the design this module implements.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .change_parser import parse_change_file, select_batch
from .docx_package import create_backup, extract_docx
from .manifest import ManifestError, get_manifest, refresh_manifest as _refresh_manifest_impl, resolve_section
from .models import ApplySummary
from .ooxml import DocumentEditor
from .report_writer import update_changes_report
from .run_state import read_completed_ids, state_path, write_state
from .stable_ids import generate_manifest
from .validator import validate_docx


def _error(message: str) -> dict:
    return {"status": "ERROR", "message": message}


def _load_project_registry() -> list[dict]:
    """Parse ``csa-context/PROJECTS.yaml`` -- a small, fixed-shape list of
    project entries -- without requiring PyYAML. Returns ``[]`` if the file
    is missing or unparseable; callers treat an empty registry as "the
    cross-project safety check is unavailable" rather than blocking every
    operation on a framework installation issue.
    """
    registry_path = (
        Path(os.environ["CSA_PROJECTS_FILE"])
        if os.environ.get("CSA_PROJECTS_FILE")
        else Path(__file__).resolve().parents[2] / "csa-context" / "PROJECTS.yaml"
    )
    if not registry_path.is_file():
        return []
    projects: list[dict] = []
    current: dict = {}
    try:
        for raw_line in registry_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if raw_line[:1] not in (" ", "\t"):
                # Top-level key (e.g. the "projects:" list header) -- not
                # part of an entry, so nothing to record.
                continue
            if stripped.startswith("- key:"):
                if current:
                    projects.append(current)
                current = {}
                stripped = stripped[2:]  # drop leading "- "
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip().strip('"').strip("'")
        if current:
            projects.append(current)
    except OSError:
        return []
    return projects


def _resolve_registered_project(workspace_path: Path) -> dict | None:
    """Return the PROJECTS.yaml entry whose ``project_root`` is exactly
    ``workspace_path`` or an ancestor of it, or ``None`` if no registered
    project matches.
    """
    for project in _load_project_registry():
        root = project.get("project_root")
        if not root:
            continue
        try:
            root_path = Path(root).expanduser().resolve()
        except OSError:
            continue
        if workspace_path == root_path or root_path in workspace_path.parents:
            return project
    return None


def _check_workspace_registered(workspace_path: Path) -> dict | None:
    """Cross-project safety guard.

    This framework is shared by more than one CSA project. A stale cwd, an
    unset ``workspace`` argument, or a copy-pasted path from the wrong
    project could otherwise make a tool call silently read or write another
    project's DOCX, run-state, or evidence data. Before any operation
    touches a workspace, confirm that workspace is exactly the
    ``project_root`` of a project registered in ``csa-context/PROJECTS.yaml``
    (or a path under it) -- never a guess, never a partial match.

    Returns an ``{"status": "ERROR", ...}`` dict to hand straight back to
    the caller if the workspace is not registered, or ``None`` if it is
    fine to proceed. If the registry itself can't be read, this check is
    skipped (returns ``None``) rather than blocking every call in the
    framework on an installation problem -- that failure mode is reported
    separately, not silently treated as "safe".
    """
    if not _load_project_registry():
        return None
    if _resolve_registered_project(workspace_path) is not None:
        return None
    return _error(
        "WORKSPACE_NOT_REGISTERED: "
        f"{workspace_path} is not the project_root (or a path under it) of any "
        "project listed in csa-context/PROJECTS.yaml. Refusing to operate against "
        "an unregistered workspace -- this is the cross-project safety guard that "
        "stops one project's agent run from reading or writing another project's "
        "data. If this is a genuine new project, register it in PROJECTS.yaml "
        "first (see the Project Selection step in csa-orchestrator-agent.md); "
        "otherwise check the workspace path passed to this call."
    )


# ---------------------------------------------------------------------------
# Step 0: readiness / lock precondition.
#
# Everything below runs *before* a backup is taken or a byte of the working
# DOCX is touched. A document that is open in Word, half-written, or already
# structurally broken must come back as ``NOT_READY`` -- never as a traceback,
# and never as a half-applied batch on top of a broken file.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Readiness:
    """Outcome of the step-0 preconditions for one working DOCX."""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    message: str = ""
    validation: dict[str, str] = field(default_factory=dict)


def _word_lock_files(docx: Path) -> list[Path]:
    """Existing Word owner/lock files sitting beside ``docx``.

    Word writes a hidden owner file next to the document it has open. Current
    versions name it ``~$`` plus the filename with its first two characters
    dropped (``Report.docx`` -> ``~$port.docx``); the plain ``~$<filename>``
    form also shows up (short names, some older/one-drive paths). Either one
    means a human has the document open, so both are checked.
    """
    candidates = [docx.with_name(f"~${docx.name}")]
    if len(docx.name) > 2:
        candidates.append(docx.with_name(f"~${docx.name[2:]}"))
    return [candidate for candidate in candidates if candidate.exists()]


def _check_document_ready(docx: Path) -> _Readiness:
    """Cheap, non-mutating preconditions for editing ``docx``.

    Checked in increasing order of cost: the path exists and is non-empty,
    no Word lock file sits beside it, it opens as a zip archive (catches a
    mid-write/corrupt package before DocxEngine does), and ``validate_docx``
    already reports no failures. The first failure wins; nothing here ever
    raises outward.
    """
    if not docx.exists():
        return _Readiness(False, ["missing_docx"], f"Working DOCX does not exist: {docx}")

    try:
        size = docx.stat().st_size
    except OSError as exc:
        return _Readiness(False, ["unreadable_docx"], f"Working DOCX cannot be read: {docx} ({exc})")
    if size == 0:
        return _Readiness(
            False,
            ["empty_docx"],
            f"Working DOCX is zero bytes (likely a failed copy or an in-progress write): {docx}",
        )

    locks = _word_lock_files(docx)
    if locks:
        return _Readiness(
            False,
            ["locked_by_word"],
            f"Working DOCX appears to be open in Word (lock file {locks[0].name} is present next to "
            f"{docx.name}). Close the document in Word and retry; nothing was backed up or edited.",
        )

    try:
        with zipfile.ZipFile(docx) as archive:
            corrupt_member = archive.testzip()
    except Exception as exc:  # BadZipFile, OSError, truncated mid-write package, ...
        return _Readiness(
            False,
            ["unreadable_archive"],
            f"Working DOCX is not a readable DOCX (zip) package: {docx} ({type(exc).__name__}: {exc})",
        )
    if corrupt_member:
        return _Readiness(
            False,
            ["unreadable_archive"],
            f"Working DOCX archive is corrupt; first bad member: {corrupt_member} ({docx})",
        )

    try:
        validation = validate_docx(docx)
    except Exception as exc:  # the validator itself should never take a caller down
        return _Readiness(
            False,
            ["validation_failed"],
            f"Pre-flight validation could not run on {docx}: {type(exc).__name__}: {exc}",
        )
    failures = {key: value for key, value in validation.items() if str(value).startswith("Fail")}
    if failures:
        detail = "; ".join(f"{key}: {value}" for key, value in sorted(failures.items()))
        return _Readiness(
            False,
            ["validation_failed"],
            f"Working DOCX already fails integrity checks before any edit was applied -- {detail}",
            validation,
        )

    return _Readiness(True, [], "Document is ready to edit.", validation)


def _section_heading(section_label: str | None) -> str | None:
    if not section_label:
        return None
    if " - " in section_label:
        return section_label.split(" - ", 1)[1].strip()
    return section_label.strip()


def _scope_records(records, start_edit_id, end_edit_id):
    scoped = records
    if start_edit_id:
        try:
            start_index = next(i for i, rec in enumerate(scoped) if rec.edit_id == start_edit_id)
            scoped = scoped[start_index:]
        except StopIteration:
            return []
    if end_edit_id:
        try:
            end_index = next(i for i, rec in enumerate(scoped) if rec.edit_id == end_edit_id)
            scoped = scoped[: end_index + 1]
        except StopIteration:
            return []
    return scoped


def _apply_batch(editor, batch, summary: ApplySummary, author: str, initials: str) -> None:
    for record in batch:
        result = editor.apply_change(record, author, initials)
        summary.results.append(result)
        if result.status == "APPLIED":
            summary.applied.append(record.edit_id)
        elif result.status == "ALREADY_APPLIED":
            summary.already_applied.append(record.edit_id)
        elif result.status == "BLOCKED":
            summary.blocked.append(record.edit_id)
            break
        else:
            summary.unresolved.append(record.edit_id)


def _summary_payload(summary: ApplySummary) -> dict:
    return {
        "status": summary.status,
        "section": summary.section,
        "docx": str(summary.docx),
        "backup": str(summary.backup) if summary.backup else None,
        "change_file": str(summary.change_file),
        "batch_ids": summary.batch_ids,
        "applied": summary.applied,
        "already_applied": summary.already_applied,
        "completed_ids": summary.completed_ids,
        "blocked": summary.blocked,
        "unresolved": summary.unresolved,
        "next_edit_id": summary.next_edit_id,
        "validation": summary.validation,
        "run_state": str(summary.run_state_path) if summary.run_state_path else None,
        "report_updated": summary.report_updated,
        "results": [asdict(result) for result in summary.results],
    }


def _id_manifest_path(workspace: Path, docx: Path) -> Path:
    """Where the stable-ID manifest for a working DOCX is cached on disk.

    Keyed by the resolved *document*, not the section: ``stable_ids``
    computes IDs for every heading/paragraph/table-row in the whole DOCX in
    one pass, unscoped to any one section (:mod:`csa_docx.stable_ids`
    ``generate_manifest`` walks the full paragraph-and-table-row list
    ``DocxEngineEditor.paragraphs_with_table_rows()`` returns, and
    ``section_heading`` is never used to filter it). Most CSA projects
    have every section's change file pointing at the same single working
    DOCX (see ``manifest.py``), so a manifest keyed by section number would
    just be N identical copies of the same document-wide data. Keying by
    the docx path instead means the first ``prepareDocument`` call for any
    section builds it once, and every other section sharing that file gets
    an immediate ``regenerated: false`` no-op -- "prepare the document" and
    "prepare the section" collapse into the same call.
    """
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in docx.stem).strip("_") or "document"
    # Lives beside the working DOCX (``<Final Version>/run-state/``), the same
    # place the section run-state files go (see ``run_state.state_path``).
    # ``workspace`` is kept only so existing callers and tests keep working.
    return docx.parent / "run-state" / f"stable-ids-{safe_name}.json"


def _structure_fingerprint(entries: list[dict]) -> str:
    """Fingerprint of the heading skeleton the stable IDs are derived from.

    Stable IDs are structural: they only move when the heading hierarchy
    itself changes. So the count *and* the order of headings (level plus
    assigned section path) is exactly the drift that invalidates a cached
    manifest -- body text edits deliberately do not.
    """
    skeleton = "\n".join(
        f"{entry.get('level')}:{entry.get('section_path')}"
        for entry in entries
        if entry.get("kind") == "heading"
    )
    return hashlib.sha256(skeleton.encode("utf-8")).hexdigest()


def _id_manifest_counts(entries: list[dict]) -> dict[str, int]:
    counts = {"headings": 0, "paragraphs": 0, "table_rows": 0}
    for entry in entries:
        kind = entry.get("kind")
        if kind == "heading":
            counts["headings"] += 1
        elif kind == "paragraph":
            counts["paragraphs"] += 1
        elif kind == "table_row":
            counts["table_rows"] += 1
    return counts


def _read_id_manifest(path: Path) -> dict | None:
    """The cached ID manifest, or None when it is absent/unreadable.

    An unreadable or truncated cache is treated exactly like a missing one
    (regenerate), never as an error -- the file is derived data.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(slots=True)
class _DocumentTarget:
    """What ``prepareDocument``/``lookupStableId`` resolved to act on.

    ``section``/``change_file`` are ``None`` in the true-step-0 case: the
    working DOCX found before any ``reviews/`` change file exists yet, so
    there is no section to report.
    """

    docx: Path
    section: str | None = None
    change_file: str | None = None


def _find_workspace_docx(workspace: Path) -> Path:
    """The one working ``.docx`` in a workspace with no section manifest yet.

    Step 0, before ``reviewDocument`` (or a human) has created a single
    ``reviews/ChangesCSA_*.md`` file: there is nothing for
    :func:`manifest.get_manifest` to scan, so the document itself has to be
    found directly instead of via a section. Searches recursively (the
    common case really is just one ``.docx`` alone in a folder, but a
    shallow project layout with no change files yet should still resolve),
    skipping Word lock files and anything under an archive/old-looking
    directory (:func:`manifest._is_archived`, the same rule
    ``build_manifest`` uses) so a stray backup never competes with the
    live document. Never guesses: raises :class:`ManifestError` on zero or
    more than one candidate, naming them.
    """
    from .manifest import _is_archived

    candidates = [
        p
        for p in workspace.rglob("*.docx")
        if not p.name.startswith("~$") and not _is_archived(p, workspace)
    ]
    if not candidates:
        raise ManifestError(f"No .docx file found under {workspace}.")
    if len(candidates) > 1:
        # Project folders also hold reference documents (older CSAs, designs, review notes).
        # The working document lives in a "01 Final Version" folder: if exactly one candidate
        # is there, it is the working document. Otherwise still refuse to guess.
        final = [p for p in candidates if any(part.lower() == "01 final version" for part in p.relative_to(workspace).parts[:-1])]
        if len(final) == 1:
            return final[0]
    if len(candidates) > 1:
        raise ManifestError(
            f"{len(candidates)} .docx files found under {workspace} "
            f"({', '.join(sorted(p.name for p in candidates))}); expected exactly one "
            "at this stage (before any reviews/ change file exists, there's no section "
            "number to disambiguate with -- move or archive the extra file(s))."
        )
    return candidates[0]


def _resolve_shared_document(workspace: Path, section: str | None) -> _DocumentTarget:
    """Resolve what a document-wide operation (``prepareDocument``,
    ``lookupStableId``) should act on.

    ``section`` given -> exactly :func:`manifest.resolve_section` (same
    refresh-and-retry-once behaviour), wrapped as a :class:`_DocumentTarget`.

    ``section`` omitted, and at least one section's change file already
    exists -> only valid when every section resolves to the *same* working
    ``.docx`` (the normal case: one document, sixteen sections' worth of
    change files pointing at it) -- the manifest is scanned, and if there
    is exactly one distinct docx path across every section, the
    lowest-numbered section is returned as the representative entry purely
    so the response has something readable in ``section``; it has no other
    significance; any section sharing that docx would resolve identically.

    ``section`` omitted, and *no* section's change file exists yet (true
    step 0 -- the working ``.docx`` sitting alone before ``reviewDocument``
    has created a single ``reviews/`` file) -> :func:`_find_workspace_docx`
    finds the document directly; ``section``/``change_file`` come back
    ``None``.

    Never guesses across more than one distinct docx (either sense above):
    raises :class:`ManifestError` naming what's ambiguous, the same way
    every other ambiguity in this framework fails loud rather than picking
    one silently.
    """
    if section is not None:
        entry = resolve_section(workspace, section)
        return _DocumentTarget(docx=Path(entry.docx), section=str(int(section)), change_file=entry.change_file)

    manifest = get_manifest(workspace)
    if not manifest:
        # No reviews/ change file exists anywhere yet -- there is no
        # section manifest to have an opinion, so go straight to the
        # workspace's one working docx instead of erroring.
        return _DocumentTarget(docx=_find_workspace_docx(workspace))

    distinct_docx = {entry.docx for entry in manifest.values()}
    if len(distinct_docx) > 1:
        raise ManifestError(
            f"{len(distinct_docx)} distinct working DOCX files found across sections "
            f"under {workspace} ({', '.join(sorted(distinct_docx))}); pass an explicit "
            "`section` so it's clear which one to use."
        )
    first_section = min(manifest, key=int)
    entry = manifest[first_section]
    return _DocumentTarget(docx=Path(entry.docx), section=first_section, change_file=entry.change_file)


def prepareDocument(section: str | None = None, *, workspace: str | Path = ".", force_regenerate: bool = False) -> dict:
    """Step 0, the very first call in a project: is the working DOCX
    editable, and are its stable IDs current?

    This is meant to run before anything else exists yet -- before a
    ``reviews/`` folder, before any ``ChangesCSA_*.md`` change file, at the
    point where the workspace holds nothing but the raw working ``.docx``.
    ``section`` is optional (and should normally be omitted): the
    readiness checks and the ID manifest this builds
    (:mod:`csa_docx.stable_ids`) both cover the *entire* document, every
    heading/paragraph/table-row in it, so there is nothing section-specific
    to ask for in the first place, let alone a section that could exist
    yet. Leave it out and :func:`_resolve_shared_document` finds the
    working ``.docx`` directly (:func:`_find_workspace_docx`) when no
    ``reviews/`` change file exists anywhere -- the true step-0 case -- or
    via the one shared docx every section's change file already points at
    (:mod:`csa_docx.manifest`'s one-docx-per-Final-Version-folder rule)
    once a later step has created some. It only raises (as
    ``{"status": "ERROR", ...}``) if that's genuinely ambiguous -- more
    than one ``.docx`` sitting in the workspace with no section number yet
    to disambiguate with, or more than one distinct working docx across
    sections once they exist -- and never silently guesses either way.
    Passing a specific ``section`` still works once the section manifest
    exists, and resolves to the same document in the common one-docx case.

    The manifest is cached by the resolved docx path
    (:func:`_id_manifest_path`), so calling this once prepares the whole
    document for everything downstream: the ``csa-change-review-agent``
    (``.agents/csa-change-review.md``) -- the authoring step that creates
    the ``reviews/`` folder and walks the document section by section
    deciding what needs to change, writing that out as ``ChangesCSA_*.md``
    files -- can look up each change's ``@H...`` ID from the one shared
    manifest (:func:`lookupStableId`) and drop it straight into ``Where:``
    instead of quoting text, and once those change files exist, calling
    this again (with or without a section) is just an instant
    ``regenerated: false`` no-op confirming nothing has drifted, not a
    rebuild.

    Regenerating is idempotent: an existing manifest whose heading skeleton
    still matches the document is left alone and reported with
    ``"regenerated": false``. If the structure *has* drifted the manifest is
    rebuilt and the response says so (``"reason": "structure_drift"``)
    rather than rewriting it silently. ``force_regenerate=True`` rebuilds
    unconditionally.

    ``id_manifest_summary.runs`` counts the ``-T<n>-R<n>`` table-row IDs
    (the ``R`` component of the ID format), alongside ``paragraphs`` for the
    ``-P<n>`` IDs; ``headings``/``table_rows`` are the same numbers under
    their structural names.
    """
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    # section=None resolves the working docx directly -- via the section
    # manifest if reviews/ change files already exist (the normal re-run
    # case), or straight off the workspace's one .docx if none do yet (true
    # step 0, before reviewDocument has created anything). Only fails loud
    # if that's genuinely ambiguous -- see _resolve_shared_document.
    try:
        target = _resolve_shared_document(workspace_path, section)
    except (ManifestError, ValueError) as exc:
        return _error(str(exc))

    section = target.section
    docx = target.docx

    resolved_project = _resolve_registered_project(workspace_path)
    project_stamp = (
        {"key": resolved_project.get("key"), "label": resolved_project.get("label")}
        if resolved_project
        else None
    )

    readiness = _check_document_ready(docx)
    if not readiness.ok:
        return {
            "status": "NOT_READY",
            "reasons": readiness.reasons,
            "message": readiness.message,
            "section": section,
            "docx": str(docx),
            "id_manifest_summary": {"paragraphs": 0, "runs": 0, "regenerated": False},
            "validation": readiness.validation,
            "project": project_stamp,
        }

    # Same opening path cli_apply_section.py's --dump-ids uses: DocxEngine
    # owns reading the package, stable_ids owns turning its paragraph list
    # into IDs. Opening a Document does not mutate it.
    # paragraphs_with_table_rows() (not the vendor Document.paragraphs(),
    # which excludes tables entirely) interleaves table rows in document
    # order so stable_ids's existing table_anchor handling actually fires --
    # see its docstring for why table_rows was always 0 before this.
    try:
        from .engines.docxengine_adapter import DocxEngineEditor

        editor = DocxEngineEditor(docx, section_heading=None)
        entries = generate_manifest(editor.paragraphs_with_table_rows())
    except Exception as exc:
        return _error(f"Could not read stable IDs from {docx}: {type(exc).__name__}: {exc}")

    counts = _id_manifest_counts(entries)
    fingerprint = _structure_fingerprint(entries)
    manifest_path = _id_manifest_path(workspace_path, docx)
    existing = _read_id_manifest(manifest_path)
    drifted = existing is not None and existing.get("structure_fingerprint") != fingerprint

    if existing is None:
        reason = "created"
    elif force_regenerate:
        reason = "forced"
    elif drifted:
        reason = "structure_drift"
    else:
        reason = "unchanged"

    regenerated = reason != "unchanged"
    if regenerated:
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        # Which section's prepareDocument call happened to
                        # (re)build this -- metadata only. The manifest
                        # itself covers the whole document and is shared by
                        # every section that resolves to this same docx.
                        "generated_by_section": section,
                        "docx": str(docx),
                        "generated_at": datetime.now(UTC).isoformat(),
                        "structure_fingerprint": fingerprint,
                        "counts": counts,
                        "entries": entries,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            return _error(f"Could not write the stable-ID manifest {manifest_path}: {exc}")

    return {
        "status": "READY",
        "reasons": [],
        "section": section,
        "docx": str(docx),
        "change_file": target.change_file,
        "id_manifest_summary": {
            "paragraphs": counts["paragraphs"],
            "runs": counts["table_rows"],
            "headings": counts["headings"],
            "table_rows": counts["table_rows"],
            "regenerated": regenerated,
            "reason": reason,
            "path": str(manifest_path),
        },
        "validation": readiness.validation,
        # Cross-project safety: which registered project this workspace
        # resolved to. Agents confirm this matches the project they believe
        # they are working on before using anything else in this response.
        "project": project_stamp,
    }


_ID_QUERY_RE = re.compile(r"^@H\d")


def lookupStableId(
    query: str,
    section: str | None = None,
    *,
    workspace: str | Path = ".",
    kind: str | None = None,
    limit: int = 10,
    case_sensitive: bool = False,
) -> dict:
    """Resolve a change-file ``Where:`` anchor from the cached ID manifest.

    Deterministic complement to :func:`prepareDocument`: the manifest it
    reads must already exist (run ``prepareDocument`` first -- this never
    builds or opens the DOCX itself, it only reads the cached JSON, so it
    stays cheap enough to call once per edit while drafting a change
    file). ``section`` is optional, same as ``prepareDocument``: the
    manifest already covers the whole document, so it's only needed to
    disambiguate when a workspace has more than one distinct working docx
    (see :func:`_resolve_shared_document`) -- the common one-docx case
    needs no section at all. Two query modes, chosen automatically:

    - ``query`` looks like a stable ID itself (starts with ``@H`` followed
      by a digit, e.g. ``@H2.1.4-P2``) -> exact match on ``id``. Useful for
      confirming an ID pulled from a previous run is still current.
    - anything else -> case-insensitive substring match against each
      entry's ``text`` preview (case-sensitive if ``case_sensitive=True``).

    ``kind`` optionally filters to ``"heading"``, ``"paragraph"``, or
    ``"table_row"``. Results are capped at ``limit`` (``truncated: true``
    when there were more); ``unique_id`` is the single match's ``id`` when
    ``match_count == 1``, else ``None`` -- the common case a caller wants to
    check before trusting a lookup as unambiguous. Never BLOCKS and never
    raises on an empty or ambiguous result -- picking the right match among
    several is left to the caller, the same way this framework leaves
    wording judgment to a human or bigger model everywhere else.
    """
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    try:
        target = _resolve_shared_document(workspace_path, section)
    except (ManifestError, ValueError) as exc:
        return _error(str(exc))

    section = target.section
    docx = target.docx
    manifest_path = _id_manifest_path(workspace_path, docx)
    payload = _read_id_manifest(manifest_path)
    if payload is None:
        return _error(
            f"No ID manifest found for {docx} (expected at {manifest_path}). "
            "Call prepareDocument() first."
        )

    entries = payload.get("entries") or []
    query_stripped = query.strip()

    if _ID_QUERY_RE.match(query_stripped):
        matches = [e for e in entries if e.get("id") == query_stripped]
    else:
        needle = query_stripped if case_sensitive else query_stripped.lower()
        matches = []
        for e in entries:
            haystack = e.get("text") or ""
            if not case_sensitive:
                haystack = haystack.lower()
            if needle in haystack:
                matches.append(e)

    if kind:
        matches = [e for e in matches if e.get("kind") == kind]

    match_count = len(matches)
    limited = matches[:limit]

    # A stale manifest doesn't block the lookup (rebuilding needs DocxEngine,
    # which this function deliberately never opens) -- it's just flagged so
    # the caller can decide whether to re-run prepareDocument first. A cheap
    # mtime comparison, not a structure-fingerprint recheck.
    possibly_stale = False
    try:
        possibly_stale = docx.stat().st_mtime > manifest_path.stat().st_mtime
    except OSError:
        pass

    return {
        "status": "OK",
        "section": section,
        "docx": str(docx),
        "manifest_path": str(manifest_path),
        "manifest_generated_at": payload.get("generated_at"),
        "possibly_stale": possibly_stale,
        "query": query,
        "match_count": match_count,
        "truncated": match_count > limit,
        "matches": limited,
        "unique_id": limited[0]["id"] if match_count == 1 else None,
    }


def apply_next_batch(
    section: str,
    limit: int = 3,
    *,
    workspace: str | Path = ".",
    change_file: str | Path | None = None,
    docx: str | Path | None = None,
    start_edit_id: str | None = None,
    end_edit_id: str | None = None,
    comment_author: str = "Wenzel Joubert",
    comment_initials: str = "WJ",
    engine: str = "docxengine",
    track_changes: bool = True,
) -> dict:
    """Apply the next bounded batch of approved edits for ``section``.

    ``change_file``/``docx`` are optional overrides; when omitted they are
    resolved from the section manifest (:mod:`csa_docx.manifest`), so the
    caller only ever needs to pass a section number. Returns the same JSON
    shape ``cli_apply_section.py`` has always printed: status
    (SECTION_COMPLETE | PARTIAL_COMPLETE | BLOCKED), applied/blocked edit
    IDs, the next edit ID if any, and validation results.

    Before any backup is taken the working DOCX is put through the same
    step-0 readiness checks :func:`prepareDocument` runs (open-in-Word lock
    file, zero-byte/corrupt package, pre-existing validation failures). When
    one of those trips, the call returns early with ``{"status":
    "NOT_READY", "reasons": [...], ...}`` and the document is left
    completely untouched -- no backup, no partial batch.
    """
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    if change_file is None or docx is None:
        try:
            entry = resolve_section(workspace_path, section)
        except ManifestError as exc:
            return _error(str(exc))
        change_file = change_file or entry.change_file
        docx = docx or entry.docx

    change_file = Path(change_file).resolve()
    docx = Path(docx).resolve()

    if not change_file.exists():
        return _error(f"Change file does not exist: {change_file}")
    if not docx.exists():
        return _error(f"Working DOCX does not exist: {docx}")

    state = state_path(docx.parent, section)

    section_label, records = parse_change_file(change_file)
    section = str(section) or (section_label or "unknown")
    completed_ids = read_completed_ids(state)
    scoped_records = _scope_records(records, start_edit_id, end_edit_id)
    batch = select_batch(records, completed_ids, limit, start_edit_id, end_edit_id)
    batch_ids = [record.edit_id for record in batch]

    summary = ApplySummary(
        status="PLANNED",
        section=section,
        change_file=change_file,
        docx=docx,
        backup=None,
        batch_ids=batch_ids,
        run_state_path=state,
        completed_ids=[record.edit_id for record in records if record.edit_id in completed_ids],
    )

    if not batch:
        summary.status = "SECTION_COMPLETE"
        summary.validation = validate_docx(docx)
        summary.completed_ids = [record.edit_id for record in records if record.edit_id in completed_ids]
        # A section with nothing left to do is already reflected in the
        # existing run-state (the first completing run wrote the backup
        # path, validation evidence and per-edit results there). Re-running
        # the CLI on a finished section must not replace that state with a
        # bare summary - only create it when the section has no run-state
        # at all (e.g. completion recorded solely in the change file).
        if not state.exists():
            write_state(state, records, summary)
            update_changes_report(change_file, summary)
        summary.report_updated = False
        return _summary_payload(summary)

    # Step 0: never create a backup -- let alone start editing -- on a
    # document that is open in Word, mid-write, or already broken. The
    # caller does not have to remember to ask for this; a NOT_READY result
    # means the working DOCX was not touched at all.
    readiness = _check_document_ready(docx)
    if not readiness.ok:
        return {
            "status": "NOT_READY",
            "message": readiness.message,
            "reasons": readiness.reasons,
            "section": section,
            "docx": str(docx),
            "change_file": str(change_file),
            "batch_ids": batch_ids,
            "validation": readiness.validation,
        }

    summary.backup = create_backup(docx, section)
    editor = None
    package = None
    try:
        if engine == "docxengine":
            from .engines.docxengine_adapter import DocxEngineEditor

            editor = DocxEngineEditor(
                docx, section_heading=_section_heading(section_label), track_changes=track_changes
            )
        else:
            package = extract_docx(docx)
            editor = DocumentEditor(package.path("word/document.xml"), section_heading=_section_heading(section_label))

        summary.status = "IN_PROGRESS"
        write_state(state, records, summary)
        _apply_batch(editor, batch, summary, comment_author, comment_initials)
        editor.save()
        if package is not None:
            package.save(docx)
    finally:
        if package is not None:
            package.cleanup()

    done_ids = set(summary.applied + summary.already_applied)
    remaining = [record.edit_id for record in scoped_records if record.edit_id not in (completed_ids | done_ids)]
    if summary.blocked:
        remaining = summary.blocked + [edit_id for edit_id in remaining if edit_id not in summary.blocked]
    summary.completed_ids = [
        record.edit_id for record in records if record.edit_id in (completed_ids | done_ids)
    ]
    summary.next_edit_id = remaining[0] if remaining else None
    summary.validation = validate_docx(docx)
    summary.status = "BLOCKED" if summary.blocked else ("PARTIAL_COMPLETE" if summary.next_edit_id else "SECTION_COMPLETE")

    write_state(state, records, summary)
    update_changes_report(change_file, summary)
    write_state(state, records, summary)
    return _summary_payload(summary)


def get_section_status(section: str, *, workspace: str | Path = ".") -> dict:
    """Read-only: the run-state summary for one section, without applying
    anything. Returns ``{"status": "NOT_STARTED", ...}`` when no run-state
    file exists yet for that section."""
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    try:
        entry = resolve_section(workspace_path, section)
    except ManifestError as exc:
        return _error(str(exc))

    state = state_path(Path(entry.docx).parent, section)
    if not state.exists():
        return {
            "status": "NOT_STARTED",
            "section": str(int(section)),
            "change_file": entry.change_file,
            "docx": entry.docx,
        }

    fields: dict[str, str] = {}
    for line in state.read_text(encoding="utf-8").splitlines():
        if line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            fields[key.strip()] = value.strip()

    return {
        "status": fields.get("Status", "UNKNOWN"),
        "section": str(int(section)),
        "change_file": entry.change_file,
        "docx": entry.docx,
        "completed_edit_ids": fields.get("Completed edit IDs"),
        "blocked_edit_ids": fields.get("Blocked edit IDs"),
        "next_edit_id": fields.get("Next edit ID"),
        "run_state": str(state),
    }


def list_sections(*, workspace: str | Path = ".", force_refresh: bool = False) -> dict:
    """Every known section (from the manifest) plus its current status.
    This is the one call a small model needs to decide what to work on
    next — no path or naming-convention knowledge required."""
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    try:
        manifest = get_manifest(workspace_path, force_refresh=force_refresh)
    except ManifestError as exc:
        return _error(str(exc))

    sections = []
    for section in sorted(manifest, key=int):
        sections.append(get_section_status(section, workspace=workspace_path))
    return {"status": "OK", "sections": sections}


def validate_section(section: str, *, workspace: str | Path = ".") -> dict:
    """Run the DOCX integrity checks (archive zip test, XML well-formedness,
    comment-ID consistency, table-row comment safety) for one section's
    working docx, without applying any edits."""
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    try:
        entry = resolve_section(workspace_path, section)
    except ManifestError as exc:
        return _error(str(exc))
    docx = Path(entry.docx)
    if not docx.exists():
        return _error(f"Working DOCX does not exist: {docx}")
    return {"status": "OK", "section": str(int(section)), "docx": str(docx), "validation": validate_docx(docx)}


def refresh_manifest(*, workspace: str | Path = ".") -> dict:
    """Rebuild the section manifest by scanning the workspace for section
    change files and the working DOCX. The manifest is always derived from
    the live folder layout (nothing is cached to disk), so this is a
    no-op reset for stale paths: archiving old files and adding a new
    document is picked up on the next call automatically."""
    workspace_path = Path(workspace).resolve()
    _workspace_guard = _check_workspace_registered(workspace_path)
    if _workspace_guard is not None:
        return _workspace_guard
    try:
        manifest = _refresh_manifest_impl(workspace_path)
    except ManifestError as exc:
        return _error(str(exc))
    return {
        "status": "OK",
        "sections": sorted(manifest, key=int),
        "manifest": {section: entry.to_dict() for section, entry in manifest.items()},
    }


# ---------------------------------------------------------------------------
# create_table: insert a new table that matches the document's own tables.
#
# Thin re-export of :func:`csa_docx.tables.create_table` so the public API
# surface (this module) is the only thing callers need to import. The
# implementation lives in :mod:`csa_docx.tables` so it can be tested and
# extended in isolation.
# ---------------------------------------------------------------------------


def create_table(
    docx: str | Path,
    *,
    after: str,
    rows: int | None = None,
    cols: int = 2,
    data: list[list[str]] | None = None,
    header: bool = True,
    backup: bool = True,
) -> dict:
    """Insert a new table immediately after the paragraph ``after``.

    The new table's style, banding, and cell markup are cloned from one of
    the document's existing tables (discovered at run time), so it looks
    identical to its siblings. See :func:`csa_docx.tables.create_table` for
    the full contract, return shape, and failure modes.
    """
    from .tables import create_table as _impl

    return _impl(
        docx,
        after=after,
        rows=rows,
        cols=cols,
        data=data,
        header=header,
        backup=backup,
    )
