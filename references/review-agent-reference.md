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
