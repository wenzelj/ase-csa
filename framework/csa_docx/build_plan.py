"""Build-lane planner: from approved section files to scaffolding and change
records.

Given a document created from the CSA template (whose stable-ID manifest
``tools.prepareDocument`` has already written), map every rendered statement
in the section files to the template placeholder it replaces. See
``.agents/docs/build-lane-spec.md`` section 5, steps 2, 3 and 4.

The mapping is structural, never by guessed numbers: the manifest entry for
the heading whose text equals the section file's ``heading:`` is found by
normalised text, and every placeholder is located relative to that heading in
the manifest's document order.

- ``plan_records`` -> ``{framework_section: [record, ...]}`` in document
  order, each record carrying ``edit_id``, ``title``, ``where``, ``do``,
  ``text``, ``why``, ``note`` (the fields a change file needs).
- ``plan_scaffold`` -> one entry per table or bullet list whose count in the
  section file differs from the placeholders in the document;
  ``run_scaffold`` runs ``scaffold_csa.py`` once per entry, and the caller
  runs ``prepareDocument(force_regenerate=True)`` afterwards so the stable
  IDs are rebuilt.

``plan_records`` raises :class:`ValueError` naming a statement when that
statement has no placeholder in the document; run the scaffold step first.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import tools
from .check_section import normalise_heading
from .section_file import parse_section_file

#: ``##`` headings inside section blocks.
_DISCOVERY_HEADING = "Discovery Information"
_DRAWBRIDGE_HEADING = "Drawbridge Impact"
_SUMMARY_HEADING = "Summary"
_FINDINGS_HEADING = "Findings"
_GLOSSARY_HEADING = "Terms"
_COVERAGE_HEADING = "Hosts"
_NOTES_HEADING = "Discovery Notes"
_NOTE_HEADING = "Notes"  # migration: the note under the 5.4 table

#: Glossary rows are appended after the template's standard rows.
_GLOSSARY_STANDARD_ROWS = 10


def _manifest_entries(workspace: Path) -> tuple[Path, list[dict]]:
    """Load the prepared manifest for the workspace's working document.

    Resolves the working DOCX exactly like ``prepareDocument`` does (and
    fails when it is ambiguous), then reads the JSON that call wrote.
    """
    target = tools._resolve_shared_document(workspace, None)
    payload = tools._read_id_manifest(tools._id_manifest_path(workspace, target.docx))
    if not payload:
        raise ValueError(
            f"No prepared manifest for {target.docx}; run tools.prepareDocument(workspace) first."
        )
    return target.docx, payload.get("entries") or []


def _framework_section(section_path: str) -> str:
    """Framework section number of an entry: the Heading 1 ordinal, i.e. the
    number after ``@H`` in the heading ID minus 1 (``@H4.5`` gives ``"3"``)."""
    return str(int(section_path.split(".")[0]) - 1)


def _norm(text: str) -> str:
    return normalise_heading(text)


def _find_heading(entries: list[dict], text: str, *, level: int | None = None) -> dict | None:
    """The first heading entry whose normalised text matches ``text``."""
    for entry in entries:
        if entry.get("kind") != "heading":
            continue
        if level is not None and entry.get("level") != level:
            continue
        if _norm(entry.get("text") or "") == _norm(text):
            return entry
    return None


def _body_under(entries: list[dict], start_id: str, section_path: str) -> list[dict]:
    """Entries between the heading ``start_id`` and the next heading of any
    level, kept to those in the heading's section, in document order."""
    start = next((i for i, e in enumerate(entries) if e.get("id") == start_id), None)
    if start is None:
        return []
    out: list[dict] = []
    for e in entries[start + 1:]:
        if e.get("kind") == "heading":
            break
        if (e.get("section_path") or "").startswith(section_path):
            out.append(e)
    return out


def _subheading(entries: list[dict], section_path: str, level: int, text: str) -> dict | None:
    """The level-``level`` heading named ``text`` under ``section_path``."""
    for e in entries:
        if (e.get("kind") == "heading" and e.get("level") == level
                and (e.get("section_path") or "").startswith(section_path + ".")
                and _norm(e.get("text") or "") == _norm(text)):
            return e
    return None


def _scaffold_entry(entries: list[dict], kind: str, heading_text: str, count: int,
                    ref_entry: dict, table: int = 1) -> dict:
    """One ``plan_scaffold`` entry: the 1-based occurrence of ``ref_entry``
    among same-level same-text headings plus the needed count. ``table`` is
    included only when it is not the first table under the heading."""
    entry = {
        "kind": kind,
        "heading": heading_text,
        "occurrence": _occurrence(entries, ref_entry),
        "count": count,
    }
    if kind == "rows" and table != 1:
        entry["table"] = table
    return entry



def _occurrence(entries: list[dict], heading_entry: dict) -> int:
    """1-based occurrence of ``heading_entry`` among all headings with the
    same normalised text (any level), in document order. Mirrors
    scaffold_csa.py, which counts matching headings and returns the
    ordinal of the target among them."""
    norm = _norm(heading_entry.get("text") or "")
    count = 0
    for e in entries:
        if e.get("kind") == "heading" and _norm(e.get("text") or "") == norm:
            count += 1
            if e.get("id") == heading_entry.get("id"):
                return count
    raise ValueError(f"heading {heading_entry.get('id')!r} not found in manifest")


def _fill_items(entries: list[dict], items: list, have: list[dict], text: str,
                cells_lists: list, scaffold: dict | None) -> None:
    """Append ``len(cells_lists)`` statement items: the first ``len(have)`` map
    onto existing placeholders in order, any remainder maps to the synthetic
    ``(+1)`` placeholder the scaffold step will create, each carrying the
    shared ``scaffold`` entry when there is one.

    ``entries`` is the manifest entry list (for section_path of the synthetic
    ID); ``have`` is the list of existing placeholder entries (table rows or
    bullets); ``cells_lists`` is the list of cell lists (or texts) from the
    section file; ``scaffold`` is the scaffold entry for the overflow (may be
    None when everything fits).
    """
    if len(cells_lists) > len(have):
        assert scaffold is not None
    for n, cells in enumerate(cells_lists, start=1):
        if n <= len(have):
            entry = have[n - 1]
        else:
            entry = {"id": f"{have[-1]['id']}(+1)",
                     "section_path": have[-1]["section_path"]}
        text_n = " | ".join(cells) if isinstance(cells, list) else cells
        items.append((entry, f"{text} {n}", text_n,
                      scaffold if n > len(have) else None))


def _load_template_blocks() -> dict:
    """Load the template-blocks.json map (cached)."""
    import json as _json
    path = (Path(__file__).resolve().parents[2]
            / "skills" / "csa-document-template" / "references" / "template-blocks.json")
    return _json.loads(path.read_text(encoding="utf-8"))


def _migration_map_entry(blocks: dict, heading: str):
    """The migration subsection entry for ``heading`` from the template map."""
    for m in blocks.get("migration", []):
        if normalise_heading(m.get("heading") or "") == normalise_heading(heading):
            return m
    return None


def _collect_scaffolds(items: list) -> list:
    """Collect distinct scaffold entries from items (deduped by identity)."""
    seen: list[dict] = []
    for _entry, _key, _text, sc in items:
        if sc is not None and all(sc is not s for s in seen):
            seen.append(sc)
    return seen


def _resolve_section_file(workspace: Path, path: Path) -> dict:
    """Resolve one section file against the manifest.

    Returns ``{"block", "heading", "heading_entry", "items", "scaffold"}``
    where ``items`` is a list of ``(manifest_entry, statement_key, text,
    scaffold_entry|None)`` in document order. ``text`` is filled in by
    ``plan_records``; a trailing placeholder with no statement (``text is
    None`` with no scaffold) is deleted. Raises :class:`ValueError` naming the
    statement when the document has no placeholder that could carry it.
    """
    parsed = parse_section_file(path)
    _, entries = _manifest_entries(workspace)
    heading_text = parsed["heading"].strip()
    block = parsed["block"]
    items: list[tuple[dict, str, str | None, dict | None]] = []

    if block == "domain":
        heading_entry = _find_heading(entries, heading_text, level=2)
        if heading_entry is None:
            raise ValueError(f"no Heading 2 {heading_text!r} in the document")
        section_path = heading_entry["section_path"]

        # Requirement rows: the table_row entries of the domain's first table,
        # whose text starts with "<Req ID> |".
        req_rows = [e for e in entries if e.get("kind") == "table_row"
                    and (e.get("section_path") or "") == section_path]
        for req in parsed.get("requirements", []):
            req_id = req["req_id"].strip()
            row = next((r for r in req_rows if (r.get("text") or "").startswith(req_id + " |")), None)
            if row is None:
                raise ValueError(
                    f"no placeholder row for requirement {req_id} under "
                    f"{heading_entry['id']} ({heading_entry.get('text')!r})"
                )
            text = f"Observed: {req['current_state']}\nAssessment: {req['rating']}"
            items.append((row, req_id, text, None))

        # Discovery Information: table rows (template v1.2) or bullets (v1.1).
        cells_lists = parsed.get("tables", {}).get(_DISCOVERY_HEADING, [])
        bullets = parsed.get("bullets", {}).get(_DISCOVERY_HEADING, [])
        if cells_lists:
            di = _subheading(entries, section_path, 3, _DISCOVERY_HEADING)
            if di is None:
                raise ValueError(f"no Heading 3 {_DISCOVERY_HEADING!r} under {heading_entry['id']}")
            di_sp = di["section_path"]
            rows = [e for e in entries
                    if e.get("kind") == "table_row"
                    and (e.get("section_path") or "") == di_sp]
            data = rows[1:]  # first row is the header row
            sc = _scaffold_entry(entries, "rows", _DISCOVERY_HEADING, len(cells_lists), di) if len(cells_lists) > len(data) else None
            _fill_items(entries, items, data, _DISCOVERY_HEADING, cells_lists, sc)
        elif bullets:
            # v1.1: Discovery Information is a bullet list under the Heading 3.
            di = _subheading(entries, section_path, 3, _DISCOVERY_HEADING)
            if di is None:
                raise ValueError(f"no Heading 3 {_DISCOVERY_HEADING!r} under {heading_entry['id']}")
            di_sp = di["section_path"]
            para_entries = [e for e in _body_under(entries, di["id"], di_sp)
                            if e.get("kind") == "paragraph"]
            sc = _scaffold_entry(entries, "bullets", _DISCOVERY_HEADING, len(bullets), di) if len(bullets) > len(para_entries) else None
            _fill_items(entries, items, para_entries, _DISCOVERY_HEADING, bullets, sc)

        # Discovery Notes: the optional bullet(s) after the Discovery table
        # under the same Heading 3. The template ships one placeholder bullet
        # (the first paragraph under "Discovery Information" after the table
        # rows); there is no separate "Discovery Notes" heading in the
        # document. Present in the file: Replace. Absent: Delete.
        di_h = _subheading(entries, section_path, 3, _DISCOVERY_HEADING)
        if di_h is not None:
            di_sp = di_h["section_path"]
            notes_para = None  # template v1.3: the optional note paragraph after the table
            seen_row = False
            for e in _body_under(entries, di_h["id"], di_sp):
                if e.get("kind") == "table_row":
                    seen_row = True
                elif e.get("kind") == "paragraph" and seen_row:
                    notes_para = e
                    break
            note = parsed.get("paragraphs", {}).get(_NOTES_HEADING, [])
            if note:
                if notes_para is None:
                    raise ValueError(f"statement {_NOTES_HEADING!r} has no placeholder under {di_h['id']}")
                items.append((notes_para, _NOTES_HEADING, note[0], None))
            elif notes_para is not None:
                # No note in the file: delete the optional note paragraph.
                items.append((notes_para, _NOTES_HEADING, None, None))

        # Drawbridge Impact: the first paragraph under the domain's Heading 3.
        draw = parsed.get("paragraphs", {}).get(_DRAWBRIDGE_HEADING) or []
        if draw:
            dib = _subheading(entries, section_path, 3, _DRAWBRIDGE_HEADING)
            if dib is None:
                raise ValueError(f"no Heading 3 {_DRAWBRIDGE_HEADING!r} under {heading_entry['id']}")
            paras = [e for e in _body_under(entries, dib["id"], dib["section_path"])
                     if e.get("kind") == "paragraph"]
            if not paras:
                raise ValueError(
                    f"statement {_DRAWBRIDGE_HEADING!r} has no placeholder under {dib['id']}"
                )
            items.append((paras[0], _DRAWBRIDGE_HEADING, draw[0], None))

        # 3.1 / 3.2 tables: the rows of the table that follows the matching
        # label paragraph (a template placeholder paragraph whose text is the
        # table heading).
        for table_heading, cells_lists in parsed.get("tables", {}).items():
            if table_heading in (_DISCOVERY_HEADING, "Requirements"):
                continue  # handled above
            label = next((e for e in _body_under(entries, heading_entry["id"], section_path)
                          if e.get("kind") == "paragraph"
                          and _norm(e.get("text") or "") == _norm(table_heading)), None)
            if label is None:
                raise ValueError(f"no table label {table_heading!r} under {heading_entry['id']}")
            idx = entries.index(label)
            rows: list[dict] = []
            for e in entries[idx + 1:]:
                if e.get("kind") == "heading":
                    break
                if e.get("kind") == "table_row":
                    rows.append(e)
                elif rows:
                    break
            data = rows[1:]  # first row is the header row
            sc = _scaffold_entry(entries, "rows", table_heading, len(cells_lists), label) if len(cells_lists) > len(data) else None
            _fill_items(entries, items, data, table_heading, cells_lists, sc)

    elif block == "executive-summary":
        heading_entry = _find_heading(entries, heading_text, level=2)
        if heading_entry is None:
            raise ValueError(f"no Heading 2 {heading_text!r} in the document")
        paras = [e for e in _body_under(entries, heading_entry["id"], heading_entry["section_path"])
                 if e.get("kind") == "paragraph"]
        summary = parsed.get("paragraphs", {}).get(_SUMMARY_HEADING, [])
        if len(summary) > len(paras):
            raise ValueError(
                f"statement {_SUMMARY_HEADING!r} paragraph {len(summary)} has no placeholder left "
                f"under {heading_entry['id']} (the document has {len(paras)})"
            )
        for n, text in enumerate(summary, start=1):
            items.append((paras[n - 1], f"{_SUMMARY_HEADING} {n}", text, None))
        # Unused placeholders are deleted.
        for n in range(len(summary), len(paras)):
            items.append((paras[n], f"{_SUMMARY_HEADING} {n + 1}", None, None))

    elif block == "migration":
        # Load the template map for this migration subsection.
        blocks_map = _load_template_blocks()
        mig_entry = _migration_map_entry(blocks_map, heading_text)

        # The subsection heading in the document (level 2 for most, level 1
        # would be unusual but the manifest drives this).
        heading_entry = _find_heading(entries, heading_text, level=2)
        if heading_entry is None:
            heading_entry = _find_heading(entries, heading_text, level=1)
        if heading_entry is None:
            raise ValueError(f"no heading {heading_text!r} in the document")

        section_path = heading_entry["section_path"]
        # All body entries under the heading, in document order.
        body = _body_under(entries, heading_entry["id"], section_path)

        # Separate body into: intro paragraphs (before the first table row),
        # table rows, and post-table paragraphs (Findings bullets).
        intro_paras: list[dict] = []
        all_rows: list[dict] = []
        post_paras: list[dict] = []
        seen_row = False
        for e in body:
            if e.get("kind") == "table_row":
                all_rows.append(e)
                seen_row = True
            elif e.get("kind") == "paragraph":
                if seen_row:
                    post_paras.append(e)
                else:
                    intro_paras.append(e)
            # skip headings (shouldn't appear under a single subsection)

        # Summary: replaces the intro paragraph (the "Table" label paragraph
        # is also an intro paragraph; skip it if present).
        summary = parsed.get("paragraphs", {}).get(_SUMMARY_HEADING, [])
        if summary:
            # Prefer the first intro paragraph that is NOT a "Table" label.
            intro_for_summary = None
            for p in intro_paras:
                if _norm(p.get("text") or "") != _norm("Table"):
                    intro_for_summary = p
                    break
            if intro_for_summary is None:
                intro_for_summary = intro_paras[0] if intro_paras else None
            if intro_for_summary is None:
                raise ValueError(
                    f"statement {_SUMMARY_HEADING!r} has no placeholder under {heading_entry['id']}"
                )
            items.append((intro_for_summary, _SUMMARY_HEADING, summary[0], None))

        # Table rows.
        cells_lists = parsed.get("tables", {}).get("Table", [])
        rows = all_rows
        data = rows[1:] if rows else []
        if cells_lists:
            sc = (_scaffold_entry(entries, "rows", heading_text, len(cells_lists), heading_entry)
                  if len(cells_lists) > len(data) else None)
            _fill_items(entries, items, data, "Table", cells_lists, sc)

        # Group Policy header row: Replace with the file's header cells.
        if (mig_entry and mig_entry.get("table", {}).get("project_columns_from") is not None
                and rows):
            hdr_cells = parsed.get("table_headers", {}).get("Table")
            if hdr_cells:
                items.append((rows[0], "Table 0", " | ".join(hdr_cells), None))

        # Findings bullets: after the table, or (5.3, 5.6: no table) the subsection's own
        # paragraphs, which are its placeholder bullets.
        findings = parsed.get("bullets", {}).get(_FINDINGS_HEADING, [])
        bullet_paras = post_paras if all_rows else intro_paras
        if findings:
            sc = (_scaffold_entry(entries, "bullets", heading_text, len(findings), heading_entry)
                  if len(findings) > len(bullet_paras) else None)
            _fill_items(entries, items, bullet_paras, _FINDINGS_HEADING, findings, sc)

        # Notes (template v1.3, 5.4): one optional plain paragraph under the table.
        if all_rows and (mig_entry or {}).get("note_paragraphs"):
            note = parsed.get("paragraphs", {}).get(_NOTE_HEADING, [])
            if post_paras:
                items.append((post_paras[0], _NOTE_HEADING, note[0] if note else None, None))
            elif note:
                raise ValueError(f"statement {_NOTE_HEADING!r} has no placeholder under {heading_entry['id']}")

    elif block == "governance":
        # Governance: fill only the placeholder bullets after the standard 3.
        blocks_map = _load_template_blocks()
        gov_entry = blocks_map.get("governance", {})
        standard = gov_entry.get("standard_bullets", 3)
        actions = parsed.get("bullets", {}).get("Actions", [])
        heading_entry = _find_heading(entries, heading_text, level=1)
        if heading_entry is None:
            raise ValueError(f"no Heading 1 {heading_text!r} in the document")
        gov_sp = heading_entry["section_path"]
        # All bullets under the heading (standard + placeholder).
        all_bullets = [e for e in _body_under(entries, heading_entry["id"], gov_sp)
                       if e.get("kind") == "paragraph"]
        placeholders = all_bullets[standard:]
        if not actions:
            # No actions: delete the placeholder bullet(s).
            for p in placeholders:
                items.append((p, "Actions", None, None))
        else:
            sc = None
            if len(actions) > len(placeholders):
                sc = _scaffold_entry(entries, "bullets", heading_text,
                                     standard + len(actions), heading_entry)
            for n, text in enumerate(actions, start=1):
                if n <= len(placeholders):
                    entry = placeholders[n - 1]
                else:
                    entry = {"id": f"{placeholders[-1]['id']}(+1)",
                             "section_path": placeholders[-1]["section_path"]}
                items.append((entry, f"Actions {n}", text,
                              sc if n > len(placeholders) else None))

    elif block in ("glossary", "coverage"):
        # Template v1.2: the glossary is an appendix (Heading 1); Discovery Coverage is
        # 5.1, a Heading 2 under Migration Discovery.
        level = 1 if block == "glossary" else 2
        heading_entry = _find_heading(entries, heading_text, level=level)
        if heading_entry is None:
            raise ValueError(f"no Heading {level} {heading_text!r} in the document")
        rows = [e for e in entries if e.get("kind") == "table_row"
                and (e.get("section_path") or "") == heading_entry["section_path"]]
        data_rows = rows[1:]  # first row is the header row
        if block == "glossary":
            terms = parsed.get("tables", {}).get(_GLOSSARY_HEADING, [])
            free = max(0, len(data_rows) - _GLOSSARY_STANDARD_ROWS)
            sc = None
            if len(terms) > free:
                sc = _scaffold_entry(
                    entries, "rows", heading_text,
                    len(terms) + _GLOSSARY_STANDARD_ROWS, heading_entry)
            for n, cells in enumerate(terms, start=1):
                idx = _GLOSSARY_STANDARD_ROWS + n - 1
                if idx < len(data_rows):
                    row = data_rows[idx]
                else:
                    row = {"id": f"{data_rows[-1]['id']}(+1)",
                           "section_path": data_rows[-1]["section_path"]}
                items.append((row, f"{_GLOSSARY_HEADING} {n}", " | ".join(cells),
                              sc if idx >= len(data_rows) else None))
        else:
            # Summary paragraph (optional).
            summary = parsed.get("paragraphs", {}).get(_SUMMARY_HEADING, [])
            if summary:
                paras = [e for e in _body_under(entries, heading_entry["id"], heading_entry["section_path"])
                         if e.get("kind") == "paragraph"]
                if not paras:
                    raise ValueError(f"statement {_SUMMARY_HEADING!r} has no placeholder under {heading_entry['id']}")
                items.append((paras[0], _SUMMARY_HEADING, summary[0], None))
            # Hosts table rows.
            hosts = parsed.get("tables", {}).get(_COVERAGE_HEADING, [])
            sc = _scaffold_entry(entries, "rows", heading_text, len(hosts), heading_entry) if len(hosts) > len(data_rows) else None
            _fill_items(entries, items, data_rows, _COVERAGE_HEADING, hosts, sc)
    else:
        raise ValueError(f"unknown block kind {block!r}")

    return {
        "block": block,
        "heading": heading_text,
        "heading_entry": heading_entry,
        "items": items,
        "scaffolds": [s for s in _collect_scaffolds(items) if s],
        "evidence": parsed.get("evidence", {}),
    }


def _record(resolved: dict, entry: dict, key: str, text: str | None, file_name: str) -> dict:
    if text is None:
        do, record_text = "Delete", ""
    else:
        do, record_text = "Replace", text
    return {
        "edit_id": "",  # numbered in document order per framework section
        "title": f"{resolved['heading']}: {key}",
        "where": entry["id"],
        "do": do,
        "text": record_text,
        "why": ", ".join(resolved["evidence"].get(key, [])),
        "note": f"Built from approved section file {file_name}.",
    }


def plan_records(workspace, section_paths) -> dict[str, list[dict]]:
    """Map every rendered statement in ``section_paths`` to the stable ID of
    the template placeholder it replaces.

    Returns ``{framework_section: [record, ...]}`` in document order, where a
    record carries ``edit_id``, ``title``, ``where``, ``do``, ``text``,
    ``why``, ``note``. Statements whose placeholder does not exist raise
    :class:`ValueError` naming the statement; run the scaffold step first.
    """
    workspace = Path(workspace).resolve()
    grouped: dict[str, list[dict]] = {}
    for path in section_paths:
        path = Path(path)
        resolved = _resolve_section_file(workspace, path)
        for entry, key, text, _scaffold in resolved["items"]:
            section_no = _framework_section(entry["section_path"])
            grouped.setdefault(section_no, []).append(
                _record(resolved, entry, key, text, path.name)
            )
    for section_no, records in grouped.items():
        for n, record in enumerate(records, start=1):
            record["edit_id"] = f"S{section_no}-E{n}"
    return grouped


def plan_scaffold(workspace, section_paths) -> list[dict]:
    """One entry per table or bullet list whose count in the section files
    differs from the placeholders in the document:
    ``{"kind": "bullets" | "rows", "heading", "occurrence", "count"}``, plus
    ``"table"`` when it is not the first table under the heading.

    Empty when every count fits the template's placeholders.
    """
    workspace = Path(workspace).resolve()
    out: list[dict] = []
    seen: set[tuple] = set()
    for path in section_paths:
        resolved = _resolve_section_file(workspace, Path(path))
        for entry in resolved["scaffolds"]:
            key = (entry["kind"], entry["heading"], entry["occurrence"], entry.get("table", 1))
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
    return out


def run_scaffold(workspace, docx, plan) -> list[dict]:
    """Run ``scaffold_csa.py`` once per ``plan`` entry, in order.

    Each call sets that block's placeholder count (absolute, idempotent); the
    caller runs ``tools.prepareDocument(force_regenerate=True)`` afterwards so
    the stable IDs are rebuilt. Raises :class:`RuntimeError` with the script's
    output on any non-zero exit.
    """
    script = (Path(__file__).resolve().parents[2]
              / "skills" / "csa-document-template" / "scripts" / "scaffold_csa.py")
    if not script.is_file():
        raise RuntimeError(f"scaffold script not found: {script}")
    results: list[dict] = []
    for entry in plan:
        cmd = [
            sys.executable, str(script), entry["kind"],
            "--docx", str(docx),
            "--heading", entry["heading"],
            "--heading-occurrence", str(entry["occurrence"]),
            "--set-count", str(entry["count"]),
        ]
        if entry["kind"] == "rows" and entry.get("table", 1) != 1:
            cmd += ["--table", str(entry["table"])]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"scaffold_csa.py failed ({' '.join(cmd)}): "
                f"{proc.stdout.strip()}\n{proc.stderr.strip()}"
            )
        results.append({"entry": entry, "output": proc.stdout.strip()})
    return results
