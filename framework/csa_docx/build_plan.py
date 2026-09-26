"""Build-lane planner: from approved section files to change records.

Given a document created from the CSA template (whose stable-ID manifest
``tools.prepareDocument`` has already written), map every rendered statement
in the section files to the stable ID of the template placeholder it
replaces. See ``.agents/docs/build-lane-spec.md`` section 5, steps 2 and 4.

The mapping is structural, never by guessed numbers: the manifest entry for
the heading whose text equals the section file's ``heading:`` is found by
text, and every placeholder is located relative to that heading in the
manifest's document order.

``plan_records`` returns ``{framework_section: [record, ...]}`` in document
order; ``plan_scaffold`` returns the list of bullets the document is still
missing (empty when every count fits the template -- S58 fills in the rest
and ``run_scaffold`` stays out of this story's scope).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import tools
from .section_file import parse_section_file, rendered_statements

#: ``##`` headings inside a domain block and where their content lands.
_DISCOVERY_HEADING = "Discovery Information"
_DRAWBRIDGE_HEADING = "Drawbridge Impact"
_SUMMARY_HEADING = "Summary"
_FINDINGS_HEADING = "Findings"
_GLOSSARY_HEADING = "Terms"
_COVERAGE_HEADING = "Hosts"


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
    entries = payload.get("entries") or []
    return target.docx, entries


def _framework_section(section_path: str) -> str:
    """Framework section number of an entry: the Heading 1 ordinal, i.e. the
    number after ``@H`` in the heading ID minus 1 (``@H4.5`` gives ``"3"``)."""
    return str(int(section_path.split(".")[0]) - 1)


def _find_heading(entries: list[dict], text: str, *, level: int | None = None) -> dict | None:
    for entry in entries:
        if entry.get("kind") != "heading":
            continue
        if level is not None and entry.get("level") != level:
            continue
        if (entry.get("text") or "").strip() == text.strip():
            return entry
    return None


def _entry_at(entries: list[dict], entry_id: str) -> dict | None:
    for entry in entries:
        if entry.get("id") == entry_id:
            return entry
    return None


def _paragraphs_after(entries: list[dict], entry_id: str, *, section_path: str,
                      stop_at_heading: bool = False) -> list[dict]:
    """Body paragraphs after ``entry_id``, in document order, while the
    section path stays under the given heading (stops at a deeper or equal
    heading when ``stop_at_heading``)."""
    start = next((i for i, e in enumerate(entries) if e.get("id") == entry_id), None)
    if start is None:
        return []
    out: list[dict] = []
    for e in entries[start + 1:]:
        if e.get("kind") == "heading":
            if stop_at_heading:
                break
            if not (e.get("section_path") or "").startswith(section_path + "."):
                break
            continue
        if e.get("kind") == "paragraph" and (e.get("section_path") or "").startswith(section_path):
            out.append(e)
    return out


def _table_rows_after(entries: list[dict], entry_id: str, *, section_path: str) -> list[dict]:
    """Table rows after ``entry_id`` belonging to the table that follows it:
    stops at the first non-table-row entry, so it never bleeds past the table."""
    start = next((i for i, e in enumerate(entries) if e.get("id") == entry_id), None)
    if start is None:
        return []
    out: list[dict] = []
    for e in entries[start + 1:]:
        if e.get("kind") != "table_row":
            break
        if not (e.get("section_path") or "").startswith(section_path):
            break
        out.append(e)
    return out


def _domain_table_records(entries: list[dict], section_path: str, heading: dict,
                          table_heading: str) -> list[tuple[dict, str, str]]:
    """Find the label paragraph (the table heading) under the domain and the
    data rows of the table that follows it. Returns
    ``(row_entry, statement_key, cell_text)`` per row after the header row."""
    for e in entries:
        if (e.get("kind") != "paragraph"
                or not (e.get("section_path") or "").startswith(section_path + ".")
                or (e.get("text") or "").strip() != table_heading):
            continue
        rows = _table_rows_after(entries, e["id"], section_path=section_path)
        data = [r for r in rows[1:]]  # first row is the header row
        out = []
        for n, r in enumerate(data, start=1):
            out.append((r, f"{table_heading} {n}", " | ".join((r.get("text") or "").split(" | "))))
        return out
    return []


def _domain_subheading(entries: list[dict], text: str, section_path: str, domain_id: str) -> dict | None:
    """The Heading 3 under the given domain whose text equals ``text`` (every
    domain repeats the same subheading names, so the global first match would
    land in the wrong domain)."""
    for e in entries:
        if (e.get("kind") == "heading" and e.get("level") == 3
                and (e.get("section_path") or "").startswith(section_path + ".")
                and (e.get("text") or "").strip() == text.strip()):
            return e
    return None


def _domain_records(entries: list[dict], parsed: dict, heading_entry: dict) -> list[tuple[dict, str, str]]:
    """``(manifest_entry, statement_key, record_text)`` for one domain block
    in document order: requirement rows, then the Discovery Information
    bullets, then the Drawbridge Impact paragraph, then any 3.1/3.2 tables."""
    section_path = heading_entry["section_path"]
    out: list[tuple[dict, str, str]] = []

    # Requirement rows: the table_row entries whose text starts with "<Req ID> |".
    rows = [e for e in entries if e.get("kind") == "table_row"
            and (e.get("section_path") or "") == section_path]
    for req in parsed.get("requirements", []):
        req_id = req["req_id"].strip()
        row = next((r for r in rows if (r.get("text") or "").startswith(req_id + " |")), None)
        if row is None:
            raise ValueError(
                f"no placeholder row for requirement {req_id} under "
                f"{heading_entry['id']} ({heading_entry.get('text')!r})"
            )
        text = f"Observed: {req['current_state']}\nAssessment: {req['rating']}"
        out.append((row, req_id, text))

    # Discovery Information bullets: the paragraphs under the domain's
    # Heading 3 "Discovery Information", in order.
    bullets = parsed.get("bullets", {}).get(_DISCOVERY_HEADING, [])
    di = _domain_subheading(entries, _DISCOVERY_HEADING, section_path, heading_entry["id"])
    if bullets and di is None:
        raise ValueError(f"no Heading 3 {_DISCOVERY_HEADING!r} under {heading_entry['id']}")
    if bullets:
        paras = _paragraphs_after(entries, di["id"], section_path=di["section_path"],
                                  stop_at_heading=True)
        if len(paras) < len(bullets):
            raise ValueError(
                f"statement {_DISCOVERY_HEADING!r} has {len(bullets)} bullet(s) but the document "
                f"under {di['id']} only has {len(paras)} placeholder bullet(s)"
            )
        for n, (para, text) in enumerate(zip(paras, bullets), start=1):
            out.append((para, f"{_DISCOVERY_HEADING} {n}", text))

    # Drawbridge Impact: the paragraph under the domain's Heading 3.
    db = parsed.get("paragraphs", {}).get(_DRAWBRIDGE_HEADING) or []
    if db:
        di3 = _domain_subheading(entries, _DRAWBRIDGE_HEADING, section_path, heading_entry["id"])
        if di3 is None:
            raise ValueError(f"no Heading 3 {_DRAWBRIDGE_HEADING!r} under {heading_entry['id']}")
        paras = _paragraphs_after(entries, di3["id"], section_path=di3["section_path"],
                                  stop_at_heading=True)
        if not paras:
            raise ValueError(
                f"no paragraph under {di3['id']} for statement {_DRAWBRIDGE_HEADING!r}"
            )
        out.append((paras[0], _DRAWBRIDGE_HEADING, db[0]))

    # 3.1 / 3.2 tables: the table rows after the header row of the table
    # that follows the matching label paragraph.
    for table_heading in parsed.get("tables", {}):
        out.extend(_domain_table_records(entries, section_path, heading_entry, table_heading))
    return out


def _number_edit_ids(out: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Edit IDs ``S<N>-E<n>``, numbered in document order within each
    framework section (the records arrive in document order)."""
    for section_no, records in out.items():
        for n, record in enumerate(records, start=1):
            record["edit_id"] = f"S{section_no}-E{n}"
    return out


def plan_records(workspace, section_paths) -> dict[str, list[dict]]:
    """Map every rendered statement in ``section_paths`` to the stable ID of
    the template placeholder it replaces.

    Returns ``{framework_section: [record, ...]}`` in document order, where a
    record carries ``edit_id``, ``title``, ``where``, ``do``, ``text``,
    ``why``, ``note`` (the fields a change file needs). Statements whose
    placeholder does not exist raise :class:`ValueError` naming the statement.
    """
    workspace = Path(workspace).resolve()
    _, entries = _manifest_entries(workspace)

    statements_by_key: dict[str, tuple[dict, str, str]] = {}
    grouped: dict[str, list[dict]] = {}
    ordered_items: list[tuple[dict, str, str, dict]] = []
    for path in section_paths:
        path = Path(path)
        parsed = parse_section_file(path)
        file_name = path.name
        heading_text = parsed["heading"].strip()
        block = parsed["block"]

        if block == "domain":
            heading_entry = _find_heading(entries, heading_text, level=2)
            if heading_entry is None:
                raise ValueError(f"no Heading 2 {heading_text!r} in the document")
            items = _domain_records(entries, parsed, heading_entry)
        elif block == "executive-summary":
            heading_entry = _find_heading(entries, heading_text, level=2)
            if heading_entry is None:
                raise ValueError(f"no Heading 2 {heading_text!r} in the document")
            paras = _paragraphs_after(entries, heading_entry["id"],
                                      section_path=heading_entry["section_path"],
                                      stop_at_heading=True)
            summary = parsed.get("paragraphs", {}).get(_SUMMARY_HEADING, [])
            items = []
            for n, text in enumerate(summary, start=1):
                if n > len(paras):
                    raise ValueError(
                        f"statement {_SUMMARY_HEADING!r} has no placeholder left "
                        f"(paragraph {n} beyond the document's {len(paras)})"
                    )
                items.append((paras[n - 1], f"{_SUMMARY_HEADING} {n}", text))
            for n, para in enumerate(paras[len(summary):], start=len(summary) + 1):
                items.append((para, f"{_SUMMARY_HEADING} {n}", None))
        elif block == "migration":
            heading_entry = _find_heading(entries, heading_text, level=2)
            if heading_entry is None:
                raise ValueError(f"no Heading 2 {heading_text!r} in the document")
            findings = parsed.get("bullets", {}).get(_FINDINGS_HEADING, [])
            paras = _paragraphs_after(entries, heading_entry["id"],
                                      section_path=heading_entry["section_path"],
                                      stop_at_heading=True)
            items = []
            for n, text in enumerate(findings, start=1):
                if n > len(paras):
                    raise ValueError(
                        f"statement {_FINDINGS_HEADING!r} bullet {n} has no placeholder left "
                        f"(the document under {heading_entry['id']} only has {len(paras)})"
                    )
                items.append((paras[n - 1], f"{_FINDINGS_HEADING} {n}", text))
        elif block in ("glossary", "coverage"):
            heading_entry = _find_heading(entries, heading_text, level=1)
            if heading_entry is None:
                raise ValueError(f"no Heading 1 {heading_text!r} in the document")
            table_heading = _GLOSSARY_HEADING if block == "glossary" else _COVERAGE_HEADING
            rows = [e for e in entries if e.get("kind") == "table_row"
                    and (e.get("section_path") or "") == heading_entry["section_path"]]
            data_rows = rows[1:]
            items = []
            if block == "glossary":
                standard = 10
                terms = parsed.get("tables", {}).get(table_heading, [])
                if len(terms) + standard > len(data_rows):
                    raise ValueError(
                        f"statement {table_heading!r} needs {len(terms)} row(s) after the "
                        f"{standard} standard rows but only {len(data_rows) - standard} are free"
                    )
                for n, cells in enumerate(terms, start=1):
                    items.append((data_rows[standard + n - 1], f"{table_heading} {n}",
                                  " | ".join(cells)))
            else:
                hosts = parsed.get("tables", {}).get(table_heading, [])
                if len(hosts) > len(data_rows):
                    raise ValueError(
                        f"statement {table_heading!r} needs {len(hosts)} row(s) but the "
                        f"document only has {len(data_rows)} placeholder row(s)"
                    )
                for n, cells in enumerate(hosts, start=1):
                    items.append((data_rows[n - 1], f"{table_heading} {n}",
                                  " | ".join(cells)))
        else:
            raise ValueError(f"unknown block kind {block!r}")

        for entry, key, text in items:
            section_no = _framework_section(entry["section_path"])
            do = "Delete" if text is None else "Replace"
            grouped.setdefault(section_no, []).append({
                "entry": entry,
                "title": f"{heading_text}: {key}",
                "where": entry["id"],
                "do": do,
                "text": "" if text is None else text,
                "why": ", ".join(parsed.get("evidence", {}).get(key, [])),
                "note": f"Built from approved section file {file_name}.",
            })

    return _number_edit_ids(grouped)


def plan_scaffold(workspace, section_paths) -> list[dict]:
    """S58 hook: the scaffolding the document still needs so that every
    statement has a placeholder to replace.

    In this story it returns ``[]`` when every count fits the template's
    placeholders; S58 fills in the rest.
    """
    return []
