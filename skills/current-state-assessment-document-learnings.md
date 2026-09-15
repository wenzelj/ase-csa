# Current-State-Assessment-Document Agent Learnings

This append-only file captures reusable lessons learned while applying approved Current State Assessment changes to DOCX files.

Each entry should use this format:

```text
## YYYY-MM-DD - <short lesson title>

Context:
<section/document/task context>

Problem observed:
<what made the run harder, failed, or required special handling>

Cause:
<why it happened>

Improved approach:
<what the agent should do next time>

Validation:
<how to confirm the improved approach worked>
```

## 2026-09-14 - Initial learning log

Context:
Agent instruction update.

Problem observed:
Reusable operational lessons can be lost between section runs if they are only mentioned in chat or buried in a section change report.

Cause:
The implementation agent previously had no dedicated append-only place for run learnings.

Improved approach:
After each completed section task, record reusable lessons in this file and mention whether a lesson was added in the section `## Changes Report`.

Validation:
Confirm this file is updated when a run produces a reusable lesson, and confirm the section change report records either the lesson update or `No new reusable skill lesson identified`.

## 2026-09-14 - Back up the active DOCX before every edit run

Context:
Current-State-Assessment-Document Agent instruction update.

Problem observed:
A resumed section run may edit an existing working DOCX without first creating a fresh recovery point for that specific run.

Cause:
The previous backup wording focused on creating the initial working copy and treated later recovery copies as optional.

Improved approach:
Before any DOCX changes, create a timestamped backup of the exact DOCX that will be edited. This applies to first runs, resumed section runs, repair runs, and comment-only update runs.

Validation:
Confirm the backup exists, has a non-zero file size, and is recorded in the section `## Changes Report` before reporting completion.

## 2026-09-15 - Section 3 DOCX OOXML edit workflow

- Context: Applying approved Section 3 changes E-38 to E-68 to the IAMPS Current State Assessment working DOCX.
- Problem observed: The document-render helper could not run in this macOS-local environment because `pdf2image` and bundled LibreOffice/soffice were unavailable. `python-docx` was also unavailable, so package-level OOXML editing was required.
- Cause: The local Python environment lacked the document skill renderer dependencies and the DOCX had to be edited without high-level DOCX libraries.
- Corrected approach: Treat the DOCX as an OOXML package, preserve existing ZIP members, edit only `word/document.xml` and `word/comments.xml`, anchor table comments inside cell paragraphs, then validate with `unzip -t`, XML parsing, comment marker pairing, direct `w:tr` child checks, replacement text checks, and `textutil` conversion as a fallback openability signal.
- Validate next time: Confirm render dependencies before relying on render output. If unavailable, report render validation as blocked and include the fallback checks actually performed.

## 2026-09-15 - Section 4 region rebuild: splice at paragraph boundaries, verify balance

Context: Applying approved Section 4 changes E-69 to E-76 to the IAMPS Current State Assessment working DOCX.

Problem observed: A first edit attempt rebuilt the whole Section 4 paragraph region using a regex that matched the next Heading1 style occurrence. The match started mid-paragraph, leaving an orphaned closing paragraph tag at the section seam and producing a document.xml that failed XML parsing.

Cause: Region boundaries were derived from a style match inside a paragraph instead of from the start of the paragraph element, so the slice was not paragraph-aligned.

Improved approach:
- Identify the region by exact paragraph identity (find the unique intro paragraph and the next section heading paragraph as full `<w:p>...</w:p>` strings) and splice `xml[:start] + new_region + xml[heading_start:]`.
- Make sure the new region contains only complete paragraph elements and ends cleanly before the next heading paragraph.
- After every splice, verify well-formed XML and that paragraph open/self-closing/close counts are balanced and identical to the pre-edit file outside the region.

Validation:
XML parsing of word/document.xml, paragraph element balance check, comment marker pairing for the new comment IDs, scoped old/new text checks, and a full text comparison confirming changes only within the target section region all passed before repackaging.

## 2026-09-15 - Use bounded iterations for large sections

Context:
Agent instruction improvement after long CSA section runs sometimes reached the end of context or worked for a long time without producing a document change.

Problem observed:
Treating an entire section as one uninterrupted unit can make the agent spend too long planning, searching anchors, rendering, or recovering from compaction before it saves useful work.

Cause:
The previous workflow had section-level stopping rules but no edit-count batch size, time box, run-state checkpoint, or no-progress stop condition.

Improved approach:
For sections with more than 5 approved edit IDs, default to bounded iteration mode. Parse the full section, select the next safe batch, back up the active DOCX, apply only that batch, validate it, update the `## Changes Report`, and write `.agents/run-state/current-state-assessment-document-section-<SECTION>.md` with the next edit ID.

Validation:
Confirm every iteration writes durable evidence: backup path, working DOCX path, current edit IDs, completed edit IDs, validation result, next edit ID, and status. If no durable evidence changes during an iteration, stop with `NO_PROGRESS_STOP` rather than continuing indefinitely.

## 2026-09-15 - Prefer the reusable CSA DOCX framework for repeated edits

Context:
Created `.agents/framework/csa_docx/` to reduce repeated model reasoning during Current State Assessment DOCX implementation runs.

Problem observed:
The agent repeatedly spends time parsing approved Markdown change records, selecting edit batches, creating backups, editing Word XML, adding comments, validating comments, and writing reports.

Cause:
Those steps are deterministic workflow mechanics but were previously handled by the model each run.

Improved approach:
Before manual DOCX editing, use `.agents/framework/csa_docx/cli_apply_section.py` for simple insert, replace, and delete operations with unique paragraph anchors. Let the framework create backups, update run-state, add Word comments, validate the DOCX package, and update `## Changes Report`. Fall back to manual document-skill work only for complex range/table/style operations or framework `BLOCKED` results.

Validation:
Run the CLI on a temporary DOCX/change-file copy first. Confirm JSON status, backup path, report update, run-state update, comment ID consistency, XML parse checks, and table-row comment safety before using it on the real working DOCX.

## 2026-09-15 - Treat short cleaned Where values as anchors in the CSA framework

Context:
Section 5 bounded framework run, first batch E-77 to E-81.

Problem observed:
The framework blocked on E-77 because the Markdown parser cleaned backticks from a simple `Where` value, leaving only the anchor text without a keyword such as `beginning exactly`.

Cause:
Anchor extraction expected backticks, quotes, or recognised wording patterns after the parser had already normalised Markdown formatting.

Improved approach:
When `Where` is a short single-line value and no stronger pattern is found, treat that cleaned value as the anchor candidate. Still require exactly one matching paragraph before editing.

Validation:
Rerun the bounded framework batch and confirm it either applies E-77 using one unique match or blocks with an actual document match-count reason.

## 2026-09-15 - Do not preserve bullet numbering for prose replacements

Context:
Section 5 bounded framework run, E-80.

Problem observed:
A replacement paragraph rendered with an accidental bullet because the framework preserved the original paragraph's numbering properties while replacing it with approved prose text.

Cause:
The first framework replacement implementation preserved paragraph properties too broadly.

Improved approach:
When a replacement paragraph does not start as a Markdown list item, remove list numbering and list indentation from that paragraph during replacement. Preserve list numbering only when the approved replacement text is itself a list item.

Validation:
Render the affected page after replacement and confirm the paragraph appears as normal prose with no accidental bullet marker.

## 2026-09-15 - Framework must block complex range and table operations

Context:
Section 5 continuation after the first framework batch, covering E-82 to E-86.

Problem observed:
Several approved changes used wording such as `following bullets`, `heading and two introductory sentences`, and `row beginning`, which require scoped range or table-cell handling rather than a single paragraph replacement.

Cause:
The first framework version could safely handle simple unique paragraph operations, but complex instructions need structural context across neighbouring paragraphs or table cells.

Improved approach:
The framework now returns `BLOCKED` for complex range/table markers such as `following`, `through`, `all content`, `both paragraphs`, `row beginning`, `rows`, and `assessment wording`. The agent must then use controlled manual OOXML handling for that one batch, with comments anchored inside the changed paragraph or table cell.

Validation:
For complex batches, confirm the old range text is absent, approved replacement text is present, comments are anchored safely, `word/document.xml` and `word/comments.xml` parse, and no comment markers or runs are direct children of `w:tr`.

## 2026-09-15 - Patch run-state when framework Python cannot write `.agents`

Context:
Section 5 final batch E-92 to E-94.

Problem observed:
The reusable CSA framework failed before producing a structured status because Python could not write `.agents/run-state/current-state-assessment-document-section-5.md`, even though the same file could be updated with `apply_patch`.

Cause:
The workspace permission profile allowed patch-backed edits to the agent files, but direct Python file writes to the `.agents` run-state path returned `PermissionError: Operation not permitted`.

Improved approach:
When framework execution fails only at run-state/report persistence, do not keep retrying the same framework command. Continue with controlled manual DOCX OOXML edits for the selected batch, then update the change report, run-state, and learning notes using `apply_patch`.

Validation:
Confirm the DOCX package and comments validate, render the affected pages, and read back the report/run-state status after the patch-backed updates.

## 2026-09-15 - Make CLI and EVO runs stop after small batches

Context:
Running the Current-State-Assessment-Document Agent through `codex exec --profile evo-x3-qwen`.

Problem observed:
The agent can take too long and continue reasoning past the intended bounded iteration, especially when the local model is slower or context compaction occurs.

Cause:
The bounded iteration rule allowed batches of five edits and relied on general prose instructions to stop, which a CLI/local-model run may not follow consistently.

Improved approach:
Use a hard CLI/EVO execution contract: default to 3 edit IDs and 10 minutes, write run-state before mutation, make a verified backup, apply only the selected batch, validate, update the report, then stop immediately with the next edit ID and resume command.

Validation:
Read the agent definition and confirm the default limit is `ITERATION_EDIT_LIMIT=3`, `ITERATION_TIME_LIMIT_MINUTES=10`, and the CLI/EVO hard stop rules prohibit planning or starting the next batch after report/run-state updates.

## 2026-09-16 - Move repeated table and range edits into the framework

Context:
Framework upgrade for Codex EVO Qwen runs of the Current-State-Assessment-Document Agent.

Problem observed:
The agent still relied on LLM reasoning for table rows and paragraph range replacements even when the approved Markdown described deterministic operations.

Cause:
The framework deliberately blocked `row beginning`, multi-row table edits, and `replace the content beginning ... through ... with` range edits, forcing manual OOXML work for repeated patterns.

Improved approach:
The framework now handles labelled table row replacements for `Observed` and `Assessment`, multi-row table updates when approved text labels each row, and uniquely bounded paragraph range replacements. The agent and skill wrappers should treat the framework as the worker and use LLM reasoning only for framework blockers or invalid output.

Validation:
Unit tests passed with `7 passed`. A temp-copy smoke test applied Section 5 `E-92` to `E-94` from a pre-edit backup using the framework only, producing `SECTION_COMPLETE`, comments `92` to `94` by `Wenzel Joubert` / `WJ`, and passing DOCX archive, XML, comment consistency, and table-row comment safety checks.

## 2026-09-16 - Handle subsection body replacement in the framework

Context:
Framework upgrade after a Section 6 run blocked on an approved instruction to replace all content in a numbered subsection.

Problem observed:
The framework treated `Replace all content in Section X.Y.Z` as complex manual OOXML work, even when the target body was a simple paragraph range under one Word heading.

Cause:
The operation classifier blocked `all content` before trying to locate the unique `Where` anchor and infer the containing heading range.

Improved approach:
When the approved action says `Replace all content in Section X.Y.Z`, locate the unique `Where` anchor, find the previous Word heading, preserve that heading, replace body paragraphs up to the next same-or-higher heading, and add a Word comment to the first replacement paragraph. Keep returning `BLOCKED` if the anchor or heading range is ambiguous.

Validation:
Framework tests passed with `12 passed`. A temp-copy smoke test applied Section 6 `E-99`, produced `SECTION_COMPLETE`, added comment `99`, passed DOCX archive/XML/comment checks, removed the old subsection body, inserted the approved two replacement paragraphs, and preserved the next subsection heading.

## 2026-09-16 - Run the CSA framework under python3.14, not the default python3
Context: Section 6 bounded framework run (batch E-100 to E-101), framework-first mode.

Problem observed:
The first framework invocation crashed before doing any work with `TypeError: dataclass() got an unexpected keyword argument 'slots'` because the shell default `python3` resolved to Python 3.9.6, while the `csa_docx` modules use `@dataclass(slots=True)` (Python 3.10+).

Cause:
The `.pyc` cache is under `.agents/framework/csa_docx/__pycache__/*.cpython-314.pyc`, showing the framework was authored and run under Python 3.14. The interactive/terminal `python3` in this environment is the system 3.9.

Improved approach:
Invoking the framework via an explicit modern interpreter works. Use `python3.14 .agents/framework/csa_docx/cli_apply_section.py ...` (available at `/opt/homebrew/bin/python3.14`). Confirm the interpreter version first if the default `python3` is ambiguous, and do not retry the same failing `python3` command.

Validation:
Rerun the bounded framework batch under `python3.14`; confirm it returns a structured JSON status (e.g. `APPLIED` + `BLOCKED`), creates a verified timestamped backup, and passes the DOCX archive/XML/comment/table-row checks.

## 2026-09-16 - Handle pipe-format multi-cell table rows in the framework
Context: Section 6 E-101 blocked the framework: "Could not extract labelled table replacement values".

Problem observed:
E-101 specifies a two-row table replacement using the pipe format `**DNS Location |** value1 | value2`, where the first segment names the table row and the remaining segments are the cell values for that row. The framework only understood the `Label - Observed:` / `Label - Assessment:` labelled triple format, so it could not extract any values and blocked.

Cause:
`_extract_labeled_values` only matches the `<label> <field>:` line shape, while some approved change records describe table rows positionally with ` | ` separators. The actual table (3 columns: Aspect, Observed State, Evidence) means a row label plus exactly two values.

Improved approach:
Before trying the labelled-triple path, `_apply_table_row_change` now calls `_extract_pipe_row_replacements(text)` to collect `(label, values)` rows. `_apply_pipe_row_replacements` resolves each label uniquely against the first cell of every `w:tr`, and only proceeds if the row has exactly `len(values) + 1` cells — the label names cell 1 and the values fill cells 2..N. Any non-unique label or cell-count mismatch still returns `BLOCKED`.

Validation:
Two new tests (16 passing total): `test_extract_pipe_row_replacements` for the parser, and `test_replace_pipe_format_table_rows_like_e101` which builds a 5-row 3-column table and asserts both `DNS Location` and `Local DNS Services` rows are fully rewritten with one comment. The live rerun on the real DOCX applied E-101 (4 cells across 2 rows, comment ID 101) with archive/XML/comment/table-row-safety checks all passing.

## 2026-09-16 - Handle anchor plus following bullets in the framework

Context:
Framework upgrade after a Section 6 run blocked on an approved instruction to replace one sentence and its following bullets.

Problem observed:
The framework either had to block on `bullets` wording or risk replacing only the anchor paragraph while leaving the old following bullet paragraphs behind.

Cause:
The operation classifier did not have a deterministic range operation for `Replace this sentence and its N bullets`, and Word may store visible bullets as ordinary adjacent paragraphs.

Improved approach:
When the approved action says `Replace this sentence and its N bullets`, locate the unique anchor paragraph, select that paragraph plus the declared number of following non-empty content paragraphs before the next heading, replace the range with the approved Markdown paragraphs, and add one Word comment to the first replacement paragraph. Keep returning `BLOCKED` if the anchor is not unique or a heading appears before enough content paragraphs are found.

Validation:
Framework tests passed with `14 passed`. A temp-copy smoke test applied Section 6 `E-100`, produced `SECTION_COMPLETE`, added comment `100`, passed DOCX archive/XML/comment checks, removed the old sentence and first old bullet, inserted the approved replacement paragraphs as separate paragraphs, and preserved the following summary table content.
