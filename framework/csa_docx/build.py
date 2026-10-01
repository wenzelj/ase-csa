"""Build-lane document work for `csa build` (S60).

This module does the *document* work of a build: create the document from
the CSA template, scaffold the placeholder counts, plan and write the
canonical change records, apply them, and (for a preview) strip comments and
archive the records. The ``csa build`` command in ``bin/csa`` owns the
preconditions, the approval of the records and the report.

The apply step reuses :mod:`csa_docx.build_apply`, which in turn drives the
same :func:`csa_docx.tools.apply_next_batch` engine ``csa apply`` uses, so
``csa build`` adds no new DOCX-writing code.

See ``.agents/docs/build-lane-spec.md`` section 5.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import build_apply, build_plan, tools


# The build writes the first draft. Peer reviews move it through 0.x (revise lane) until it is issued as 1.0.
FIRST_DRAFT_VERSION = "0.1"


def _skills_dir() -> Path:
    """The .agents/skills directory (parents: csa_docx -> framework -> .agents)."""
    return Path(__file__).resolve().parents[2] / "skills"


def new_document(workspace: Path, out: Path, *, system_name: str,
                 prepared_for: str | None = None, prepared_by: str | None = None,
                 doc_version: str | None = None, status: str | None = None) -> Path:
    """Create a fresh document from the project's CSA template (new_csa.py).

    Relative ``out`` is resolved under ``workspace``. Raises :class:`RuntimeError`
    naming the script output when the script fails.
    """
    workspace = Path(workspace).resolve()
    out = Path(out)
    if not out.is_absolute():
        out = workspace / out
    out.parent.mkdir(parents=True, exist_ok=True)
    script = _skills_dir() / "csa-document-template" / "scripts" / "new_csa.py"
    if not script.is_file():
        raise RuntimeError(f"new_csa.py not found: {script}")
    argv = [sys.executable, str(script), "--workspace", str(workspace),
            "--out", str(out), "--system-name", system_name]
    for flag, value in (("--prepared-for", prepared_for), ("--prepared-by", prepared_by),
                        ("--doc-version", doc_version or FIRST_DRAFT_VERSION), ("--status", status)):
        if value:
            argv += [flag, value]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines())[-1500:]
        raise RuntimeError(f"new_csa.py failed (rc={proc.returncode}):\n{tail}")
    return out


def scaffold(workspace: Path, docx: Path, section_paths: list[Path]) -> list[dict]:
    """Scaffold placeholder counts for ``section_paths`` and re-prepare the document.

    Runs :func:`build_plan.plan_scaffold` + :func:`build_plan.run_scaffold`, then
    :func:`tools.prepareDocument` with ``force_regenerate=True`` so the stable
    IDs reflect the new counts. Returns the scaffold entries actually run.
    """
    workspace = Path(workspace).resolve()
    plan = build_plan.plan_scaffold(workspace, section_paths)
    if not plan:
        return []
    results = build_plan.run_scaffold(workspace, docx, plan)
    tools.prepareDocument(workspace=workspace, force_regenerate=True)
    return results


def _preview_workspace(root: Path, build_id: str) -> Path:
    """A throw-away workspace for a preview, inside the project (so the framework's
    registered-workspace guard accepts it) but under ``archive`` (so the project's
    own document search ignores it). Holds only a copy of the CSA templates."""
    pw = root / "csa-work" / "build" / "archive" / f"work-preview-{build_id}"
    shutil.rmtree(pw, ignore_errors=True)
    (pw / "CSA Template").mkdir(parents=True)
    for t in (root / "CSA Template").glob("CSA_Template_v*.dotx"):
        shutil.copy2(t, pw / "CSA Template" / t.name)
    if not any((pw / "CSA Template").iterdir()):
        raise RuntimeError(f"no CSA_Template_v*.dotx in {root / 'CSA Template'}")
    return pw


def prepare(root: Path, section_paths: list, *, system_name: str, build_id: str, preview: bool,
            prepared_for: str | None = None, prepared_by: str | None = None,
            doc_version: str | None = None, status: str | None = None) -> dict:
    """Steps 1-4 of spec section 5: create, scaffold, plan and write the records.

    A real build works in the project's ``01 Final Version``; a preview in its own
    workspace (:func:`_preview_workspace`). ``csa build`` approves the returned
    change files, then calls :func:`apply`. Returns ``workspace``, ``docx``,
    ``sections``, ``records`` (count per section), ``scaffold`` and ``change_files``.
    """
    root = Path(root).resolve()
    section_paths = [Path(p) for p in section_paths]
    ws = _preview_workspace(root, build_id) if preview else root
    docx = ws / "01 Current State AS Built" / "01 Final Version" / f"Current State Assessment - {system_name}.docx"
    try:
        new_document(ws, docx, system_name=system_name, prepared_for=prepared_for,
                     prepared_by=prepared_by, doc_version=doc_version, status=status)
        prep = tools.prepareDocument(workspace=ws)
        if prep.get("status") != "READY":
            detail = {k: prep.get(k) for k in ("status", "reasons", "message", "code") if prep.get(k)}
            raise RuntimeError(f"prepareDocument did not return READY on the new document: {detail}")
        scaffolded = scaffold(ws, docx, section_paths)
        records = build_plan.plan_records(ws, section_paths)
        if not records:
            raise RuntimeError("the section files produced no records")
        cfs = build_apply.write_build_records(ws, records, system_name, build_id)
    except Exception:
        if preview:
            shutil.rmtree(ws, ignore_errors=True)
        raise
    return {"workspace": str(ws), "docx": str(docx), "preview": preview,
            "sections": sorted((int(k) for k in records)),
            "records": {int(k): len(v) for k, v in records.items()},
            "scaffold": scaffolded, "change_files": [str(c) for c in cfs]}


def apply(workspace: Path, sections: list, *, system_name: str, build_id: str, preview: bool,
          root: Path | None = None) -> dict:
    """Step 5: apply the (approved) records. A real build applies them as tracked
    changes and keeps comments and change files for ``csa review`` / ``csa cleanup``.
    A preview applies them untracked, strips comments, copies the document to
    ``<root>/csa-work/build/archive/preview-<build_id>/`` and deletes its workspace."""
    ws = Path(workspace).resolve()
    docx = ws / "01 Current State AS Built" / "01 Final Version" / f"Current State Assessment - {system_name}.docx"
    try:
        applied = build_apply.apply_build_records(ws, [str(s) for s in sections], app=system_name,
                                                  track_changes=not preview, build_id=build_id)
        result = {"applied": applied["sections"], "docx": str(docx)}
        if preview:
            dest_dir = Path(root).resolve() / "csa-work" / "build" / "archive" / f"preview-{build_id}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"Current State Assessment - {system_name} - PREVIEW.docx"
            shutil.copy2(docx, dest)
            result["preview_docx"] = str(dest)
        return result
    finally:
        if preview:
            shutil.rmtree(ws, ignore_errors=True)


def working_document(root: Path, system_name: str) -> Path | None:
    """The project's working DOCX in ``01 Final Version`` (``None`` when there is none yet).
    With several, the one named after the system wins; otherwise there must be exactly one."""
    fv = Path(root).resolve() / "01 Current State AS Built" / "01 Final Version"
    docs = sorted(d for d in fv.glob("*.docx") if not d.name.startswith("~$"))
    if not docs:
        return None
    named = fv / f"Current State Assessment - {system_name}.docx"
    if named in docs:
        return named
    if len(docs) == 1:
        return docs[0]
    raise RuntimeError(f"several documents in {fv}: {', '.join(d.name for d in docs)}; keep one working DOCX there")


def place_prepare(root: Path, section_path, *, system_name: str, source: str,
                  prepared_for: str | None = None, prepared_by: str | None = None,
                  doc_version: str | None = None, status: str | None = None) -> dict:
    """Placement, step 1 of 2 (``csa place``): put one section file into the working document.

    Creates version 0.1 from the CSA template when the project has no document yet,
    scaffolds the placeholder counts this section needs, re-prepares the stable IDs,
    plans the records and adds them to the per-section change files
    (:func:`build_apply.append_place_records`). ``csa place`` records the approval,
    then calls :func:`place_apply`. A section file that was placed before is placed
    again the same way: its new records replace the placed text as tracked changes.
    Returns ``docx``, ``created``, ``sections``, ``change_files``, ``new_edits``, ``scaffold``.
    """
    root = Path(root).resolve()
    path = Path(section_path)
    docx = working_document(root, system_name)
    created = docx is None
    if created:
        docx = root / "01 Current State AS Built" / "01 Final Version" / f"Current State Assessment - {system_name}.docx"
        new_document(root, docx, system_name=system_name, prepared_for=prepared_for,
                     prepared_by=prepared_by, doc_version=doc_version, status=status)
    prep = tools.prepareDocument(workspace=root, force_regenerate=not created)
    if prep.get("status") != "READY":
        detail = {k: prep.get(k) for k in ("status", "reasons", "message", "code") if prep.get(k)}
        raise RuntimeError(f"prepareDocument did not return READY: {detail}")
    scaffolded = scaffold(root, docx, [path])
    records = build_plan.plan_records(root, [path])
    if not records:
        raise RuntimeError(f"{path.name} produced no records")
    out = build_apply.append_place_records(root, records, system_name, source)
    return {"docx": str(docx), "created": created, "sections": sorted(int(k) for k in records),
            "scaffold": scaffolded, **out}


def place_apply(root: Path, sections: list, *, system_name: str, docx: str, change_files: dict | None = None,
                plain: bool = False) -> dict:
    """Placement, step 2 of 2: apply the section change files (``{N: path}`` from
    :func:`place_prepare`) as tracked changes, each edit with its evidence comment,
    until every section is complete. ``plain`` applies them as normal text in the real
    document instead: no tracked changes, no evidence comments, no preview archive."""
    applied = build_apply.apply_build_records(Path(root).resolve(), [str(s) for s in sections], app=system_name,
                                              track_changes=True, build_id="place", docx=Path(docx),
                                              change_files={str(k): v for k, v in (change_files or {}).items()},
                                              plain=plain)
    return {"applied": applied["sections"], "docx": docx}


def build(workspace: Path, section_paths: list, *, system_name: str, build_id: str, preview: bool,
          prepared_for: str | None = None, prepared_by: str | None = None,
          doc_version: str | None = None, status: str | None = None) -> dict:
    """prepare + apply without an approval step in between (tests and tools only;
    ``csa build`` approves the records between the two)."""
    r = prepare(workspace, section_paths, system_name=system_name, build_id=build_id, preview=preview,
                prepared_for=prepared_for, prepared_by=prepared_by, doc_version=doc_version, status=status)
    r.update(apply(r["workspace"], r["sections"], system_name=system_name, build_id=build_id,
                   preview=preview, root=workspace))
    return r
