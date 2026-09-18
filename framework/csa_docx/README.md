# CSA DOCX Framework

Reusable helpers for applying approved Current State Assessment Markdown change records to Word `.docx` files.

The framework is intentionally conservative. It automates repeatable tasks and returns `BLOCKED` when an anchor, range, or edit instruction is ambiguous instead of guessing.

## Current Capabilities

- Parse approved Markdown change records into edit records.
- Select bounded edit batches by section and edit ID.
- Create verified timestamped DOCX backups.
- Inspect and edit `word/document.xml` in a DOCX package.
- Use the vendored open-source `docxengine` library by default for anchored paragraph, list, section-body, heading-bounded range, subsection-delete, paragraph-plus-following-line, and supported table-cell edits.
- Add Word comments with configured author and initials.
- Validate ZIP integrity, XML parseability, comment relationships, comment marker pairing, and unsafe direct table-row comment markers.
- Update `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/current-state-assessment-document-section-<SECTION>.md`.
- Append/update `## Changes Report` in the approved Markdown change file.
- Replace `Observed` and `Assessment` cells for uniquely matched table rows.
- Replace multi-row table values when the approved text labels each row, for example `Network Services - Observed`.
- Replace paragraph ranges described as `replace the content beginning ... through ... with`.
- Replace paragraph ranges described as `Replace this sentence and all bullets through: <end anchor>`.
- Replace heading-bounded ranges described as `Replace all content from this heading through the sentence ending: <end anchor>`.
- Replace all body content in a subsection when the approved instruction says `Replace all content in Section X.Y.Z`, the `Where` anchor is unique, and the containing Word heading range is unambiguous.
- Replace entire subsection bodies when the approved instruction says `Replace the entire subsection`.
- Replace an anchor paragraph and a fixed number of following bullet/content paragraphs when the approved instruction says `Replace this sentence and its N bullets`.
- Replace an anchor paragraph plus the following line when the approved instruction says `Replace this paragraph and the following line`.
- Delete a contiguous heading range when the approved instruction says `Delete Sections ... up to <next heading>`.
- Convert Markdown bullet lines into separate Word paragraphs instead of collapsing adjacent bullets into one paragraph.
- Convert multi-paragraph Markdown *blockquote* replacement text (the project's standard way of writing a multi-paragraph `**Text:**` field - every line, including blank separators, prefixed with `>`) into separate Word paragraphs, stripping the `>` markers instead of leaking them into the applied text. Fixed 2026-09-17: a bare `>` separator line is non-empty and previously defeated blank-line paragraph splitting in `markdown_to_paragraph_texts`, collapsing an entire multi-paragraph/bulleted blockquote into one corrupted paragraph containing literal `>` characters (found via E-146 and E-153 in Section 9; both were applied under the buggy code and were subsequently repaired in place).
- Scope a non-unique anchor to the correct subsection by heading name even when the change file's section label and the document's heading use different British/American spelling (for example "Synchronisation" vs "Synchronization") via `ooxml.spelling_normalised_text`.
- Replace an entire table's content (header and/or row labels included) when the approved instruction says `Replace the table content`, even when the approved text renames row labels and the approved caption text isn't literally present in the document. Locates the table via its caption when that caption matches uniquely, otherwise via being the single unambiguous table inside the section-heading-scoped range; overwrites every cell positionally with `docx_table set_cells` once dimensions are confirmed to match, and refuses (BLOCKS) rather than reshapes a table whose row/column count differs from the replacement.
- Resolve a labelled table-row lookup (Observed/Assessment value update) with a fuzzy match on the row label when no exact/prefix match exists, via the vendored `rapidfuzz` (falling back to the standard-library `difflib` if rapidfuzz's vendored wheel doesn't match the running platform), accepting only a clear, unambiguous best match.

## Example

```bash
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --engine docxengine \
  --section 4 \
  --change-file "7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section4_E69_E76.md" \
  --docx "7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx" \
  --limit 3 \
  --comment-author "Wenzel Joubert" \
  --comment-initials "WJ"
```

The framework defaults to DocxEngine. The explicit engine flag is still shown here for clarity:

```bash
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --engine docxengine \
  --section 6 \
  --change-file "7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section6_E95_E111.md" \
  --docx "7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx" \
  --limit 1 \
  --start-edit-id E-100 \
  --end-edit-id E-100
```

## Safety Model

The framework only edits the active working DOCX passed with `--docx`. It creates a `.bak` backup before mutation. It does not create new document versions by itself.

Supported edit operations are deliberately narrow:

- Insert before/after a uniquely matched paragraph anchor.
- Replace a uniquely matched paragraph anchor with approved text.
- Delete a uniquely matched paragraph anchor.
- Replace labelled table-row `Observed` and `Assessment` values through DocxEngine table cell writes.
- Replace labelled multi-row table values through DocxEngine table cell writes.
- Replace a uniquely bounded paragraph range with approved paragraphs or bullets.
- Replace a uniquely bounded sentence-plus-bullets range ending at an approved final bullet anchor.
- Replace all content below a containing subsection heading while preserving that heading and the next same-or-higher heading.
- Replace an anchor paragraph plus a declared number of following bullet/content paragraphs, stopping safely if a heading is encountered too early.

Unsupported, ambiguous, or non-unique operations are reported as `BLOCKED` instead of guessed. A blocker should now mean a real document or instruction ambiguity, not an unrecognised wording variant.

Use DocxEngine for paragraph, list, range, subsection-body, subsection-delete, paragraph-plus-following-line, and supported table-cell operations. Use `--engine legacy` only when explicitly testing or recovering an older legacy path.

## Vendored Third-Party Libraries

Alongside `docxengine`, `framework/vendor/` also carries:

- `mistune` (pure Python, MIT) - parses approved replacement Markdown tables for the whole-table-replace capability, instead of a hand-rolled pipe-table regex.
- `rapidfuzz` (MIT) - fuzzy row-label matching for the labelled table-row lookup. Vendored as a wheel built for the Mac's `/opt/homebrew/bin/python3.14` (macOS arm64, cp314); the adapter falls back to `difflib` if that wheel doesn't import on whatever interpreter actually runs it.

Both were fetched by running `python3.14 -m pip download <package> --no-deps -d .` on the Mac (network access to PyPI is not available from every environment this framework may run in) and unpacked directly into `framework/vendor/` the same way the `docxengine` wheel is - no system-wide `pip install` required on any machine that runs this framework.
