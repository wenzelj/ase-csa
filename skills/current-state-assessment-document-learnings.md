# Current-State-Assessment-Document Agent Learnings (inbox)

Append-only inbox for reusable lessons from applying approved Current State Assessment changes to the DOCX. It is not a diary and not an issue tracker:

- Defects, blocked edits and recurring problems go to `.agents/issues-open.md`.
- Questions only Wenzel can answer go to `.agents/needs-decision.md`.
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
