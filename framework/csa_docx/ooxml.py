from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

from .models import ChangeRecord, EditResult

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

ET.register_namespace("w", W_NS)


def qn(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(qn(W_NS, "t")))


def normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


_BRITISH_SPELLING_PATTERNS = (
    (re.compile(r"isation\b", re.IGNORECASE), "ization"),
    (re.compile(r"isable\b", re.IGNORECASE), "izable"),
    (re.compile(r"ising\b", re.IGNORECASE), "izing"),
    (re.compile(r"ised\b", re.IGNORECASE), "ized"),
    (re.compile(r"iser\b", re.IGNORECASE), "izer"),
)


def spelling_normalised_text(value: str) -> str:
    """``normalise_text`` plus British "-ise"/"-isation" -> American "-ize"/"-ization".

    Approved CSA change records are authored in Australian/British English
    (for example "Section 9 - Time Synchronisation"), while the underlying Word
    document heading may use American spelling for the same section (for
    example "Time Synchronization"), or vice versa. A literal substring check
    between a change record's section label and a document heading then fails
    even though they name the same section, which silently defeats the
    heading-scoped anchor disambiguation in
    ``docxengine_adapter.DocxEngineEditor._scope_matches`` and produces a
    spurious multi-match ``BLOCKED`` result for an anchor phrase (like
    "This confirms:") that is reused, by design, across several subsections.
    Apply this to both sides of a heading-name comparison, not to approved
    edit text itself.
    """
    text = normalise_text(value)
    for pattern, replacement in _BRITISH_SPELLING_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def find_anchor(where: str) -> str | None:
    ticks = re.findall(r"`([^`]+)`", where)
    if ticks:
        return ticks[0].strip()
    quoted = re.findall(r'"([^"]+)"', where)
    if quoted:
        return quoted[0].strip()
    patterns = [
        r"beginning exactly:\s*(.+)$",
        r"sentence exactly:\s*(.+)$",
        r"heading exactly:\s*(.+)$",
        r"bullet exactly:\s*(.+)$",
        r"bullet beginning exactly:\s*(.+)$",
        r"text beginning exactly:\s*(.+)$",
        r"words beginning exactly:\s*(.+)$",
        # Covers "immediately before:" / "immediately after:", optionally
        # with descriptive filler before the colon (e.g. "immediately after
        # the WMI evidence:"). Missing previously, so Where clauses using
        # this phrasing (Section 11/12 edits E-177, E-196) fell through to
        # treating the entire Where text as the anchor, which is always
        # wrong since it also contains the "Section N, immediately
        # before/after..." prefix.
        r"immediately before(?:[^:\n]*):\s*(.+)$",
        r"immediately after(?:[^:\n]*):\s*(.+)$",
        # "Anchor: in Section N.M.K" / "Anchor: in the paragraph after X" -
        # the anchor itself, with a location description after "in". The old
        # code fell through to treating the whole string (including the
        # "in Section ..." suffix) as the anchor, which matches no paragraph.
        r"^(?P<anch>.+?)\s+in\s+(?:section|subsection|paragraph|heading|the paragraph)(?:\s+.*)?$",
        # "standalone text exactly:" - a short, deliberately isolated phrase
        # (e.g. a one-word subheading) called out differently from
        # "sentence exactly"/"heading exactly" but functionally identical.
        r"standalone text exactly:\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, where, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    cleaned = normalise_text(where)
    if cleaned and "\n" not in where.strip() and len(cleaned) <= 240:
        return cleaned
    return None


def _strip_blockquote_marker(line: str) -> str:
    """Strip a leading Markdown blockquote marker ("> " or a bare ">").

    The project's change records write multi-paragraph **Text:** replacement
    content as a Markdown blockquote (each line, including blank separator
    lines, prefixed with ">"). Without this, a bare ">" separator line is
    non-empty and defeats blank-line paragraph splitting, and the literal
    "> " prefix leaks into the applied document text. This mirrors the
    stripping already done in change_parser._extract_text_block and in the
    table/label extraction helpers below, applied here too since
    markdown_to_paragraph_texts is the shared choke point every replacement
    path (record.text-based and raw-regex-extracted range replacements
    alike) funnels through before text is written into the DOCX.
    """
    stripped = line.rstrip()
    left = stripped.lstrip()
    if left.startswith(">"):
        left = left[1:]
        if left.startswith(" "):
            left = left[1:]
        return left
    return stripped


def markdown_to_paragraph_texts(markdown_text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for raw_line in markdown_text.splitlines():
        line = _strip_blockquote_marker(raw_line)
        if not line.strip():
            if current:
                parts.append("\n".join(current).strip())
                current = []
            continue
        text = _strip_inline_markdown(line)
        if text.startswith("- "):
            if current:
                parts.append("\n".join(current).strip())
                current = []
            parts.append(text)
            continue
        current.append(text)
    if current:
        parts.append("\n".join(current).strip())
    return [part for part in parts if part]


def _strip_inline_markdown(value: str) -> str:
    value = re.sub(r"^\s*[-*]\s+", "- ", value.strip())
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    return value.replace("`", "")


class DocumentEditor:
    def __init__(self, document_xml_path: Path, section_heading: str | None = None):
        self.document_xml_path = document_xml_path
        self.section_heading = normalise_text(section_heading or "")
        self.tree = ET.parse(document_xml_path)
        self.root = self.tree.getroot()

    def paragraphs(self) -> list[ET.Element]:
        return list(self.root.iter(qn(W_NS, "p")))

    def apply_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        action = record.action.lower()
        where_lower = record.where.lower()
        if "row beginning" in where_lower:
            return self._apply_table_row_change(record, author, initials)
        if _has_range_replacement(record):
            return self._apply_range_replacement(record, author, initials)
        if _has_section_body_replacement(record):
            return self._apply_section_body_replacement(record, author, initials)
        if _has_anchor_plus_bullets_replacement(record):
            return self._apply_anchor_plus_bullets_replacement(record, author, initials)
        if _has_counted_bullet_block(record):
            return self._apply_counted_bullet_block(record, author, initials)

        complex_markers = [
            "both paragraphs",
            "following",
            "through",
            "bullets",
            "rows",
            "assessment wording",
        ]
        if any(marker in action or marker in where_lower for marker in complex_markers):
            return EditResult(
                record.edit_id,
                "BLOCKED",
                "Complex range or table operation requires controlled manual OOXML handling",
            )
        anchor = find_anchor(record.where)
        if not anchor:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract a unique anchor from Where")

        matches = self._matching_paragraphs(anchor, record.where)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor)

        paragraph = matches[0]
        before = paragraph_text(paragraph)

        if "insert before" in action:
            if not record.text:
                return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor)
            inserted = self._insert_paragraphs(paragraph, record.text, before=True)
            comment_id = self.add_comment(inserted[0], record, author, initials)
            return EditResult(record.edit_id, "APPLIED", "Inserted approved text before anchor", anchor, comment_id)

        if "insert after" in action:
            if not record.text:
                return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor)
            inserted = self._insert_paragraphs(paragraph, record.text, before=False)
            comment_id = self.add_comment(inserted[0], record, author, initials)
            return EditResult(record.edit_id, "APPLIED", "Inserted approved text after anchor", anchor, comment_id)

        if "replace" in action:
            if not record.text:
                return EditResult(record.edit_id, "BLOCKED", "Replace action has no Text", anchor)
            replacement_paragraphs = markdown_to_paragraph_texts(record.text)
            if not replacement_paragraphs:
                return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", anchor)
            self._set_paragraph_text(paragraph, replacement_paragraphs[0], preserve_list=replacement_paragraphs[0].startswith("- "))
            last = paragraph
            for extra in replacement_paragraphs[1:]:
                last = self._insert_text_paragraph_after(last, extra)
            comment_id = self.add_comment(paragraph, record, author, initials)
            return EditResult(record.edit_id, "APPLIED", f"Replaced paragraph text beginning: {before[:80]}", anchor, comment_id)

        if "delete" in action:
            parent = self._parent_map()[paragraph]
            comment_target = self._nearest_paragraph_sibling(parent, paragraph)
            comment_id = self.add_comment(comment_target, record, author, initials) if comment_target is not None else None
            parent.remove(paragraph)
            return EditResult(record.edit_id, "APPLIED", "Deleted uniquely matched paragraph", anchor, comment_id)

        return EditResult(record.edit_id, "BLOCKED", f"Unsupported Do instruction: {record.action}", anchor)

    def _apply_table_row_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Table row change has no Text")

        pipe_rows = _extract_pipe_row_replacements(record.text, record.where)
        if pipe_rows:
            return self._apply_pipe_row_replacements(pipe_rows, record, author, initials)

        row_labels = _extract_row_labels(record.where, record.text)
        if not row_labels:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract row label from Where")

        field_values = _extract_labeled_values(record.text)
        if not field_values:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract labelled table replacement values")

        comment_id: str | None = None
        changed = 0
        for row_label in row_labels:
            row = self._find_unique_table_row(row_label)
            if row is None:
                return EditResult(record.edit_id, "BLOCKED", f"Table row anchor not unique or not found: {row_label}", row_label)
            headers = self._table_headers_for_row(row)
            replacements = _values_for_row(row_label, field_values)
            if not replacements:
                return EditResult(record.edit_id, "BLOCKED", f"No replacement values matched table row: {row_label}", row_label)
            for field_name, value in replacements.items():
                cell_index = _cell_index_for_field(headers, field_name)
                if cell_index is None:
                    return EditResult(record.edit_id, "BLOCKED", f"Could not identify table column for {field_name}", row_label)
                paragraph = self._first_cell_paragraph(row, cell_index)
                self._set_paragraph_text(paragraph, value, preserve_list=False)
                if comment_id is None:
                    comment_id = self.add_comment(paragraph, record, author, initials)
                changed += 1

        range_result = None
        if _has_range_replacement(record):
            range_result = self._apply_range_replacement(record, author, initials, add_new_comment=False)
            if range_result.status != "APPLIED":
                return range_result

        detail = f"Updated {changed} table cell(s)"
        if range_result:
            detail += " and replaced the related paragraph range"
        return EditResult(record.edit_id, "APPLIED", detail, ", ".join(row_labels), comment_id)

    def _apply_pipe_row_replacements(
        self,
        pipe_rows: list[tuple[str, list[str]]],
        record: ChangeRecord,
        author: str,
        initials: str,
    ) -> EditResult:
        changed = 0
        comment_id: str | None = None
        affected_labels: list[str] = []
        for row_label, cells in pipe_rows:
            row = self._find_unique_table_row(row_label)
            if row is None:
                return EditResult(record.edit_id, "BLOCKED", f"Table row anchor not unique or not found: {row_label}", row_label)
            table_cells = row.findall(qn(W_NS, "tc"))
            # `cells` may be the full new row (when the anchor came from Where
            # and is distinct from the row's own content) or just the
            # non-label cells (historical shape, where the label cell is the
            # anchor and is left untouched). Detect which by matching the
            # cell count rather than assuming an offset.
            if len(table_cells) == len(cells):
                start_index = 0
            elif len(table_cells) == len(cells) + 1:
                start_index = 1
            else:
                return EditResult(
                    record.edit_id,
                    "BLOCKED",
                    f"Pipe row for {row_label} supplies {len(cells)} value(s); table row has {len(table_cells)} cells (expected {len(table_cells)} or {len(table_cells) - 1})".strip(),
                    row_label,
                )
            for position, value in enumerate(cells):
                cell = table_cells[position + start_index]
                paragraph = cell.find(qn(W_NS, "p"))
                if paragraph is None:
                    paragraph = ET.SubElement(cell, qn(W_NS, "p"))
                self._set_paragraph_text(paragraph, value, preserve_list=False)
                if comment_id is None:
                    comment_id = self.add_comment(paragraph, record, author, initials)
                changed += 1
            if row_label not in affected_labels:
                affected_labels.append(row_label)
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Updated {changed} table cell(s) across {len(affected_labels)} row(s)",
            ", ".join(affected_labels),
            comment_id,
        )

    def _apply_range_replacement(
        self,
        record: ChangeRecord,
        author: str,
        initials: str,
        add_new_comment: bool = True,
    ) -> EditResult:
        range_spec = _extract_range_spec(record.raw)
        if not range_spec:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract range replacement boundaries")
        start_anchor, end_anchor, replacement_text = range_spec
        replacement_paragraphs = markdown_to_paragraph_texts(replacement_text)
        if not replacement_paragraphs:
            return EditResult(record.edit_id, "BLOCKED", "Range replacement parsed to no paragraphs", start_anchor)

        paragraphs = self.paragraphs()
        start_index = _unique_paragraph_index(paragraphs, start_anchor)
        end_index = _unique_paragraph_index(paragraphs, end_anchor)
        if start_index is None or end_index is None or end_index < start_index:
            return EditResult(record.edit_id, "BLOCKED", "Range boundaries not unique or out of order", start_anchor)

        old_range = paragraphs[start_index : end_index + 1]
        parent_map = self._parent_map()
        template_ppr = old_range[0].find(qn(W_NS, "pPr"))
        comment_id: str | None = None
        for offset, text in enumerate(replacement_paragraphs):
            if offset < len(old_range):
                paragraph = old_range[offset]
            else:
                paragraph = self._insert_text_paragraph_after(old_range[-1], "")
                old_range.append(paragraph)
                parent_map = self._parent_map()
            if template_ppr is not None:
                ppr = paragraph.find(qn(W_NS, "pPr"))
                if ppr is not None:
                    paragraph.remove(ppr)
                paragraph.insert(0, ET.fromstring(ET.tostring(template_ppr)))
            self._set_paragraph_text(paragraph, text, preserve_list=text.startswith("- "))
            if add_new_comment and offset == 0:
                comment_id = self.add_comment(paragraph, record, author, initials)

        for paragraph in old_range[len(replacement_paragraphs) :]:
            parent = parent_map[paragraph]
            parent.remove(paragraph)

        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced paragraph range beginning: {start_anchor[:80]}",
            start_anchor,
            comment_id,
        )

    def _apply_anchor_plus_bullets_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Anchor plus bullets replacement has no Text")

        bullet_count = _extract_following_bullet_count(record.action)
        if bullet_count is None:
            return EditResult(record.edit_id, "BLOCKED", "Could not determine following bullet count")

        anchor = find_anchor(record.where)
        if not anchor:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract anchor from Where")

        matches = self._matching_paragraphs(anchor, record.where)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor)

        paragraphs = self.paragraphs()
        anchor_index = paragraphs.index(matches[0])
        end_index = _range_end_for_following_content(paragraphs, anchor_index, bullet_count)
        if end_index is None:
            return EditResult(record.edit_id, "BLOCKED", f"Could not find {bullet_count} following bullet/content paragraph(s)", anchor)

        old_range = paragraphs[anchor_index : end_index + 1]
        replacement_paragraphs = markdown_to_paragraph_texts(record.text)
        if not replacement_paragraphs:
            return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", anchor)

        comment_id = self._replace_paragraph_range(old_range, replacement_paragraphs, record, author, initials)
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced anchor paragraph and {bullet_count} following bullet/content paragraph(s)",
            anchor,
            comment_id,
        )

    def _apply_section_body_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Section body replacement has no Text")

        anchor = find_anchor(record.where)
        if not anchor:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract section body anchor from Where")

        matches = self._matching_paragraphs(anchor, record.where)
        if len(matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Section body anchor match count was {len(matches)}; expected 1", anchor)

        paragraphs = self.paragraphs()
        anchor_index = paragraphs.index(matches[0])
        heading_index = _previous_heading_index(paragraphs, anchor_index)
        if heading_index is None:
            return EditResult(record.edit_id, "BLOCKED", "Could not identify containing section heading", anchor)

        heading_level = _paragraph_heading_level(paragraphs[heading_index])
        if heading_level is None:
            return EditResult(record.edit_id, "BLOCKED", "Containing section heading has no Word heading level", anchor)

        end_index = len(paragraphs)
        for index in range(heading_index + 1, len(paragraphs)):
            level = _paragraph_heading_level(paragraphs[index])
            if level is not None and level <= heading_level:
                end_index = index
                break

        old_range = paragraphs[heading_index + 1 : end_index]
        if not old_range:
            return EditResult(record.edit_id, "BLOCKED", "Containing section has no replaceable body content", anchor)

        replacement_paragraphs = markdown_to_paragraph_texts(record.text)
        if not replacement_paragraphs:
            return EditResult(record.edit_id, "BLOCKED", "Section body replacement parsed to no paragraphs", anchor)

        comment_id = self._replace_paragraph_range(old_range, replacement_paragraphs, record, author, initials)
        heading_text = normalise_text(paragraph_text(paragraphs[heading_index]))
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced body content under heading: {heading_text[:80]}",
            anchor,
            comment_id,
        )

    def _counted_bullet_anchor(self) -> str | None:
        return find_anchor(self.where)

    def _apply_counted_bullet_block(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        count = _extract_following_bullet_count(record.action)
        anchor = find_anchor(record.where)
        if not anchor:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract anchor from Where (counted bullet block)")
        sub_bullets = "sub-bullet" in record.action.lower()
        anchor_matches = self._matching_paragraphs(anchor, record.where) if not sub_bullets else self._all_paragraph_matches(anchor)
        if len(anchor_matches) != 1:
            return EditResult(record.edit_id, "BLOCKED", f"Counted bullet block anchor not unique or not found: {anchor}", anchor)
        anchor_para = anchor_matches[0]
        anchor_index = self.paragraphs().index(anchor_para)
        if sub_bullets:
            block, block_count = self._sub_list_block_under_heading(anchor_index, count)
            if block_count != count:
                return EditResult(
                    record.edit_id,
                    "BLOCKED",
                    f"Expected {count} sub-bullet(s) under {anchor!r}; found {block_count}",
                    anchor,
                )
        else:
            parent_info = self._list_info(anchor_para)
            if parent_info is None or parent_info[0] < 0:
                return EditResult(record.edit_id, "BLOCKED", "Anchor is not a numbered/bulleted list item", anchor)
            anchor_level, anchor_numid = parent_info
            block, block_count = self._following_sibling_list(anchor_index, anchor_level, anchor_numid, count)
            if block_count != count:
                return EditResult(record.edit_id, "BLOCKED", f"Expected {count} list paragraph(s) beginning at {anchor!r}; found {block_count}", anchor)

        paragraphs = self.paragraphs()
        if "delete" in record.action.lower():
            for para in block:
                parent = self._parent_map()[para]
                parent.remove(para)
            if "heading" in record.action.lower() and "sub" in record.action.lower():
                comment_target = anchor_para
            elif "heading" in record.action.lower():
                comment_target = self._nearest_paragraph_sibling(self._parent_map()[anchor_para], anchor_para)
            else:
                comment_target = self._nearest_paragraph_sibling(self._parent_map()[block[0]], block[0])
            comment_id = self.add_comment(comment_target, record, author, initials) if comment_target is not None else None
            return EditResult(
                record.edit_id,
                "APPLIED",
                f"Deleted {len(block)} paragraph(s) under/beginning: {anchor[:80]}",
                anchor,
                comment_id,
            )

        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Replace counted bullet block has no Text", anchor)
        replacement_paragraphs = markdown_to_paragraph_texts(record.text)
        if not replacement_paragraphs:
            return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", anchor)
        if len(replacement_paragraphs) != len(block):
            return EditResult(record.edit_id, "BLOCKED",
                             f"Replacement supplies {len(replacement_paragraphs)} paragraph(s); existing block has {len(block)}; refusing to silently add/remove bullets", anchor)
        comment_id = self._replace_paragraph_range(block, replacement_paragraphs, record, author, initials)
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced {len(block)} bullet paragraph(s) beginning: {anchor[:80]}",
            anchor,
            comment_id,
        )

    def _list_info(self, paragraph: ET.Element) -> tuple[int, str | None] | None:
        ppr = paragraph.find(qn(W_NS, "pPr"))
        if ppr is None:
            return None
        numpr = ppr.find(qn(W_NS, "numPr"))
        if numpr is None:
            return None
        ilvl = numpr.find(qn(W_NS, "ilvl"))
        numid = numpr.find(qn(W_NS, "numId"))
        ilvl_val = int(ilvl.get(qn(W_NS, "val"), "0")) if ilvl is not None else 0
        numid_val = numid.get(qn(W_NS, "val")) if numid is not None else None
        return ilvl_val, numid_val

    def _all_paragraph_matches(self, anchor: str) -> list[ET.Element]:
        wanted = normalise_text(anchor)
        matches: list[ET.Element] = []
        for paragraph in self.paragraphs():
            text = normalise_text(paragraph_text(paragraph))
            if not text:
                continue
            if text == wanted or text.startswith(wanted):
                matches.append(paragraph)
        return matches

    def _following_sibling_list(self, anchor_index: int, level: int, numid: str | None, want: int) -> tuple[list[ET.Element], int]:
        paragraphs = self.paragraphs()
        block: list[ET.Element] = []
        for index in range(anchor_index, len(paragraphs)):
            info = self._list_info(paragraphs[index])
            if info is None or info[0] != level or (numid is not None and info[1] != numid):
                break
            block.append(paragraphs[index])
            if len(block) == want:
                return block, len(block)
        return block, len(block)

    def _sub_list_block_under_heading(self, heading_index: int, want: int) -> tuple[list[ET.Element], int]:
        paragraphs = self.paragraphs()
        block: list[ET.Element] = []
        for index in range(heading_index + 1, len(paragraphs)):
            if _paragraph_heading_level(paragraphs[index]) is not None:
                break
            info = self._list_info(paragraphs[index])
            if info is None:
                continue
            block.append(paragraphs[index])
            if len(block) == want:
                break
        return block, len(block)

    def _nearest_paragraph_under_heading(self, heading_index: int, level: int) -> ET.Element | None:
        paragraphs = self.paragraphs()
        for index in range(heading_index + 1, len(paragraphs)):
            if _paragraph_heading_level(paragraphs[index]) is not None:
                break
            info = self._list_info(paragraphs[index])
            if info is not None and info[0] >= level:
                return paragraphs[index]
        for index in range(heading_index - 1, -1, -1):
            if _paragraph_heading_level(paragraphs[index]) is not None:
                return None
            info = self._list_info(paragraphs[index])
            if info is not None and info[0] >= level:
                return paragraphs[index]
        return None

    def add_comment(self, paragraph: ET.Element, record: ChangeRecord, author: str, initials: str) -> str:
        comments_path = self.document_xml_path.parent / "comments.xml"
        comments_tree, comments_root = load_or_create_comments(comments_path)
        existing_ids = [int(node.get(qn(W_NS, "id"), "0")) for node in comments_root.findall(qn(W_NS, "comment"))]
        comment_id = str(max(existing_ids, default=-1) + 1)

        comment = ET.SubElement(comments_root, qn(W_NS, "comment"), {
            qn(W_NS, "id"): comment_id,
            qn(W_NS, "author"): author,
            qn(W_NS, "initials"): initials,
        })
        p = ET.SubElement(comment, qn(W_NS, "p"))
        r = ET.SubElement(p, qn(W_NS, "r"))
        t = ET.SubElement(r, qn(W_NS, "t"))
        t.text = f"{record.edit_id}: {record.why or record.title}"

        children = list(paragraph)
        insert_at = 1 if children and children[0].tag == qn(W_NS, "pPr") else 0
        paragraph.insert(insert_at, ET.Element(qn(W_NS, "commentRangeStart"), {qn(W_NS, "id"): comment_id}))
        paragraph.append(ET.Element(qn(W_NS, "commentRangeEnd"), {qn(W_NS, "id"): comment_id}))
        ref_run = ET.Element(qn(W_NS, "r"))
        ET.SubElement(ref_run, qn(W_NS, "commentReference"), {qn(W_NS, "id"): comment_id})
        paragraph.append(ref_run)

        comments_tree.write(comments_path, encoding="utf-8", xml_declaration=True)
        ensure_comment_relationships(self.document_xml_path.parent)
        return comment_id

    def save(self) -> None:
        self.tree.write(self.document_xml_path, encoding="utf-8", xml_declaration=True)

    def _matching_paragraphs(self, anchor: str, where: str) -> list[ET.Element]:
        wanted_values = _anchor_variants(anchor) if "heading" in where.lower() else [normalise_text(anchor)]
        matches: list[ET.Element] = []
        for paragraph in self._paragraphs_for_where(where):
            text = normalise_text(paragraph_text(paragraph))
            if not text:
                continue
            if "exactly" in where.lower():
                if any(text == wanted or text.startswith(wanted) for wanted in wanted_values):
                    matches.append(paragraph)
            elif any(wanted in text for wanted in wanted_values):
                matches.append(paragraph)
        return matches

    def _paragraphs_for_where(self, where: str) -> list[ET.Element]:
        paragraphs = self.paragraphs()
        if not self.section_heading or "section" not in where.lower():
            return paragraphs

        section_index = self._find_section_heading_index(paragraphs)
        if section_index is None:
            return paragraphs

        section_level = _paragraph_heading_level(paragraphs[section_index])
        if section_level is None:
            return paragraphs

        end_index = len(paragraphs)
        for index in range(section_index + 1, len(paragraphs)):
            level = _paragraph_heading_level(paragraphs[index])
            if level is not None and level <= section_level:
                end_index = index
                break
        return paragraphs[section_index:end_index]

    def _find_section_heading_index(self, paragraphs: list[ET.Element]) -> int | None:
        wanted = normalise_text(self.section_heading).lower()
        for index, paragraph in enumerate(paragraphs):
            level = _paragraph_heading_level(paragraph)
            text = normalise_text(paragraph_text(paragraph)).lower()
            if level is not None and text == wanted:
                return index
        return None

    def _nearest_paragraph_sibling(self, parent: ET.Element, paragraph: ET.Element) -> ET.Element | None:
        siblings = list(parent)
        index = siblings.index(paragraph)
        for sibling in siblings[index + 1 :]:
            if sibling.tag == qn(W_NS, "p"):
                return sibling
        for sibling in reversed(siblings[:index]):
            if sibling.tag == qn(W_NS, "p"):
                return sibling
        return None

    def _insert_paragraphs(self, paragraph: ET.Element, markdown_text: str, before: bool) -> list[ET.Element]:
        parent = self._parent_map()[paragraph]
        siblings = list(parent)
        index = siblings.index(paragraph) + (0 if before else 1)
        inserted: list[ET.Element] = []
        for offset, text in enumerate(markdown_to_paragraph_texts(markdown_text)):
            new_paragraph = make_paragraph(text)
            parent.insert(index + offset, new_paragraph)
            inserted.append(new_paragraph)
        return inserted

    def _insert_text_paragraph_after(self, paragraph: ET.Element, text: str) -> ET.Element:
        parent = self._parent_map()[paragraph]
        index = list(parent).index(paragraph) + 1
        new_paragraph = make_paragraph(text)
        parent.insert(index, new_paragraph)
        return new_paragraph

    def _set_paragraph_text(self, paragraph: ET.Element, text: str, preserve_list: bool = True) -> None:
        ppr = paragraph.find(qn(W_NS, "pPr"))
        if ppr is not None and not preserve_list:
            for child in list(ppr):
                if child.tag in {qn(W_NS, "numPr"), qn(W_NS, "ind")}:
                    ppr.remove(child)
        paragraph.clear()
        if ppr is not None:
            paragraph.append(ppr)
        paragraph.append(make_run(text))

    def _replace_paragraph_range(
        self,
        old_range: list[ET.Element],
        replacement_paragraphs: list[str],
        record: ChangeRecord,
        author: str,
        initials: str,
        add_new_comment: bool = True,
    ) -> str | None:
        parent_map = self._parent_map()
        template_ppr = old_range[0].find(qn(W_NS, "pPr"))
        comment_id: str | None = None
        for offset, text in enumerate(replacement_paragraphs):
            if offset < len(old_range):
                paragraph = old_range[offset]
            else:
                paragraph = self._insert_text_paragraph_after(old_range[-1], "")
                old_range.append(paragraph)
                parent_map = self._parent_map()
            if template_ppr is not None:
                ppr = paragraph.find(qn(W_NS, "pPr"))
                if ppr is not None:
                    paragraph.remove(ppr)
                paragraph.insert(0, ET.fromstring(ET.tostring(template_ppr)))
            self._set_paragraph_text(paragraph, text, preserve_list=text.startswith("- "))
            if add_new_comment and offset == 0:
                comment_id = self.add_comment(paragraph, record, author, initials)

        for paragraph in old_range[len(replacement_paragraphs) :]:
            parent = parent_map[paragraph]
            parent.remove(paragraph)
        return comment_id

    def _parent_map(self) -> dict[ET.Element, ET.Element]:
        return {child: parent for parent in self.root.iter() for child in list(parent)}

    def _find_unique_table_row(self, row_label: str) -> ET.Element | None:
        matches: list[ET.Element] = []
        wanted = normalise_text(row_label)
        for row in self.root.iter(qn(W_NS, "tr")):
            cells = row.findall(qn(W_NS, "tc"))
            if not cells:
                continue
            # Some tables split what a Where clause describes as one label
            # (e.g. "6 Architectural Review") across the first two cells
            # ("6", "Architectural Review") rather than one cell. Try
            # progressively longer joins of the leading cells so both
            # conventions resolve, counting the row only once.
            joined = ""
            row_matches = False
            for cell in cells:
                cell_text = " ".join(paragraph_text(p) for p in cell.iter(qn(W_NS, "p")))
                joined = f"{joined} {cell_text}".strip() if joined else cell_text
                candidate = normalise_text(joined)
                if candidate == wanted or candidate.startswith(wanted):
                    row_matches = True
                    break
            if row_matches:
                matches.append(row)
        return matches[0] if len(matches) == 1 else None

    def _table_headers_for_row(self, row: ET.Element) -> list[str]:
        parent = self._parent_map()[row]
        first_row = parent.find(qn(W_NS, "tr"))
        if first_row is None:
            return []
        return [
            normalise_text(" ".join(paragraph_text(p) for p in cell.iter(qn(W_NS, "p"))))
            for cell in first_row.findall(qn(W_NS, "tc"))
        ]

    def _first_cell_paragraph(self, row: ET.Element, cell_index: int) -> ET.Element:
        cells = row.findall(qn(W_NS, "tc"))
        if cell_index >= len(cells):
            raise IndexError(f"Table row has no cell index {cell_index}")
        paragraph = cells[cell_index].find(qn(W_NS, "p"))
        if paragraph is None:
            paragraph = ET.SubElement(cells[cell_index], qn(W_NS, "p"))
        return paragraph


def make_paragraph(text: str) -> ET.Element:
    p = ET.Element(qn(W_NS, "p"))
    p.append(make_run(text))
    return p


def make_run(text: str) -> ET.Element:
    r = ET.Element(qn(W_NS, "r"))
    t = ET.SubElement(r, qn(W_NS, "t"))
    if text.startswith(" ") or text.endswith(" "):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = html.unescape(text)
    return r


def _extract_row_labels(where: str, text: str) -> list[str]:
    labels = re.findall(r"row beginning(?:\s+exactly)?\s*:?\s*`([^`]+)`", where, flags=re.IGNORECASE)
    if labels:
        primary = [label.strip() for label in labels if label.strip()]
    else:
        plain_label = re.search(r"row beginning(?:\s+exactly)?\s*:?\s+(.+)$", where, flags=re.IGNORECASE)
        anchor = plain_label.group(1).strip() if plain_label else find_anchor(where)
        if anchor and anchor.lower().startswith("row beginning "):
            anchor = anchor[len("row beginning ") :].strip()
        primary = [anchor] if anchor else []

    row_specific = []
    for label, _field, _value in _extract_labeled_value_triples(text):
        if label:
            row_specific.append(label.strip())

    if row_specific:
        result: list[str] = []
        for label in row_specific:
            if label not in result:
                result.append(label)
        return result

    result: list[str] = []
    for label in primary:
        if label and label not in result:
            result.append(label)
    return result


def _extract_pipe_row_replacements(text: str, where: str = "") -> list[tuple[str, list[str]]]:
    parsed_lines: list[list[str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        if line.startswith(">"):
            line = line[1:].lstrip()
        line = _strip_inline_markdown(line)
        if "|" not in line:
            continue
        segments = [segment.strip() for segment in line.split("|")]
        segments = [segment for segment in segments if segment]
        if len(segments) < 2:
            continue
        parsed_lines.append(segments)

    data_rows: list[list[str]] = []
    for index, segments in enumerate(parsed_lines):
        if all(_is_markdown_table_separator_cell(cell) for cell in segments):
            continue
        next_line = parsed_lines[index + 1] if index + 1 < len(parsed_lines) else None
        if next_line is not None and all(_is_markdown_table_separator_cell(cell) for cell in next_line):
            continue
        data_rows.append(segments)

    if not data_rows:
        return []

    # The anchor used to FIND the existing row must come from the Where
    # clause (the row's CURRENT text), never from the replacement Text
    # itself. The Text's first cell is frequently the corrected (NEW) value
    # for that same cell -- e.g. renumbering "4 System Assessment" to "3" --
    # so using it as the search key looks for a row that doesn't exist yet,
    # or (worse) silently matches an unrelated row that already contains
    # that value. When Where supplies one anchor per data row, use those and
    # return the FULL row (including the first/label cell) as replacement
    # values so that cell gets written too. When Where doesn't parse cleanly
    # into a matching number of anchors, fall back to the historical
    # behaviour (label cell doubles as the search anchor and is not itself
    # rewritten) so callers that never relied on Where keep working exactly
    # as before.
    where_anchors = _extract_row_labels(where, "") if where else []

    # Only trust the Where-derived anchor for the single-row-edit shape
    # (exactly one data row, exactly one Where anchor). Multi-row pipe edits
    # in this document set (e.g. the "DNS Location" / "Local DNS Services"
    # pair) use a single Where clause covering the whole table, with the
    # per-row anchor implicitly being each row's own first cell -- which is
    # a stable identifying label there, not a value being renumbered. Only
    # a single-row edit can unambiguously pair one Where anchor with one
    # data row, which is also the only shape where the label cell itself is
    # known to be a renumbered/corrected value rather than a stable anchor.
    if len(data_rows) == 1 and len(where_anchors) == 1:
        return [(where_anchors[0], data_rows[0])]

    return [(segments[0], segments[1:]) for segments in data_rows]


def _is_markdown_table_separator_cell(value: str) -> bool:
    return bool(re.fullmatch(r":?-{3,}:?", value.strip()))


def _extract_labeled_values(text: str) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for label, field, value in _extract_labeled_value_triples(text):
        values.setdefault(label, {})[field] = value
    return values


def _extract_labeled_value_triples(text: str) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    cleaned = "\n".join(line[1:].lstrip() if line.lstrip().startswith(">") else line for line in text.splitlines())
    pattern = re.compile(
        r"^\s*(?:[-*]\s*)?(?:(?P<label>.+?)\s*-\s*)?(?P<field>Observed|Assessment):\s*(?P<value>.+)$",
        re.IGNORECASE,
    )
    for line in cleaned.splitlines():
        line = _strip_inline_markdown(line.strip())
        match = pattern.match(line)
        if not match:
            continue
        triples.append(
            (
                (match.group("label") or "").strip(),
                match.group("field").strip().lower(),
                match.group("value").strip(),
            )
        )
    return triples


def _values_for_row(row_label: str, values: dict[str, dict[str, str]]) -> dict[str, str]:
    if row_label in values:
        return values[row_label]
    if "" in values:
        return values[""]
    row_norm = normalise_text(row_label).lower()
    for label, row_values in values.items():
        if normalise_text(label).lower() == row_norm:
            return row_values
    return {}


def _cell_index_for_field(headers: list[str], field_name: str) -> int | None:
    candidates = {
        "observed": ("observed", "evidence"),
        "assessment": ("assessment",),
    }[field_name]
    for index, header in enumerate(headers):
        header_lower = header.lower()
        if any(candidate in header_lower for candidate in candidates):
            return index
    fallback = {"observed": 2, "assessment": 3}[field_name]
    return fallback if len(headers) > fallback else None


def _has_range_replacement(record: ChangeRecord) -> bool:
    return bool(_extract_range_spec(record.raw))


def _has_section_body_replacement(record: ChangeRecord) -> bool:
    return bool(re.search(r"\breplace all content in section\b", record.action, re.IGNORECASE))


def _has_full_table_replacement(record: ChangeRecord) -> bool:
    """True when the approved Do: instruction is a wholesale table-content
    replacement (row labels and values may both change) rather than an update
    of Observed/Assessment values under a stable, unchanged row label."""
    return bool(re.search(r"\breplace the table content\b", record.action, re.IGNORECASE))


def _has_anchor_plus_bullets_replacement(record: ChangeRecord) -> bool:
    action = record.action.lower()
    return "replace" in action and "bullet" in action and _extract_following_bullet_count(record.action) is not None


def _has_counted_bullet_block(record: ChangeRecord) -> bool:
    action = record.action.lower()
    if "bullet" not in action:
        return False
    if _extract_following_bullet_count(record.action) is None:
        return False
    if "replace the content beginning" in record.raw.lower() and " through " in record.raw.lower():
        return False
    if re.search(r"\breplace all content in section\b", action, re.IGNORECASE):
        return False
    return "replace" in action or "delete" in action


def _extract_following_bullet_count(action: str) -> int | None:
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    match = re.search(r"\b(?:its|the)?\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:sub-)?bullets?\b", action, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    return int(value) if value.isdigit() else number_words[value]


def _range_end_for_following_content(paragraphs: list[ET.Element], anchor_index: int, content_count: int) -> int | None:
    found = 0
    end_index = anchor_index
    for index in range(anchor_index + 1, len(paragraphs)):
        if _paragraph_heading_level(paragraphs[index]) is not None:
            return None
        end_index = index
        if normalise_text(paragraph_text(paragraphs[index])):
            found += 1
        if found == content_count:
            return end_index
    return None


def _extract_range_spec(raw: str) -> tuple[str, str, str] | None:
    structured = re.search(
        r"\*\*where:\*\*.*?`(?P<start>[^`]+)`.*?\*\*do:\*\*\s*(?P<action>.*?)(?=\*\*text:\*\*)\*\*text:\*\*\s*(?P<replacement>.*?)(?:\n\*\*why:\*\*|\n---|\n## |\Z)",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if structured:
        action = structured.group("action")
        if "replace" in action.lower() and "through" in action.lower():
            end_anchor = _extract_range_end_anchor(action)
            if end_anchor:
                return structured.group("start").strip(), end_anchor, structured.group("replacement").strip()

    legacy = re.search(
        r"replace the content beginning\s+`([^`]+)`\s+through(?: the)?(?: final)?(?: bullet)?\s+`([^`]+)`\s+with:\s*\n(?P<replacement>.*?)(?:\n---|\n## |\Z)",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if legacy:
        return legacy.group(1).strip(), legacy.group(2).strip(), legacy.group("replacement").strip()
    return None


def _extract_range_end_anchor(action: str) -> str | None:
    after_through = re.split(r"\bthrough\b", action, flags=re.IGNORECASE, maxsplit=1)
    if len(after_through) != 2:
        return None
    tail = after_through[1]
    ticks = re.findall(r"`([^`]+)`", tail)
    if ticks:
        return ticks[-1].strip()
    quotes = re.findall(r'"([^"]+)"', tail)
    if quotes:
        return quotes[-1].strip()
    return None


def _unique_paragraph_index(paragraphs: list[ET.Element], anchor: str) -> int | None:
    wanted_values = _anchor_variants(anchor)
    matches = [
        index
        for index, paragraph in enumerate(paragraphs)
        if any(
            normalise_text(paragraph_text(paragraph)) == wanted
            or normalise_text(paragraph_text(paragraph)).startswith(wanted)
            for wanted in wanted_values
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _anchor_variants(anchor: str) -> list[str]:
    base = normalise_text(anchor)
    variants = [base]
    without_number = re.sub(r"^\d+(?:\.\d+)*\s+", "", base).strip()
    if without_number and without_number not in variants:
        variants.append(without_number)
    return variants


def _paragraph_heading_level(paragraph: ET.Element) -> int | None:
    ppr = paragraph.find(qn(W_NS, "pPr"))
    if ppr is None:
        return None
    pstyle = ppr.find(qn(W_NS, "pStyle"))
    if pstyle is None:
        return None
    style = pstyle.get(qn(W_NS, "val"), "")
    match = re.match(r"Heading(\d+)$", style)
    return int(match.group(1)) if match else None


def _previous_heading_index(paragraphs: list[ET.Element], before_index: int) -> int | None:
    for index in range(before_index - 1, -1, -1):
        if _paragraph_heading_level(paragraphs[index]) is not None:
            return index
    return None


def load_or_create_comments(comments_path: Path) -> tuple[ET.ElementTree, ET.Element]:
    if comments_path.exists():
        tree = ET.parse(comments_path)
        return tree, tree.getroot()
    root = ET.Element(qn(W_NS, "comments"))
    return ET.ElementTree(root), root


def ensure_comment_relationships(word_dir: Path) -> None:
    rels_path = word_dir / "_rels" / "document.xml.rels"
    rels_tree = ET.parse(rels_path)
    rels_root = rels_tree.getroot()

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
        rels_tree.write(rels_path, encoding="utf-8", xml_declaration=True)

    content_types_path = word_dir.parent / "[Content_Types].xml"
    ct_tree = ET.parse(content_types_path)
    ct_root = ct_tree.getroot()
    if not any(part.get("PartName") == "/word/comments.xml" for part in ct_root):
        override = ET.SubElement(ct_root, qn(CONTENT_TYPES_NS, "Override"))
        override.set("PartName", "/word/comments.xml")
        override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
        ct_tree.write(content_types_path, encoding="utf-8", xml_declaration=True)
