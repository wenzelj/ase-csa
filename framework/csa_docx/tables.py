"""Reusable "create a table that matches the document's own tables" helper.

The change-file pipeline (``cli_apply_section.py`` / ``apply_next_batch``) can
only edit *existing* tables: ``set_cells``, row/column insert/delete, whole-table
content replacement. It has no "new table" operation. This module adds that
capability with a single conservative function, :func:`create_table`, that:

* resolves a robust anchor paragraph (via ``stable_ids.build_id_map`` +
  ``Document.paragraphs()``), refusing to guess when the anchor is ambiguous;
* discovers the document's *own* table look at run time (the dominant
  ``w:tblStyle``, the dominant ``w:tblLook`` banding flag, and the
  per-row/cell ``cnfStyle`` banding pattern used by its existing tables)
  instead of hardcoding any style name -- so a future document that changes
  style still gets tables that look identical to its siblings;
* clones the ``<w:tblPr>``, ``<w:tblGrid>``, and the ``<w:tr>``/``<w:tc>``
  markup of a real existing table, adjusting only the column count and the
  ``<w:t>`` text content;
* writes the new table immediately after the resolved anchor paragraph;
* runs the framework's ``validator.validate_docx`` and returns the result.

All failure modes come back as ``{"status": "ERROR", "message": ...}`` (or
``"BLOCKED"`` when the anchor is ambiguous), never as a traceback. The caller
is responsible for making a recoverable ``.bak`` backup if they want one --
:func:`create_table` takes a ``backup`` flag (default ``True``) and creates
a timestamped ``.bak`` copy next to the working DOCX before any mutation.
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

# Vendor bootstrap: make docxengine importable. Same ordering as the adapter.
_THIS_DIR = Path(__file__).resolve().parent
_VENDOR_DIR = _THIS_DIR.parent / "vendor"
if _VENDOR_DIR.exists() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))


def _error(message: str) -> dict[str, Any]:
    return {"status": "ERROR", "message": message}


def _blocked(message: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "message": message}


def _read_document_xml(docx: Path) -> str:
    with zipfile.ZipFile(docx) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _write_document_xml(docx: Path, new_xml: str) -> None:
    """Replace ``word/document.xml`` inside the ZIP, preserving every other member.

    Uses each member's original ``ZipInfo`` so compression/attributes survive
    the rewrite, and atomically replaces the final file.
    """
    tmp = docx.with_name(docx.name + ".tmp_new")
    try:
        with zipfile.ZipFile(docx, "r") as zin:
            with zipfile.ZipFile(tmp, "w") as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == "word/document.xml":
                        data = new_xml.encode("utf-8")
                    zout.writestr(info, data)
        shutil.move(str(tmp), str(docx))
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Anchor resolution
# ---------------------------------------------------------------------------


def _resolve_anchor(docx: Path, after: str) -> dict[str, Any] | None:
    """Resolve an anchor (either a stable-ID like ``@H16`` or a live anchor
    like ``P2139#2dbe``) to the live ``P#`` anchor of that paragraph.

    Returns ``{"anchor": "P2139#2dbe", "text": "Glossary and Acronyms",
    "index": 2139}`` on success, or ``None`` when the anchor is not
    recognisable.
    """
    from csa_docx.stable_ids import build_id_map
    from docxengine import Document

    doc = Document.open(str(docx))
    try:
        paragraphs = doc.paragraphs()
    finally:
        # docxengine's Document has no explicit close(); falling out of scope
        # frees the package's temp dir (see _document.py Session semantics).
        pass

    if after.startswith("P") and re.match(r"^P\d+#\w+$", after or ""):
        m = re.match(r"^P(\d+)", after or "")
        if not m:
            return None
        idx = int(m.group(1))
        if idx >= len(paragraphs):
            return None
        return {
            "anchor": paragraphs[idx].anchor,
            "text": paragraphs[idx].text,
            "index": idx,
        }

    # Stable-ID path.
    id_map = build_id_map(paragraphs)
    idx = id_map.get(after)
    if idx is None:
        return None
    return {
        "anchor": paragraphs[idx].anchor,
        "text": paragraphs[idx].text,
        "index": idx,
    }


def _anchor_offset(docx: Path, anchor: str) -> int | None:
    """The byte offset *immediately after* the ``<w:p>...</w:p>`` whose
    ``entry.anchor`` equals ``anchor``, or ``None`` when not found.

    Uses docxengine's own ``build_anchor_index`` against the live document so
    the offset is computed from the exact same XML bytes we will splice into.
    """
    from docxengine._anchors import build_anchor_index
    from docxengine._opc import Package

    package = Package.open(str(docx))
    try:
        for entry in build_anchor_index(package):
            if entry.kind == "paragraph" and entry.anchor == anchor:
                return entry.span.end
        return None
    finally:
        cleanup = getattr(package, "cleanup", None) or getattr(package, "close", None)
        if callable(cleanup):
            cleanup()


# ---------------------------------------------------------------------------
# Style discovery (never hardcoded)
# ---------------------------------------------------------------------------


def _all_tables(docx: Path) -> list[str]:
    xml = _read_document_xml(docx)
    return re.findall(r"<w:tbl[^>]*>.*?</w:tbl>", xml, re.S)


def _dominant_table_style(docx: Path) -> str | None:
    """The most common ``w:tblStyle`` value across the document's tables."""
    counts: Counter[str] = Counter()
    for tbl in _all_tables(docx):
        m = re.search(r'<w:tblStyle w:val="([^"]+)"', tbl)
        if m:
            counts[m.group(1)] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _pick_reference_table(docx: Path, cols: int) -> str | None:
    """The single existing table whose markup best represents the document's
    house style. Preference order:

    1. A table with the same column count (so ``<w:tblGrid>`` and every
       ``<w:tcW>`` line up 1:1 with the new table).
    2. Otherwise, a table with at least ``cols`` columns (we can drop
       trailing columns and their ``<w:tcW>`` entries).
    3. Otherwise, the first table at all.

    Returns the raw ``<w:tbl>...</w:tbl>`` XML string, or ``None`` when the
    document has no tables.
    """
    tables = _all_tables(docx)
    if not tables:
        return None

    def col_count(tbl: str) -> int:
        return len(re.findall(r"<w:gridCol\b", tbl))

    same = [t for t in tables if col_count(t) == cols]
    if same:
        return same[0]

    wider = [t for t in tables if col_count(t) >= cols]
    if wider:
        return min(wider, key=lambda t: col_count(t) - cols)

    return tables[0]


def _extract(tbl: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}[^>]*>.*?</{tag}>", tbl, re.S)
    return m.group(0) if m else None


def _extract_p(cell: str) -> str | None:
    return _extract(cell, "w:p")


def _replace_text(p: str, new_text: str) -> str:
    """Replace the text content of the (single) run inside ``<w:p>``.

    The template cell has exactly one ``<w:r>`` and one ``<w:t>`` (verified
    against the live DOCX); we substitute that ``<w:t>`` with the new text
    while preserving the surrounding run markup (Arial font, spacing, etc.).
    """
    escaped = (
        new_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    m = re.search(r"<w:t([^>]*)>", p)
    if m is None:
        return re.sub(
            r"(</w:r>)$",
            f"<w:r><w:t xml:space=\"preserve\">{escaped}</w:t></w:r>",
            p,
            count=1,
        )
    attrs = m.group(1) or ""
    end = p.find("</w:t>", m.end())
    if end == -1:
        return re.sub(
            r"<w:t[^>]*/>",
            f'<w:t{attrs} xml:space="preserve">{escaped}</w:t>',
            p,
            count=1,
        )
    end += len("</w:t>")
    keep_space = ' xml:space="preserve"' if "preserve" in attrs else attrs
    return p[: m.start()] + f"<w:t{keep_space}>{escaped}</w:t>" + p[end:]


def _drop_trailing_cells(row: str, keep: int) -> str:
    cells = list(re.finditer(r"<w:tc>.*?</w:tc>", row, re.S))
    if len(cells) <= keep:
        return row
    cut = cells[keep].start()
    return row[:cut] + row[cells[-1].end():]


def _drop_trailing_grid_cols(tbl: str, keep: int) -> str:
    m = re.search(r"<w:tblGrid>.*?</w:tblGrid>", tbl, re.S)
    if not m:
        return tbl
    grid = m.group(0)
    cols = re.findall(r"<w:gridCol[^>]*/>", grid)
    if len(cols) <= keep:
        return tbl
    new_grid = "<w:tblGrid>" + "".join(cols[:keep]) + "</w:tblGrid>"
    return tbl[: m.start()] + new_grid + tbl[m.end():]


def _rebuild_table(
    reference: str,
    cols: int,
    data: list[list[str]],
    header: bool,
) -> str:
    """Clone ``reference`` table's markup for a new ``cols``-column table.

    * ``<w:tblPr>`` is copied verbatim (dominant style + banding flag).
    * ``<w:tblGrid>`` is trimmed to ``cols`` entries.
    * Row 0 is cloned from the reference's row 0 (header band ``cnfStyle``);
      subsequent rows are cloned from row 1 (data band). If the reference has
      only one row, every row uses row 0's markup.
    * Per-cell ``<w:tc>`` is cloned from the column-matched cell of the
      reference row; any extra trailing columns are dropped.
    * ``<w:t>`` text is replaced with the caller's data.
    * No ``<w:b>`` bold is added (banding handles the visual emphasis), and
      no ``<w:shd>`` fills are injected (style-driven, matching the document).
    """
    tbl_pr = _extract(reference, "w:tblPr") or (
        '<w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
    )
    ref_rows = re.findall(r"<w:tr[^>]*>.*?</w:tr>", reference, re.S)
    if not ref_rows:
        raise ValueError("Reference table has no <w:tr> rows to clone.")
    header_row = ref_rows[0]
    data_row = ref_rows[1] if len(ref_rows) > 1 else ref_rows[0]

    def build_row(row_template: str, cells_text: list[str]) -> str:
        row = _drop_trailing_cells(row_template, len(cells_text))
        cell_pattern = re.compile(r"<w:tc>.*?</w:tc>", re.S)
        cell_spans = list(cell_pattern.finditer(row))
        if len(cell_spans) != len(cells_text):
            raise ValueError(
                f"Cell count mismatch after trim: template has {len(cell_spans)}, "
                f"caller passed {len(cells_text)}."
            )
        out = row
        for span, text in reversed(list(zip(cell_spans, cells_text))):
            cell = span.group(0)
            p = _extract_p(cell)
            if p is None:
                raise ValueError("Template cell has no <w:p> to clone.")
            new_p = _replace_text(p, text)
            p_offset = cell.index(p)
            new_cell = cell[:p_offset] + new_p + cell[p_offset + len(p):]
            out = out[: span.start()] + new_cell + out[span.end():]
        return out

    rows: list[str] = []
    if data:
        for i, cells in enumerate(data):
            template = header_row if (i == 0 and header) else data_row
            rows.append(build_row(template, cells))
    else:
        for i in range(max(cols, 1)):
            template = header_row if (i == 0 and header) else data_row
            rows.append(build_row(template, [""] * cols))

    grid_xml = _drop_trailing_grid_cols(reference, cols)
    grid = _extract(grid_xml, "w:tblGrid") or (
        "<w:tblGrid>" + "".join('<w:gridCol w:w="3000" />' for _ in range(cols)) + "</w:tblGrid>"
    )
    return f"<w:tbl>{tbl_pr}{grid}{''.join(rows)}</w:tbl>"


# ---------------------------------------------------------------------------
# Public entry point
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
) -> dict[str, Any]:
    """Insert a new table immediately after the paragraph ``after``.

    The new table's ``<w:tblPr>``, ``<w:tblGrid>``, row ``cnfStyle`` banding,
    and cell markup are all cloned from one of the document's existing tables
    (discovered at run time -- the dominant style, not a hardcoded name), so
    the new table is visually indistinguishable from its siblings. Only the
    ``<w:t>`` text content and the column count are caller-controlled.

    Parameters
    ----------
    docx:
        Path to the working ``.docx``.
    after:
        Anchor for the paragraph the table is inserted after. Either a
        stable-ID (``@H16``) or a live paragraph anchor (``P2139#2dbe``).
        A live anchor is preferred (no manifest lookup needed).
    rows:
        Number of rows (including the header row when ``header=True``).
        Ignored when ``data`` is supplied (``len(data)`` wins).
    cols:
        Number of columns. Default 2.
    data:
        Optional 2-D list of cell strings, one inner list per row. Row 0 is
        the header row when ``header=True``. When supplied, ``rows`` is
        ignored; when omitted, ``rows`` empty-string cells are produced.
    header:
        When ``True`` (default), row 0 uses the reference table's header-row
        markup (``firstRow=1`` ``cnfStyle`` banding). When ``False``, every
        row uses the data-row markup.
    backup:
        When ``True`` (default), a timestamped ``.bak`` copy is created next
        to ``docx`` before any mutation. Set ``False`` only when the caller
        has already taken a backup it is going to keep.

    Returns
    -------
    A plain ``dict``. On success:

    * ``status`` = ``"OK"``
    * ``table_xml`` = the raw ``<w:tbl>...</w:tbl>`` that was written
    * ``style`` = the ``w:tblStyle`` value cloned from the reference table
    * ``backup`` = the backup path (when ``backup=True``)
    * ``validation`` = the result of ``csa_docx.validator.validate_docx``
      for the new package (``archive_integrity``, ``xml_parse:*``,
      ``comment_id_consistency``, ``table_row_comment_safety``)

    On failure: ``{"status": "ERROR" | "BLOCKED", "message": ...}`` with no
    mutation of ``docx``.
    """
    docx_path = Path(docx).resolve()
    if not docx_path.exists():
        return _error(f"DOCX does not exist: {docx_path}")
    if not docx_path.is_file():
        return _error(f"DOCX path is not a file: {docx_path}")
    if cols < 1:
        return _error(f"cols must be >= 1, got {cols}")

    # 1. Resolve the anchor before touching anything.
    anchor_info = _resolve_anchor(docx_path, after)
    if anchor_info is None:
        return _blocked(
            f"Anchor {after!r} could not be resolved to a live paragraph. "
            "Pass a stable-ID like '@H16' or a live anchor like 'P2139#2dbe'."
        )
    anchor = anchor_info["anchor"]

    # 2. Discover the document's own table style (no hardcoding).
    reference = _pick_reference_table(docx_path, cols)
    if reference is None:
        return _error(
            "Document has no existing tables to clone style from. "
            "Add at least one styled table (or pass a template) before "
            "creating a new one."
        )

    # 3. Build the new table's XML.
    if data is not None:
        for i, row in enumerate(data):
            if len(row) != cols:
                return _error(
                    f"data[{i}] has {len(row)} cells but cols={cols}; "
                    f"every row must have exactly {cols} cells."
                )
        row_count = len(data)
    else:
        if rows is None or rows < 1:
            return _error("Provide either data or rows >= 1.")
        row_count = rows

    try:
        new_table = _rebuild_table(reference, cols, data or [], header)
    except Exception as exc:  # pragma: no cover - defensive
        return _error(f"Failed to clone reference table markup: {exc}")

    style_match = re.search(r'<w:tblStyle w:val="([^"]+)"', new_table)
    style = style_match.group(1) if style_match else None

    # 4. Backup before mutating (unless the caller already did).
    backup_path: str | None = None
    if backup:
        from datetime import datetime

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = str(
            docx_path.with_name(f"{docx_path.name}.before_table_{stamp}.bak")
        )
        try:
            shutil.copy2(docx_path, backup_path)
        except OSError as exc:
            return _error(f"Could not create backup {backup_path!r}: {exc}")

    # 5. Splice the new table in after the anchor paragraph.
    offset = _anchor_offset(docx_path, anchor)
    if offset is None:
        return _error(
            f"Resolved anchor {anchor!r} is no longer present in the "
            "paragraph index. No mutation was made."
        )
    xml = _read_document_xml(docx_path)
    new_xml = xml[:offset] + new_table + xml[offset:]
    _write_document_xml(docx_path, new_xml)

    # 6. Validate the result.
    from csa_docx.validator import validate_docx

    validation = validate_docx(docx_path)

    with zipfile.ZipFile(docx_path) as archive:
        final_xml = archive.read("word/document.xml").decode("utf-8")
    table_count = len(re.findall(r"<w:tbl[^>]*>.*?</w:tbl>", final_xml, re.S))

    return {
        "status": "OK",
        "anchor": anchor,
        "anchor_text": anchor_info["text"],
        "cols": cols,
        "rows": row_count,
        "style": style,
        "table_xml": new_table,
        "table_count_after": table_count,
        "backup": backup_path,
        "validation": validation,
    }
