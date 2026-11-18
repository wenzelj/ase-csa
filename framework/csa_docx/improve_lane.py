"""Deterministic checks for proposals in the standalone CSA Improve lane."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

from .improve_contract import ImprovementProposal, validate_proposal


_FUTURE_WORDS = ("should", "recommend", "recommended", "future state", "target state")
_ABSENCE_ONLY = ("not found", "no evidence", "not observed", "no record")
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W_T = f"{{{_W_NS}}}t"
_W_P = f"{{{_W_NS}}}p"


def _visible_xml_text(element: Any) -> str:
    """Return visible paragraph/cell text, including tracked insertions.

    python-docx's ``Paragraph.text`` and ``Cell.text`` omit text nested in
    ``w:ins``.  Improve contexts are intentionally built from the rendered
    document XML, so Apply must use the same visible-text view when locating
    anchors in a DOCX that already contains tracked changes.
    """
    return "".join(node.text or "" for node in element.iter(_W_T))


def _visible_cell_text(cell: Any) -> str:
    return " ".join(_visible_xml_text(paragraph).strip()
                    for paragraph in cell._tc.iter(_W_P)
                    if _visible_xml_text(paragraph).strip()).strip()


def _replace_visible_paragraph_text(paragraph: Any, anchor: str, replacement: str) -> bool:
    root = getattr(paragraph, "_p", paragraph)
    nodes = list(root.iter(_W_T))
    current = "".join(node.text or "" for node in nodes)
    if anchor not in current or current.count(anchor) != 1 or not nodes:
        return False
    updated = current.replace(anchor, replacement, 1)
    nodes[0].text = updated
    for node in nodes[1:]:
        node.text = ""
    return True


def _row_values(value: str) -> list[str]:
    return [part.strip() for part in value.split("|")]


def _row_matches(row: Any, expected: list[str]) -> bool:
    return len(row.cells) == len(expected) and all(
        _visible_cell_text(cell) == value for cell, value in zip(row.cells, expected)
    )


def _set_visible_cell_text(cell: Any, value: str) -> None:
    paragraphs = [element for element in cell._tc.iter(_W_P)
                  if _visible_xml_text(element).strip()]
    if paragraphs and _replace_visible_paragraph_text(
            paragraphs[0], _visible_xml_text(paragraphs[0]), value):
        return
    cell.text = value


def _context_evidence_ids(context: Mapping[str, Any]) -> set[str]:
    ids = set(context.get("supporting_evidence_ids") or ())
    for key in ("new_evidence", "related_evidence"):
        for row in context.get(key) or ():
            if isinstance(row, Mapping) and row.get("evidence_id"):
                ids.add(str(row["evidence_id"]))
    subsection = context.get("subsection_data") or {}
    ids.update(str(value) for value in subsection.get("available_evidence_ids", []) if value)
    for row in subsection.get("available_evidence", []) or ():
        if isinstance(row, Mapping) and (row.get("evidence_id") or row.get("id")):
            ids.add(str(row.get("evidence_id") or row.get("id")))
    return ids


def validate_for_context(
    proposal: ImprovementProposal | Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate a proposal against the exact current-answer context.

    This function is intentionally read-only.  It does not apply edits, call a
    model or search the index.
    """
    errors = list(validate_proposal(proposal))
    if errors:
        return tuple(errors)
    typed = proposal if isinstance(proposal, ImprovementProposal) else ImprovementProposal.from_dict(proposal)
    if typed.section_key != context.get("section_key"):
        errors.append("proposal section_key does not match the context")
    if typed.base_document_hash != context.get("document_hash"):
        errors.append("proposal base_document_hash is stale")
    answer_text = str(context.get("answer_text") or "")
    available = _context_evidence_ids(context)
    cited = set(typed.evidence_ids)
    for edit in typed.edits:
        cited.update(edit.evidence_ids)
        if edit.operation != "keep" and edit.before not in answer_text:
            errors.append(f"{edit.block_id}: before text is not in the current answer")
        if re.search(r"\bE-\d+\b", edit.after):
            errors.append(f"{edit.block_id}: evidence IDs belong in evidence_ids metadata, not answer text")
        # ``reason`` is review metadata and may legitimately describe a
        # recommendation that the edit is deliberately not making.  Only the
        # proposed document text must stay within current-state boundaries.
        if any(word in edit.after.lower() for word in _FUTURE_WORDS):
            errors.append(f"{edit.block_id}: future-state recommendations are not current-state edits")
        if edit.operation != "keep" and context.get("improvement_findings") and not edit.addresses:
            errors.append(f"{edit.block_id}: changed edits must address a supplied rating, reader or gap finding")
    unknown = sorted(cited - available)
    if unknown:
        errors.append("proposal cites evidence outside the supplied context: " + ", ".join(unknown))
    if typed.rating_decision == "change" and typed.new_rating == "Not Met":
        basis = (typed.rating_basis or "").lower()
        if any(phrase in basis for phrase in _ABSENCE_ONLY):
            errors.append("Not Met cannot be based only on an absence of evidence")
    return tuple(dict.fromkeys(errors))


def check(proposal: ImprovementProposal | Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_for_context(proposal, context)
    return {"valid": not errors, "errors": list(errors), "section_key": context.get("section_key"),
            "base_document_hash": context.get("document_hash")}


def _document_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _apply_text(path: Path, proposal: ImprovementProposal) -> None:
    text = path.read_text(encoding="utf-8")
    for edit in proposal.edits:
        if edit.operation == "keep":
            continue
        if edit.before not in text:
            raise ValueError(f"{edit.block_id}: before text is no longer in the document")
        replacement = edit.after if edit.operation == "replace_sentence" else edit.before + "\n" + edit.after
        text = text.replace(edit.before, replacement, 1)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _apply_docx(path: Path, proposal: ImprovementProposal, heading: str = "") -> None:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - depends on the host runtime
        raise ValueError("python-docx is required for draft Improve application") from exc
    document = Document(str(path))
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from .improve_context import _heading_level, _section_key

    sections = []
    active = False
    level = None
    for element in document.element.body:
        if element.tag.endswith("}p"):
            paragraph = Paragraph(element, document)
            current_level = _heading_level(paragraph.style.name)
            if current_level is not None:
                if active and current_level <= level:
                    break
                visible_heading = _visible_xml_text(element)
                if not active and (_section_key(visible_heading) == proposal.section_key
                                   or (heading and visible_heading.strip() == heading.strip())):
                    active, level = True, current_level
                    continue
            if active:
                sections.append(paragraph)
        elif active and element.tag.endswith("}tbl"):
            sections.append(Table(element, document))
    if not active:
        raise ValueError(f"Cannot locate subsection {proposal.section_key} for Apply")
    paragraphs = [item for item in sections if isinstance(item, Paragraph)]
    tables = [item for item in sections if isinstance(item, Table)]
    # python-docx exposes table-cell paragraphs separately from the document
    # paragraph list.  CSA answers are commonly authored in tables, so a
    # proposal's sentence may be valid in the extracted answer while missing
    # from ``document.paragraphs``.
    table_paragraphs = [Paragraph(element, document) for table in tables
                        for element in table._tbl.iter(_W_P)]
    all_paragraphs = paragraphs + table_paragraphs
    changed = False
    replaced_anchors = {}
    for edit in proposal.edits:
        if edit.operation == "keep":
            continue
        row_insert = edit.operation == "insert_after" and "|" in edit.before and "|" in edit.after
        if edit.operation in {"replace_row", "insert_row", "delete_row"} or row_insert:
            before_cells = _row_values(edit.before)
            after_rows = [line.strip() for line in edit.after.splitlines() if line.strip()]
            after_cells = _row_values(after_rows[0]) if after_rows else []
            if edit.operation == "delete_row":
                row_match = next((row for table in tables for row in table.rows
                                  if _row_matches(row, before_cells)), None)
                if row_match is None:
                    raise ValueError(f"{edit.block_id}: row to delete is no longer in the document")
                row_match._tr.getparent().remove(row_match._tr)
                changed = True
                continue
            if edit.operation == "insert_row" or row_insert:
                if not after_cells:
                    raise ValueError(f"{edit.block_id}: inserted row is empty")
                anchor = next((row for table in tables for row in table.rows
                               if _row_matches(row, before_cells)), None)
                if anchor is None:
                    raise ValueError(f"{edit.block_id}: row anchor is no longer in the document")
                from copy import deepcopy
                from docx.table import _Row
                table = next(table for table in tables if any(row._tr is anchor._tr for row in table.rows))
                rows_to_insert = after_rows if row_insert else [edit.after]
                if row_insert and _row_values(rows_to_insert[0]) == before_cells:
                    rows_to_insert = rows_to_insert[1:]
                if row_insert and rows_to_insert:
                    replacement_cells = _row_values(after_rows[0])
                    if len(replacement_cells) != len(anchor.cells):
                        raise ValueError(f"{edit.block_id}: replacement row has a different column count")
                    for cell, value in zip(anchor.cells, replacement_cells):
                        if _visible_cell_text(cell) != value:
                            _set_visible_cell_text(cell, value)
                    rows_to_insert = rows_to_insert[1:]
                for row_text in rows_to_insert:
                    cells = _row_values(row_text)
                    new_tr = deepcopy(anchor._tr)
                    anchor._tr.addnext(new_tr)
                    new_row = _Row(new_tr, table)
                    if len(cells) != len(new_row.cells):
                        raise ValueError(f"{edit.block_id}: inserted row has a different column count")
                    for cell, value in zip(new_row.cells, cells):
                        cell.text = value
                    anchor = new_row
                changed = True
                continue
            # Some proposals supply only the value cell, including in
            # requirement tables. Require a unique, complete cell match.
            if len(before_cells) == 1 and len(after_cells) == 1:
                matches = {cell._tc: cell for table in tables for row in table.rows
                           for cell in row.cells[1:]
                           if " ".join(_visible_cell_text(cell).split()) == " ".join(before_cells[0].split())}
                if len(matches) > 1:
                    raise ValueError(f"{edit.block_id}: before text matches multiple table cells")
                if matches:
                    next(iter(matches.values())).text = after_cells[0]
                    changed = True
                    continue
            row_match = next((row for table in tables for row in table.rows
                              if _row_matches(row, before_cells)), None)
            if row_match is None:
                raise ValueError(f"{edit.block_id}: before row is no longer in the document")
            if len(after_cells) != len(row_match.cells):
                raise ValueError(f"{edit.block_id}: replacement row has a different column count")
            for cell, value in zip(row_match.cells, after_cells):
                if _visible_cell_text(cell) != value:
                    _set_visible_cell_text(cell, value)
            changed = True
            continue
        anchor = edit.before
        if edit.operation == "insert_after" and anchor in replaced_anchors:
            paragraph, anchor = replaced_anchors[anchor]
        else:
            matches = [item for item in all_paragraphs if anchor in _visible_xml_text(item._p)]
            if len(matches) > 1:
                raise ValueError(f"{edit.block_id}: before text matches multiple paragraphs")
            paragraph = matches[0] if matches else None
        visible_text = _visible_xml_text(paragraph._p) if paragraph is not None else ""
        if paragraph is None or anchor not in visible_text:
            raise ValueError(f"{edit.block_id}: before text is no longer in the document")
        if visible_text.count(anchor) != 1:
            raise ValueError(f"{edit.block_id}: before text matches multiple locations")
        if edit.operation == "replace_sentence":
            replacement = edit.after
            replaced_anchors[edit.before] = (paragraph, edit.after)
        else:
            replacement = anchor + " " + edit.after
            replaced_anchors[edit.before] = (paragraph, replacement)
        if not _replace_visible_paragraph_text(paragraph, anchor, replacement):
            raise ValueError(f"{edit.block_id}: before text is no longer in the document")
        changed = True
    if not changed:
        raise ValueError("Improve proposal made no document change")
    temporary = path.with_suffix(path.suffix + ".tmp")
    document.save(str(temporary))
    temporary.replace(path)


def apply_proposal(
    document_path: Path | str,
    proposal: ImprovementProposal | Mapping[str, Any],
    context: Mapping[str, Any],
    backup_dir: Path | str,
) -> dict[str, Any]:
    """Apply a checked proposal with a backup and hash guard.

    This is the draft-stage plain-text path.  It never creates tracked changes.
    """
    source = Path(document_path)
    typed = proposal if isinstance(proposal, ImprovementProposal) else ImprovementProposal.from_dict(proposal)
    errors = validate_for_context(typed, context)
    if errors:
        raise ValueError("cannot apply Improve proposal: " + "; ".join(errors))
    if _document_hash(source) != context.get("document_hash"):
        raise ValueError("working document changed since the Improve proposal was built")
    destination = Path(backup_dir)
    destination.mkdir(parents=True, exist_ok=True)
    backup = destination / f"{source.stem}-before-improve-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{source.suffix}"
    shutil.copy2(source, backup)
    if source.suffix.lower() == ".docx":
        _apply_docx(source, typed, str(context.get("heading") or ""))
    else:
        _apply_text(source, typed)
    return {"status": "OK", "backup": str(backup), "document_hash": _document_hash(source),
            "section_key": typed.section_key, "edit_count": len([edit for edit in typed.edits if edit.operation != "keep"])}
