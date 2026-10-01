"""Build-lane apply step: turn planned change records into canonical change
files, then apply them to the working document.

``write_build_records`` renders one ``reviews/ChangesCSA_<App>_Section<N>.md``
per framework section from the ``build_plan.plan_records`` output, in the same
format ``csa check-change`` / ``csa approve`` expect. Every file is checked
with ``check_change`` (structure and hygiene, no anchors, no lint) and the
call raises on the first ERROR.

``apply_build_records`` then drives ``tools.apply_next_batch`` per section
until the section is complete. With ``track_changes=True`` (a real build) the
Word comments and the change files stay where ``csa review`` and
``csa cleanup`` find them. With ``track_changes=False`` (a preview) the
comments are stripped from the DOCX - the same regexes
``new_csa.strip_comments`` uses - ``word/comments.xml`` is emptied, and the
change files with their run-state files are moved to
``csa-work/build/archive/preview-<build_id>/`` (the project's
``reviews/`` is left alone). See ``.agents/docs/build-lane-spec.md``
section 5, steps 4 and 5.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from . import tools
from .run_state import read_completed_ids, remove_edit_ids, state_path

#: Comment markup the build's apply step removes for a preview (S60), copied
#: from the new_csa.py script so this module stays importable without it.
# Any run holding a comment reference, whatever its run properties or attribute spacing
# (ElementTree writes '<w:rStyle w:val="CommentReference" />' with a space).
_COMMENT_REF_RUN_RE = re.compile(
    r'<w:r(?:\s[^>]*)?>(?:(?!</w:r>).)*?<w:commentReference\b[^>]*/>\s*</w:r>', re.S)
_COMMENT_REF_SIMPLE_RE = re.compile(r'<w:commentReference\b[^>]*/>')
_COMMENT_RANGE_RE = re.compile(r'<w:commentRange(?:Start|End)\b[^>]*/>')


def _framework_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _check_file(change_file: Path) -> None:
    """Run ``python -m csa_docx.check_change`` on one written change file and
    raise :class:`RuntimeError` naming the finding when there is any ERROR."""
    proc = subprocess.run(
        [sys.executable, "-m", "csa_docx.check_change", str(change_file),
         "--no-anchors", "--no-lint", "--json"],
        capture_output=True, text=True, cwd=str(_framework_dir()))
    if proc.returncode == 0:
        return
    tail = "\n".join(line for line in (proc.stdout + proc.stderr).splitlines()
                      if line.strip())[-1500:]
    raise RuntimeError(f"check_change failed for {change_file}:\n{tail}")


def _record_md(record: dict) -> str:
    lines = [f"### {record['edit_id']} - {record['title']}", "",
             f"**Where:** `{record['where']}`", "",
             f"**Do:** {record['do']}", ""]
    text = (record.get("text") or "").strip()
    if text:
        lines += ["**Text:**", ""]
        lines += [f"> {line}" if line else ">" for line in text.splitlines()]
        lines.append("")
    why = (record.get("why") or "").strip() or "(none recorded)"
    lines += [f"**Why:** {why}", ""]
    note = (record.get("note") or "").strip() or "(none)"
    lines += [f"**Note:** {note}", ""]
    return "\n".join(lines)


def write_build_records(workspace, records: dict, app: str, build_id: str) -> list[Path]:
    """Write one canonical change file per framework section and check it.

    ``records`` is ``build_plan.plan_records`` output
    (``{framework_section: [record, ...]}``). Returns the change-file paths
    in section order. Raises :class:`RuntimeError` when any file fails
    ``csa check-change`` (structure + hygiene, anchors and lint off).
    """
    workspace = Path(workspace).resolve()
    unresolved = [r["edit_id"] for recs in records.values() for r in recs if "(+" in (r.get("where") or "")]
    if unresolved:
        # A "(+1)" stand-in means the scaffold step did not make room for the statement.
        # The apply engine would read "@H..-P1(+1)" as "@H..-P1" and overwrite it.
        raise RuntimeError(f"records still point at a placeholder that does not exist yet: {', '.join(unresolved)}")
    reviews = workspace / "01 Current State AS Built" / "01 Final Version" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for section in sorted(records, key=int):
        change_file = reviews / f"ChangesCSA_{app}_Section{section}.md"
        parts = [
            f"# Changes to Current State Assessment - {app}",
            f"## Section {section} Change Record",
            "",
            f"**Section:** {section}",
            f"**Status:** Approved for implementation (csa build {build_id}, "
            f"from reviewed section files).",
            "",
        ]
        for record in records[section]:
            parts += [_record_md(record), "---", ""]
        change_file.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
        _check_file(change_file)
        paths.append(change_file)
    return paths


_EDIT_NO_RE = re.compile(r"^#{2,4}\s+(?:REJECTED\s+)?S(\d+)-E(\d+)\b", re.M)
_REPORT_HEADING_RE = re.compile(r"^## .*Report\s*$", re.M)


def _last_edit_number(reviews: Path, section: str) -> int:
    """Highest ``S<section>-E<n>`` used by any change file for ``section`` in
    ``reviews`` (labelled files included), so new edits number on from it."""
    top = 0
    for f in reviews.glob(f"ChangesCSA_*_Section{section}*.md"):
        if not re.search(rf"_Section{section}(?:_[^.]+)?\.md$", f.name):
            continue
        for m in _EDIT_NO_RE.finditer(f.read_text(encoding="utf-8")):
            if m[1] == str(section):
                top = max(top, int(m[2]))
    return top


def append_place_records(workspace, records: dict, app: str, source: str) -> dict:
    """Add planned records to the per-section change files, for ``csa place``.

    The placement path writes one section file at a time straight into the
    working document. Each framework section keeps one change file,
    ``reviews/ChangesCSA_<App>_Section<N>.md`` (the same file ``csa build``
    writes), so ``csa review N`` and ``csa cleanup N`` still see one record
    per section. New records are numbered on from the highest edit ID in any
    change file of that section and are inserted before the first ``## ...
    Report`` block (the apply engine rewrites everything from its
    ``## Changes Report`` on). Every file is checked with ``check_change``.

    Returns ``{"change_files": {N: path}, "new_edits": {N: [edit ids]}, "new_files": [paths this
    call created]}``.
    """
    workspace = Path(workspace).resolve()
    reviews = workspace / "01 Current State AS Built" / "01 Final Version" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    new_edits: dict[str, list[str]] = {}
    new_files: list[str] = []
    for section in sorted(records, key=int):
        existing = sorted(f for f in reviews.glob(f"ChangesCSA_*_Section{section}.md"))
        change_file = existing[0] if existing else reviews / f"ChangesCSA_{app}_Section{section}.md"
        start = _last_edit_number(reviews, section)
        ids = []
        for n, record in enumerate(records[section], start=start + 1):
            record["edit_id"] = f"S{section}-E{n}"
            ids.append(record["edit_id"])
        block = "\n".join(part for record in records[section] for part in (_record_md(record), "---", ""))
        if not change_file.is_file():
            new_files.append(str(change_file))
        if change_file.is_file():
            text = change_file.read_text(encoding="utf-8")
            m = _REPORT_HEADING_RE.search(text)
            head, tail = (text[:m.start()], text[m.start():]) if m else (text, "")
            head = head.rstrip()
            if not head.endswith("---"):
                head += "\n\n---"
            text = head + "\n\n" + block.rstrip() + "\n" + (("\n" + tail) if tail else "")
        else:
            text = "\n".join([
                f"# Changes to Current State Assessment - {app}",
                f"## Section {section} Change Record",
                "",
                f"**Section:** {section}",
                f"**Status:** Placed from section files by csa place ({source}).",
                "",
                block.rstrip(),
            ]) + "\n"
        change_file.write_text(text, encoding="utf-8")
        _check_file(change_file)
        files[section] = str(change_file)
        new_edits[section] = ids
    return {"change_files": files, "new_edits": new_edits, "new_files": new_files}


def _strip_comments(docx: Path, only_ids: set[str] | None = None) -> None:
    """Remove Word comments from the DOCX in place (write to a temp file, then replace).

    Without ``only_ids`` every comment goes: the comment-reference runs and the
    ``w:commentRangeStart``/``w:commentRangeEnd`` marks leave ``word/document.xml`` and
    ``word/comments.xml`` becomes an empty ``<w:comments>`` root. With ``only_ids`` only
    the comments with those ids go (their reference runs, range marks and entries), and
    every other comment stays exactly as it was."""
    with zipfile.ZipFile(docx) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
    xml = parts["word/document.xml"].decode("utf-8")
    if only_ids is None:
        xml = _COMMENT_REF_RUN_RE.sub("", xml)
        xml = _COMMENT_REF_SIMPLE_RE.sub("", xml)
        xml = _COMMENT_RANGE_RE.sub("", xml)
        if "word/comments.xml" in names:
            parts["word/comments.xml"] = b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    else:
        if not only_ids or "word/comments.xml" not in names:
            return
        ids = "|".join(sorted(only_ids))
        xml = re.sub(r'<w:r(?:\s[^>]*)?>(?:(?!</w:r>).)*?<w:commentReference\b[^>]*\bw:id="(?:%s)"[^>]*/>\s*</w:r>' % ids,
                     "", xml, flags=re.S)
        xml = re.sub(r'<w:commentReference\b[^>]*\bw:id="(?:%s)"[^>]*/>' % ids, "", xml)
        xml = re.sub(r'<w:commentRange(?:Start|End)\b[^>]*\bw:id="(?:%s)"[^>]*/>' % ids, "", xml)
        cx = parts["word/comments.xml"].decode("utf-8")
        parts["word/comments.xml"] = re.sub(
            r'<w:comment\b[^>]*?\bw:id="(?:%s)"[^>]*?(?:/>|>.*?</w:comment>)' % ids, "", cx, flags=re.S).encode("utf-8")
    parts["word/document.xml"] = xml.encode("utf-8")
    _write_parts(docx, names, parts)


def _write_parts(docx: Path, names: list[str], parts: dict[str, bytes]) -> None:
    """Rewrite the DOCX in place from ``parts`` (write to a temp file, then replace)."""
    fd, tmp_name = tempfile.mkstemp(dir=str(docx.parent), suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(name, parts[name])
        os.replace(tmp, docx)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _strip_edit_bookmarks(docx: Path, edit_ids) -> None:
    """Remove the ``CSA_<edit id>`` bookmarks the apply step leaves on the paragraphs it edited.
    A plain placement keeps no edit records, so a bookmark left behind would capture the next
    edit that is given the same ID."""
    from .bookmarks import sanitise_bookmark_name
    names = {sanitise_bookmark_name(e) for e in edit_ids}
    if not names:
        return
    with zipfile.ZipFile(docx) as z:
        zip_names = z.namelist()
        parts = {n: z.read(n) for n in zip_names}
    xml = parts["word/document.xml"].decode("utf-8")
    ids = {m[1] for m in re.finditer(r'<w:bookmarkStart\b[^>]*?\bw:id="(\d+)"[^>]*?\bw:name="([^"]*)"[^>]*/>', xml)
           if m[2] in names}
    ids |= {m[2] for m in re.finditer(r'<w:bookmarkStart\b[^>]*?\bw:name="([^"]*)"[^>]*?\bw:id="(\d+)"[^>]*/>', xml)
            if m[1] in names}
    if not ids:
        return
    alt = "|".join(sorted(ids))
    xml = re.sub(r'<w:bookmarkStart\b[^>]*\bw:id="(?:%s)"[^>]*/>' % alt, "", xml)
    xml = re.sub(r'<w:bookmarkEnd\b[^>]*\bw:id="(?:%s)"[^>]*/>' % alt, "", xml)
    parts["word/document.xml"] = xml.encode("utf-8")
    _write_parts(docx, zip_names, parts)


def _comment_ids(docx: Path) -> set[str]:
    """The ids of the Word comments in the DOCX (empty when it has none)."""
    with zipfile.ZipFile(docx) as z:
        if "word/comments.xml" not in z.namelist():
            return set()
        return set(re.findall(r'<w:comment\b[^>]*?\bw:id="(\d+)"', z.read("word/comments.xml").decode("utf-8")))


_ID_LIST_RE = re.compile(r"^((?:[A-Za-z ]+: )?)(S\d+-[EA]\d+(?:, S\d+-[EA]\d+)*)$")


def _without_ids(line: str, drop: set[str]) -> str | None:
    """``line`` without ``drop`` in it when it is a comma-separated list of edit IDs (optionally
    after a ``Label: `` prefix, ``None`` standing for an empty list); ``None`` for the result line
    of a dropped edit. Other lines are returned as is."""
    r = re.match(r"^- (S\d+-[EA]\d+): ", line)
    if r:
        return None if r[1] in drop else line
    m = _ID_LIST_RE.match(line)
    if not m:
        return line
    kept = [i for i in m[2].split(", ") if i not in drop]
    return m[1] + (", ".join(kept) if kept else "None")


def _drop_plain_records(change_file: Path, docx: Path, section: str, edit_ids: list[str]) -> None:
    """Leave no trace of a plain placement: remove its edit records from the change file (and
    the per-edit hashes of its ``.approval.json``) and its IDs from the section's run-state.
    Earlier edits and their run-state entries stay as they were."""
    drop = set(edit_ids)
    if not drop:
        return
    if change_file.is_file():
        text = change_file.read_text(encoding="utf-8")
        for edit_id in sorted(drop):
            m = re.search(rf"^#{{2,4}}\s+(?:REJECTED\s+)?{re.escape(edit_id)}\b.*$", text, re.M)
            while m:
                nxt = re.search(r"^#{1,3}\s", text[m.end():], re.M)
                end = m.end() + nxt.start() if nxt else len(text)
                text = text[:m.start()] + text[end:]
                m = re.search(rf"^#{{2,4}}\s+(?:REJECTED\s+)?{re.escape(edit_id)}\b.*$", text, re.M)
        m = _REPORT_HEADING_RE.search(text)
        if m:   # the apply engine's report lists every edit it applied, plain ones included
            text = text[:m.start()] + "\n".join(
                l for l in (_without_ids(line, drop) for line in text[m.start():].split("\n")) if l is not None)
        change_file.write_text(text, encoding="utf-8")
    approval = change_file.parent / (change_file.stem + ".approval.json")
    if approval.is_file():
        data = json.loads(approval.read_text(encoding="utf-8"))
        data["hashes"] = {k: v for k, v in (data.get("hashes") or {}).items() if k not in drop}
        data["rejected"] = [k for k in (data.get("rejected") or []) if k not in drop]
        approval.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    remove_edit_ids(state_path(docx.parent, section), drop)


def apply_build_records(workspace, sections, *, app: str, track_changes: bool, build_id: str,
                        docx: Path | None = None, change_files: dict | None = None,
                        plain: bool = False, new_edits: dict | None = None,
                        new_files: list | None = None) -> dict:
    """Apply the written change files for each framework section.

    ``app`` is the system name used by :func:`write_build_records` to name
    the change files and the working DOCX.

    Calls ``tools.apply_next_batch(section, 500, ...)`` until the status is
    ``SECTION_COMPLETE``; a ``BLOCKED`` or ``ERROR`` status raises
    :class:`RuntimeError` naming the edit ID and the message.

    A preview (``track_changes=False``) then strips every Word comment from
    the DOCX and moves the change files with their run-state files into
    ``reviews/archive/preview-<build_id>/``. A real build leaves the
    comments and the change files in place for ``csa review`` and
    ``csa cleanup``. Returns ``{"sections": {N: applied_count}, "records":
    total}``.

    ``plain`` (``csa place --plain``) applies the edits untracked to the real document,
    removes only the evidence comments this call added, and leaves no records behind:
    ``new_edits`` (``{N: [edit ids]}``) are taken out of the change file, its approval
    record and the run-state, and a change file listed in ``new_files`` (made by this
    placement) is deleted when no edits are left in it.
    """
    workspace = Path(workspace).resolve()
    fv = workspace / "01 Current State AS Built" / "01 Final Version"
    # The DOCX always sits in the workspace's own "01 Final Version". A preview
    # runs in its own throw-away workspace (build.prepare), so this never
    # touches the project's real folders.
    docx_dir = fv
    fixed_docx = Path(docx) if docx else None
    if plain:
        # Plain placement: untracked edits in the real document, no evidence comments, no archive.
        track_changes = False
        if fixed_docx is None:
            raise RuntimeError("plain placement needs the working DOCX")
        comments_before = _comment_ids(fixed_docx)
    applied_by_section = {}
    plain_files: dict[str, Path] = {}
    for section in sections:
        # Pass the change file and DOCX explicitly (layout fixed by build.prepare).
        given = (change_files or {}).get(str(section))
        matches = [Path(given)] if given else sorted((fv / "reviews").glob(f"ChangesCSA_*_Section{section}.md"))
        if not matches:
            raise RuntimeError(
                f"section {section}: no change file in {fv / 'reviews'} "
                f"(expected ChangesCSA_*_Section{section}.md)")
        change_file = matches[0]
        if plain:
            plain_files[str(section)] = change_file
        docx = fixed_docx or docx_dir / f"Current State Assessment - {app}.docx"
        applied = 0
        while True:
            res = tools.apply_next_batch(str(section), 500,
                                         workspace=workspace,
                                         track_changes=track_changes,
                                         change_file=change_file, docx=docx)
            status = res.get("status")
            if status == "SECTION_COMPLETE":
                break
            if status == "NOT_READY":
                raise RuntimeError(f"section {section}: document not ready: "
                                   f"{res.get('message')}")
            if status in ("BLOCKED", "ERROR"):
                edit_id = (res.get("blocked") or [None])[0] or res.get("next_edit_id") or "?"
                detail = res.get("message") or res.get("reasons") or {
                    k: v for k, v in res.items() if k not in ("status", "applied", "docx") and v}
                raise RuntimeError(f"section {section} edit {edit_id}: {status}: {detail}")
            # PARTIAL_COMPLETE: count and continue with the next batch.
            applied += len(res.get("applied") or [])
            docx = Path(res.get("docx") or docx)
        docx = Path(res.get("docx") or docx)
        state = state_path(docx.parent, str(section))
        completed = read_completed_ids(state)
        applied_by_section[str(section)] = len(completed)

    if plain:
        _strip_comments(docx, _comment_ids(docx) - comments_before)
        _strip_edit_bookmarks(docx, [e for ids in (new_edits or {}).values() for e in ids])
        for section, change_file in plain_files.items():
            _drop_plain_records(change_file, docx, section, list((new_edits or {}).get(section) or []))
            if (str(change_file) in {str(f) for f in (new_files or [])} and change_file.is_file()
                    and not re.search(r"^#{2,4}\s+(?:REJECTED\s+)?S\d+-E\d+\b", change_file.read_text(encoding="utf-8"), re.M)):
                change_file.unlink()
                (change_file.parent / (change_file.stem + ".approval.json")).unlink(missing_ok=True)
    elif not track_changes:
        if docx is None:
            raise RuntimeError("no working DOCX recorded by the apply step")
        _strip_comments(docx)
        # Preview: archive the records + run-state inside the preview workspace.
        archive = fv / "reviews" / "archive" / f"preview-{build_id}"
        archive.mkdir(parents=True, exist_ok=True)
        for section in sections:
            for name in (f"ChangesCSA_*_Section{section}.md",
                         f"ChangesCSA_*_Section{section}_*.md"):
                for path in sorted((fv / "reviews").glob(name)):
                    shutil.move(str(path), str(archive / path.name))
                for sidecar in (f"ChangesCSA_*_Section{section}.md.approval.json",
                                f"ChangesCSA_*_Section{section}_*.md.approval.json"):
                    for path in sorted((fv / "reviews").glob(sidecar)):
                        shutil.move(str(path), str(archive / path.name))
            state = state_path(docx_dir, str(section))
            if state.exists():
                shutil.move(str(state), str(archive / state.name))

    return {
        "sections": {int(k): v for k, v in applied_by_section.items()},
        "records": sum(applied_by_section.values()),
    }
