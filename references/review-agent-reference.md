# Reference for `csa-change-review.md`

Moved here from `csa-change-review.md` to keep the agent card short. The agent card links to each section by heading.

## Change Report Verification

If the approved `.md` change file contains a `## Changes Report` section, verify the report against the DOCX.

Check that the report accurately states:

- the section completed;
- the working DOCX path or filename;
- the change file path or filename;
- applied edit IDs;
- already-applied edit IDs;
- unresolved edit IDs;
- skipped edit IDs;
- number of Word comments added or present;
- comment author, if reported;
- validation result;
- saved output path.

If the report is stale, inaccurate, incomplete, or contradicts the DOCX, record this as a finding.

If no `## Changes Report` exists, record that as a finding when the implementation agent was required to append one.

## DOCX Integrity And OOXML Validation

Before judging the implementation complete, validate the DOCX package.

At minimum, check:

- the file exists and is a DOCX/OOXML package;
- archive integrity passes, for example with `unzip -t`;
- `[Content_Types].xml` parses successfully;
- `word/document.xml` parses successfully;
- `word/_rels/document.xml.rels` parses successfully;
- `word/styles.xml` and `word/numbering.xml` parse successfully when present;
- `word/comments.xml` parses successfully when comments are expected;
- `word/comments.xml` has a valid relationship from `word/_rels/document.xml.rels`;
- `[Content_Types].xml` contains the comments content type when comments exist;
- each comment ID has matching `w:commentRangeStart`, `w:commentRangeEnd`, and `w:commentReference` markers;
- no comment ID is duplicated unexpectedly;
- no required comments are orphaned;
- no `w:commentRangeStart`, `w:commentRangeEnd`, `w:r`, or `w:commentReference` elements appear directly under any `w:tr`.

For table comments, valid placement is inside the affected table cell paragraph:

```text
w:tr
  -> w:tc
     -> w:p
        -> w:commentRangeStart
        -> w:r / changed text runs
        -> w:commentRangeEnd
        -> w:r
           -> w:commentReference
```

Invalid placement that must fail review:

```text
w:tr
  -> w:commentRangeStart
  -> w:r
     -> w:commentReference
  -> w:commentRangeEnd
```

## Render And Open Validation

When rendering tools are available through the document skill, render the DOCX and inspect enough page images to confirm readability and obvious layout integrity.

At minimum:

- render the whole DOCX;
- confirm the renderer completes without error;
- count rendered pages;
- inspect the cover or first page for gross corruption;
- inspect pages containing the reviewed section when identifiable;
- inspect any page containing heavily edited tables when practical.

Do not claim visual validation passed unless render/open validation actually ran.

## Unauthorised Change Detection

If the original/source DOCX is supplied, compare the original to the new/working DOCX.

Classify differences as:

- authorised content edits from the `.md` file;
- authorised comment additions;
- authorised version naming or version metadata;
- unavoidable formatting repairs directly caused by authorised edits;
- unauthorised changes;
- inconclusive differences requiring manual review.

Do not treat ZIP entry order, compression metadata, timestamps, or benign package rewrites as unauthorised content changes by themselves.

Focus on visible document content, Word comments, relationships, styles, numbering, headers, footers, tables, images, and fields.

If the original/source DOCX is not available, report that unauthorised-change detection is limited and explain what checks were still possible.

## Table And Numbering Review

For table edits:

- verify only the approved cells or rows changed;
- verify table row count and column count remain valid unless the `.md` file authorised structural changes;
- verify nested tables were not accidentally flattened or corrupted;
- verify cell text, row order, shading, borders, and alignment are preserved where practical;
- verify comments are anchored inside table cells, not directly under table rows.

For heading and numbering edits:

- verify heading levels remain correct;
- verify section numbering did not restart unexpectedly;
- verify table of contents impact is either correct or explicitly deferred;
- verify cross-references and bookmarks were not obviously broken.

## Editorial Edit Check

An edit whose `Why` starts with `Editorial --` was proposed under the authoring agent's `EDIT_MODE=editorial`: a concision change that must not alter any fact. For each one in the batch, after confirming it was applied as approved:

1. Compare the removed text with the applied text and list any fact (name, number, dependency, rating, limitation, uncertainty wording) that is gone from the edited location.
2. For each such fact, check that the stable ID named in the `Why` as "still stated at" does state it in the current DOCX. Resolve that ID with `lookupStableId`; it may have moved if other edits were applied.
3. A fact that is gone and not stated at the named location -> `P1 HIGH` `Editorial fact loss`. A fact that is weakened or strengthened in the new wording -> `P2 MEDIUM`.
4. Optionally run `csa-writing-style/scripts/prose_lint.py --section <N>` on the DOCX and report the after-state metrics next to the change file's expected values. A lint shortfall is a `P3 LOW` note, never a fail on its own.

## Recovery And Repair Boundary

If review fails, do not automatically repair the DOCX.

Report the issue and recommended action first.

Only repair after explicit user instruction such as:

```text
Fix the failed review findings.
```

When repairing:

- make a backup before editing;
- modify only what is necessary to correct the failed implementation;
- preserve approved content and comments;
- re-run the review after repair.

## Example Review Input

For IAMPS Section 1, an example approved change file is:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/01 Current State AS Built/01 Final Version/reviews/ChangesCSA_IAMPS_Section1.md
```

Use that file as source of truth when it is the supplied change file, but keep this agent generic for any other application Current State Assessment.

## Generic Scope

This agent is generic for any application or system Current State Assessment.

Do not hard-code IAMPS, Aurizon, OT 3.5, section numbers, edit ranges, filenames, or project-specific assumptions.

Infer the application name, document title, section number, edit IDs, expected comments, and expected output from the supplied files.

## Bounded Review Iteration Mode

Default to small, restartable review iterations instead of attempting every edit in a large section in one uninterrupted run.

Use this mode whenever:

- the reviewed section has more than 8 approved edit IDs;
- the implementation `## Changes Report` is partial;
- the DOCX requires OOXML-level inspection;
- comment anchoring is complex, especially inside tables;
- full rendering is slow, unavailable, or repeatedly fails;
- the current context has already compacted;
- the agent has spent material time reviewing without writing durable review evidence.

Default limits:

- `REVIEW_EDIT_LIMIT=8`
- `REVIEW_TIME_LIMIT_MINUTES=20`
- `RUN_SCOPE=next-review-batch`

The user may override these with:

```text
SECTION=3
START_EDIT_ID=S3-E1
END_EDIT_ID=S3-E7
Review the requested section using the agent defaults.
```

or:

```text
SECTION=3
REVIEW_EDIT_LIMIT=12
Review the requested section using the agent defaults.
```

Only use `RUN_SCOPE=full-section` when the user explicitly supplies it or the section has 8 or fewer edit IDs.

### Review Planning

Before inspecting the DOCX deeply:

- parse the approved `.md` file into a verification inventory;
- identify every approved edit ID and question/comment-only item;
- read the implementation `## Changes Report`;
- identify the working DOCX, backup, applied edit IDs, unresolved edit IDs, and skipped edit IDs;
- read the existing `## Change Review Report`, if present;
- choose the next unreviewed batch in edit-number order;
- create or update the run-state file for this section;
- report the selected review batch in the run-state before heavy DOCX inspection.

Use this run-state path pattern:

```text
01 Current State AS Built/01 Final Version/run-state/csa-change-review-section-<SECTION>.md
```

Create the `01 Current State AS Built/01 Final Version/run-state` directory if it does not exist.

The run-state file must contain:

- section number or title;
- approved change file path;
- reviewed DOCX path;
- original/source DOCX path when available;
- full verification inventory;
- implementation report status;
- current review batch edit IDs;
- reviewed edit IDs and statuses;
- unresolved, failed, or blocked edit IDs;
- DOCX integrity evidence gathered;
- unauthorised-change detection status;
- next edit ID to review;
- latest status: `PLANNED`, `IN_PROGRESS`, `PARTIAL_REVIEW_COMPLETE`, `REVIEW_COMPLETE`, `BLOCKED`, or `NO_PROGRESS_STOP`.

### Review Execution

For the selected batch only:

- verify approved content changes;
- verify old text removal where required;
- verify comment presence, anchor, edit ID, reason, author, and initials where practical;
- verify the implementation `## Changes Report` claims for that batch;
- run package/comment OOXML checks needed for the reviewed comments;
- render/open validate once per batch when tools are available, prioritising pages that contain the reviewed section;
- write or update the `## Change Review Report`;
- update the run-state file.

Do not repeat full-document comparison after every edit. Use full unauthorised-change comparison once per review batch when feasible, and definitely when the section review becomes complete.

### No-Progress Stop

Do not work for hours without producing durable review evidence.

Stop and report `NO_PROGRESS_STOP` when any of these occur:

- one full review attempt produces no `.md` review report or run-state change;
- the same DOCX extraction, anchor search, or render failure repeats without new evidence;
- the time limit is reached before any edit in the selected batch can be verified;
- context compaction occurs and the run-state is not current enough to continue safely;
- the working DOCX or change report cannot be identified safely.

When stopping for no progress:

- do not claim the review passed or failed globally unless evidence supports that result;
- write the blocker, attempted edit ID, evidence checked, and next recommended command to the run-state file;
- add a short partial `## Change Review Report` entry if the change file can be updated safely;
- return the exact resume prompt to the user.

### Review Completion

At the end of each successful review iteration, report one of:

- `PARTIAL_REVIEW_COMPLETE` when more edit IDs remain;
- `REVIEW_COMPLETE` when every approved edit in the requested section has been reviewed and the final result is `PASS`, `PASS WITH NOTES`, `FAIL`, or `BLOCKED`;
- `BLOCKED` when user input, missing evidence, or implementation repair is required;
- `NO_PROGRESS_STOP` when the safety rule above triggered.

For `PARTIAL_REVIEW_COMPLETE`, include the exact next command, for example:

```text
Load this agent definition:
<agent path>

Act as the C-S-A-Change-Review Agent.

SECTION=3
Review the requested section using the agent defaults.
```

The next run must read the run-state first and continue from `next edit ID`.

## Finding Severity

Use these severity levels:

- `P0 BLOCKER`: DOCX cannot be opened/rendered, approved changes cannot be reviewed, or the wrong file was edited.
- `P1 HIGH`: approved content is missing or incorrect; unauthorised content changes are detected; required comments are missing for material edits; comment anchors corrupt Word structure.
- `P2 MEDIUM`: change report is inaccurate, comment reason is weak or partly misaligned, validation evidence is incomplete, or formatting drift affects the reviewed section.
- `P3 LOW`: minor wording/reporting issue, non-blocking transparency note, or validation limitation that does not affect correctness.

Every finding must include:

- severity;
- edit ID or document area;
- expected result from the `.md` source of truth;
- observed result in the DOCX or report;
- recommended action.

## Review Report Format

Produce a Markdown review report.

Use this structure:

```text
# CSA Change Review Report

Review result: PASS / PASS WITH NOTES / FAIL / BLOCKED

Reviewed document
<full DOCX path>

Approved change file
<full .md path>

Section reviewed
<section number/title>

Source of truth
The approved Markdown change file was used as the source of truth.

Change report reviewed
Present: Yes/No
Accurate: Yes/No/Partially/Not reviewed

Sign-off for cleanup: YES / NO / NOT APPLICABLE
Edit IDs covered by this sign-off: <comma-separated edit IDs, or "None">

Summary
<brief outcome>

Edit verification
| Edit ID | Status | Evidence | Comment check |
|---|---|---|---|
| S<N>-E1 | CORRECT / ... | <what was verified; evidence: E-nnn / no evidence on record / contradicted by E-nnn> | <comment author, anchor, reason> |

Findings
| Severity | Area/Edit ID | Finding | Recommended action |
|---|---|---|---|
| P1 HIGH | S<N>-E4 | <issue> | <action> |

DOCX integrity validation
- Archive integrity: Pass/Fail/Not run
- XML package parse: Pass/Fail/Not run
- Comment relationships: Pass/Fail/Not applicable
- Comment ID consistency: Pass/Fail/Not applicable
- Table-row comment safety: Pass/Fail/Not applicable
- Render/open validation: Pass/Fail/Not run
- Rendered page count: <count or Not run>

Unauthorised change detection
Original/source DOCX supplied: Yes/No
Result: None detected / Issues found / Limited

Reviewer notes
<notes, limitations, and next step>
```

Keep the report factual and evidence-backed. Do not hide limitations.

## Report Persistence

After completing the review, write the review report to the same approved section `.md` change file that was reviewed.

Append it below the implementation `## Changes Report` section using this heading:

```text
## Change Review Report
```

If the `.md` file already contains a `## Change Review Report` section for the same reviewed DOCX and section, update that existing review report instead of appending a duplicate.

Do not edit approved change instructions above the report sections.

For bounded review iterations, the report may be partial. Label it `PARTIAL_REVIEW_COMPLETE`, include the reviewed edit IDs, open edit IDs, next edit ID, and the run-state path. Replace or update the partial report when later iterations add evidence.

After saving the updated `.md` change file, respond to the user with the same review report.

## Continuous Skill Improvement

After every completed review, capture what was learned so the next review is stricter, clearer and easier to repeat.

Use this local skill-notes path for this agent:

```text
.agents/skills/csa-change-review-learnings.md
```

At the end of each run:

- identify any reusable lesson from the review, validation, DOCX inspection, comment verification, table-comment safety checks, section detection, report comparison, unauthorised-change detection, rendering, file permissions, or recovery work;
- add only lessons that are generic enough to help future Current State Assessment change reviews;
- include the date, section or document context, issue or risk observed, evidence used, corrected review approach, and how to validate it next time;
- keep project facts and approved technical changes out of the skill notes unless they are needed as an example;
- do not copy confidential document content into the skill notes unless necessary and already present in the approved `.md` change file;
- do not edit approved change instructions above the report sections;
- do not modify global Codex skills unless the user explicitly asks for that;
- if the lesson changes how this agent should behave on every future run, update this agent `.md` with a small, controlled instruction change and mention that in the `## Change Review Report`;
- if there was nothing reusable to learn, record `No new reusable skill lesson identified` in the `## Change Review Report`.

The skill note must be append-only unless the user explicitly asks for cleanup. Prefer short, evidence-backed entries over broad rules.
