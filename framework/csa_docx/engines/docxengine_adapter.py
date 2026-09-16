from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from csa_docx.models import ChangeRecord, EditResult
from csa_docx.ooxml import (
    CONTENT_TYPES_NS,
    REL_NS,
    W_NS,
    _anchor_variants,
    _cell_index_for_field,
    _extract_following_bullet_count,
    _extract_labeled_values,
    _extract_pipe_row_replacements,
    _extract_range_spec,
    _extract_row_labels,
    _has_anchor_plus_bullets_replacement,
    _has_range_replacement,
    _has_section_body_replacement,
    _values_for_row,
    find_anchor,
    markdown_to_paragraph_texts,
    normalise_text,
    paragraph_text,
    qn,
)

VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor"
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from docxengine import Document
    from docxengine.errors import ToolError
except Exception as exc:  # pragma: no cover - exercised only when dependency is absent.
    Document = None  # type: ignore[assignment]
    ToolError = Exception  # type: ignore[assignment]
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class DocxEngineEditor:
    """CSA adapter over the open-source DocxEngine library.

    The adapter keeps CSA-specific decisions in this framework and delegates the
    DOCX package mutation, anchor validation, and comment wiring to DocxEngine.
    Unsupported operations return BLOCKED so the controller can fall back or stop.
    """

    def __init__(self, docx_path: Path, section_heading: str | None = None):
        if Document is None:
            raise RuntimeError(f"docxengine is unavailable: {IMPORT_ERROR}")
        self.docx_path = Path(docx_path)
        self.section_heading = normalise_text(section_heading or "")
        self.doc = Document.open(self.docx_path)

    def apply_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        where_lower = record.where.lower()
        if "row beginning" in where_lower or "table" in where_lower:
            return self._apply_table_row_change(record, author, initials)
        if _has_section_body_replacement(record) or "replace the entire subsection" in record.action.lower():
            return self._apply_section_body_replacement(record, author, initials)
        if _has_range_replacement(record) or _extract_heading_to_sentence_range(record):
            return self._apply_explicit_range_replacement(record, author, initials)
        if _has_paragraph_plus_following_line_replacement(record):
            return self._apply_anchor_plus_following_content(record, 1, author, initials)
        if _has_delete_until_heading(record):
            return self._apply_delete_until_heading(record, author, initials)
        if _has_anchor_plus_bullets_replacement(record):
            return self._apply_anchor_plus_bullets_replacement(record, author, initials)
        return self._apply_simple_paragraph_change(record, author, initials)

    def save(self) -> None:
        self.doc.save(self.docx_path)

    def _apply_simple_paragraph_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        anchor_text = find_anchor(record.where)
        if not anchor_text:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract a unique anchor from Where")
        matches = self._matching_paragraphs(anchor_text, record.where)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
        paragraph = matches[0]
        action = record.action.lower()

        try:
            if "insert before" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor_text)
                result = self.doc.insert(record.text, before=paragraph.anchor, author=author)
                comment_anchor = _result_anchor(result) or paragraph.anchor
                comment_id = self._add_comment(comment_anchor, record, author, initials)
                return EditResult(record.edit_id, "APPLIED", "Inserted approved text before anchor with DocxEngine", anchor_text, comment_id)

            if "insert after" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor_text)
                result = self.doc.insert(record.text, after=paragraph.anchor, author=author)
                comment_anchor = _result_anchor(result) or paragraph.anchor
                comment_id = self._add_comment(comment_anchor, record, author, initials)
                return EditResult(record.edit_id, "APPLIED", "Inserted approved text after anchor with DocxEngine", anchor_text, comment_id)

            if "delete" in action and "replace" not in action:
                self.doc.delete(anchor=paragraph.anchor, author=author)
                return EditResult(record.edit_id, "APPLIED", "Deleted anchored paragraph with DocxEngine", anchor_text)

            if "replace" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Replace action has no Text", anchor_text)
                replacement_paragraphs = markdown_to_paragraph_texts(record.text)
                if not replacement_paragraphs:
                    return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", anchor_text)
                result = self.doc.edit_paragraph(paragraph.anchor, replacement_paragraphs[0], author=author)
                first_anchor = _result_anchor(result) or self._find_unique_text(replacement_paragraphs[0])
                if first_anchor is None:
                    return EditResult(record.edit_id, "BLOCKED", "Could not re-anchor edited paragraph", anchor_text)
                if len(replacement_paragraphs) > 1:
                    self.doc.insert("\n".join(replacement_paragraphs[1:]), after=first_anchor, author=author)
                comment_id = self._add_comment(first_anchor, record, author, initials)
                return EditResult(record.edit_id, "APPLIED", "Replaced anchored paragraph with DocxEngine", anchor_text, comment_id)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", anchor_text)

        return EditResult(record.edit_id, "BLOCKED", f"Unsupported action for DocxEngine adapter: {record.action}", anchor_text)

    def _apply_anchor_plus_bullets_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Anchor plus bullets replacement has no Text")
        bullet_count = _extract_following_bullet_count(record.action)
        if bullet_count is None:
            return EditResult(record.edit_id, "BLOCKED", "Could not determine following bullet count")
        anchor_text = find_anchor(record.where)
        if not anchor_text:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract anchor from Where")

        paragraphs = self.doc.paragraphs()
        matches = self._matching_paragraphs(anchor_text, record.where, paragraphs)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
        anchor_index = paragraphs.index(matches[0])
        end_index = self._following_content_end(paragraphs, anchor_index, bullet_count)
        if end_index is None:
            return EditResult(record.edit_id, "BLOCKED", f"Could not find {bullet_count} following bullet/content paragraph(s)", anchor_text)

        result = self._replace_range_by_index(
            record,
            paragraphs,
            anchor_index,
            end_index,
            record.text,
            author,
            initials,
            f"Replaced anchor paragraph and {bullet_count} following bullet/content paragraph(s) with DocxEngine",
        )
        if result.status != "APPLIED":
            return result

        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced anchor paragraph and {bullet_count} following bullet/content paragraph(s) with DocxEngine",
            anchor_text,
            result.comment_id,
        )

    def _apply_explicit_range_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Range replacement has no Text")
        range_spec = _extract_range_spec(record.raw)
        if range_spec:
            start_anchor, end_anchor, replacement_text = range_spec
        else:
            heading_range = _extract_heading_to_sentence_range(record)
            if not heading_range:
                return EditResult(record.edit_id, "BLOCKED", "Could not extract DocxEngine range boundaries")
            start_anchor, end_anchor = heading_range
            replacement_text = record.text

        paragraphs = self.doc.paragraphs()
        start_index = self._unique_paragraph_index(start_anchor, paragraphs, allow_prefix=True)
        end_index = self._unique_paragraph_index(end_anchor, paragraphs, allow_prefix=True, allow_suffix=True)
        if start_index is None or end_index is None or end_index < start_index:
            return EditResult(record.edit_id, "BLOCKED", "Range boundaries not unique or out of order", start_anchor)
        return self._replace_range_by_index(
            record,
            paragraphs,
            start_index,
            end_index,
            replacement_text,
            author,
            initials,
            f"Replaced paragraph range beginning: {start_anchor[:80]} with DocxEngine",
        )

    def _apply_section_body_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Section body replacement has no Text")
        anchor_text = find_anchor(record.where)
        if not anchor_text:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract section body anchor from Where")
        paragraphs = self.doc.paragraphs()
        matches = self._matching_paragraphs(anchor_text, record.where, paragraphs)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Section body anchor match count was {len(matches)}; expected 1", anchor_text)
        anchor_index = paragraphs.index(matches[0])
        heading_index = self._previous_heading_index(paragraphs, anchor_index)
        if heading_index is None:
            return EditResult(record.edit_id, "BLOCKED", "Could not identify containing section heading", anchor_text)
        end_index = self._section_body_end_index(paragraphs, heading_index)
        if end_index <= heading_index:
            return EditResult(record.edit_id, "BLOCKED", "Containing section has no replaceable body content", anchor_text)
        return self._replace_range_by_index(
            record,
            paragraphs,
            heading_index + 1,
            end_index,
            record.text,
            author,
            initials,
            f"Replaced body content under heading: {paragraphs[heading_index].text[:80]}",
        )

    def _apply_anchor_plus_following_content(self, record: ChangeRecord, content_count: int, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Anchor plus following content replacement has no Text")
        anchor_text = find_anchor(record.where)
        if not anchor_text:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract anchor from Where")
        paragraphs = self.doc.paragraphs()
        matches = self._matching_paragraphs(anchor_text, record.where, paragraphs)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
        anchor_index = paragraphs.index(matches[0])
        end_index = self._following_content_end(paragraphs, anchor_index, content_count)
        if end_index is None:
            return EditResult(record.edit_id, "BLOCKED", f"Could not find {content_count} following content paragraph(s)", anchor_text)
        return self._replace_range_by_index(
            record,
            paragraphs,
            anchor_index,
            end_index,
            record.text,
            author,
            initials,
            f"Replaced anchor paragraph and {content_count} following paragraph(s) with DocxEngine",
        )

    def _apply_delete_until_heading(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        start_anchor = find_anchor(record.where)
        end_anchor = _extract_delete_until_heading(record)
        if not start_anchor or not end_anchor:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract delete range boundaries")
        paragraphs = self.doc.paragraphs()
        start_matches = self._matching_paragraphs(start_anchor, record.where, paragraphs)
        if len(start_matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Delete start boundary match count was {len(start_matches)}; expected 1", start_anchor)
        start_index = paragraphs.index(start_matches[0])
        boundary_index = self._next_matching_heading_index(paragraphs, start_index + 1, end_anchor)
        if boundary_index is None or boundary_index <= start_index:
            return EditResult(record.edit_id, "BLOCKED", "Delete range boundaries not unique or out of order", start_anchor)
        comment_target = paragraphs[boundary_index].anchor
        try:
            comment_id = self._add_comment(comment_target, record, author, initials)
            self._delete_indices(paragraphs, start_index, boundary_index - 1, author)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", start_anchor)
        return EditResult(record.edit_id, "APPLIED", f"Deleted range from {start_anchor[:80]} up to {end_anchor[:80]}", start_anchor, comment_id)

    def _apply_table_row_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Table row change has no Text")

        pipe_rows = _extract_pipe_row_replacements(record.text)
        if pipe_rows:
            return self._apply_pipe_row_replacements(pipe_rows, record, author, initials)

        row_labels = _extract_row_labels(record.where, record.text)
        if not row_labels:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract row label from Where")

        field_values = _extract_labeled_values(record.text)
        if not field_values:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract labelled table replacement values")

        updates: list[TableCellUpdate] = []
        for row_label in row_labels:
            row_ref = self._find_unique_table_row(row_label)
            if row_ref is None:
                return EditResult(record.edit_id, "BLOCKED", f"Table row anchor not unique or not found: {row_label}", row_label)
            replacements = _values_for_row(row_label, field_values)
            if not replacements:
                return EditResult(record.edit_id, "BLOCKED", f"No replacement values matched table row: {row_label}", row_label)
            for field_name, value in replacements.items():
                cell_index = _cell_index_for_field(row_ref.headers, field_name)
                if cell_index is None:
                    return EditResult(record.edit_id, "BLOCKED", f"Could not identify table column for {field_name}", row_label)
                updates.append(TableCellUpdate(row_ref.table_anchor, row_ref.row_index, cell_index, row_label, value))

        return self._apply_table_updates(updates, record, author, initials)

    def _apply_pipe_row_replacements(
        self,
        pipe_rows: list[tuple[str, list[str]]],
        record: ChangeRecord,
        author: str,
        initials: str,
    ) -> EditResult:
        updates: list[TableCellUpdate] = []
        for row_label, cells in pipe_rows:
            row_ref = self._find_unique_table_row(row_label)
            if row_ref is None:
                return EditResult(record.edit_id, "BLOCKED", f"Table row anchor not unique or not found: {row_label}", row_label)
            row_cell_count = len(row_ref.cell_texts)
            if row_cell_count != len(cells) + 1:
                return EditResult(
                    record.edit_id,
                    "BLOCKED",
                    f"Pipe row for {row_label} supplies {len(cells)} value(s); table row has {row_cell_count} cells (expected label + {row_cell_count - 1})".strip(),
                    row_label,
                )
            for position, value in enumerate(cells):
                updates.append(TableCellUpdate(row_ref.table_anchor, row_ref.row_index, position + 1, row_label, value))

        return self._apply_table_updates(updates, record, author, initials)

    def _apply_table_updates(
        self,
        updates: list["TableCellUpdate"],
        record: ChangeRecord,
        author: str,
        initials: str,
    ) -> EditResult:
        if not updates:
            return EditResult(record.edit_id, "BLOCKED", "No table cell updates were resolved")

        grouped: dict[str, list[TableCellUpdate]] = {}
        for update in updates:
            grouped.setdefault(update.table_anchor, []).append(update)

        try:
            for table_anchor, table_updates in grouped.items():
                self.doc.table(
                    "set_cells",
                    anchor=table_anchor,
                    cells=[
                        {"r": update.row_index, "c": update.cell_index, "text": update.value}
                        for update in table_updates
                    ],
                    author=author,
                )
            comment_id = self._add_table_cell_comment(updates[0], record, author, initials)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine table error: {exc}", updates[0].row_label)

        affected_labels = []
        for update in updates:
            if update.row_label not in affected_labels:
                affected_labels.append(update.row_label)
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Updated {len(updates)} table cell(s) across {len(affected_labels)} row(s) with DocxEngine",
            ", ".join(affected_labels),
            comment_id,
        )

    def _find_unique_table_row(self, row_label: str) -> "TableRowRef | None":
        matches: list[TableRowRef] = []
        wanted = normalise_text(row_label)
        for table_anchor, rows in self._table_rows():
            headers = rows[0] if rows else []
            for row_index, cell_texts in enumerate(rows):
                if not cell_texts:
                    continue
                first_cell = normalise_text(cell_texts[0])
                if first_cell == wanted or first_cell.startswith(wanted):
                    matches.append(TableRowRef(table_anchor, row_index, headers, cell_texts))
        return matches[0] if len(matches) == 1 else None

    def _table_rows(self) -> list[tuple[str, list[list[str]]]]:
        package = self.doc._doc.package
        data = package.part(package.main_document_part())
        root = ET.fromstring(data)
        body = root.find(qn(W_NS, "body"))
        if body is None:
            return []
        tables: list[tuple[str, list[list[str]]]] = []
        table_index = 0
        for child in list(body):
            if child.tag != qn(W_NS, "tbl"):
                continue
            table_index += 1
            rows: list[list[str]] = []
            for row in [node for node in list(child) if node.tag == qn(W_NS, "tr")]:
                cells: list[str] = []
                for cell in [node for node in list(row) if node.tag == qn(W_NS, "tc")]:
                    cells.append(normalise_text(" ".join(paragraph_text(p) for p in cell.iter(qn(W_NS, "p")))))
                rows.append(cells)
            tables.append((f"T{table_index}", rows))
        return tables

    def _add_table_cell_comment(self, update: "TableCellUpdate", record: ChangeRecord, author: str, initials: str) -> str | None:
        package = self.doc._doc.package
        main_part = package.main_document_part()
        root = ET.fromstring(package.part(main_part))
        paragraph = self._find_table_cell_paragraph(root, update)
        if paragraph is None:
            return None

        comment_id = self._append_comment_part(record, author, initials)
        children = list(paragraph)
        insert_at = 1 if children and children[0].tag == qn(W_NS, "pPr") else 0
        paragraph.insert(insert_at, ET.Element(qn(W_NS, "commentRangeStart"), {qn(W_NS, "id"): comment_id}))
        paragraph.append(ET.Element(qn(W_NS, "commentRangeEnd"), {qn(W_NS, "id"): comment_id}))
        ref_run = ET.Element(qn(W_NS, "r"))
        ET.SubElement(ref_run, qn(W_NS, "commentReference"), {qn(W_NS, "id"): comment_id})
        paragraph.append(ref_run)

        package.set_part(main_part, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        self.doc._doc.mark_dirty()
        self._ensure_comment_relationship_parts()
        return comment_id

    def _find_table_cell_paragraph(self, root: ET.Element, update: "TableCellUpdate") -> ET.Element | None:
        table_ordinal = int(update.table_anchor[1:])
        body = root.find(qn(W_NS, "body"))
        if body is None:
            return None
        seen = 0
        for child in list(body):
            if child.tag != qn(W_NS, "tbl"):
                continue
            seen += 1
            if seen != table_ordinal:
                continue
            rows = [node for node in list(child) if node.tag == qn(W_NS, "tr")]
            if update.row_index >= len(rows):
                return None
            cells = [node for node in list(rows[update.row_index]) if node.tag == qn(W_NS, "tc")]
            if update.cell_index >= len(cells):
                return None
            paragraph = cells[update.cell_index].find(qn(W_NS, "p"))
            if paragraph is None:
                paragraph = ET.SubElement(cells[update.cell_index], qn(W_NS, "p"))
            return paragraph
        return None

    def _append_comment_part(self, record: ChangeRecord, author: str, initials: str) -> str:
        package = self.doc._doc.package
        comments_part = "word/comments.xml"
        if package.has_part(comments_part):
            comments_root = ET.fromstring(package.part(comments_part))
        else:
            comments_root = ET.Element(qn(W_NS, "comments"))
        existing_ids = [int(node.get(qn(W_NS, "id"), "0")) for node in comments_root.findall(qn(W_NS, "comment"))]
        comment_id = str(max(existing_ids, default=-1) + 1)
        comment = ET.SubElement(
            comments_root,
            qn(W_NS, "comment"),
            {
                qn(W_NS, "id"): comment_id,
                qn(W_NS, "author"): author,
                qn(W_NS, "initials"): initials,
            },
        )
        paragraph = ET.SubElement(comment, qn(W_NS, "p"))
        run = ET.SubElement(paragraph, qn(W_NS, "r"))
        text = ET.SubElement(run, qn(W_NS, "t"))
        text.text = f"{record.edit_id}: {record.why or record.title}"
        package.set_part(comments_part, ET.tostring(comments_root, encoding="utf-8", xml_declaration=True))
        self.doc._doc.mark_dirty()
        return comment_id

    def _ensure_comment_relationship_parts(self) -> None:
        package = self.doc._doc.package
        rels_part = "word/_rels/document.xml.rels"
        if package.has_part(rels_part):
            rels_root = ET.fromstring(package.part(rels_part))
        else:
            rels_root = ET.Element(qn(REL_NS, "Relationships"))
        if not any(rel.get("Type", "").endswith("/comments") for rel in rels_root):
            ids = []
            for rel in rels_root:
                rel_id = rel.get("Id", "")
                if rel_id.startswith("rId") and rel_id[3:].isdigit():
                    ids.append(int(rel_id[3:]))
            rel = ET.SubElement(rels_root, qn(REL_NS, "Relationship"))
            rel.set("Id", f"rId{max(ids, default=0) + 1}")
            rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")
            rel.set("Target", "comments.xml")
            package.set_part(rels_part, ET.tostring(rels_root, encoding="utf-8", xml_declaration=True))

        content_types_part = "[Content_Types].xml"
        ct_root = ET.fromstring(package.part(content_types_part))
        if not any(part.get("PartName") == "/word/comments.xml" for part in ct_root):
            override = ET.SubElement(ct_root, qn(CONTENT_TYPES_NS, "Override"))
            override.set("PartName", "/word/comments.xml")
            override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
            package.set_part(content_types_part, ET.tostring(ct_root, encoding="utf-8", xml_declaration=True))
        self.doc._doc.mark_dirty()

    def _matching_paragraphs(self, anchor_text: str, where: str, paragraphs=None):
        paragraphs = paragraphs if paragraphs is not None else self.doc.paragraphs()
        variants = _anchor_variants(anchor_text)
        exact_matches = [p for p in paragraphs if normalise_text(p.text) in variants]
        if exact_matches:
            return self._scope_matches(exact_matches)
        if "beginning exactly" in where.lower() or "text beginning" in where.lower() or "words beginning" in where.lower():
            prefix_matches = [p for p in paragraphs if any(normalise_text(p.text).startswith(variant) for variant in variants)]
            return self._scope_matches(prefix_matches)
        contains_matches = [p for p in paragraphs if any(variant in normalise_text(p.text) for variant in variants)]
        return self._scope_matches(contains_matches)

    def _scope_matches(self, matches):
        if not self.section_heading or len(matches) <= 1:
            return matches
        paragraphs = self.doc.paragraphs()
        heading_indexes = [
            index
            for index, paragraph in enumerate(paragraphs)
            if _is_heading(paragraph) and self.section_heading in normalise_text(paragraph.text)
        ]
        if not heading_indexes:
            return matches
        first_heading = heading_indexes[-1]
        heading_level = _heading_level(paragraphs[first_heading])
        next_heading = len(paragraphs)
        for index in range(first_heading + 1, len(paragraphs)):
            level = _heading_level(paragraphs[index])
            if level is not None and heading_level is not None and level <= heading_level:
                next_heading = index
                break
        scoped_anchors = {paragraphs[index].anchor for index in range(first_heading + 1, next_heading)}
        return [match for match in matches if match.anchor in scoped_anchors]

    def _following_content_end(self, paragraphs, anchor_index: int, count: int) -> int | None:
        found = 0
        index = anchor_index + 1
        while index < len(paragraphs) and found < count:
            paragraph = paragraphs[index]
            if _is_heading(paragraph):
                return None
            if normalise_text(paragraph.text):
                found += 1
            index += 1
        if found != count:
            return None
        return index - 1

    def _replace_range_by_index(
        self,
        record: ChangeRecord,
        paragraphs,
        start_index: int,
        end_index: int,
        replacement_text: str,
        author: str,
        initials: str,
        message: str,
    ) -> EditResult:
        replacement_paragraphs = markdown_to_paragraph_texts(replacement_text)
        if not replacement_paragraphs:
            return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", paragraphs[start_index].text)
        start_anchor_text = paragraphs[start_index].text
        old_following = paragraphs[start_index + 1 : end_index + 1]
        try:
            result = self.doc.edit_paragraph(paragraphs[start_index].anchor, replacement_paragraphs[0], author=author)
            first_anchor = _result_anchor(result) or self._find_unique_text(replacement_paragraphs[0])
            if first_anchor is None:
                return EditResult(record.edit_id, "BLOCKED", "Could not re-anchor edited paragraph", start_anchor_text)
            for paragraph in reversed(old_following):
                self.doc.delete(anchor=paragraph.anchor, author=author)
            if len(replacement_paragraphs) > 1:
                self.doc.insert("\n".join(replacement_paragraphs[1:]), after=first_anchor, author=author)
            comment_id = self._add_comment(first_anchor, record, author, initials)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", start_anchor_text)
        return EditResult(record.edit_id, "APPLIED", message, start_anchor_text, comment_id)

    def _delete_indices(self, paragraphs, start_index: int, end_index: int, author: str) -> None:
        for paragraph in reversed(paragraphs[start_index : end_index + 1]):
            self.doc.delete(anchor=paragraph.anchor, author=author)

    def _unique_paragraph_index(self, anchor_text: str, paragraphs, *, allow_prefix: bool = False, allow_suffix: bool = False) -> int | None:
        variants = _anchor_variants(anchor_text)
        matches: list[int] = []
        for index, paragraph in enumerate(paragraphs):
            text = normalise_text(paragraph.text)
            if any(text == variant or (allow_prefix and text.startswith(variant)) or (allow_suffix and text.endswith(variant)) for variant in variants):
                matches.append(index)
        return matches[0] if len(matches) == 1 else None

    def _next_matching_heading_index(self, paragraphs, start_index: int, anchor_text: str) -> int | None:
        variants = _anchor_variants(anchor_text)
        for index in range(start_index, len(paragraphs)):
            if _heading_level(paragraphs[index]) is None:
                continue
            text = normalise_text(paragraphs[index].text)
            if any(text == variant or text.startswith(variant) for variant in variants):
                return index
        return None

    def _previous_heading_index(self, paragraphs, start_index: int) -> int | None:
        for index in range(start_index, -1, -1):
            if _heading_level(paragraphs[index]) is not None:
                return index
        return None

    def _section_body_end_index(self, paragraphs, heading_index: int) -> int:
        heading_level = _heading_level(paragraphs[heading_index])
        end_index = len(paragraphs) - 1
        for index in range(heading_index + 1, len(paragraphs)):
            level = _heading_level(paragraphs[index])
            if level is not None and heading_level is not None and level <= heading_level:
                end_index = index - 1
                break
        return end_index

    def _find_unique_text(self, text: str) -> str | None:
        target = normalise_text(text)
        matches = [p for p in self.doc.paragraphs() if normalise_text(p.text) == target]
        return matches[0].anchor if len(matches) == 1 else None

    def _add_comment(self, anchor: str, record: ChangeRecord, author: str, initials: str) -> str | None:
        self._ensure_comment_namespaces()
        comment_text = f"{record.edit_id}: {record.why.strip()}"
        if record.questions:
            comment_text += "\nQuestions:\n" + "\n".join(f"- {question}" for question in record.questions)
        if initials:
            comment_text += f"\nInitials: {initials}"
        result = self.doc.comment("add", anchor=anchor, text=comment_text, author=author)
        return str(result.get("comment_id")) if result.get("comment_id") else None

    def _ensure_comment_namespaces(self) -> None:
        package = self.doc._doc.package
        part_name = "word/comments.xml"
        if not package.has_part(part_name):
            return
        data = package.part(part_name)
        match = re.search(rb"<w:comments\b[^>]*>", data)
        if not match:
            return
        open_tag = match.group(0)
        if b"xmlns:w14=" in open_tag:
            return
        patched = data[: match.start()] + open_tag.replace(
            b"<w:comments",
            b'<w:comments xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"',
            1,
        ) + data[match.end() :]
        if patched != data:
            package.set_part(part_name, patched)
            self.doc._doc.mark_dirty()


def _result_anchor(result: dict[str, object]) -> str | None:
    value = result.get("anchor") or result.get("new_anchor")
    return str(value) if value else None


def _is_heading(paragraph) -> bool:
    return _heading_level(paragraph) is not None


def _heading_level(paragraph) -> int | None:
    style = paragraph.style or ""
    match = re.match(r"Heading([1-9])", style)
    return int(match.group(1)) if match else None


def _extract_heading_to_sentence_range(record: ChangeRecord) -> tuple[str, str] | None:
    match = re.search(
        r"\*\*where:\*\*.*?heading:\s*`([^`]+)`.*?\*\*do:\*\*\s*replace all content from this heading through the sentence ending:\s*`([^`]+)`",
        record.raw,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _has_paragraph_plus_following_line_replacement(record: ChangeRecord) -> bool:
    action = record.action.lower()
    return "replace this paragraph and the following line" in action or "replace this paragraph and following line" in action


def _has_delete_until_heading(record: ChangeRecord) -> bool:
    action = record.action.lower()
    return action.startswith("delete sections") and " up to " in action


def _extract_delete_until_heading(record: ChangeRecord) -> str | None:
    match = re.search(r"\bup to\s+`([^`]+)`", record.action, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bup to\s+([0-9]+(?:\.[0-9]+)*\s+[^\n.]+)", record.action, re.IGNORECASE)
    return match.group(1).strip() if match else None


class TableRowRef:
    def __init__(self, table_anchor: str, row_index: int, headers: list[str], cell_texts: list[str]):
        self.table_anchor = table_anchor
        self.row_index = row_index
        self.headers = headers
        self.cell_texts = cell_texts


class TableCellUpdate:
    def __init__(self, table_anchor: str, row_index: int, cell_index: int, row_label: str, value: str):
        self.table_anchor = table_anchor
        self.row_index = row_index
        self.cell_index = cell_index
        self.row_label = row_label
        self.value = value
