from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Vendor bootstrap must run before any import that needs docxengine on
# sys.path - including csa_docx.bookmarks below, which imports
# docxengine._anchors directly. Getting this order wrong is exactly the
# bug documented in the learnings file (2026-09-17).
VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor"
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from csa_docx.bookmarks import add_bookmark_at_anchor, find_bookmark
from csa_docx.comment_text import build_comment_text
from csa_docx.models import ChangeRecord, EditResult
from csa_docx.stable_ids import extract_stable_id, build_id_map
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
    _has_full_table_replacement,
    _has_range_replacement,
    _has_section_body_replacement,
    _values_for_row,
    find_anchor,
    markdown_to_paragraph_texts,
    normalise_text,
    paragraph_text,
    qn,
    spelling_normalised_text,
)

try:
    from docxengine import Document, build_anchor_index
    from docxengine.errors import ToolError
except Exception as exc:  # pragma: no cover - exercised only when dependency is absent.
    Document = None  # type: ignore[assignment]
    build_anchor_index = None  # type: ignore[assignment]
    ToolError = Exception  # type: ignore[assignment]
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

try:
    import mistune
except Exception:  # pragma: no cover - vendored dependency missing.
    mistune = None  # type: ignore[assignment]

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except Exception:  # pragma: no cover - vendored dependency missing or platform mismatch.
    _rapidfuzz_fuzz = None

# Minimum similarity (0-100) for a fuzzy row-label fallback match, and the
# minimum margin the best match must lead the second-best by. Both are
# deliberately conservative: a close call is left BLOCKED rather than guessed.
_FUZZY_ROW_LABEL_THRESHOLD = 85
_FUZZY_ROW_LABEL_MARGIN = 10


def _label_similarity(a: str, b: str) -> float:
    """Similarity score 0-100 between two normalised row labels.

    Prefers the vendored rapidfuzz (fast, well-tested string similarity);
    falls back to the standard-library difflib if rapidfuzz did not import
    (e.g. its vendored wheel doesn't match the running platform/interpreter).
    """
    if _rapidfuzz_fuzz is not None:
        return _rapidfuzz_fuzz.ratio(a, b)
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio() * 100


def _inline_text(node: dict) -> str:
    node_type = node.get("type")
    if node_type == "linebreak":
        return "\n"
    if node_type in ("text", "codespan"):
        return node.get("raw", "")
    return "".join(_inline_text(child) for child in node.get("children", []) or [])


def _cell_text(cell: dict) -> str:
    return normalise_text("".join(_inline_text(child) for child in cell.get("children", []) or []))


def _parse_markdown_table(text: str) -> list[list[str]] | None:
    """Parse one Markdown pipe table (header row + data rows) from ``text``.

    Uses the vendored mistune parser (with its table plugin) instead of a
    hand-rolled regex, so escaped pipes, inline formatting inside cells, and
    alignment markers are all handled the same way a Markdown renderer would.
    Returns ``None`` when no table block is found or mistune is unavailable.
    """
    if mistune is None:
        return None
    markdown = mistune.create_markdown(renderer=None, plugins=["table"])
    for token in markdown(text):
        if token.get("type") != "table":
            continue
        rows: list[list[str]] = []
        for part in token.get("children", []) or []:
            if part.get("type") == "table_head":
                rows.append([_cell_text(cell) for cell in part.get("children", []) or []])
            elif part.get("type") == "table_body":
                for row in part.get("children", []) or []:
                    rows.append([_cell_text(cell) for cell in row.get("children", []) or []])
        return rows or None
    return None



_XMLNS_RE = re.compile(rb'xmlns:([A-Za-z_][\w.-]*)="([^"]*)"')
_ROOT_TAG_RE = re.compile(rb"<(?!\?|!)[^>]*>")


def _parse_part_preserving(data: bytes) -> ET.Element:
    """Parse an OOXML part with ElementTree after registering the part's own namespace
    prefixes, so that serialising it again keeps them (w14, mc, wp, a, ...)."""
    for prefix, uri in _XMLNS_RE.findall(data):
        name = prefix.decode()
        if re.fullmatch(r"ns\d+", name):
            continue
        try:
            ET.register_namespace(name, uri.decode())
        except ValueError:
            pass
    return ET.fromstring(data)


def _serialize_part_preserving(root: ET.Element, original: bytes) -> bytes:
    """Serialise ``root`` and put back the original root start tag. ElementTree drops
    namespace declarations the part does not use, but ``mc:Ignorable="w14 ..."`` still
    names them, which makes the package invalid (Word reports unreadable content and
    LibreOffice will not open it). The original tag declares every prefix again."""
    old_tag = _ROOT_TAG_RE.search(original)
    default_ns = re.search(rb'\sxmlns="([^"]*)"', old_tag.group(0)) if old_tag else None
    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if default_ns:
        # [Content_Types].xml and .rels parts must keep their default namespace;
        # ElementTree writes it as an "nsN:" prefix, which Word and LibreOffice
        # reject. (Its default_namespace option fails on their unprefixed
        # attributes.) Turn the generated prefix back into the default namespace.
        m = re.search(rb'xmlns:(ns\d+)="' + re.escape(default_ns.group(1)) + rb'"', out)
        if m:
            prefix = m.group(1)
            out = re.sub(rb"(</?)" + prefix + rb":", rb"\1", out)
            out = out.replace(b"xmlns:" + prefix + b"=", b"xmlns=")
    new_tag = _ROOT_TAG_RE.search(out)
    if not old_tag or not new_tag:
        return out
    closing = b"/>" if new_tag.group(0).endswith(b"/>") else b">"
    old = old_tag.group(0)
    if closing == b"/>" and not old.endswith(b"/>"):
        old = old[:-1] + b"/>"
    elif closing == b">" and old.endswith(b"/>"):
        old = old[:-2] + b">"
    return out[: new_tag.start()] + old + out[new_tag.end():]


_CURRENTLY_RE = re.compile(r"currently:\s*[\"\u201c](.+?)[\"\u201d]\s*$", re.S)


def _norm_text(t: str) -> str:
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def _currently_segments(where: str) -> list[str]:
    """The text a record quotes as the target's current wording ('currently: "... ..."'),
    split at ellipses into segments long enough to identify the paragraph."""
    m = _CURRENTLY_RE.search(where or "")
    if not m:
        return []
    return [_norm_text(seg) for seg in re.split(r"\s*(?:\.\.\.|\u2026)\s*", m.group(1)) if len(seg.strip()) >= 12]


def verified_stable_index(where: str, paragraphs, id_str: str, id_map: dict) -> tuple[int | None, str | None]:
    """Resolve a stable ID, then check the paragraph against the record's 'currently' quote.

    Stable IDs are positional, so an earlier edit that adds or removes a paragraph shifts
    every later ID. When the quoted text is not in the paragraph the ID now points at, use
    the one paragraph that does contain it; if none or several do, block rather than guess.
    Records without a quote keep the old, ID-only behaviour."""
    idx = id_map.get(id_str)
    segs = _currently_segments(where)
    if not segs:
        return (idx, None) if idx is not None else (None, f"Stable ID {id_str} not found in document")

    def fits(i: int) -> bool:
        text = _norm_text(getattr(paragraphs[i], "text", "") or "")
        return bool(text) and all(seg in text for seg in segs)

    if idx is not None and fits(idx):
        return idx, None
    found = [i for i in range(len(paragraphs)) if fits(i)]
    if len(found) == 1:
        return found[0], None
    return None, (f"Stable ID {id_str} now points at text that does not match the record's 'currently' quote, "
                  f"and {len(found)} paragraphs contain that quote; run csa prepare and re-anchor the record")

class DocxEngineEditor:
    """CSA adapter over the open-source DocxEngine library.

    The adapter keeps CSA-specific decisions in this framework and delegates the
    DOCX package mutation, anchor validation, and comment wiring to DocxEngine.
    Unsupported operations return BLOCKED so the controller can fall back or stop.
    """

    def __init__(self, docx_path: Path, section_heading: str | None = None, track_changes: bool = True):
        if Document is None:
            raise RuntimeError(f"docxengine is unavailable: {IMPORT_ERROR}")
        self.docx_path = Path(docx_path)
        self.section_heading = normalise_text(section_heading or "")
        self.doc = Document.open(self.docx_path)
        # Direction B (framework-robustness-plan.md §4): Phase 1 applies as
        # Word tracked changes by default (docx_insert/docx_delete/
        # docx_edit_paragraph all support it natively), so the working
        # document always keeps both the old and the approved new content
        # until a human accepts or rejects them - nothing is destructively
        # removed at apply time. Phase 2 (the review agent) signs off, and
        # only then does the small Phase 3 cleanup agent call
        # `docx_revision accept_all` to finalise. Pass track_changes=False
        # to restore the old destructive-apply behaviour (e.g. for a
        # one-off repair where tracked markup isn't wanted).
        self.track_changes = track_changes

    def apply_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        where_lower = record.where.lower()
        if _has_full_table_replacement(record):
            return self._apply_full_table_replacement(record, author, initials)
        if (
            "row beginning" in where_lower
            or "table" in where_lower
            or (extract_stable_id(record.where) is not None and extract_stable_id(record.where).kind == "T")
        ):
            return self._apply_table_row_change(record, author, initials)
        # New-table insertion: the approved Text contains a Markdown pipe
        # table and the action is an insert/replace that does not target
        # an existing table.  This is the path that handles "populate a
        # previously empty section with a table" (e.g. Section 17 / S17-E1).
        if record.text and _parse_markdown_table(record.text) is not None:
            return self._apply_new_table_insertion(record, author, initials)
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
        # The vendor library's docx_save gate refuses any package with an
        # error-severity validation issue, but the CSA source documents can
        # legitimately arrive carrying a pre-existing structural wart (e.g. an
        # orphaned part with no [Content_Types].xml entry) that has nothing to
        # do with the edits this batch just made. DocxEngine ships a narrow,
        # mechanical repair (content-type defaults, orphaned-relationship
        # cleanup, revision-id dedup, orphaned reference removal) that is safe
        # to run for exactly this reason: it only fixes what the validator
        # flagged, it does not touch document content, and it leaves
        # warning-severity issues alone. We run it here, before the gate,
        # only when the gate would have refused the save, and only report the
        # structural fixes (not their internal reasoning) to the caller via
        # the ``save_repair`` attribute - callers can surface this in their
        # changes report if they want to, but it is never a blocker on its
        # own. If the package is still invalid after the vendor repair (i.e.
        # the problem was not one of the mechanical classes the repair covers),
        # the original save error is raised unchanged so the controller still
        # sees a hard failure rather than silently shipping a bad package.
        try:
            self.doc.save(self.docx_path)
            return
        except ToolError as exc:
            self.save_repair = []
            from docxengine._validate import repair_package, is_valid, validate_package

            package = self.doc._session.get(self.doc.doc_id).package
            fixed, remaining = repair_package(package)
            if not is_valid(validate_package(package)):
                self.save_repair = None
                raise
            self.save_repair = fixed
            self.doc.save(self.docx_path)

    def _apply_simple_paragraph_change(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        # Direction A (framework-robustness-plan.md section 3): a durable OOXML
        # bookmark from a previous successful run of this exact edit ID takes
        # priority over text-matching. This makes a retry idempotent and
        # immune to the document drift that causes most of the
        # "Anchor match count was 0/N" blocks this framework has seen -
        # once an edit has been located and applied once, its location is
        # never re-derived from wording again. Falls straight through to the
        # normal text-based path when no bookmark exists yet (every record
        # not yet retrofitted, i.e. all of them at the time this was added).
        bookmarked_anchor = find_bookmark(self, record.edit_id)
        anchor_text = find_anchor(record.where)
        paragraphs = self.doc.paragraphs()
        if bookmarked_anchor:
            paragraph = next((p for p in paragraphs if p.anchor == bookmarked_anchor), None)
            if paragraph is None:
                return EditResult(record.edit_id, "BLOCKED", "Bookmarked location no longer resolves to a paragraph", anchor_text)
            matches = [paragraph]
        else:
            stable_id = extract_stable_id(record.where)
            if stable_id:
                id_map = build_id_map(paragraphs)
                id_str = str(stable_id)
                idx, why = verified_stable_index(record.where, paragraphs, id_str, id_map)
                if idx is not None:
                    paragraph = paragraphs[idx]
                    matches = [paragraph]
                    anchor_text = anchor_text or id_str
                else:
                    return EditResult(record.edit_id, "BLOCKED", why, id_str)
            else:
                if not anchor_text:
                    return EditResult(record.edit_id, "BLOCKED", "Could not extract a unique anchor from Where")
                matches = self._matching_paragraphs(anchor_text, record.where)
                if len(matches) != 1:
                    return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
                paragraph = matches[0]
        action = record.action.lower()

        try:
            if "confirm" in action and "confirm" not in record.where.lower():
                # Reviewer-approved "retain as-is / verify no change" outcome.
                # Locates the target element, leaves its text untouched and
                # records a verification comment. Used for retain/no-op edits
                # (e.g. glossary "full expansion not established" rows).
                comment_id = self._add_comment(paragraph.anchor, record, author, initials)
                self._tag_bookmark(record.edit_id, paragraph.anchor)
                return EditResult(record.edit_id, "APPLIED",
                    "Confirmed existing content (no document change per approved record)", anchor_text, comment_id)

            if "insert before" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor_text)
                result = self.doc.insert(record.text, before=paragraph.anchor, author=author, track_changes=self.track_changes)
                comment_anchor = _result_anchor(result) or paragraph.anchor
                comment_id = self._add_comment(comment_anchor, record, author, initials)
                self._tag_bookmark(record.edit_id, comment_anchor)
                return EditResult(record.edit_id, "APPLIED", "Inserted approved text before anchor with DocxEngine", anchor_text, comment_id)

            if "insert after" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Insert action has no Text", anchor_text)
                if len(matches) == 0:
                    # No literal anchor: the *Where* may reference a numbered
                    # subsection ("Section 10.2, after the revised Section
                    # 10.2.2"). Try to resolve it as a subsection-end insert;
                    # if it doesn't apply, keep the standard BLOCKED result below.
                    subsection_result = self._apply_subsection_end_insert(record, author, initials)
                    if subsection_result.status == "APPLIED":
                        return subsection_result
                    return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
                result = self.doc.insert(record.text, after=paragraph.anchor, author=author, track_changes=self.track_changes)
                comment_anchor = _result_anchor(result) or paragraph.anchor
                comment_id = self._add_comment(comment_anchor, record, author, initials)
                self._tag_bookmark(record.edit_id, comment_anchor)
                return EditResult(record.edit_id, "APPLIED", "Inserted approved text after anchor with DocxEngine", anchor_text, comment_id)

            if "delete" in action and "replace" not in action:
                self.doc.delete(anchor=paragraph.anchor, author=author, track_changes=self.track_changes)
                return EditResult(record.edit_id, "APPLIED", "Deleted anchored paragraph with DocxEngine", anchor_text)

            if "replace" in action:
                if not record.text:
                    return EditResult(record.edit_id, "BLOCKED", "Replace action has no Text", anchor_text)
                replacement_paragraphs = markdown_to_paragraph_texts(record.text)
                if not replacement_paragraphs:
                    return EditResult(record.edit_id, "BLOCKED", "Replacement text parsed to no paragraphs", anchor_text)
                result = self.doc.edit_paragraph(paragraph.anchor, replacement_paragraphs[0], author=author, track_changes=self.track_changes)
                first_anchor = _result_anchor(result) or self._find_unique_text(replacement_paragraphs[0])
                if first_anchor is None:
                    return EditResult(record.edit_id, "BLOCKED", "Could not re-anchor edited paragraph", anchor_text)
                if len(replacement_paragraphs) > 1:
                    self.doc.insert("\n".join(replacement_paragraphs[1:]), after=first_anchor, author=author, track_changes=self.track_changes)
                comment_id = self._add_comment(first_anchor, record, author, initials)
                self._tag_bookmark(record.edit_id, first_anchor)
                return EditResult(record.edit_id, "APPLIED", "Replaced anchored paragraph with DocxEngine", anchor_text, comment_id)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", anchor_text)

        return EditResult(record.edit_id, "BLOCKED", f"Unsupported action for DocxEngine adapter: {record.action}", anchor_text)

    def _tag_bookmark(self, edit_id: str, anchor: str) -> None:
        """Best-effort Direction-A retrofit: bookmark a just-applied edit's
        final location so future runs (dry-run replay or a real re-apply)
        resolve it by durable name instead of re-deriving it from wording.
        Never lets a bookmark failure turn a successful edit into a block -
        this is pure upside when it works and a silent no-op when it can't
        (e.g. track_changes moved the content into a w:ins the anchor index
        doesn't yet see cleanly). A skipped tag just means this edit stays on
        the text-matching path next time, exactly like today.
        """
        try:
            add_bookmark_at_anchor(self, anchor, edit_id)
        except Exception:  # noqa: BLE001 - deliberately swallow; see docstring
            pass

    def _resolve_paragraph_index(self, record: ChangeRecord, anchor_text: str, paragraphs, mismatch_label: str):
        """Direction A: shared bookmark-first resolution for the dispatch
        methods that locate a single anchor paragraph by matching Where text
        (anchor-plus-bullets, section-body, anchor-plus-following-content).
        Mirrors the logic in _apply_simple_paragraph_change. Returns
        (index, None) on success, or (None, EditResult) with a BLOCKED
        result to return as-is when resolution fails either way.
        Stable-ID resolution takes priority over text matching when the
        Where field contains an @-prefixed structural ID.
        """
        bookmarked_anchor = find_bookmark(self, record.edit_id)
        if bookmarked_anchor:
            for index, paragraph in enumerate(paragraphs):
                if paragraph.anchor == bookmarked_anchor:
                    return index, None
            return None, EditResult(record.edit_id, "BLOCKED", "Bookmarked location no longer resolves to a paragraph", anchor_text)
        stable_id = extract_stable_id(record.where)
        if stable_id:
            id_map = build_id_map(paragraphs)
            id_str = str(stable_id)
            idx, why = verified_stable_index(record.where, paragraphs, id_str, id_map)
            if idx is not None:
                return idx, None
            return None, EditResult(record.edit_id, "BLOCKED", why, id_str)
        matches = self._matching_paragraphs(anchor_text, record.where, paragraphs)
        if len(matches) != 1:
            return None, EditResult(record.edit_id, "BLOCKED", f"{mismatch_label} was {len(matches)}; expected 1", anchor_text)
        return paragraphs.index(matches[0]), None

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
        anchor_index, blocked = self._resolve_paragraph_index(record, anchor_text, paragraphs, "Anchor match count")
        if blocked:
            return blocked
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
        start_index = self._scoped_unique_index(start_anchor, paragraphs, allow_prefix=True)
        end_index = self._scoped_unique_index(end_anchor, paragraphs, allow_prefix=True, allow_suffix=True)
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

    def _apply_new_table_insertion(
        self, record: ChangeRecord, author: str, initials: str
    ) -> EditResult:
        """Insert a new native Word table when the approved Text contains a
        Markdown pipe table and no existing table is the target.

        Handles the "populate a previously empty section with a table" case
        (e.g. Appendixes) that ``_apply_full_table_replacement`` cannot
        cover because there is no existing table to overwrite.

        Strategy:
        1. Resolve the anchor paragraph (bookmark > stable-ID > text match).
        2. Split ``record.text`` into non-table content, table data, and
           non-table content (in document order).
        3. Insert the non-table paragraphs around the table via DocxEngine.
        4. Create the native table via ``csa_docx.tables.create_table``
           (clones the document's own table style).
        5. Add the Word comment on the table's first row.
        """
        from csa_docx.tables import create_table as _create_table

        anchor_text = find_anchor(record.where)
        paragraphs = self.doc.paragraphs()

        # Resolve the anchor paragraph
        bookmarked = find_bookmark(self, record.edit_id)
        if bookmarked:
            paragraph = next((p for p in paragraphs if p.anchor == bookmarked), None)
            if paragraph is None:
                return EditResult(record.edit_id, "BLOCKED", "Bookmarked location no longer resolves to a paragraph", anchor_text)
            matches = [paragraph]
        else:
            stable_id = extract_stable_id(record.where)
            if stable_id:
                id_map = build_id_map(paragraphs)
                id_str = str(stable_id)
                idx, why = verified_stable_index(record.where, paragraphs, id_str, id_map)
                if idx is not None:
                    paragraph = paragraphs[idx]
                    matches = [paragraph]
                else:
                    return EditResult(record.edit_id, "BLOCKED", why, anchor_text)
            else:
                if not anchor_text:
                    return EditResult(record.edit_id, "BLOCKED", "Could not extract a unique anchor from Where", None)
                matches = self._matching_paragraphs(anchor_text, record.where)
                if len(matches) != 1:
                    return EditResult(record.edit_id, "BLOCKED", f"Anchor match count was {len(matches)}; expected 1", anchor_text)
                paragraph = matches[0]

        # Parse the text into segments
        table_rows = _parse_markdown_table(record.text)
        if not table_rows:
            return EditResult(record.edit_id, "BLOCKED", "Could not parse a table from Text", None)
        cols = max(len(row) for row in table_rows)

        # Split text around the table block
        # Find the table block boundaries in the raw text
        lines = record.text.splitlines()
        in_table = False
        table_start = None
        table_end = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("|") and not in_table:
                table_start = i
                in_table = True
            elif in_table:
                if stripped.startswith("|"):
                    table_end = i
                else:
                    break  # table block ended
        if table_start is None:
            return EditResult(record.edit_id, "BLOCKED", "Could not locate table block in Text", None)
        if table_end is None:
            table_end = len(lines) - 1

        before_lines = lines[:table_start]
        after_lines = lines[table_end + 1:]

        # Filter out Markdown separator rows (|---|---|) from table_rows
        data_rows = [
            row for row in table_rows
            if not all(re.match(r"^[\s:|-]+$", cell.strip()) for cell in row)
        ]
        if not data_rows:
            return EditResult(record.edit_id, "BLOCKED", "Parsed table has no data rows", None)

        # Determine the anchor for table insertion.
        # If there is content before the table, insert those paragraphs first,
        # then the table after the last inserted paragraph.
        # If there is no content before, insert the table after the resolved anchor.
        insert_after_anchor = paragraph.anchor
        before_text = "\n".join(before_lines).strip()
        after_text = "\n".join(after_lines).strip()

        try:
            # Insert "before" paragraphs (if any)
            if before_text:
                before_paras = markdown_to_paragraph_texts(before_text)
                for pt in reversed(before_paras):
                    self.doc.insert(pt, after=insert_after_anchor, author=author, track_changes=self.track_changes)
                # The last inserted paragraph is now the anchor for the table
                # We need to find it by its text
                new_paras = self.doc.paragraphs()
                last_text = before_paras[-1] if before_paras else None
                if last_text:
                    for p in reversed(new_paras):
                        if p.text and p.text.strip() == last_text.strip():
                            insert_after_anchor = p.anchor
                            break
            else:
                # No before-content: table goes right after the resolved anchor
                pass

            # Create the native table
            result = _create_table(
                self.docx_path,
                after=insert_after_anchor,
                cols=cols,
                data=data_rows,
                header=True,
                backup=False,  # framework already handles backup
            )

            if result.get("status") not in ("OK",):
                return EditResult(
                    record.edit_id, "BLOCKED",
                    f"create_table failed: {result.get('message', result.get('status'))}",
                    None,
                )

            # Insert "after" paragraphs (if any) - they go after the table
            if after_text:
                after_paras = markdown_to_paragraph_texts(after_text)
                # We need to find the table's position to insert after it.
                # The table was inserted after insert_after_anchor, so the
                # next paragraph after that position is where we continue.
                # For simplicity, insert after the anchor (DocxEngine will
                # place it in document order after the table).
                for pt in reversed(after_paras):
                    self.doc.insert(pt, after=insert_after_anchor, author=author, track_changes=self.track_changes)

            # Add comment on the anchor paragraph
            comment_id = self._add_comment(insert_after_anchor, record, author, initials)
            self._tag_bookmark(record.edit_id, insert_after_anchor)

            return EditResult(
                record.edit_id, "APPLIED",
                f"Inserted new table ({len(data_rows)}x{cols}) with DocxEngine + create_table",
                anchor_text, comment_id,
            )

        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", anchor_text)

    def _apply_section_body_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Section body replacement has no Text")
        paragraphs = self.doc.paragraphs()
        stable_id = extract_stable_id(record.where)
        if stable_id:
            id_str = str(stable_id)
            id_map = build_id_map(paragraphs)
            anchor_index, why = verified_stable_index(record.where, paragraphs, id_str, id_map)
            if anchor_index is None:
                return EditResult(record.edit_id, "BLOCKED", why, id_str)
        else:
            anchor_text = find_anchor(record.where)
            if not anchor_text:
                return EditResult(record.edit_id, "BLOCKED", "Could not extract section body anchor from Where")
            anchor_index, blocked = self._resolve_paragraph_index(record, anchor_text, paragraphs, "Section body anchor match count")
            if blocked:
                return blocked
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

    def _apply_subsection_end_insert(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        """Insert approved text at the end of a numbered subsection.

        Handles edits whose *Where* references a subsection by number
        (e.g. "Section 10.2, after the revised Section 10.2.2") rather than by
        a literal paragraph. Resolves the most specific numbered subsection
        referenced within the run's section, finds the last body paragraph, and
        inserts the text after it via DocxEngine. Returns BLOCKED if no target
        subsection can be resolved uniquely so the caller can fall back.
        """
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Subsection end insert has no Text")
        number = _extract_subsection_number(record.where)
        if not number:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract subsection number from Where")
        paragraphs = self.doc.paragraphs()
        scope = self._section_scope(paragraphs)
        lo, hi = (scope[1], scope[2]) if scope else (0, len(paragraphs) - 1)
        heading_index = self._subsection_heading_index(paragraphs, number, lo, hi)
        bookmarked_anchor = find_bookmark(self, record.edit_id)
        if bookmarked_anchor:
            anchor_paragraph = next((p for p in paragraphs if p.anchor == bookmarked_anchor), None)
            if anchor_paragraph is None:
                return EditResult(record.edit_id, "BLOCKED", "Bookmarked location no longer resolves to a paragraph", number)
        else:
            if heading_index is None:
                return EditResult(record.edit_id, "BLOCKED", f"Could not uniquely resolve subsection heading for {number}", number)
            body_end = self._section_body_end_index(paragraphs, heading_index)
            anchor_index = body_end if body_end >= heading_index + 1 else heading_index
            anchor_paragraph = paragraphs[anchor_index]
        heading_label = paragraphs[heading_index].text[:60] if heading_index is not None else "(resolved via bookmark)"
        try:
            result = self.doc.insert(record.text, after=anchor_paragraph.anchor, author=author, track_changes=self.track_changes)
            comment_anchor = _result_anchor(result) or anchor_paragraph.anchor
            comment_id = self._add_comment(comment_anchor, record, author, initials)
            self._tag_bookmark(record.edit_id, comment_anchor)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", number)
        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Inserted approved text after subsection {number}: {heading_label} with DocxEngine",
            number,
            comment_id,
        )

    def _subsection_heading_index(self, paragraphs, number: str, lo: int, hi: int) -> int | None:
        """Index of the unique heading whose leading numbered token equals *number*
        within the given index window, or None if absent or non-unique."""
        wanted = number.lower()
        index: int | None = None
        for i in range(max(0, lo), min(hi, len(paragraphs) - 1) + 1):
            if not _is_heading(paragraphs[i]):
                continue
            text = normalise_text(paragraphs[i].text).lower()
            if text == wanted or text.startswith(wanted + " ") or text.startswith(wanted + "\t"):
                if index is not None:
                    return None  # non-unique within scope -> do not guess
                index = i
        return index

    def _apply_anchor_plus_following_content(self, record: ChangeRecord, content_count: int, author: str, initials: str) -> EditResult:
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Anchor plus following content replacement has no Text")
        anchor_text = find_anchor(record.where)
        if not anchor_text:
            return EditResult(record.edit_id, "BLOCKED", "Could not extract anchor from Where")
        paragraphs = self.doc.paragraphs()
        anchor_index, blocked = self._resolve_paragraph_index(record, anchor_text, paragraphs, "Anchor match count")
        if blocked:
            return blocked
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

        pipe_rows = _extract_pipe_row_replacements(record.text, record.where)
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
            # `cells` may be the full new row (Where supplied a distinct
            # anchor from the row's own content) or just the non-label cells
            # (historical shape: the label cell is the anchor and stays
            # untouched). Detect which by matching the cell count rather
            # than assuming a fixed offset.
            if row_cell_count == len(cells):
                start_index = 0
            elif row_cell_count == len(cells) + 1:
                start_index = 1
            else:
                return EditResult(
                    record.edit_id,
                    "BLOCKED",
                    f"Pipe row for {row_label} supplies {len(cells)} value(s); table row has {row_cell_count} cells (expected {row_cell_count} or {row_cell_count - 1})".strip(),
                    row_label,
                )
            for position, value in enumerate(cells):
                updates.append(TableCellUpdate(row_ref.table_anchor, row_ref.row_index, position + start_index, row_label, value))

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
            if self.track_changes:
                # DocxEngine's set_cells ignores track_changes, so write the cells
                # as tracked revisions here (S64).
                self._set_cells_tracked(updates, author)
            else:
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

    def _apply_full_table_replacement(self, record: ChangeRecord, author: str, initials: str) -> EditResult:
        """Wholesale 'replace the table content' edit: overwrite every cell of an
        existing table positionally from a parsed replacement table, rather than
        matching rows by a label that the edit may itself be renaming.
        """
        if not record.text:
            return EditResult(record.edit_id, "BLOCKED", "Table replacement has no Text")

        new_rows = _parse_markdown_table(record.text)
        if not new_rows:
            return EditResult(record.edit_id, "BLOCKED", "Could not parse a replacement table from Text")

        table_anchor, comment_anchor, reason = self._locate_table_for_replacement(record)
        if table_anchor is None:
            return EditResult(record.edit_id, "BLOCKED", reason or "Could not locate the target table")

        existing_rows = dict(self._table_rows()).get(table_anchor)
        if existing_rows is None:
            return EditResult(record.edit_id, "BLOCKED", f"Could not read existing table: {table_anchor}", table_anchor)

        new_dims = (len(new_rows), len(new_rows[0]) if new_rows else 0)
        old_dims = (len(existing_rows), len(existing_rows[0]) if existing_rows else 0)
        if new_dims != old_dims or any(len(row) != new_dims[1] for row in new_rows):
            return EditResult(
                record.edit_id,
                "BLOCKED",
                f"Replacement table is {new_dims[0]}x{new_dims[1]}; existing table {table_anchor} is "
                f"{old_dims[0]}x{old_dims[1]} - refusing to reshape a table without explicit row/column "
                "insert instructions",
                table_anchor,
            )

        cells = [
            {"r": r, "c": c, "text": value}
            for r, row in enumerate(new_rows)
            for c, value in enumerate(row)
        ]
        try:
            self.doc.table("set_cells", anchor=table_anchor, cells=cells, author=author)
            comment_id = self._add_comment(comment_anchor, record, author, initials) if comment_anchor else None
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine table error: {exc}", table_anchor)

        return EditResult(
            record.edit_id,
            "APPLIED",
            f"Replaced table content ({new_dims[0]}x{new_dims[1]}) with DocxEngine: {table_anchor}",
            table_anchor,
            comment_id,
        )

    def _locate_table_for_replacement(
        self, record: ChangeRecord
    ) -> tuple[str | None, str | None, str | None]:
        """Return ``(table_anchor, comment_anchor, reason_if_not_found)``.

        Tries the approved caption text first (scoped by section heading, same
        as paragraph anchors); when that caption isn't literal document text
        (0 matches - the approved change record may be using a generic template
        caption rather than quoting this section), falls back to the table
        being the single, unambiguous table within the section-heading-scoped
        paragraph range. Never guesses among multiple candidates either way.
        """
        caption = find_anchor(record.where)
        paragraphs = self.doc.paragraphs()

        if caption:
            caption_matches = self._matching_paragraphs(caption, record.where, paragraphs)
            if len(caption_matches) == 1:
                table_anchor = self._first_table_after(caption_matches[0].anchor)
                if table_anchor:
                    return table_anchor, caption_matches[0].anchor, None
            elif len(caption_matches) > 1:
                return None, None, f"Table caption anchor match count was {len(caption_matches)}; expected 1"

        bounds = self._section_paragraph_bounds(paragraphs)
        if bounds is None:
            return None, None, f"Could not locate table caption '{caption}' and no section heading scope was available"
        start_index, end_index = bounds
        tables = self._tables_in_section(start_index, end_index, paragraphs)
        if len(tables) == 1:
            comment_anchor = self._paragraph_before_table(tables[0]) or paragraphs[start_index].anchor
            return tables[0], comment_anchor, None
        if not tables:
            return None, None, f"Could not locate table caption '{caption}' and no table was found within the scoped section"
        return None, None, f"Could not locate table caption '{caption}' and {len(tables)} tables exist within the scoped section"

    def _section_paragraph_bounds(self, paragraphs=None) -> tuple[int, int] | None:
        """(start_index, end_index) bounding the body paragraphs under
        self.section_heading, mirroring the heading lookup in _scope_matches."""
        if not self.section_heading:
            return None
        paragraphs = paragraphs if paragraphs is not None else self.doc.paragraphs()
        heading_indexes = [
            index
            for index, paragraph in enumerate(paragraphs)
            if _is_heading(paragraph)
            and spelling_normalised_text(self.section_heading) in spelling_normalised_text(paragraph.text)
        ]
        if not heading_indexes:
            return None
        first_heading = heading_indexes[-1]
        heading_level = _heading_level(paragraphs[first_heading])
        next_heading = len(paragraphs)
        for index in range(first_heading + 1, len(paragraphs)):
            level = _heading_level(paragraphs[index])
            if level is not None and heading_level is not None and level <= heading_level:
                next_heading = index
                break
        return first_heading, next_heading

    def _first_table_after(self, paragraph_anchor: str) -> str | None:
        if build_anchor_index is None:
            return None
        entries = build_anchor_index(self.doc._doc.package)
        found = False
        for entry in entries:
            if found and entry.kind == "table":
                return entry.anchor
            if entry.anchor == paragraph_anchor:
                found = True
        return None

    def _paragraph_before_table(self, table_anchor: str) -> str | None:
        if build_anchor_index is None:
            return None
        entries = build_anchor_index(self.doc._doc.package)
        previous_paragraph: str | None = None
        for entry in entries:
            if entry.anchor == table_anchor:
                return previous_paragraph
            if entry.kind == "paragraph":
                previous_paragraph = entry.anchor
        return None

    def _tables_in_section(self, start_index: int, end_index: int, paragraphs) -> list[str]:
        if build_anchor_index is None:
            return []
        entries = build_anchor_index(self.doc._doc.package)
        start_anchor = paragraphs[start_index].anchor
        end_anchor = paragraphs[end_index].anchor if end_index < len(paragraphs) else None
        tables: list[str] = []
        in_range = False
        for entry in entries:
            if entry.anchor == start_anchor:
                in_range = True
                continue
            if end_anchor is not None and entry.anchor == end_anchor:
                break
            if in_range and entry.kind == "table":
                tables.append(entry.anchor)
        return tables

    def _stable_id_map(self) -> dict[str, int]:
        if not hasattr(self, "_stable_id_map_cache"):
            from csa_docx.stable_ids import build_id_map
            # Keep the entries the map indexes into: the map is built once per batch, and
            # a later paragraph deletion would shift a freshly built list under it.
            self._stable_id_entries_cache = self.paragraphs_with_table_rows()
            self._stable_id_map_cache = build_id_map(self._stable_id_entries_cache)
        return self._stable_id_map_cache

    def _resolve_stable_table_row(self, stable_id) -> "TableRowRef | None":
        """Resolve a T-kind StableId to a TableRowRef using _table_rows().

        build_id_map assigns table rows in document order (T1, T2, ...) and
        1-based row ordinals within each table. _table_rows() uses the same
        document-order T{ordinal} anchor convention, so the two line up:
        ordinal N here is table index N-1 there.
        """
        id_map = self._stable_id_map()
        id_str = str(stable_id)
        index = id_map.get(id_str)
        if index is None:
            return None
        # Index into the same snapshot the map was built from. Table ordinals and row
        # ordinals do not change during a batch (edits never add or remove tables or rows).
        entry = self._stable_id_entries_cache[index]
        table_anchor = getattr(entry, "table_anchor", None)
        if not table_anchor:
            return None
        # table_anchor is "T{n}"; find the matching table in _table_rows()
        # and use the stable row ordinal (1-based) as row_index (0-based).
        m = re.match(r"T(\d+)$", table_anchor)
        if not m:
            return None
        table_ordinal = int(m.group(1))
        all_tables = self._table_rows()
        if table_ordinal - 1 >= len(all_tables):
            return None
        anchor, rows = all_tables[table_ordinal - 1]
        row_index = (stable_id.row or 1) - 1
        if row_index >= len(rows):
            return None
        headers = rows[0] if rows else []
        return TableRowRef(anchor, row_index, headers, rows[row_index])

    def _find_unique_table_row(self, row_label: str) -> "TableRowRef | None":
        # Stable structural ID (e.g. "@H2.8-T1-R10") takes priority over any
        # cell-text matching: it is immune to wording drift and is the
        # authoritative locator the change file supplies. Resolve it against
        # the same manifest builder (build_id_map over
        # paragraphs_with_table_rows) that prepareDocument/lookupStableId use,
        # then map that entry's (table ordinal, row ordinal) onto the
        # T{ordinal}/row-index convention _table_rows() uses. Falls through
        # to the existing text/fuzzy matching below when the label is not a
        # resolvable stable ID.
        stable_id = extract_stable_id(row_label)
        if stable_id is not None and stable_id.kind == "T":
            # A resolvable table-row stable ID is a precise structural
            # locator - trust it and skip cell-text/fuzzy matching entirely
            # (the label text in a Where clause is frequently a quoted
            # human-readable row with literal "|" separators that will never
            # equal the pipe-less cell-join used for text matching). If the
            # ID is well-formed but no longer resolves (document drifted
            # since the manifest was built), surface a clear BLOCKED rather
            # than silently guessing a different row by text.
            row_ref = self._resolve_stable_table_row(stable_id)
            if row_ref is not None:
                return row_ref
            return None

        wanted = normalise_text(row_label)
        matches: list[TableRowRef] = []
        all_rows: list[TableRowRef] = []
        for table_anchor, rows in self._table_rows():
            headers = rows[0] if rows else []
            for row_index, cell_texts in enumerate(rows):
                if not cell_texts:
                    continue
                ref = TableRowRef(table_anchor, row_index, headers, cell_texts)
                all_rows.append(ref)
                # Some tables (e.g. a "Section | Title | Purpose | ..." map)
                # split what a Where clause describes as one label -- e.g.
                # "6 Architectural Review" -- across the first two cells
                # ("6", "Architectural Review") rather than storing it in a
                # single cell. Try progressively longer joins of the leading
                # cells so both conventions resolve, but only count the row
                # once even if more than one join happens to match.
                joined = ""
                row_matches = False
                for cell in cell_texts:
                    joined = f"{joined} {cell}".strip() if joined else cell
                    candidate = normalise_text(joined)
                    if candidate == wanted or candidate.startswith(wanted):
                        row_matches = True
                        break
                if row_matches:
                    matches.append(ref)
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None  # already ambiguous on exact/prefix match - don't fuzzy-rescue a close call

        # No exact/prefix match anywhere: try a fuzzy fallback for minor wording
        # differences, but only accept a clear, unambiguous best match.
        scored = [
            (_label_similarity(wanted.lower(), normalise_text(ref.cell_texts[0]).lower()), ref)
            for ref in all_rows
        ]
        scored = [item for item in scored if item[0] >= _FUZZY_ROW_LABEL_THRESHOLD]
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1:
            return scored[0][1]
        if scored[0][0] - scored[1][0] >= _FUZZY_ROW_LABEL_MARGIN:
            return scored[0][1]
        return None

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

    def paragraphs_with_table_rows(self) -> list["Paragraph | _ManifestTableRow"]:
        """Body paragraphs and table rows, interleaved in true document order.

        ``self.doc.paragraphs()`` (the vendored ``docxengine.Document.paragraphs``)
        only ever returns body-level ``w:p`` elements -- tables are a deliberately
        separate concern in that library (see its docstring: "Tables anchor as
        ``T{ordinal}``... cell text is a projection concern"). ``stable_ids.py``'s
        manifest builder *does* implement ``@H<section>-T<n>-R<n>`` table-row IDs,
        but never saw any, because nothing ever fed it a paragraph-shaped object
        with a ``table_anchor`` set -- ``prepareDocument()`` always reported
        ``table_rows: 0`` even though the document has tables (confirmed against
        `word/document.xml` directly during Section 1 CSA authoring on
        2026-09-20).

        This walks the same body-level anchor index the vendor library itself
        derives paragraph/table anchors from (``build_anchor_index``), so each
        table's position relative to the surrounding headings/paragraphs -- and
        therefore its ``@H<section>`` attribution -- is exact, then expands each
        table into its rows via ``_table_rows()`` (already used by the table-edit
        path, so the ``T{n}`` numbering is guaranteed to line up: both walk the
        same body-level ``w:tbl`` elements in the same order).
        """
        package = self.doc._doc.package
        ordered_paragraphs = self.doc.paragraphs()
        rows_by_table = dict(self._table_rows())
        merged: list[Paragraph | _ManifestTableRow] = []
        p_index = 0
        for entry in build_anchor_index(package):
            if entry.kind == "paragraph":
                merged.append(ordered_paragraphs[p_index])
                p_index += 1
            elif entry.kind == "table":
                table_anchor = entry.anchor  # e.g. "T3" -- same scheme _table_rows() uses
                for row_index, cells in enumerate(rows_by_table.get(table_anchor, []), start=1):
                    preview = " | ".join(cell for cell in cells if cell)
                    merged.append(
                        _ManifestTableRow(
                            anchor=f"{table_anchor}-R{row_index}",
                            text=preview,
                            table_anchor=table_anchor,
                        )
                    )
        return merged

    def _set_cells_tracked(self, updates: list["TableCellUpdate"], author: str) -> None:
        """Write table cells as tracked changes: every existing run in the cell becomes
        a tracked deletion (``w:del`` / ``w:delText``) and the new text a tracked
        insertion (``w:ins``) in the cell's first paragraph, keeping that paragraph's
        properties and the first run's formatting. Content controls (the Rating
        dropdown) stay in place. Cells whose text already matches are left alone.
        Revision IDs continue from the highest existing ``w:ins``/``w:del`` id, as
        DocxEngine allocates them."""
        from datetime import datetime, timezone
        import copy as _copy

        package = self.doc._doc.package
        main_part = package.main_document_part()
        original = package.part(main_part)
        root = _parse_part_preserving(original)
        ins_tag, del_tag = qn(W_NS, "ins"), qn(W_NS, "del")
        rev = 1 + max((int(e.get(qn(W_NS, "id"), "0")) for e in root.iter()
                       if e.tag in (ins_tag, del_tag) and e.get(qn(W_NS, "id"), "").isdigit()), default=0)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parents = {child: parent for parent in root.iter() for child in parent}

        def revision(tag: str) -> ET.Element:
            nonlocal rev
            el = ET.Element(tag, {qn(W_NS, "id"): str(rev), qn(W_NS, "author"): author, qn(W_NS, "date"): date})
            rev += 1
            return el

        def inside_revision(el: ET.Element) -> bool:
            p = parents.get(el)
            while p is not None:
                if p.tag in (ins_tag, del_tag):
                    return True
                p = parents.get(p)
            return False

        for update in updates:
            paragraph = self._find_table_cell_paragraph(root, update)
            if paragraph is None:
                raise ToolError(f"table cell not found for {update.row_label}")
            cell = paragraph
            while cell is not None and cell.tag != qn(W_NS, "tc"):
                cell = parents.get(cell)
            if cell is None:
                raise ToolError(f"table cell not found for {update.row_label}")
            old_text = "".join(t.text or "" for t in cell.iter(qn(W_NS, "t")) if not inside_revision(t))
            if old_text.strip() == update.value.strip():
                continue
            runs = [r for r in cell.iter(qn(W_NS, "r"))
                    if not inside_revision(r) and r.find(qn(W_NS, "commentReference")) is None]
            first_rpr = next((r.find(qn(W_NS, "rPr")) for r in runs if r.find(qn(W_NS, "rPr")) is not None), None)
            target_p = next(cell.iter(qn(W_NS, "p")))  # first paragraph, also inside a content control
            wrappers: list[ET.Element] = []
            for run in runs:
                parent = parents[run]
                index = list(parent).index(run)
                for t in run.findall(qn(W_NS, "t")):
                    t.tag = qn(W_NS, "delText")
                for t in run.findall(qn(W_NS, "instrText")):
                    t.tag = qn(W_NS, "delInstrText")
                wrapper = revision(del_tag)
                parent.remove(run)
                wrapper.append(run)
                parent.insert(index, wrapper)
                parents[wrapper] = parent
                parents[run] = wrapper
                wrappers.append(wrapper)
            ins = revision(ins_tag)
            new_run = ET.SubElement(ins, qn(W_NS, "r"))
            if first_rpr is not None:
                rpr = _copy.deepcopy(first_rpr)
                for style in rpr.findall(qn(W_NS, "rStyle")):
                    if style.get(qn(W_NS, "val")) == "PlaceholderText":
                        rpr.remove(style)  # the grey placeholder look must not carry over
                if len(rpr):
                    new_run.append(rpr)
            for i, line in enumerate(update.value.split("\n")):
                if i:
                    ET.SubElement(new_run, qn(W_NS, "br"))
                t = ET.SubElement(new_run, qn(W_NS, "t"))
                t.text = line
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            if wrappers:
                # Insert right after the deleted text, in the same container, so a
                # value replacing a content control's placeholder (the Rating
                # dropdown) lands inside the control.
                container = parents[wrappers[0]]
                last = max((w for w in wrappers if parents[w] is container), key=lambda w: list(container).index(w))
                container.insert(list(container).index(last) + 1, ins)
                parents[ins] = container
                if container.tag == qn(W_NS, "sdtContent"):
                    sdt_pr = parents[container].find(qn(W_NS, "sdtPr"))
                    if sdt_pr is not None:
                        for flag in sdt_pr.findall(qn(W_NS, "showingPlcHdr")):
                            sdt_pr.remove(flag)
            else:
                target_p.append(ins)
                parents[ins] = target_p

        package.set_part(main_part, _serialize_part_preserving(root, original))
        self.doc._doc.mark_dirty()

    def _add_table_cell_comment(self, update: "TableCellUpdate", record: ChangeRecord, author: str, initials: str) -> str | None:
        package = self.doc._doc.package
        main_part = package.main_document_part()
        original = package.part(main_part)
        root = _parse_part_preserving(original)
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

        package.set_part(main_part, _serialize_part_preserving(root, original))
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
        comments_original = package.part(comments_part) if package.has_part(comments_part) else None
        if comments_original is not None:
            comments_root = _parse_part_preserving(comments_original)
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
        text.text = build_comment_text(record)
        comments_xml = ET.tostring(comments_root, encoding="utf-8", xml_declaration=True)
        if comments_original is not None:
            comments_xml = _serialize_part_preserving(comments_root, comments_original)
        package.set_part(comments_part, comments_xml)
        self.doc._doc.mark_dirty()
        return comment_id

    def _ensure_comment_relationship_parts(self) -> None:
        package = self.doc._doc.package
        rels_part = "word/_rels/document.xml.rels"
        if package.has_part(rels_part):
            rels_original = package.part(rels_part)
            rels_root = _parse_part_preserving(rels_original)
        else:
            rels_original = None
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
            package.set_part(rels_part, _serialize_part_preserving(
                rels_root, rels_original or f'<Relationships xmlns="{REL_NS}"/>'.encode()))

        content_types_part = "[Content_Types].xml"
        ct_original = package.part(content_types_part)
        ct_root = _parse_part_preserving(ct_original)
        if not any(part.get("PartName") == "/word/comments.xml" for part in ct_root):
            override = ET.SubElement(ct_root, qn(CONTENT_TYPES_NS, "Override"))
            override.set("PartName", "/word/comments.xml")
            override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
            package.set_part(content_types_part, _serialize_part_preserving(ct_root, ct_original))
        self.doc._doc.mark_dirty()

    def _section_scope(self, paragraphs=None) -> tuple[int, int, int] | None:
        """Return ``(root_heading_index, body_start, body_end)`` for the run's
        section, or ``None`` when no scope is defined.

        The scope root is the **top-level** heading whose text matches
        ``self.section_heading`` - the smallest heading level among all matching
        headings (the last one on any tie). Anchoring on the last match (the old
        ``heading_indexes[-1]`` behaviour) could land on an H2/H3 sub-heading such
        as "Observed Security Controls", which silently narrows the section body
        to that sub-heading's span and leaves the real top-level section body
        unsreachable. Scoping to the top-level heading is the correct interpretation
        of a "Section N" edit and also resolves anchors that are globally
        duplicated (e.g. a leftover orphan copy of a section) to the one inside the
        intended section.

        Section labels in change files are "N - Title" but the document
        headings carry only the title (the number is structural, assigned by
        ordinal position - see stable_ids.py). Match on the title part.
        """
        if not self.section_heading:
            return None
        paragraphs = paragraphs if paragraphs is not None else self.doc.paragraphs()
        wanted = spelling_normalised_text(self.section_heading)
        title_wanted = wanted
        if " - " in wanted:
            title_wanted = wanted.split(" - ", 1)[1].strip()
        candidates: list[tuple[int, int | None]] = []
        for index, paragraph in enumerate(paragraphs):
            if not _is_heading(paragraph):
                continue
            if title_wanted in spelling_normalised_text(paragraph.text):
                candidates.append((index, _heading_level(paragraph)))
        if not candidates:
            # Fall back to the full "N - Title" form (some documents do
            # number their headings explicitly).
            for index, paragraph in enumerate(paragraphs):
                if not _is_heading(paragraph):
                    continue
                if wanted in spelling_normalised_text(paragraph.text):
                    candidates.append((index, _heading_level(paragraph)))
        if not candidates:
            return None
        finite = [(index, level) for index, level in candidates if level is not None]
        if not finite:
            return None
        top_level = min(level for _, level in finite)
        root_index = max(index for index, level in finite if level == top_level)
        heading_level = _heading_level(paragraphs[root_index])
        body_end = len(paragraphs) - 1
        for index in range(root_index + 1, len(paragraphs)):
            level = _heading_level(paragraphs[index])
            if level is not None and heading_level is not None and level <= heading_level:
                body_end = index - 1
                break
        return root_index, root_index + 1, body_end

    def _scoped_matches(self, matches, paragraphs):
        """Narrow a full-document match list to the run's section body.

        Must run against the *same* paragraph list the matches came from
        (``self.doc.paragraphs()`` returns fresh objects on every call, so a
        scope built from a second call would never match by identity or
        anchor - the first version of this filter silently returned an empty
        list for every anchor, which is exactly the "match count was 0"
        block seen for scoped anchors like "Confirms: in Section 2.2.2").
        Returns the list unchanged when there is no scope or the match list
        is already unique.
        """
        scope = self._section_scope(paragraphs)
        if scope is None or len(matches) <= 1:
            return matches
        _, body_start, body_end = scope
        scope_anchors = {paragraphs[index].anchor for index in range(body_start, body_end + 1)}
        return [match for match in matches if match.anchor in scope_anchors]

    def _scoped_unique_index(self, anchor_text: str, paragraphs, *, allow_prefix: bool = False, allow_suffix: bool = False) -> int | None:
        """Resolve an anchor to a unique paragraph index.

        Uses a globally-unique match when one exists (existing behaviour). When
        the anchor is globally duplicated, falls back to resolving it within the
        run's section body, so a "Section N" edit is disambiguated to the intended
        section rather than blocked. Still returns ``None`` when there is no
        unique resolution - never guessing.
        """
        # Stable-ID anchors resolve deterministically (structural, not text),
        # so a range boundary given as an @H... id is exact even when the same
        # wording repeats elsewhere in the section.
        stable_id = extract_stable_id(anchor_text)
        if stable_id:
            id_str = str(stable_id)
            id_map = build_id_map(paragraphs)
            if id_str in id_map:
                return id_map[id_str]
            return None
        index = self._unique_paragraph_index(anchor_text, paragraphs, allow_prefix=allow_prefix, allow_suffix=allow_suffix)
        if index is not None:
            return index
        scope = self._section_scope(paragraphs)
        if scope is None:
            return None
        root_index, body_start, body_end = scope
        variants = _anchor_variants(anchor_text)
        matches = [
            index
            for index in range(body_start, body_end + 1)
            if any(
                normalise_text(paragraphs[index].text).startswith(variant)
                if allow_prefix
                else normalise_text(paragraphs[index].text).endswith(variant)
                if allow_suffix
                else normalise_text(paragraphs[index].text) == variant
                for variant in variants
            )
        ]
        return matches[0] if len(matches) == 1 else None

    def _matching_paragraphs(self, anchor_text: str, where: str, paragraphs=None):
        paragraphs = paragraphs if paragraphs is not None else self.doc.paragraphs()
        variants = _anchor_variants(anchor_text)

        exact_matches = [p for p in paragraphs if normalise_text(p.text) in variants]
        if exact_matches:
            return self._scoped_matches(exact_matches, paragraphs)
        if "beginning exactly" in where.lower() or "text beginning" in where.lower() or "words beginning" in where.lower():
            prefix_matches = [p for p in paragraphs if any(normalise_text(p.text).startswith(variant) for variant in variants)]
            return self._scoped_matches(prefix_matches, paragraphs)
        contains_matches = [p for p in paragraphs if any(variant in normalise_text(p.text) for variant in variants)]
        return self._scoped_matches(contains_matches, paragraphs)

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
            result = self.doc.edit_paragraph(paragraphs[start_index].anchor, replacement_paragraphs[0], author=author, track_changes=self.track_changes)
            first_anchor = _result_anchor(result) or self._find_unique_text(replacement_paragraphs[0])
            if first_anchor is None:
                return EditResult(record.edit_id, "BLOCKED", "Could not re-anchor edited paragraph", start_anchor_text)
            for paragraph in reversed(old_following):
                self.doc.delete(anchor=paragraph.anchor, author=author, track_changes=self.track_changes)
            if len(replacement_paragraphs) > 1:
                self.doc.insert("\n".join(replacement_paragraphs[1:]), after=first_anchor, author=author, track_changes=self.track_changes)
            comment_id = self._add_comment(first_anchor, record, author, initials)
            self._tag_bookmark(record.edit_id, first_anchor)
        except ToolError as exc:
            return EditResult(record.edit_id, "BLOCKED", f"DocxEngine error: {exc}", start_anchor_text)
        return EditResult(record.edit_id, "APPLIED", message, start_anchor_text, comment_id)

    def _delete_indices(self, paragraphs, start_index: int, end_index: int, author: str) -> None:
        for paragraph in reversed(paragraphs[start_index : end_index + 1]):
            self.doc.delete(anchor=paragraph.anchor, author=author, track_changes=self.track_changes)

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
        comment_text = build_comment_text(record)  # author and initials are comment metadata, not text
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
    """Pull the resulting anchor out of a DocxEngine tool-call result dict.

    Different DocxEngine tools shape their result differently: some return a
    single anchor under "anchor"/"new_anchor", but docx_insert returns a
    *list* under "new_anchors" (plural) - confirmed by direct inspection
    (`doc.insert(...)` -> `{"new_anchors": ["P1166#4751"]}`). Before this fix,
    every insert-before/insert-after edit fell through this function to
    ``None`` (neither singular key matched), so the caller always fell back
    to the pre-insert paragraph anchor for its immediately-following
    `_add_comment` call. Inserting a paragraph shifts every paragraph
    ordinal at or after the insertion point, so that fallback anchor is
    already stale by the time `_add_comment` uses it - the edit's *content*
    change would have silently succeeded while the comment attach failed
    with a confusing "anchor is stale" error, blocking the whole edit
    (found while diagnosing E-177's "Anchor P1166#4670 is stale" block,
    which traced back to here rather than to the insert itself).
    """
    value = result.get("anchor") or result.get("new_anchor")
    if not value:
        anchors = result.get("new_anchors") or result.get("anchors")
        if isinstance(anchors, (list, tuple)) and anchors:
            value = anchors[0]
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


class _ManifestTableRow:
    """Paragraph-shaped view of one table row, for ``stable_ids``'s manifest builder only.

    ``stable_ids.build_id_map``/``generate_manifest`` read a paragraph-like
    object's ``style``, ``text``, ``anchor``, and ``table_anchor`` via
    ``getattr(...)`` with defaults, so this only needs to supply those four
    attributes -- it is never passed to any DocxEngine edit call (table edits
    go through ``_apply_table_row_change``'s row-label matching instead, which
    reads the DOCX directly and does not use this class).
    """

    __slots__ = ("anchor", "text", "style", "table_anchor")

    def __init__(self, anchor: str, text: str, table_anchor: str, style: str | None = None) -> None:
        self.anchor = anchor
        self.text = text
        self.style = style
        self.table_anchor = table_anchor


class TableCellUpdate:
    def __init__(self, table_anchor: str, row_index: int, cell_index: int, row_label: str, value: str):
        self.table_anchor = table_anchor
        self.row_index = row_index
        self.cell_index = cell_index
        self.row_label = row_label
        self.value = value
