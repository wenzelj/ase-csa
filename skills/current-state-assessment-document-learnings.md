# Current-State-Assessment-Document Agent Learnings (inbox)

Append-only inbox for reusable lessons from applying approved Current State Assessment changes to the DOCX. It is not a diary and not an issue tracker:

- Defects, blocked edits, mismatches and questions only Wenzel can answer are raised immediately in the run's response when found (see "Issue Escalation" in `current-state-assessment-document.md`), not filed here or in a register.
- A lesson stays here until Wenzel reviews it. Each one is then promoted (playbook rule, validator or test) or dropped, and its `Status` is updated.

The previous log (45 entries, 14-17 Sep 2026) was cleared on 2026-09-21. It is recoverable from git history (last commit touching this file: `3492f3b`) and summarised in `.agents/csa-document-learnings-assessment.md`.

Keep entries short and generic. No E-numbers, paragraph numbers or document wording unless needed as a one-line example.

Entry format:

```text
## YYYY-MM-DD - <short lesson title>

Type: lesson | environment-note
Scope: document | framework | environment
Status: new | promoted (-> where) | dropped
Trigger symptom: <error message or observable sign>
Action: <what to do next time>
Validation: <how to confirm it worked>
Related issue: <ISSUE-nnn or None>
```

## Entries

## 2026-09-21 - Do not trust a fixed run-state location or a self-reported "complete"

Type: lesson
Scope: framework
Status: new
Trigger symptom: a change file has a populated `## Changes Report` (SECTION_COMPLETE) but no run-state file exists for that section, or the run-state folder has moved or vanished
Action: before any apply run, compare the run-state file (beside the working DOCX) with the change file's Changes Report. If the report says complete and there is no run-state, stop and log an issue; do not let the framework treat the section as pending. Do not diagnose a block until this check is done.
Validation: `get_section_status` returns the expected status, and no edit ID is applied twice.
Related issue: ISSUE-006

## 2026-09-21 - Cross-check numbers across a record's inserted and renumbered rows

Type: lesson
Scope: document
Status: new
Trigger symptom: a Document Map or numbered list is renumbered by some edits and extended by others in the same change record
Action: list the final numbers the whole record produces and confirm they are unique and in heading order before approving or applying. Numbers taken from stable IDs (`@H16`) are not section numbers.
Validation: the final map has no duplicate numbers and matches the Heading 1 order.
Related issue: ISSUE-007

## 2026-09-21 - A successful CLI batch can still crash on the final print; verify by content, not by exit code

Type: lesson
Scope: framework
Status: new
Trigger symptom: cli_apply_section.py exits with an UnboundLocalError on `json.dumps` after the batch has applied (ISSUE-008)
Action: treat the DOCX itself as the source of truth - unzip and confirm the approved text is present, the comments carry the edit IDs, and the run-state and Changes Report exist. A traceback at the end of a run does not mean the batch failed. Also note that re-running the CLI on an already-complete section rewrites the run-state with a stale minimal copy (ISSUE-009); restore the run-state from the change-file report and the verified DOCX state if that happens.
Validation: the section's edit text and comments are present in word/document.xml and word/comments.xml, and the run-state lists the correct completed IDs and backup path.
Related issue: closed 2026-09-21 (cli json print crash; run-state clobber on re-run) - both fixed in the framework

## 2026-09-21 - Sections 4,6,7,8,9,10,13 applied in one framework-first run

Context:
After the full authoring pass (S1–S15 complete), applied all remaining pending edits: S4-E1..E4, S6-E1..E3, S7-E1, S8-E1, S9-E1, S10-E1/E2, S13-E1. Sections 1/2/3 were already applied in earlier runs; S5/S11/S12/S14/S15 were authored-and-clean (no edits).

Issue or risk observed:
The framework's table-row edit handler only supports replacing existing rows (S6-E3 @H7.3.4-T1-R5, S7-E1 @H8.3.5-T1-R4, S9-E1 @H10.3.3-T1-R4 all "Updated N table cell(s) across 1 row(s)"), not inserting new rows (see Section 3 S3-E4, which had to be applied manually). The docxengine CLI wrapper's final `print` previously crashed with a json UnboundLocalError after a successful batch (Section 2 note), but state + report were still written; in this run the CLI exited cleanly for every section.

Improved approach:
Framework-first with --engine docxengine (default) and default --track-changes worked cleanly for all seven sections in a single run; each batch produced a timestamped backup, updated the run-state, appended/updated the ## Changes Report, and printed a valid JSON summary with all validation checks Pass (archive integrity, XML parse, comment ID consistency, table_row_comment_safety). Table-row replacements (existing row) are supported; table-row INSERTION still requires a manual DocxEngine apply. Comment author/initials came through as Wenzel Joubert / WJ only (23 comments, balanced commentRangeStart/Reference, 27 tracked-change w:ins left for human accept/reject in Word).

Validation:
Final DOCX: unzip -t OK; comment authors = {Wenzel Joubert}; initials = {WJ}; 23 comments with balanced range start/reference; 27 tracked-change insertions. All per-section batches returned validation Pass. Backups present for each applied section (before_section_4/6/7/8/9/10/13). No BLOCKED, NO_PROGRESS_STOP, or validator failures this run.

## 2026-09-22: Reusable "create table that matches the document's own tables"

**What was added**

- `csa_docx/tables.py` — new module with `create_table(docx, *, after, rows=None,
  cols=2, data=None, header=True, backup=True) -> dict`. Resolves the anchor
  via `stable_ids.build_id_map` + `Document.paragraphs()`, discovers the
  document's own table style at run time (no hardcoded `w:tblStyle`), clones
  the reference table's `<w:tblPr>` / `<w:tblGrid>` / `<w:tr>` / `<w:tc>` /
  `<w:p>` markup, and splices the new table immediately after the resolved
  anchor paragraph. Runs `validate_docx` and returns the result.
- `csa_docx/tools.py` — re-export of `create_table` so the public API surface
  (this module) is the only thing callers need to import.
- `csa_docx/cli_create_table.py` — CLI wrapper with `--docx`, `--after`,
  `--cols`, `--header`, `--row` (repeatable), `--data` (JSON), `--no-backup`.
- `csa_docx/__init__.py` — `tables` added to `__all__`.
- `.agents/skills/csa-docx-create-table/SKILL.md` — thin skill documenting
  when/how to use, the gotchas, and a smoke test.

**Why it was needed**

The change-file pipeline (`cli_apply_section.py` / `apply_next_batch`) can
only edit *existing* tables (`set_cells`, row/col insert/delete, whole-table
content replacement). It has no "new table" operation. The glossary-table
work in Section 15 required a brand-new 2-column table with "Term" /
"Definition" headings and ~29 rows of term/definition pairs; the only way to
do it was to bypass the pipeline and build the table directly. Doing that by
hand produced a `TableGrid`-style table that looked different from the
document's 29 `GridTable4-Accent6` siblings, which had to be restyled by
stripping `<w:tcW>`, `<w:shd fill="D9D9D9"/>`, and stamping the dominant
`<w:tblStyle>` / `<w:tblLook>` — a manual, error-prone step that should not
have to be repeated.

**Key design choices (the "what I learned")**

1. **No hardcoded style names.** The function scans all existing `<w:tbl>`
   elements and picks the one whose column count best matches the new
   table's. It clones that table's `<w:tblPr>` verbatim (style + `tblLook`
   banding flag), trims the `<w:tblGrid>` to the new column count, and
   clones row 0 from the reference's header row (firstRow=1 cnfStyle banding)
   and subsequent rows from the reference's data row (oddHBand/evenHBand
   banding). Each `<w:tc>` is cloned with its `w:tcW type="pct"`,
   `w:hideMark`, and `<w:p>` (Arial font, `w:spacing after="200"
   line="276" lineRule="auto"`). Only the `<w:t>` text is replaced. If the
   document's style changes in the future, the new table still matches.
2. **Anchor by stable-ID or live anchor, not by text.** The heading text
   can also appear in the cached TOC; a naive `find("Glossary")` can match
   the TOC entry instead of the real heading. Always resolve via
   `build_id_map` (or a live `P#hash` anchor) to the exact paragraph
   ordinal.
3. **DOCX is a ZIP — edit the `word/document.xml` member, not the file
   bytes.** `Path.read_text` on a `.docx` raises `UnicodeDecodeError`.
   Read via `zipfile`, modify the `word/document.xml` string, rewrite the
   whole zip preserving every other member's `ZipInfo`.
4. **Comment markers must live inside `w:tr -> w:tc -> w:p`**, never
   directly under `w:tr`. The validator's `table_row_comment_safety` check
   catches the unsafe form; Word will not open a document with the unsafe
   form.
5. **Always back up before mutating.** Default `backup=True` creates a
   timestamped `.bak` next to the working DOCX.

**Verification (this session)**

- Smoke test on a throwaway copy of the working DOCX (`/tmp/csa_cli_test.docx`):
  `create_table(..., after="@H16", cols=2, data=[["Term","Definition"],
  ["IAMPS","Integrated Airport Management and Planning System"], ...])`
  returned `status: OK`, `style: GridTable4-Accent6`,
  `table_count_after: 31` (live doc was 30), and all validation checks
  `Pass` (`archive_integrity`, `xml_parse:*`, `comment_id_consistency`,
  `table_row_comment_safety`). `Document.open` succeeded and the new table
  landed immediately after the "Glossary and Acronyms" heading.
- The new table's `<w:tblPr>` is byte-identical in shape to the existing
  2-column tables (same `GridTable4-Accent6` style, same `tblLook` banding
  flags, same `cnfStyle` banding on rows, same Arial font, same `w:tcW
  type="pct"` widths).

**Limits**

- The function does not edit existing tables — that is still the
  change-file pipeline's job (`apply_next_batch`).
- The function does not add comments to the new table — anchor any
  subsequent comment to the cell's paragraph, not the row.
- The function requires at least one existing styled table in the document
  to clone from; a table-less document will be blocked.
