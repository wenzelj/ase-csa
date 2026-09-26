---
name: csa-docx-create-table
description: Create a brand-new table in a CSA DOCX that matches the document's existing table styling, via cli_create_table.py. Use when an approved change adds a new table (glossary, acronyms, reference grid) - the change-file pipeline can only edit existing tables.
---

# CSA DOCX Create Table

Create a new table in a CSA DOCX that is visually indistinguishable from the
document's existing tables. Use this when a change requires adding a brand-new
table (e.g. a glossary, an acronym list, a small reference grid) — the
change-file pipeline (``cli_apply_section.py`` / ``apply_next_batch``) can only
edit *existing* tables, so new tables need this path.

**Note:** the example commands below use IAMPS's actual filenames and content (e.g. `Current State Assessment - IAMPS.docx`, an "IAMPS" glossary row) purely to illustrate real working syntax. When running this on another project, substitute that project's own working DOCX path and content -- do not literally reuse the IAMPS filename or row values.

## When to use

- The approved change record says "add a new table" or "insert a table for
  glossary / acronyms / reference data" at a specific heading.
- The target document already contains at least one styled table (this
  function clones its markup, so a table-less document will be blocked).
- You want the new table to use the document's own ``w:tblStyle``,
  ``w:tblLook`` banding flag, row ``cnfStyle`` banding, and cell markup
  (font, spacing, ``w:tcW`` widths) — not a hardcoded style.

## When not to use

- The change is to edit an *existing* table's cells or rows — use
  ``csa-change-authoring-agent`` / ``apply_next_batch`` instead.
- The target document has no tables at all — add one by hand first, then
  use this function for the rest.

## How to use

### Programmatic (preferred)

```python
from csa_docx.tools import create_table

result = create_table(
    "01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx",
    after="@H16",                          # or a live anchor like "P2139#2dbe"
    cols=2,
    data=[
        ["Term", "Definition"],
        ["IAMPS", "Integrated Airport Management and Planning System"],
        ["CSA", "Current State Assessment"],
    ],
    header=True,                           # row 0 uses the header-row markup
    backup=True,                           # default; creates a .bak next to the docx
)
assert result["status"] == "OK", result
```

### CLI

```bash
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_create_table.py \
    --docx "01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx" \
    --after @H16 \
    --cols 2 \
    --header "Term,Definition" \
    --row "IAMPS,Integrated Airport Management and Planning System" \
    --row "CSA,Current State Assessment"
```

Exit codes: ``0`` = OK, ``1`` = ERROR, ``2`` = BLOCKED (e.g. anchor not
found). The JSON result is printed on stdout.

## What the function does (in order)

1. **Resolves the anchor** via ``stable_ids.build_id_map`` +
   ``Document.paragraphs()``. Accepts a stable-ID (``@H16``) or a live
   anchor (``P2139#2dbe``). Refuses to guess when the anchor is ambiguous
   (returns ``BLOCKED``).
2. **Discovers the document's own table style** by scanning all existing
   ``<w:tbl>`` elements and picking the one whose column count best matches
   the new table's. No style name is hardcoded — if the document's style
   changes in the future, the new table still matches.
3. **Clones the reference table's markup**: ``<w:tblPr>`` verbatim (style +
   ``tblLook`` banding), ``<w:tblGrid>`` trimmed to the new column count,
   row 0 from the reference's header row (``firstRow=1`` ``cnfStyle``
   banding), subsequent rows from the reference's data row
   (``oddHBand``/``evenHBand`` banding). Each ``<w:tc>`` is cloned with its
   ``w:tcW`` (``type="pct"``), ``w:hideMark``, and ``<w:p>`` (Arial font,
   ``w:spacing``). Only the ``<w:t>`` text is replaced.
4. **Writes the new table** immediately after the resolved anchor paragraph
   (byte offset computed by ``docxengine._anchors.build_anchor_index``).
5. **Validates** the result with ``csa_docx.validator.validate_docx``
   (``archive_integrity``, ``xml_parse:*``, ``comment_id_consistency``,
   ``table_row_comment_safety``) and returns the result.

## Failure modes

- ``BLOCKED`` — the anchor is not a stable-ID or live anchor, or it resolves
  to a paragraph that no longer exists in the document.
- ``ERROR`` — the DOCX is missing, ``cols < 1``, ``data[i]`` has the wrong
  cell count, the document has no existing tables to clone, or the backup
  could not be created.

## Gotchas (learned from the glossary-table work)

- **The change-file pipeline has no "create table" op.** ``docx_table`` in
  the vendored engine only supports ``set_cells``, row/col insert/delete,
  ``style``, and ``delete``. New tables must be built directly via this
  module (or the raw ``Document.open(...).table("create", ...)`` API, but
  that produces a ``TableGrid``-style table that won't match the document's
  siblings).
- **Anchor by stable-ID or live anchor, not by text.** The heading text
  "Glossary and Acronyms" also appears in the cached TOC; a naive
  ``find("Glossary")`` can match the TOC entry instead of the real heading,
  and the next ``<w:tbl>`` after the TOC match is the wrong table. Always
  resolve via ``build_id_map`` (or a live ``P#hash`` anchor) to the exact
  paragraph ordinal.
- **DOCX is a ZIP — edit the ``word/document.xml`` member, not the file
  bytes.** ``Path.read_text`` on a ``.docx`` raises
  ``UnicodeDecodeError``. Read via ``zipfile``, modify the
  ``word/document.xml`` string, rewrite the whole zip preserving every other
  member's ``ZipInfo`` (this is what ``_write_document_xml`` does).
- **Comment markers must live inside ``w:tr -> w:tc -> w:p``**, never
  directly under ``w:tr``. The validator's ``table_row_comment_safety``
  check catches the unsafe form; Word will not open a document with the
  unsafe form. This function does not add comments, so it is safe by
  construction — but if you later add a comment to a cell, anchor it to the
  cell's paragraph, not the row.
- **Always back up before mutating.** The default ``backup=True`` creates a
  timestamped ``.bak`` next to the working DOCX. Only pass ``backup=False``
  if you have already taken a backup you intend to keep.
- **No hardcoded style names.** The function discovers the dominant
  ``w:tblStyle`` at run time. If the document's style changes (e.g. the
  template is regenerated), the new table still matches the siblings.

## Files

- Implementation: ``.agents/framework/csa_docx/tables.py`` (public entry
  :func:`csa_docx.tables.create_table`).
- Re-export: ``.agents/framework/csa_docx/tools.py``
  (:func:`csa_docx.tools.create_table`).
- CLI: ``.agents/framework/csa_docx/cli_create_table.py``.
- Validator: ``.agents/framework/csa_docx/validator.py``
  (:func:`csa_docx.validator.validate_docx`).

## Test

```bash
# Smoke test on a throwaway copy (never the live working DOCX):
cp "01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx" /tmp/t.docx
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_create_table.py \
    --docx /tmp/t.docx --after @H16 --cols 2 \
    --header "Term,Definition" --row "OT,Operational Technology"
# Expect: status OK, all validation Pass, table_count_after = (live count + 1).
rm -f /tmp/t.docx*
```
