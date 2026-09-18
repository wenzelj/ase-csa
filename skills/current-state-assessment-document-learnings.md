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

## 2026-09-16 - Bullet-count wording with filler words blocked E-103

Context:
Section 6 batch E-103/E-104, framework-first run. The approved action is `Replace all three finding bullets.` in 6.3.1.

Problem observed:
The framework returned `BLOCKED - Complex range or table operation requires controlled manual OOXML handling`. `_extract_following_bullet_count()` only matches a count immediately before "bullets" (e.g. `its three bullets`), so `three finding bullets` failed to parse and the record fell into the blanket `bullets` conservative block.

Cause:
The count regex `(\d+|one|two|three...)\s+(?:sub-)?bullets?` does not allow filler words between the count and the word "bullets".

Improved approach:
Allow zero to two filler content words between the count and "bullets" (e.g. `three finding bullets`, `two sub-bullets`) so the counted-bullet-block path can route the edit. In `_apply_counted_bullet_block`, the existing guard that the replacement line count must equal the existing bullet count (3 for 3) is what makes E-103 safe; keep that guard, and verify every block paragraph shares the anchor's numId and list level, and that any following deeper-level sub-list (the pending E-104 sub-bullets) is left untouched.

Validation:
Manual repair applied E-103 (3 bullets replaced in 6.3.1, comment ID 103, ListParagraph/numId 142 preserved, E-104 sub-bullets intact) with all archive/XML/comment checks passing. After the regex fix, rerun the framework test suite and add a unit test asserting `_extract_following_bullet_count("Replace all three finding bullets.") == 3`.

## 2026-09-16 - "through ... ending with" range word tripped the framework conservative block (E-112)

Context:
Section 7 batch E-112/E-113, framework-first run. The approved action was `Replace the introductory text through the bullets ending with: <end anchor>`.

Problem observed:
The framework returned `BLOCKED - Complex range or table operation requires controlled manual OOXML handling`. `_has_range_replacement` requires the exact trigger `replace the content beginning` + ` through ` + ` with:`, so the "through the bullets ending with" wording fell into the blanket `through`/`bullets` conservative block instead of the (safe) `_apply_range_replacement` path.

Cause:
The range-spec regex `_extract_range_spec` only recognises one specific sentence shape, while the change file used a semantically equivalent but differently phrased range instruction.

Improved approach:
Before manual repair, prove the range is safe and bounded: confirm both start and end anchors match exactly one paragraph each (`_unique_paragraph_index`), end index > start index, and no heading or table paragraph lies inside the span. Then reuse the framework's own primitives (`_replace_paragraph_range`, `markdown_to_paragraph_texts`, `add_comment`, framework backup + `validate_docx`) in a small script instead of hand-rolling OOXML. This keeps the comment format, range mechanics, and validation identical to a framework run.

Validation:
Manual repair applied E-112 (8 source paragraphs - 1 intro + 7 bullets - replaced by 3 approved body paragraphs at 7.0 Introduction, no heading/table in span; comment ID 113, author Wenzel Joubert/WJ), with all 7 archive/XML/comment checks passing and the old anchor text confirmed gone from the document. The following Heading-2 "Design and functionality expected" (target of E-113) was untouched.

## 2026-09-16 - Non-unique anchor with repeated heading title tripped the framework (E-113)

Context:
Section 7 batch E-113, framework-first run. Approved action `Replace this sentence and its three bullets.` at `Where: Section 7.1, sentence beginning exactly: This indicates:`.

Problem observed:
The framework returned `BLOCKED - Anchor match count was 2; expected 1` for the anchor `This indicates:`. The anchor phrase appears multiple times across the document because the document reuses the same H2 heading title "Design and functionality expected" under many different H1 sections (Architectural Review, DNS, Identity & Authentication, Network, Time Synchronization, Security Controls, Operations Monitoring, Patch & Lifecycle, Backup & Recovery, Infrastructure Dependencies), and several of those subsections open their findings with the literal lead line `This indicates:`.

Cause:
`_unique_paragraph_index` requires exactly one matching paragraph for the anchor. `This indicates:` is a generic, non-unique sentence that legitimately recurs, so uniqueness by anchor text alone is impossible. The framework correctly refused rather than guess.

Improved approach:
When a framework-reported anchor is non-unique and lives in a repeated-heading environment, disambiguate deterministically by section identity, not by rewording blind or by picking a match by hand:
- List every heading in the document and its parent H1, so each `Where: Section X.Y` maps to an exact heading paragraph index (here: H1 "Identity & Authentication" → H2 "Design and functionality expected").
- Disambiguate the candidate anchor by the nearest preceding H1 + H2 heading pair (the change file's stated section) AND by the structural fact in the `Do` (this one had exactly 3 level-0 bullets following, while the other `This indicates:` instances had 1 or 2).
- Prefer an in-place text swap (`_set_paragraph_text(..., preserve_list=True)` for the bullets, `preserve_list=False` for the lead) over `_replace_paragraph_range`, so each paragraph keeps its own pPr/numId bullet structure and count — this both preserves list rendering and avoids a heading/table inside-span check becoming necessary.
- Anchor the Word comment on the first new paragraph as usual; reuse framework backup + `validate_docx` + `parse_change_records` so the result is identical in format to a framework run.

Validation:
Manual repair applied E-113 (the `This indicates:` + 3 bullets in the Identity & Authentication / "Design and functionality expected" subsection replaced by `The design documentation indicates that:` + 3 approved bullets; list structure preserved; comment ID 114, author Wenzel Joubert/WJ), with all 7 archive/XML/comment checks passing, the old 3-bullet set confirmed gone from the document, and the neighbouring heading and following "Observed Configuration and Functionality" subsection untouched.

## 2026-09-16 - "through <end sentence." range without `content beginning` wording blocked, then manually repaired (E-123)

Context:
Section 7 batch, framework-first run. E-123 approved action: `Replace the first two paragraphs through "fallback authentication."` in Section 7.3.2 Drawbridge Impact (Evidence-Based).

Problem observed:
The framework returned `BLOCKED - Complex range or table operation requires controlled manual OOXML handling`. `_has_range_replacement` only recognises the exact trigger phrase `replace the content beginning` + `through` + `with:`, so `Replace the first two paragraphs through "<end>"` fell into the blanket conservative `through` block.

Cause:
A second, equivalent range-instruction shape (`the first N paragraphs through "<end sentence>"`) is not classified by the range regex `_extract_range_spec`.

Improved approach:
Same safe-repair procedure as E-112: prove the span is bounded (both anchors match exactly one paragraph, end index > start index, no heading or table paragraph inside the span), then reuse the framework's own primitives (`_matching_paragraphs`, `_replace_paragraph_range`, `markdown_to_paragraph_texts`, framework backup + `validate_docx`, `write_state` + `update_changes_report`) in a small script (`.agents/framework/csa_docx/manual_e123.py`) instead of hand-rolling OOXML. Verify afterwards that an identical phrase may legitimately appear elsewhere in the document (e.g. the 7.3 intro retains "all IAMPS servers are domain joined" under another edit's scope) — confirm the removed text is gone from the target span rather than from the whole document.

Validation:
Manual E-123 run replaced exactly 2 paragraphs (range 1411..1412, no heading/table in span), inserted the two approved replacement paragraphs verbatim, added comment ID 124 by Wenzel Joubert/WJ with matched commentRangeStart/End/Reference markers, and passed all 7 DOCX validators (archive integrity, XML parse, comment ID consistency, table-row comment safety). Run-state updated to PARTIAL_COMPLETE with next edit E-124.

## 2026-09-16 - Use DocxEngine for anchored paragraph/list DOCX operations

Context:
The custom OOXML framework became brittle around bullet replacements, split Word runs, and comment wiring. The framework now vendors the open-source `docxengine==1.0.0` package under `.agents/framework/vendor` and exposes it through `--engine docxengine`.

Problem observed:
Direct OOXML edits force the framework to reimplement document anchoring, list handling, comment ranges, package relationships, and validation. This made repeated section work slower than it should be and increased the chance of small XML mistakes.

Improved approach:
Keep the CSA Markdown parser, batching, backups, run-state, and change-report writer as the controller. Delegate supported paragraph/list mutations to DocxEngine through `.agents/framework/csa_docx/engines/docxengine_adapter.py`. Use `--engine docxengine` for simple paragraph insert/replace/delete and `Replace this sentence and its N bullets`. Continue using the legacy engine for table-row edits, explicit through-ranges, and full subsection replacement until those paths are migrated and smoke-tested.

Validation:
Framework tests passed with `16 passed`. A temp-copy smoke test applied Section 6 `E-100` using `--engine docxengine`, made a backup, returned `SECTION_COMPLETE`, added comment `C100` by `Wenzel Joubert`, passed all archive/XML/comment validators, removed the old anchor paragraph, and inserted the approved intro, two list paragraphs, and closing paragraph. A namespace guard was added because DocxEngine can add `w14:paraId` to an existing `comments.xml`; the guard ensures `xmlns:w14` is declared before adding a comment.

## 2026-09-17 - Expand DocxEngine coverage for Section 7 range and subsection operations

Context:
Section 7 remaining edits E-124 through E-128 exposed operation shapes that the legacy framework classified as complex range/table operations even though they are deterministic paragraph-range tasks.

Problem observed:
E-124 blocked on `Replace all content from this heading through the sentence ending`. E-125 and E-126 required full subsection-body replacement. E-127 required deleting a heading range up to the next `Drawing` heading. E-128 required replacing a paragraph and its following line. These are reusable CSA edit shapes and should not require manual OOXML each time.

Improved approach:
Use `--engine docxengine` for non-table paragraph/range operations. The DocxEngine adapter now supports explicit through-ranges, heading-to-ending-sentence ranges, subsection body replacement, paragraph plus following line replacement, and delete-sections-up-to-heading operations. Keep the legacy engine for table-row edits.

Validation:
Framework tests passed with `17 passed` before the change and `18 passed` after adding Section 7 operation-shape tests. A temp-copy smoke test from the pre-E124 Section 7 backup applied E-124, E-125, E-126, E-127, and E-128 using `--engine docxengine`, returned `SECTION_COMPLETE`, added comments C125-C129 by `Wenzel Joubert`, and passed archive/XML/comment/table-row safety validation. The live DOCX was not mutated during the smoke test.

## 2026-09-17 - Use DocxEngine table cell writes for supported CSA table edits

Context:
The framework already handled CSA table-row edits through the legacy XML engine, but `--engine docxengine` still blocked any record mentioning a table or `row beginning`.

Problem observed:
DocxEngine has table support (`set_cells`, insert/delete row or column, merge, style), but it addresses cells by table anchor and row/column coordinates. CSA change records describe tables by row labels and fields such as `Observed`, `Assessment`, or pipe-format row replacements, so a CSA mapping layer is still required.

Cause:
The earlier DocxEngine adapter delegated paragraph/range/list operations but had no row-label resolver, no column resolver, and no safe table-cell comment helper. Comments for table changes must be anchored inside a cell paragraph, never directly under `w:tr`.

Improved approach:
Resolve CSA table rows by reconstructing first-cell text, map supported fields to table columns, then call DocxEngine `table("set_cells", anchor="Tn", cells=[...])`. Add the Word comment with package-level OOXML inside the first changed cell paragraph and then run the normal comment-ID and table-row-comment-safety validators. Keep returning `BLOCKED` for ambiguous row labels, cell-count mismatches, unsupported fields, or unsupported operation shapes.

Validation:
Framework tests passed with `20 passed`. New tests cover DocxEngine pipe-format multi-row replacement and labelled `Observed`/`Assessment` table-cell replacement against an actual `.docx` package, including comment ID consistency and table-row comment safety checks.

## 2026-09-17 - Treat equivalent CSA range wording as framework-supported

Context:
Section 8 E-129 blocked with the old generic message `Complex range or table operation requires controlled manual OOXML handling`.

Problem observed:
The approved record was deterministic: it supplied a `Where` start anchor, a `Do` instruction saying `Replace the introductory text through the bullets ending with`, an explicit end anchor, and replacement text. The framework blocked only because the parser recognised narrower range phrases such as `replace the content beginning ... through ... with` and `Replace this sentence and all bullets through`.

Cause:
The classifier was too phrase-specific. The document operation was standard bounded range replacement, but the parser treated equivalent wording as unsupported.

Improved approach:
Range classification should prefer structural intent over one exact phrase. If a record contains a unique `Where` anchor, a `through ... ending with` end anchor, and a `Text` replacement block, route it to the range replacement engine and let normal uniqueness checks decide whether it is safe.

Validation:
Added a regression test for the E-129 wording. Framework tests passed with `21 passed`.

## 2026-09-17 - Stop letting legacy classifier drive normal framework runs

Context:
After adding DocxEngine support, normal framework runs could still default to the older legacy engine unless `--engine docxengine` was passed explicitly.

Problem observed:
The legacy engine contains older defensive phrase blockers such as `following`, `through`, `bullets`, and `assessment wording`. Those blockers were useful before DocxEngine coverage improved, but they now create artificial `BLOCKED` results for standard CSA edits that DocxEngine can handle.

Cause:
The framework mixed two responsibilities: transaction safety and edit interpretation. Transaction safety is still valuable, but the old edit interpreter should no longer be the default path.

Improved approach:
Default the CLI to DocxEngine. Treat legacy as an explicit recovery/testing path only. Keep parser logic structural where possible: classify edits by extracted anchors, ranges, replacement text, row labels and table coordinates rather than exact wording variants.

Validation:
Framework tests passed with `21 passed` after switching the CLI default to `docxengine` and replacing the range phrase list with a generic `Where` + `Do through` + `Text` parser.

## 2026-09-17 - E-140 non-standard disambiguation: start anchor duplicated across subsections

Context:
Section 8, E-140 bounded range replacement. Start anchor "While the design defines a segmented architecture with controlled conduits" appears in BOTH 8.3.1 Findings (para ~1525) and 8.3 Assessment (para ~1562); end anchor "Availability of externally hosted services" is unique (para ~1530). The docxengine adapter's range path correctly refuses the ambiguous start -> "Range boundaries not unique or out of order" -> BLOCKED.

Problem observed:
Framework blocks the edit because the start sentence is non-unique AND the naive disambiguation (candidate whose section region contains the end anchor) matched BOTH subsections, because the first match's section region also spanned the second candidate.

Cause:
The first start candidate's enclosing section end (1531) was past the end anchor (1530), so a loose "end <= section_end" test accepted both. The distinguishing fact is that the end anchor must sit AFTER the candidate's own heading AND before that section's end.

Improved approach:
User instruction: "if this is due to non standard disambiguation then just fix the document." Use a manual OOXML range script (pattern: manual_e140.py) that disambiguates by choosing (and verifying uniqueness of) the start candidate whose enclosing heading body satisfies h_index < s < end_index <= section_end. This isolated 8.3.1 Findings. Then: create_backup -> find range -> assert no heading inside -> DocumentEditor._replace_paragraph_range(old_range, markdown_to_paragraph_texts(record.text), record, author, initials, add_new_comment=True) -> validate -> update run-state + report. Dry-run every time; abort on any non-unique/containment/ordering violation. The 8.3 Assessment copy of the sentence is left untouched and preserved.

Validation:
After the run the new two-paragraph text appears once (para 749/750), all four old bullets/lines are gone, the start sentence now appears exactly once (the 8.3 Assessment duplicate at 8.3 remains), comment id=140 is present in word/comments.xml, and all 7 validators Pass.

## 2026-09-17 - Subsumed-edit reconciliation: one edit's target already removed by a prior 'replace entire subsection'

Context:
Section 8 final edit E-145 (Delete: 'This represents a key architectural gap when assessed against OT 3.5 principles, where:' + its 3 bullets, in 8.3.4 Assessment). Framework returned BLOCKED 'Anchor match count was 0; expected 1'.

Problem observed:
The anchor simply does not exist in the live document - it is not a disambiguation issue and not recoverable by retry.

Cause:
The previously-run E-144 approved action was 'Replace the entire subsection' for the same 8.3.4 Assessment subsection. E-145's target paragraph + bullets lived inside that subsection, so E-144's subsection replacement already deleted them. Two change-file edits overlapped in the same body.

Improved approach:
When a delete/replace edit blocks with 'Anchor match count was 0', check whether a sibling edit's 'replace entire subsection/section' already consumed the target. Verify in the live DOCX that (a) the prior edit's approved text is present and (b) the blocked edit's target is absent. If the approved effect is already achieved, reconcile run-state + change report to SECTION_COMPLETE (mark the edit SUBSUMED/NO-OP), clear Blocked and Next edit ID, and do NOT touch the DOCX (re-running would just add no-ops or comments). Use the framework's own write_state + update_changes_report so format stays consistent.

Validation:
After reconciliation: run-state Status=SECTION_COMPLETE, next=None, Blocked=None, 17/17 completed; live DOCX mtime unchanged (no mutation); DOCX contains the 3 approved E-144 paragraphs and zero matches for E-145's target/bullets; all 7 validators Pass.

## 2026-09-17 - E-149 heading-scope disambiguation defeated by British/American spelling mismatch

Context:
Section 9, E-149 (Correct the "domain-based time synchronisation" conclusion, Section 9.2.2). Anchor phrase "This confirms:" is a template phrase reused as the conclusion sentence for 4 different "Observed Behaviour"/"Operating System"/"Domain and Infrastructure Integration"/"Application Platform Components" subsections across the document (under two different H1s: Time Synchronization, and Infrastructure Dependencies). Framework returned BLOCKED 'Section body anchor match count was 4; expected 1'.

Problem observed:
DocxEngineEditor._scope_matches already disambiguates a non-unique anchor by narrowing to paragraphs inside the heading named in self.section_heading, but heading_indexes came back empty, so scoping silently fell through and returned all 4 unscoped matches.

Cause:
self.section_heading is derived from the change file's `Section: 9 - Time Synchronisation` label (Australian/British spelling), but the document's actual H1 heading is `Time Synchronization` (American spelling). `self.section_heading in normalise_text(paragraph.text)` is a plain substring check with no spelling normalisation, so "Time Synchronisation" never matches "Time Synchronization" and heading_indexes is always empty for this section - the same class of failure would hit any other -isation/-ization, -ise/-ize heading pair in later sections.

Improved approach:
Added `spelling_normalised_text()` to ooxml.py (normalise_text + regex substitution of -isation/-isable/-ising/-ised/-iser to the American -ization/-izable/-izing/-ized/-izer forms) and applied it to both sides of the heading-name comparison in DocxEngineEditor._scope_matches (framework/csa_docx/engines/docxengine_adapter.py). This is additive/normalisation-only - it does not touch approved edit text, the DOCX, or any change file.

Validation:
After the fix, DocxEngineEditor(docx, section_heading="Time Synchronisation")._matching_paragraphs("This confirms:", ...) returns exactly 1 match (P815, under Time Synchronization > Observed Configuration and Functionality > Observed Behaviour). Framework re-run applied E-149 cleanly (comment C148, all 7 validators Pass). Regression check: re-running with an unrelated section_heading ("Infrastructure Dependencies") still correctly scopes to its own 3 matches, and no section_heading still returns all 4 matches unscoped, exactly as before the fix.

## 2026-09-17 - E-150 table-row lookup has no location scope and assumes stable row labels; approved "Where" caption not present in target section

Context:
Section 9, E-150 (Correct the Summary of Observed State table, Section 9.2.2, Do: "Replace the table content"). Framework returned BLOCKED 'Table row anchor not unique or not found: Time Sources'.

Problem observed:
Two separate gaps surfaced. (1) DocxEngineEditor._find_unique_table_row searches every table in the whole document for a row whose first cell matches the label, with zero use of self.section_heading - unlike the paragraph path, there is no location scoping for tables at all. (2) The approved replacement text uses NEW row labels ("Time Sources", "Source Namespace", "Local NTP Service") that differ from the CURRENT document's row labels in the target table ("Time Source", "Time Domain", "Local NTP") - `_apply_pipe_row_replacements` looks up rows by matching the label in the new text against the existing document, which cannot work when the edit is renaming labels as part of "replace the table content" rather than updating values under a stable label.

Separately, the approved `Where` locator ("table beginning exactly: `Summary of Observed State`") does not exist anywhere in Section 9 - `docx_search` finds that exact phrase only twice in the whole document (P543 "Local DNS Capability", P638 "Local Authentication Capability"), both unrelated sections. The actual Section 9.2.2 table (T27, 5x3, positioned directly after P817 with no caption paragraph at all) is the evidently-intended target by section/content match, but nothing in the document literally reads "Summary of Observed State" there.

Cause:
`_apply_table_row_change`/`_find_unique_table_row` was designed for the narrower "update Observed/Assessment values under an existing, stable row label" case (see the 2026-09-15/16 entries on labelled table-row replacement) and was never extended with (a) section-heading scoping like `_scope_matches`, or (b) a "whole table content replacement, addressed by a preceding caption/heading rather than by row label" mode. E-150 needs the latter, and the specific caption text named in `Where` is not present in this section - it reads like a generic template caption reused across the change record's review passes for "this kind of table," not literal document text for 9.2.2.

Improved approach:
Did NOT guess. Per the agent's Anchor Mismatch Rule, a locator that cannot be found in the target section (0 matches) must not be resolved by inferring the "obviously correct" table from context, even when that inference (T27) looks highly likely - that is independent reinterpretation, not execution of an approved instruction. Left E-150 BLOCKED and stopped the batch there (the framework's own break-on-first-block behaviour already does this correctly - it is not a bug that it stopped). This is flagged for human review rather than the framework being extended blindly under pressure to unblock one edit: (a) whether to reissue/correct E-150's `Where` field to reference the correct table by a locator that actually exists in Section 9.2.2 (there is no caption paragraph to quote - the preceding sentence would need to serve as the locator instead), and separately (b) whether a general "replace whole table content: locate the table via the paragraph immediately before it (or a table index), dimension-check against the replacement, then overwrite every cell positionally via `docx_table set_cells` instead of by row-label lookup" mode is worth adding to the framework - it would help here and for any future table edit that renames row labels, but deserves its own scoped review rather than a fix rushed under one BLOCKED edit.

Validation:
`doc.search("Summary of Observed State")` -> 2 matches, neither in Section 9. `_table_rows()` confirms the live table's current row labels are "Time Source" (singular)/"Time Domain"/"Local NTP"/"Alternate Sources", not the new labels in the approved Text. No document or framework code changed for E-150; DOCX untouched beyond E-149's already-applied change.

## 2026-09-17 - Running this framework via the Cowork device-bridge (Linux VM) instead of the Mac Terminal

Context: This run executed through `device_bash` (the Cowork desktop bridge's isolated Linux VM with the IAMPS folder mounted), not a Terminal session on Wenzel's Mac.

Findings:
- `/opt/homebrew/bin/python3.14` (the interpreter this agent definition hardcodes) does not exist in that Linux VM - it only has Python 3.10.12, and even plain `import docxengine` fails there with `ImportError: cannot import name 'UTC' from 'datetime'` (`datetime.UTC` was added in Python 3.11; DocxEngine 1.0.0 declares `Requires-Python: >=3.12`).
- Workaround used for this run only (not a framework code change): inject `datetime.UTC = datetime.timezone.utc` before importing docxengine, then invoke `cli_apply_section.py` via `runpy.run_path` with `sys.argv` set. This got DocxEngine's tool surface working far enough to apply E-149 successfully and validate cleanly; no other 3.10-incompatibility surfaced in this run, but the workspace has not been fully exercised on 3.10 this way and a subtler incompatibility elsewhere in DocxEngine remains possible.
- `Path(...).resolve()` inside that VM resolves the mounted folder to a bridge-internal path (`/sessions/<session-id>/mnt/06 IAMPS/...`) rather than the real Mac path (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/...`). The framework writes these resolved paths verbatim into run-state and the change file's Changes Report, so a batch run this way needs those written paths corrected back to the real Mac path afterwards (done manually for Section 9 this run) or a future run from the Mac Terminal will not recognise its own prior run-state paths.
- No sudo, no apt python3.12, and outbound network is allowlist-blocked in that VM (`uv` is present but can't reach a python-build source), so installing a proper Python 3.12+ interpreter there isn't currently possible - the datetime shim is the only option when running this framework from Cowork rather than the Mac.

Recommendation: when running this agent from Cowork's device bridge, keep using the Python-version shim above, and always normalise any `/sessions/.../mnt/...` paths in run-state/change-report output back to the real workspace path before treating a batch run as complete.

## 2026-09-17 - E-150 unblocked: added a whole-table-replace capability using vendored mistune + rapidfuzz instead of more hand-rolled matching code

Context:
Following on from the E-150 diagnosis above (BLOCKED: `Where` caption "Summary of Observed State" not present in Section 9, and the approved replacement renames row labels the existing row-label lookup can't match). User asked for the framework's table capability to be fixed generally, and specifically asked for an open-source library to do the table work rather than more bespoke matching code.

Cause (recap):
`_apply_table_row_change`/`_find_unique_table_row`/`_apply_pipe_row_replacements` were built for "update Observed/Assessment values under a stable, unchanged row label" and had no way to (a) locate a table when its stated caption isn't literal document text, or (b) handle a wholesale content replacement where row labels themselves change between old and new.

Improved approach:
User fetched two dependency-free open-source wheels on the Mac (`python3.14 -m pip download <pkg> --no-deps -d .`) since this session's own network access is allowlist-blocked; vendored both into `framework/vendor/` exactly like `docxengine` (unzip the wheel in place - no system pip install needed):
- `mistune` (pure Python) - added `_parse_markdown_table()` in docxengine_adapter.py, using `mistune.create_markdown(renderer=None, plugins=["table"])` and walking the `table`/`table_head`/`table_body`/`table_row`/`table_cell` AST (with a small recursive inline-text extractor for `text`/`codespan`/`linebreak` nodes) to turn the approved replacement Markdown table into `list[list[str]]`. Replaces what would otherwise have been a second hand-rolled pipe-table regex parser.
- `rapidfuzz` - added `_label_similarity()` (rapidfuzz `fuzz.ratio`, falling back to stdlib `difflib.SequenceMatcher` if rapidfuzz's vendored wheel - built for the Mac's python3.14 arm64 - doesn't import on whatever interpreter actually runs it) and used it as a fallback tier inside `_find_unique_table_row`: only when there is zero exact/prefix match anywhere, score every row's label against the wanted label, and accept the best match only if it clears `_FUZZY_ROW_LABEL_THRESHOLD=85` AND leads the second-best by `_FUZZY_ROW_LABEL_MARGIN=10` - a genuinely ambiguous or low-confidence result still returns `None` (BLOCKED), never a guess. (Ran a live sanity check first: `fuzz.ratio("Time Domain", "Source Namespace")` = 29.6 vs `fuzz.ratio("Time Source", "Time Sources")` = 95.7 - confirms fuzzy label matching alone would NOT have correctly mapped "Time Domain"->"Source Namespace" for E-150, which is why that pair needed the new positional whole-table-replace path below, not a smarter fuzzy row-matcher.)

New capability - whole-table replace (`_has_full_table_replacement`/`_apply_full_table_replacement`/`_locate_table_for_replacement` in docxengine_adapter.py, `_has_full_table_replacement` in ooxml.py): triggers when the approved `Do:` says "Replace the table content" (a wholesale replacement, not a per-row keyed update, so this deliberately does NOT try to match old row labels to new ones at all):
1. Locate the table: try the approved caption via the existing `_matching_paragraphs` (heading-scoped) - if it matches exactly one paragraph, use the table immediately after it (`_first_table_after`, via `docxengine.build_anchor_index`). If the caption isn't literal document text (0 matches - as for E-150), fall back to "the single unambiguous table inside the section-heading-scoped paragraph range" (`_section_paragraph_bounds` + `_tables_in_section`, both new, using the same heading-detection helpers `_is_heading`/`_heading_level` and `spelling_normalised_text` already used by `_scope_matches`). BLOCKS with a clear reason on zero or multiple candidates either way - this is a uniqueness check, not an inference/guess.
2. Parse the replacement via `_parse_markdown_table` (mistune).
3. Compare dimensions to the existing table (`_table_rows`); BLOCK rather than reshape if row/column counts differ - inserting/deleting rows to change a table's shape is out of scope for this capability.
4. Overwrite every cell positionally via `docx_table set_cells` (DocxEngine itself does the actual mutation - the new code here is only locating the table and preparing the cell list).
5. Comment anchors to the caption paragraph if one was found, else the paragraph immediately before the table (`_paragraph_before_table`).

Validation:
Unit-tested `_locate_table_for_replacement`/`_parse_markdown_table` directly against E-150's real change record and document before running the CLI: correctly resolved to table T27 (comment anchor P817) via the section-scoped fallback (caption genuinely has 0 matches), parsed the approved 5x3 replacement table, and confirmed old/new dimensions both 5x3. Framework re-run then applied **E-150 through E-159 in one batch, zero blocks** - the fix didn't just unblock the table edit, the rest of the section's remaining edits (paragraph/range/subsection/delete operations, already-working capabilities) all applied cleanly right after it. All 7 validators Pass; DOCX opens and `unzip -t` clean. Only E-160 (the section's last edit) remains for a future batch.

Note for future table work: this capability intentionally does NOT attempt row-label correspondence for a "replace the table content" instruction - it is positional only, and refuses (BLOCKS) if dimensions differ. If a future edit needs to reshape a table (add/remove rows or columns) as part of a content replacement, that is a new, separate capability to design and review - don't extend this one to guess at insertions/deletions.

## 2026-09-17 - E-160 BLOCKED: approved locator text not present in Section 9 (content mismatch, not a framework defect)

**Context:** Section 9 batch run (E-146-E-160) via the CSA DOCX framework, docxengine engine. E-146 through E-159 applied cleanly in a prior run. E-160 blocked on `"Anchor match count was 0; expected 1"` for the exact-text locator `Future design intent is to:`.

**Investigation (docxengine `Document.search` / `Document.read`, scoped - no full-document read):**

- `doc.search("Future design intent")` returns exactly 1 hit in the whole document: anchor `P520#1132`, snippet "Future design intent is to provide localised OT DNS services…", under heading "Design and functionality expected" beneath the **DNS** section (Section 6), well outside Section 9's paragraph range.
- Section 9 ("Time Synchronization") runs from `P787` to the next H1 heading; its own "Design and functionality expected" subsection (9.1) is `P790`-`P803`. Reading that range directly shows the design-intent content in Section 9.1 is a bullet, not a standalone paragraph, and is worded differently: `P801#e789 List:ul L1` = "future-state design intends to transition relevant time services to OT-controlled infrastructure".
- So the phrase `Future design intent is to:` genuinely does not exist anywhere inside Section 9 - it only exists verbatim in Section 6 (DNS), which is a different section entirely. The nearest conceptual match in Section 9.1 exists but is a differently-worded list item, not a paragraph beginning with the approved locator text.

**Classification:** This is neither a framework matching defect (the section-scoped exact-text search worked correctly - it correctly found 0 matches because the text is genuinely absent from Section 9) nor a mechanically-safe "document quirk" (like the E-149 spelling-variant case, where the underlying meaning was unambiguous and the fix was a pure normalization). Guessing that `P801` is "close enough" and rewriting it anyway would violate the Anchor Mismatch Rule / Absolute Change Control Rule - the located text does not match the approved locator, is phrased and structured differently (list item vs. standalone paragraph), and picking it unilaterally would be exactly the kind of independent reinterpretation the rule forbids.

**Resolution:** Left BLOCKED. No document mutation, no framework change. This needs human clarification on the approved change record itself: either (a) confirm E-160's target is actually the Section 6 DNS paragraph at `P520` (and the "Section 9.1" location in the change record is a drafting error), or (b) confirm the intended target is the Section 9.1 bullet at `P801` with updated locator text that actually matches it, or (c) supply corrected locator text if neither is right.

**Note for future runs:** When a framework block reports `Anchor match count was 0`, the first investigation step should be an unscoped `doc.search()` for the locator phrase (or a shortened form of it) before assuming a framework scoping bug - it cheaply distinguishes "framework failed to find text that's really there" (a framework gap) from "the approved change record's locator text doesn't exist where it says it does" (a content/citation issue that must go back to the change author, never guessed at).

## 2026-09-17 - Framework bug: blockquote-wrapped Text fields leaked literal ">" into applied paragraphs

**Context:** User reported literal `>` characters visible in the applied Section 9 text (E-153's paragraph): `"...persists. > > The Windows hosts will continue..."`.

**Root cause:** The change-record convention writes a multi-paragraph `**Text:**` field as a Markdown blockquote - every line, including the blank separator between paragraphs, prefixed with `>`. Two extraction paths exist for replacement text:

1. `change_parser._extract_text_block` (used for `record.text` when a change record's replacement content is read from a standalone `**Text:**` field in the normal parse path) - this one already correctly stripped `>` per line.
2. `ooxml._extract_range_spec` - used whenever a change's `**Do:**` field matches "replace ... through ...:" (a very common pattern, used across almost every section's change file) - extracts the replacement text via its own regex straight from `record.raw`, bypassing `_extract_text_block` entirely and leaving the `>` markers in place.

Both paths ultimately hand their text to the single shared function `ooxml.markdown_to_paragraph_texts`, which splits text into paragraphs on blank lines and separates Markdown bullets. That function had two bugs: (a) `_strip_inline_markdown` never stripped a leading `>`, so the marker survived into paragraph/bullet text; (b) a bare `>` separator line is non-empty (`">".strip()` is truthy), so it was never recognised as a paragraph break, causing every paragraph and bullet in a multi-paragraph blockquote to be concatenated into a single corrupted paragraph.

**Fix (standard, not a document-specific patch):** Added `ooxml._strip_blockquote_marker`, applied at the top of `markdown_to_paragraph_texts` to every line before blank-line/bullet detection. This is the single choke point every replacement-text path (parsed `record.text` and raw-regex `_extract_range_spec` text alike) already funnels through, so fixing it there covers both paths without duplicating the stripping logic change_parser already had. Added two regression tests to `tests/test_change_parser.py`: one exercising `markdown_to_paragraph_texts` directly on a blockquote with a bullet list, one exercising the full `_extract_range_spec` -> `markdown_to_paragraph_texts` path end to end. All 24 existing + new tests pass.

**Repair of already-corrupted content:** Two edits in Section 9 had already been applied under the buggy code before this fix - E-146 (`P788`, comment `C145`) and E-153 (`P827`/`P833` after prior insertions shifted paragraph numbers, comment `C152`). Both were repaired in place: verified backup taken first, then the approved Text content was re-run through the fixed `markdown_to_paragraph_texts` and written via `doc.edit_paragraph` (first paragraph, same anchor position) + `doc.insert` (remaining paragraphs/bullets), matching exactly the pattern the framework's own `_replace_range_by_index` uses for a normal apply. No duplicate comments were added - the original C145/C152 comments were left attached to the corrected first paragraph. Verified after repair: `doc.validate()` reports `valid: true`; `comment_id_consistency` and `table_row_comment_safety` both Pass; a scoped search for the approved text and for the bullet items each return exactly 1 match with no literal `>` remaining anywhere in the affected range; `doc.comment("list")` shows C145 and C152 unchanged (same author/date/text).

**Not yet checked:** Sections 5, 6, 7 and 8 have also already been run through this framework and may contain the same corruption wherever their change files use the "Do: Replace ... through ...:" pattern with a multi-paragraph `**Text:**` blockquote (this pattern is common in this project's change-record convention - it also appears in `ChangesCSA_IAMPS_Section8_E129_E145.md` and `ChangesCSA_IAMPS_Section12_E193_E207.md`, at minimum). A targeted scan of those sections' applied paragraphs for a literal `>` character is recommended before treating them as clean; this was out of scope for this fix (Section 9 only) and was not performed.

**Note for future runs:** Any bug found in one text-extraction path should be checked against the *other* extraction path for the same field (`record.text` via `change_parser` vs. raw-regex extraction via `ooxml._extract_range_spec`/`_extract_heading_to_sentence_range`) before considering it fixed - this project's framework has grown more than one independent way of pulling the same "approved replacement text" out of a change record, and a fix applied to only one of them silently leaves the other broken.

## 2026-09-17 - Scanned Sections 5-8 for the same blockquote-corruption bug; repaired 5 more instances

**Context:** Follow-up to the blockquote-marker bug fixed in `markdown_to_paragraph_texts` (see the entry above). Scanned every already-completed section (5, 6, 7, 8 - Section 9 was already checked and fixed) for edits whose `Do:` field matched the "replace ... through ...:" range pattern (the only path that bypasses `change_parser`'s blockquote cleaning), then verified each candidate empirically by reading its actual current paragraph text for a literal `>`, rather than trusting the pattern match alone.

**Method:** For each section's change file, parsed records and ran `ooxml._extract_range_spec(record.raw)` against every completed edit ID; a non-`None` result flags a theoretical risk. Then, for each flagged edit, derived the *expected* clean first-paragraph text via the now-fixed `markdown_to_paragraph_texts`, searched the live document for it, and inspected the actual returned snippet/full paragraph text for a stray `>`. This distinguishes edits that were genuinely corrupted from edits that matched the risky pattern but were already clean (see below) - the pattern match alone is not sufficient evidence of corruption.

**Findings:**
- Section 5: 1 candidate (E-94) - already clean.
- Section 6: 3 candidates (E-106, E-107, E-110) - already clean.
- Section 7: 4 candidates (E-112, E-115, E-123, E-124) - **E-115 was corrupted**, other 3 already clean.
- Section 8: 5 candidates (E-129, E-136, E-138, E-140, E-141) - **E-129, E-136, E-138, E-141 were corrupted**, E-140 already clean.

Several of the "already clean" candidates were surprising given the pattern match (e.g. E-106, E-110 are single-paragraph blockquotes that, under the old buggy code, should also have leaked a leading `> `) - they were evidently corrected by some means prior to this session (a per-edit manual fix script exists in the framework directory for E-123 and E-140 specifically: `manual_e123.py`, `manual_e140.py`; the mechanism for E-106/107/110/112/124 being clean was not investigated further, since the empirical check is what matters, not the historical cause).

**Repair:** All 5 confirmed-corrupted paragraphs (E-115 in Section 7; E-129, E-136, E-138, E-141 in Section 8) were repaired the same way as E-146/E-153 in Section 9: verified backup taken first (`...before_section578_repair_<timestamp>.bak`), approved text re-derived via the fixed `markdown_to_paragraph_texts`, applied via `doc.edit_paragraph` (first paragraph, same anchor) + `doc.insert` (remaining paragraphs), original review comments (C116, C130, C136, C138, C141) left untouched - no duplicates added. Verified after repair: `validate_docx()` all Pass, zip integrity clean, each repaired anchor read back with the correct paragraph count and no `>` anywhere, and each edit's original comment confirmed present with unchanged text.

**Scope now covered:** Sections 5 through 9 have all been checked for this specific bug pattern; 7 total instances found and repaired across the project (E-146, E-153 in Section 9; E-115 in Section 7; E-129, E-136, E-138, E-141 in Section 8). No sections beyond 9 have been run through the framework yet, so there is nothing further to check until a later section's batch is processed - future sections will not hit this bug at all since the root cause is now fixed in `markdown_to_paragraph_texts`.

## 2026-09-17 - E-160 resolved: corrected change-record locator/structure at Wenzel Joubert's instruction

**Context:** E-160 was left BLOCKED (see earlier entry "E-160 BLOCKED: approved locator text not present in Section 9") pending human clarification on which of three possibilities was correct. Wenzel Joubert instructed "fix E-160 issue" to proceed.

**Resolution applied:** The Section 9.1 bullet `future-state design intends to transition relevant time services to OT-controlled infrastructure` (the only future-state design-intent content in Section 9.1) is a near-verbatim match to E-160's approved replacement text and to its title ("Retain future-state time treatment only as design context") - strong evidence this, not the Section 6 DNS paragraph, was always the intended target. Corrected two things in the approved change record itself (`ChangesCSA_IAMPS_Section9_E146_E160.md`), not the framework or the document directly:

1. The `**Where:**` locator text, from the non-existent `Future design intent is to:` to the actual document text of the target bullet.
2. The record's field structure: E-160 had embedded its replacement content inline inside `**Do:**` rather than as a separate `**Text:**` field (unlike every other edit in this file) - this is *why* `record.text` was always `None` for this edit and the framework could never have applied it, independent of the locator problem. Moved the content into a standalone `**Text:**` field matching the file's established convention.

A `**Correction note**` was added to the change record directly under the edit, documenting exactly what was changed and why (it ended up folded into the Word comment automatically, since it appears before the next `---` separator). The approved instruction and replacement wording were not altered - only the locator text and field structure needed to reconcile the record with the actual document.

**Result:** Re-ran the framework batch with no other changes; E-160 applied cleanly via the standard `_apply_simple_paragraph_change` single-paragraph replace path (comment C157). Section 9 status is now `SECTION_COMPLETE` (E-146 through E-160 all applied). Validation: `validate_docx()` all Pass, zip integrity clean, target paragraph confirmed correct via scoped `docxengine` read with no corruption, comment C157 present with correct text, and the sibling sub-bullet (`consistent time is considered relevant to the systems and integrations identified in the design`) was left untouched since the approved change did not direct anything for it.

**Note for future runs:** When a change record embeds its replacement text inline in `**Do:**` instead of a separate `**Text:**` field, `record.text` parses as `None` and every apply path that requires text will BLOCK regardless of anchor matching. This is a distinct failure mode from a locator/content mismatch - worth checking `record.text is None` explicitly as a first diagnostic step whenever a block message references "no Text" or when `_apply_simple_paragraph_change`'s replace branch is suspected, since it's a change-record authoring inconsistency rather than a framework or document defect.

## 2026-09-17 - Framework robustness plan, steps 1-3: dry-run harness, inline-Text-in-Do cleanup, Section 3 diagnosis

**Permanent regression harness:** `.agents/framework/csa_docx/tools/dry_run_all_sections.py` now exists as a reusable tool. It replays every change record in every section's approved `.md` file straight through `DocxEngineEditor.apply_change()` on a disposable scratch copy of the working DOCX, and - unlike a real `cli_apply_section.py` run - does not stop at the first BLOCKED edit, so a full per-section blocker picture is available in one pass. Sections already `SECTION_COMPLETE` are skipped by default (replaying them against the *current*, already-edited DOCX would misleadingly report false blocks against their own applied text); pass `--include-complete` to force it anyway. Authoritative baseline as of this entry: 160 edits total, 73 applied (46%), 87 blocked (54%), unchanged after the inline-Text fixes below since neither fixed record was in a still-pending section's block count in a way that flips APPLIED/BLOCKED (E-240 moved from one blocked reason to another; E-84/E-130 are in already-complete Section 5/8).

**Inline-Text-in-Do sweep (the E-160 bug, generalised):** scanned all 244 records project-wide for `record.text is None and "**Text:**" not in record.raw`. Found exactly 3, each individually investigated rather than blanket-"fixed":
- **E-240** (Section 15) - genuine instance. Its replacement content (`full expansion not established in the reviewed CSA`) was embedded inline under `**Do:**` instead of a separate `**Text:**` field. Restructured; `record.text` now parses correctly. Re-running the harness shows E-240 now progresses past the missing-Text block and fails instead on `Could not extract a unique anchor from Where` (its Where lists three separate glossary entries, not one) - a distinct, already-scoped anchor-matching issue (Task #22), not this bug.
- **E-84** (Section 5, already `SECTION_COMPLETE`) - also a genuine instance of the pattern (two `Change X to: > Y` blocks embedded inline in `Do`), but Section 5's run-state confirms E-84 was already `APPLIED` correctly when Section 5 was processed - "Complex range/table operations now block in the reusable framework and are handled manually" per that run's notes, i.e. it was hand-applied around the very blocker this bug causes. No damage to the real document. Restructured the `.md` record anyway (moved both replacements into a proper `**Text:**` field as a two-item list) purely for record-format consistency and future harness accuracy; this does not touch the already-shipped document.
- **E-130** (Section 8, already `SECTION_COMPLETE`) - investigated and determined to be a **false positive** for this bug category, not fixed. It is a `Delete this heading and the repeated sentence beneath it... Then renumber: ...` instruction with no new content to insert, so a missing `**Text:**` field is correct by design, not a symptom of the E-160 bug. (Its actual limitation is that it's a compound delete+renumber edit spanning multiple structural changes under one edit ID, which no single dispatch path fully models - already correctly resolved manually per Section 8's run-state. That compound-edit limitation is out of scope for this task.)

**Section 3 diagnosis (31/31 blocked, 100%):** root-caused as a document-content mismatch, not a framework bug - see `.agents/framework-robustness-plan.md` §9 for the full writeup. Every one of Section 3's 31 "Where" anchors quotes sentence text that does not exist anywhere in the current working DOCX (verified by unscoped substring search across all 1,731 paragraphs, not just the section-scoped range); the section heading itself resolves correctly and uniquely, and the actual paragraphs under it cover the same topics in much shorter, rewritten bullet form. This needs a human decision (re-author the 31 records against current wording, or locate the intermediate draft they were actually written against) before any further automated work on Section 3 - fuzzy/anchor-matching improvements (Task #22) cannot safely resolve a mismatch this total without risking silently attaching an approved instruction's rationale to the wrong bullet.

## 2026-09-17 - CORRECTION: Section 3 was already complete; run-state tracking gap for Sections 1-4

**This corrects the diagnosis in the immediately preceding entry.** After asking Wenzel how to handle Section 3's apparent 31/31 block and getting approval to re-author the records, a closer read of `ChangesCSA_IAMPS_Section3_E38_E68.md` itself - before starting that rework - found a fully populated "Changes Report" at the foot of the file: all 31 edits recorded Applied, comment-verified, DOCX-integrity-validated, with a real backup (`...before_section_3_20260915-071615.bak`, dated 2026-09-15). Direct document inspection confirmed the approved *new* wording (e.g. E-39's replacement paragraph) is present in the working DOCX today. Section 3 was already done. The same check against Sections 1, 2 and 4 found the identical pattern - all three have real backups and fully populated, review-agent-signed Changes Reports, but none of the four had a run-state file in `.agents/run-state/` (only Section 5 onward were ever tracked there).

**Root cause:** the dry-run harness's `_section_is_complete()` check (and, by the same logic, the real `cli_apply_section.py` "which sections are pending" logic) relies solely on the presence of a `.agents/run-state/current-state-assessment-document-section-N.md` file with `Status: SECTION_COMPLETE`. For Sections 1-4 that file simply never existed, even though the work was done and signed off - so both the harness and (more importantly) any future real apply run would treat them as pending and replay already-superseded change records against the current document. For a dry run this only produces misleading numbers; for a real run it could have duplicated already-applied INSERT edits (whose anchors are often untouched, stable text) or corrupted comment IDs.

**Fix:** backfilled `.agents/run-state/current-state-assessment-document-section-{1,2,3,4}.md`, each derived from that section's own change file "Changes Report"/"Edit verification" evidence, all marked `SECTION_COMPLETE`. No change-file content was re-authored or altered for Sections 1-4 - only the missing tracking file was added. `.agents/framework-robustness-plan.md` §9 was corrected in place (original wrong diagnosis kept, collapsed, for the record).

**Corrected baseline:** the true remaining work is Sections 10-16 only (Sections 1-9 are all now confirmed `SECTION_COMPLETE`): 83 edits, 59 applied (71%), 24 blocked (29%) - materially healthier than the previously-reported 160/73/87 figure, which was inflated by 77 edits' worth of false blocks/false-applies from replaying four already-complete sections.

**Reusable lesson:** whenever a section shows an unusually high or total block rate, check the change file's own tail for a "Changes Report" / "Applied: ..." block *before* concluding the document or the anchors are the problem - a populated report there means the section was already run for real outside of `run-state` tracking, and the fix is to backfill run-state, not to re-author or re-diagnose the content.

## 2026-09-17 - Harness fix (partial-completion skip) and find_anchor pattern generalisation

**Second false-block source found, same family as the Section 1-4 gap:** Section 10 is a genuinely in-progress section (run-state Status: BLOCKED, not complete) whose run-state correctly records E-161 through E-165 as already APPLIED (comment IDs C158-C162 present in the real document) with E-166 as the real next blocker. But `dry_run_all_sections.py`'s `_section_is_complete()` check only understands "fully SECTION_COMPLETE or not" - it has no concept of a section that is *partially* done, so it replayed all 16 of Section 10's edits from scratch, reporting E-161/162/163/165 as newly blocked (false - their anchors are gone because they're already applied) alongside the real blocker E-166. Caught by isolating E-162 with `apply_change()` called directly against a fresh copy of the current working DOCX and comparing to the run-state file's own "Completed edit IDs" line - the isolated block was real (0 matches), but cross-checking the change file's approved replacement text against the document showed it already present verbatim, which only makes sense if it had already been applied for real.

**Fix:** `replay_section()` in the harness now calls the framework's own `run_state.read_completed_ids()` for every section (not just the complete/not-complete gate) and skips any edit ID already recorded completed, regardless of whether the section as a whole is SECTION_COMPLETE. Report output now shows a `N already-completed (skipped)` count per section and the TOTAL line distinguishes "edits" (file count) from "replayed" (actually exercised) so applied/blocked percentages are computed against what was really tested, not diluted or inflated by already-done work. This is the harness-level generalisation of the same lesson as the Section 1-4 backfill: never trust "no run-state = not started" as the only signal - always check whether individual edit IDs are already marked done before replaying them.

**`find_anchor()` pattern gaps closed:** three Where-clause phrasings used across Sections 11/12/15 had no matching regex in `csa_docx/ooxml.py::find_anchor()`, so it fell through to treating the *entire* Where text (including the "Section N, ..." prefix) as the anchor - always wrong. Added:
- `immediately before(?:[^:\n]*):` / `immediately after(?:[^:\n]*):` - covers both the plain form ("immediately before:\n\nHEADING") and the form with descriptive filler before the colon ("immediately after the WMI evidence:\n\nClientType: 1"), found via E-177 and E-196.
- `standalone text exactly:` - a short isolated phrase called out with different wording from "sentence exactly"/"heading exactly" but functionally identical, found via E-190.

Deliberately did **not** match the superficially similar "after the revised Section 10.2.2" (E-166) or "after the revised Findings text from E-189" (E-191) phrasing - these aren't locator quotes at all, they're a genuine sequential-dependency reference to *another edit's own output* (the paragraph E-165/E-189 produces), which no current anchor-extraction pattern can resolve safely; matching them to garbage text would be worse than the current clear "no anchor" block. This is a distinct, unsolved problem class (dependent/chained edits within the same batch) worth its own design work later rather than a quick pattern addition.

**Result after both fixes**, corrected baseline for the only sections with real remaining work (10-16; 1-9 are all confirmed complete): 78 edits actually exercised, 60 applied (77%), 18 genuinely blocked (23%) - up from 73%/27% before this pass, with two of the three pattern-gap edits (E-190, E-196) now applying cleanly and the third (E-177) progressing past anchor extraction into a distinct, real DocxEngine "stale anchor hash" error worth investigating separately.

**Remaining genuine blocker categories in Sections 10-16** (real bugs or real content-vs-record mismatches, not false positives - not yet fixed):
- E-166 / E-191: sequential-dependency Where clauses ("after the revised X from E-NNN") - needs the editor to track and expose each edit's resulting anchor within a batch run, not just single-shot addressing.
- E-170, E-176 (Section 10): succeed if replayed in isolation against a clean document, but block when replayed after E-167-169 in real sequence - a genuine cascading/collateral effect from an earlier edit in the same section, not yet root-caused to which specific prior edit is responsible.
- E-177 (Section 11): anchor now extracts correctly but DocxEngine reports the derived paragraph hash as stale - a deeper engine-addressing issue, not a `find_anchor` problem.
- E-199 (Section 12): "Could not find 3 following bullet/content paragraph(s)" - the anchor and count logic doesn't match the actual bullet layout under this heading; not yet diagnosed.
- E-213 (Section 13): "This indicates that:" appears twice within the section's scope - a genuinely ambiguous short generic phrase needing a secondary disambiguator (e.g. nearest-to-locator-number heuristic), not yet implemented.
- E-224/226/230 (Section 14): anchor matches 3 times even within section scope - needs investigation of what's actually repeating.
- E-241 (Section 15): "Could not extract labelled table replacement values" - table-cell extraction gap, separate from the Section 15 anchor issue already fixed for E-240.

## 2026-09-17 - Real framework bug found: _result_anchor() didn't recognise docx_insert's result shape

**Root cause of E-177's "stale anchor" block (and every other insert-type edit's silent risk):** `_result_anchor()` in `docxengine_adapter.py` looked for `result.get("anchor")` or `result.get("new_anchor")` (singular keys) to find the anchor of newly-inserted content. `Document.insert()` actually returns `{"new_anchors": [...]}` - plural key, a list. Neither singular key ever matched, so `_result_anchor()` always returned `None` for an insert result, and the caller fell back to `paragraph.anchor` - the anchor of the paragraph the new content was inserted before/after, captured *before* the insert happened. Inserting a paragraph shifts every paragraph ordinal from that point on, and DocxEngine's anchors are content+position addressed (`P{ordinal}#{hash}`), so that pre-insert anchor is now genuinely stale. The very next call using it - `_add_comment(comment_anchor, ...)` - failed with DocxEngine's real, correctly-raised `anchor_stale` error, which surfaced as a confusing top-level block on an edit whose actual content change had already silently succeeded moments earlier.

Diagnosed by reproducing the exact `apply_change()` call path manually step by step outside the method (find_anchor -> `_matching_paragraphs` -> `doc.insert`) and finding it succeeded every time in isolation, then comparing byte-for-byte against the real `apply_change()` call on an identical fresh copy, which failed deterministically - proving the divergence had to be inside the method itself rather than document state or anchor computation. Tracing which of `apply_change`'s dispatch predicates ran (all `False`, confirming the "insert before" branch of `_apply_simple_paragraph_change` was reached) and inspecting `doc.insert()`'s actual return shape (`{"new_anchors": ["P1166#4751"]}`) pinned it to `_result_anchor()`.

**Fix:** `_result_anchor()` now also checks `result.get("new_anchors")` / `result.get("anchors")` and takes the first element when the singular keys are absent. Verified E-177 now applies cleanly (comment attaches to the newly-inserted paragraph, not the shifted old one). This was a real, previously-invisible framework bug affecting every insert-before/insert-after edit across all 16 sections, not just E-177 - worth a full pass later to check whether any *already-applied* insert edit's comment ended up mis-anchored to the wrong (shifted) paragraph as a result of this bug before the fix (would show as a comment sitting one paragraph off from where it should be).

## 2026-09-17 - Third instance of "an earlier broader edit already covers this edit's target" (not a bug)

E-199 (Section 12) showed the same pattern as E-170/E-176 (Section 10, see the "Harness fix" entry above): a fine-grained edit (replace 3 bullets under a specific "There is no evidence of:" occurrence) blocks in real sequential order because an earlier edit in the same file (E-197, "Replaced body content under heading: Observed Behaviour") already replaced the whole subsection containing that exact anchor. Traced with the same isolated-vs-sequential-replay method: E-199 in isolation finds 2 matches for its anchor text within section scope (ambiguous, expected - the document legitimately has two similar "There is no evidence of:" blocks in this section, one about monitoring and one about patch management); after E-197 runs first, one of those two is gone, leaving exactly 1 match - but it's the *other* occurrence (2 bullets, not the 3-bullet patch one E-199 was written for), so the bullet-count check fails.

This confirms a systemic characteristic of these change records, not a one-off: several finer edits are effectively pre-empted by a *broader* "replace the entire subsection/body" edit that appears earlier in the same file and happens to cover the same ground. Once the broader edit is applied, the finer edit becomes a legitimate no-op, and today's dispatcher reports that as a generic BLOCKED rather than a recognisable "superseded, nothing more to do" outcome. Deliberately not building an automatic "supersession detector" for this - inferring "edit X is superseded by edit Y" from natural-language Do/Why text is exactly the kind of guess that risks silently skipping a change that was NOT actually superseded. Each occurrence needs a one-line human check (does the broader edit's approved replacement text already include what the finer edit wanted?) before being marked skipped-not-blocked. Confirmed occurrences so far: E-170/E-176 (superseded by E-169/E-175), E-199 (superseded by E-197).

## 2026-09-17 - Remaining genuine multi-match ambiguity (not attempted)

E-213 (Section 13, "This indicates that:") and E-224/E-226/E-230 (Section 14, three different "sentence beginning exactly" anchors) all block with the same shape regardless of replay order (isolated or sequential) - a short, generic phrase that legitimately repeats 2-3 times within the section's scope, with no current tie-breaker. Unlike the supersession pattern above, sequencing doesn't resolve these. Deliberately not attempting an automatic disambiguation heuristic (e.g. "closest paragraph to a nearby unique anchor", "match the one whose surrounding text best fuzzy-matches the Do/Why field") without checking each one's surrounding context by hand first - a wrong guess here would silently misapply an approved edit's comment/rationale to the wrong paragraph, which is a worse outcome than the current clear block. Left as genuinely open items for a future pass (each is a 5-minute manual check, not a framework redesign).

## 2026-09-17 - Direction B (track_changes / review sign-off / cleanup agent) wired up and verified

`DocxEngineEditor` (`docxengine_adapter.py`) now takes `track_changes: bool = True` in its constructor and threads it through every one of its ~10 document-mutation call sites (`doc.insert`, `doc.delete`, `doc.edit_paragraph` - all three DocxEngine tools already supported the parameter natively, confirmed by inspecting their JSON specs, so this was pure plumbing, no new DocxEngine capability needed). `cli_apply_section.py` exposes `--track-changes`/`--no-track-changes` (default on) on the same switch.

Verified concretely on Section 11's real batch: applying all 16 edits with `track_changes=True` produced 75 `w:ins` and 79 `w:del` elements in `word/document.xml`, the file remained a valid ZIP throughout, `docx_revision list` showed the expected revision set (author, anchors, text all sane), and `docx_revision accept_all` cleanly finalised all 154 revisions (zero `w:ins`/`w:del` left, file still valid). Also confirmed via the regression harness that the flip is behaviourally invisible to which edits succeed or block - same 78 replayed / 61 applied / 17 blocked before and after - because tracked-changes mode only changes how a successful edit is written into the XML, never whether the anchor-matching/dispatch logic finds and accepts it.

`csa-change-review.md` gained a `Sign-off for cleanup: YES/NO/NOT APPLICABLE` line (plus the specific edit IDs it covers) in its report format, with explicit rules: PASS/PASS WITH NOTES sign off, FAIL/BLOCKED never do, and "can't tell if tracked changes are even on" signs off NOT APPLICABLE rather than guessing.

New agent `.agents/csa-change-cleanup.md` (Phase 3) is intentionally the smallest of the three - it makes no correctness judgement of its own, only finalises what Phase 2 already signed off, via `docx_revision accept_all` or a scoped per-revision `accept` for batch sign-offs. Six Hard Stop Conditions (no review report, NO/NOT APPLICABLE/missing sign-off, scoped sign-off narrower than the section, unexpected revision author) all resolve to "stop and report", never "guess and proceed" - matching the same caution this whole session's mistakes (Section 3, Section 10's partial-completion false-blocks) have repeatedly shown is necessary when inferring intent from natural-language records rather than exact machine-checkable state.


## 2026-09-17: Direction A bookmark module wired in and verified (partial coverage)

Built `csa_docx/bookmarks.py` - real OOXML `w:bookmarkStart`/`w:bookmarkEnd`
tags spliced directly into `word/document.xml` bytes (DocxEngine has no
bookmark tool of its own), keyed on the paragraph span from
`docxengine._anchors.build_anchor_index()`. Two functions:
`add_bookmark_at_anchor(editor, anchor, edit_id)` and
`find_bookmark(editor, edit_id)`.

Wired into `_apply_simple_paragraph_change()` only, as a scoped
proof-of-concept: check `find_bookmark()` first (skips text-matching
entirely if the edit was already tagged), and auto-tag a bookmark after
every successful insert-before/insert-after/replace so the *next* touch of
that edit ID resolves via the bookmark instead of `find_anchor()` +
`_matching_paragraphs()`.

Verified with a live round-trip test on Section 11:
- Bookmarks survive save/reopen (same anchor resolves both times).
- Bookmarks survive *upstream* edits that shift paragraph ordinals - tagged
  E-177 at `P1166#4751`; after two more edits applied earlier in the
  document, `find_bookmark` correctly returned the shifted anchor
  `P1172#4751`. This is the actual proof that bookmarks solve the problem
  ordinal-based anchors can't.
- Re-invoking `apply_change()` for the same edit ID after that shift
  resolved through the bookmark path successfully.
- Confirmed the scope gap directly: E-177/E-179/E-180 (simple
  insert/replace, dispatched to `_apply_simple_paragraph_change`) got
  bookmarks; E-178/E-181 (paragraph-range replacements, dispatched
  elsewhere) did not. The other six dispatch methods do not yet have
  bookmark integration - this is documented, not hidden.

Regression harness re-run across Sections 10-16 after this change: 78
edits replayed, 61 applied (78%), 17 blocked (22%) - identical to the
pre-bookmark baseline. Confirms the bookmark-first path is additive (changes
re-resolution durability, not first-time apply behaviour).

Next unit of work: extend the same bookmark-first-lookup + auto-tag pattern
to the remaining six dispatch methods, each verified independently the way
this one was, rather than doing all seven at once.


## 2026-09-17 (cont.): Direction A bookmark coverage extended to 6 of 8 dispatch methods

Added a shared `_resolve_paragraph_index()` helper (bookmark-first, falls
back to `_matching_paragraphs()`) to `_apply_anchor_plus_bullets_replacement`,
`_apply_section_body_replacement`, and `_apply_anchor_plus_following_content`.
Added auto-tagging directly into `_replace_range_by_index()` (the shared
range-replace helper those three plus `_apply_explicit_range_replacement`
all call), so all four get bookmark auto-tagging from one change; the range
method itself doesn't get bookmark-first lookup on entry since it resolves
two boundaries, not one anchor - judged not worth the added risk this pass.
Added bookmark-first lookup directly to `_apply_subsection_end_insert`.

Caught one real bug introduced while doing this, before it shipped:
`_apply_subsection_end_insert`'s success message referenced
`paragraphs[heading_index]`, but `heading_index` is never computed when the
bookmark path resolves the target directly - would have raised `TypeError`
on every bookmark-resolved re-apply of that edit type. Fixed with a guarded
`heading_label` computed once, before the try block.

Left untouched, with reasons documented in the plan (§12): `_apply_delete_until_heading`
(nothing survives to bookmark after a delete) and the two table-replacement
methods (table cells are addressed by row/column coordinates, not paragraph
anchors - a different mechanism than what `bookmarks.py` implements today).

Verified: live re-test on Section 11 showed E-178 and E-181 (which dispatch
through `_apply_explicit_range_replacement`) now get bookmarks, where they
didn't in the first pass. Full regression harness across Sections 10-16:
still 78 replayed / 61 applied (78%) / 17 blocked (22%), identical to every
prior baseline this session - confirms the extension is purely additive.

## 2026-09-17 — Vendor import-order bootstrap (framework fix)

- **Context:** Section 11, first run of the batch (E-177..E-186), `framework-first` mode.
- **Problem observed:** `cli_apply_section.py` failed at bootstrap with
  `ModuleNotFoundError: No module named 'docxengine'`.
- **Cause:** `csa_docx/bookmarks.py` imports `docxengine._anchors` at module top.
  `csa_docx` is imported via `cli_apply_section.py` before `docxengine_adapter.py`
  inserts `framework/vendor` onto `sys.path`, so `docxengine` is not importable
  from the plain `python3.14` interpreter on first import.
- **Corrected approach:** put the vendor bootstrap in the *earliest* module that
  needs it (bookmarks.py) or in `csa_docx/__init__.py`, before any downstream import
  of `docxengine.*`. Applied fix: `bookmarks.py` now inserts `parents[1]/vendor`
  onto `sys.path` before its `from docxengine._anchors import build_anchor_index`
  line, mirroring `engines/docxengine_adapter.py`.
- **Validation:** `python3.14 -c "import sys; sys.path.insert(0,'.agents/framework');
  from csa_docx.engines.docxengine_adapter import DocxEngineEditor;
  from csa_docx.bookmarks import find_bookmark"` succeeds. No `PYTHONPATH`
  required; the framework is self-contained for future runs.
- **Impact:** This is a one-line-per-module bootstrap fix; no functional change.
  All future `framework-first` runs no longer need `PYTHONPATH=vendor` prepended.
