# Reference for `current-state-assessment-document.md`

Moved here from `current-state-assessment-document.md` to keep the agent card short. The agent card links to each section by heading.

## Versioning

There is one working DOCX per project, found by `prepareDocument()` (and shown by `csa status`). Edit that file in place.

- Do not create a new versioned copy (`- v2.docx` and so on) unless Wenzel asks for a new version in this run.
- Never edit an original or archived DOCX.
- Do not change the document's version, dates, owners, reviewers or project names unless a change record says so.

## Backup And Working Copy Rule

The framework backs up the working DOCX before every batch and records the backup path in the `## Changes Report`. When you change the DOCX by hand, first make a timestamped copy yourself:

```text
<working-docx-name>.before_section_<section-number>_<YYYYMMDD-HHMMSS>.bak
```

Confirm the copy exists and is not empty, and record its path in the `## Changes Report`. Do not edit the DOCX if the backup cannot be made.

## Section-By-Section Execution

Only process one section per execution cycle.

Example user instruction: "Apply Section 7."

Then:

- open the current working version;
- locate the approved Section 7 `.md` change file;
- read the complete Section 7 change file;
- process the edits in edit-number order;
- make no changes outside Section 7 unless an edit explicitly requires a cross-section change;
- validate Section 7;
- save the document;
- report the result;
- stop.

Do not begin Section 8. The user must explicitly tell you to continue.

## Change Order

Apply edits in the exact documented sequence.

For example:

```text
S7-E1
S7-E2
S7-E3
...
S7-E17
```

Do not reorder them unless necessary because an earlier approved edit changes the anchor text needed by a later edit.

When that occurs:

- preserve the intended edit order;
- use the resulting text location carefully;
- do not reinterpret the approved change.

## Locating Edits

Every `Where:` in a current change file is a stable ID (`@H<path>-P<n>` for a paragraph, `@H<path>-T<n>-R<n>` for a table row), resolved through the manifest that `prepareDocument()` builds. The framework resolves it for you. When you work by hand:

- resolve the ID with `lookupStableId("@H...")` (or `csa lookup "@H..."`) and edit the paragraph or row it returns;
- never search the document for similar wording instead of resolving the ID;
- an older change file with a text anchor ("sentence beginning exactly ...") is resolved with `lookupStableId("<snippet>")`, and only a unique match (`match_count == 1`) may be edited.

## Anchor Mismatch Rule

If a stable ID does not resolve, resolves to text that no longer matches the record's quoted "currently" text, or a text anchor matches zero or several places:

- do not guess, and do not edit a paragraph that merely looks similar;
- check whether an earlier approved edit in the same change file already replaced that text, and report the edit as `ALREADY APPLIED` or `NOT APPLICABLE`, whichever is true;
- run `prepareDocument()` again only if the manifest is older than the DOCX;
- otherwise record `UNRESOLVED CHANGE` with the edit ID, the expected anchor and why it could not be applied safely, and continue only with edits that do not depend on it.

## Question Comments From Change Files

If the approved section `.md` change file contains questions, open questions, clarification items, unresolved review questions, or decision questions, add them to the Word document as question comments.

Question comments are allowed only when the question appears in the approved `.md` change file. Do not invent new questions.

Use the question text from the `.md` file as the source of truth. Preserve the meaning exactly, with only minimal wording cleanup if needed for a concise Word comment.

Use this comment format:

```text
Question
<question text from the approved change file>
```

If the question is associated with a specific edit ID, section, heading, table row, paragraph, or anchor, attach the question comment to that location.

If the question is listed in an `Open questions` section and no more specific anchor is provided, attach the question comment to the relevant section heading or nearest stable paragraph for that section.

If the approved `.md` file says there are no open questions, do not add any question comments.

Do not treat question comments as approved content edits. They are review annotations only.

Before adding a question comment, check whether the same question comment already exists. Do not create duplicate question comments when resuming work.

Include question comments in the section completion report:

- number of question comments added;
- number of question comments already present;
- any questions that could not be anchored safely.

## Comment Placement

Attach comments to:

- replaced sentence or paragraph;
- inserted paragraph;
- changed table cell or row;
- changed heading;
- relevant deleted/replacement location where possible.

If a deletion makes it impossible to anchor the comment cleanly, attach the comment to the nearest surviving heading or paragraph associated with that approved edit.

The framework writes the comment from the record's `Note` and ends it with the edit ID and the E-id(s) from `Why`, for example:

```text
Corrected: the earlier wording said all security monitoring stops, which the evidence does not support. (Ref S10-E12; evidence E-076)
```

## Word Comment OOXML Safety

When adding Word comments, preserve valid WordprocessingML structure.

For normal paragraph edits, anchor the comment range to runs inside a paragraph.

For table edits, anchor the comment inside the affected table cell paragraph. Do not attach comment markers around an entire table row. Do not place `w:commentRangeStart`, `w:commentRangeEnd`, `w:r`, or `w:commentReference` directly under `w:tr`.

Valid table comment placement must follow this shape:

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

Invalid placement that must never be produced:

```text
w:tr
  -> w:commentRangeStart
  -> w:r
     -> w:commentReference
  -> w:commentRangeEnd
```

After adding comments, inspect `word/document.xml` and confirm there are no direct `w:commentRangeStart`, `w:commentRangeEnd`, `w:r`, or `w:commentReference` elements under any `w:tr`. If any invalid table-row-level comment markup exists, fix it before saving or reporting completion.

## Deletions

If the `.md` instruction says `Do: Delete`, delete only the specified material.

Do not delete:

- surrounding blank paragraphs unless necessary for clean formatting;
- neighbouring headings;
- page breaks;
- styles;
- bookmarks;
- cross references

unless explicitly included in the approved change.

After deletion, repair only formatting artefacts directly caused by that deletion.

## Insertions

When inserting approved text, preserve the formatting style of the surrounding document.

For example:

- Heading 1 remains Heading 1;
- Heading 2 remains Heading 2;
- body text uses the document's existing body style;
- bullets use existing bullet style;
- numbered sections continue existing numbering;
- tables use the surrounding table style.

Do not introduce arbitrary fonts, colours, spacing, or custom styles.

## Table Changes

For table edits:

- preserve the existing table unless the change explicitly requires replacement;
- preserve column widths where possible;
- preserve table style;
- preserve borders;
- preserve shading;
- preserve cell alignment;
- preserve repeating headers;
- change only the specified cells or rows;
- do not recreate the entire table unless necessary.

If an approved change supplies a replacement table, reproduce it using the existing document's visual style.

## Heading And Numbering Integrity

After each approved edit, check that:

- heading levels are correct;
- section numbering is correct;
- numbering has not restarted accidentally;
- nested numbering remains valid;
- deleted sections do not leave invalid numbering;
- inserted headings use the appropriate Word heading style.

Do not independently renumber unrelated sections.

## Format Preservation

Protect the original document formatting.

Preserve:

- page size
- margins
- headers
- footers
- page numbers
- fonts
- styles
- tables
- images
- diagrams
- captions
- links
- bookmarks
- section breaks
- page breaks
- lists
- numbering
- table of contents
- document properties

Do not reformat the entire document.

## Table Of Contents And Fields

Do not unnecessarily rebuild the document.

After a section edit:

- ensure heading styles remain valid;
- update affected document fields only if necessary;
- do not change the visual structure of the Table of Contents except where an approved heading change naturally affects it.

Where automated field updates could create unrelated changes, leave them untouched and report that a final field refresh may be required after all sections are complete.

## Change Validation

After completing the section, perform a validation pass.

For every edit in the section's `.md` file, confirm one of:

- `APPLIED`
- `NOT APPLICABLE` because an earlier approved change superseded it
- `UNRESOLVED`

Verify that:

- the approved replacement text exists;
- deleted text is gone where required;
- insertions are in the correct place;
- Word comments are attached;
- comments contain the correct Edit IDs;
- no unrelated text was changed;
- formatting remains consistent;
- tables remain valid;
- section numbering remains valid;
- no content outside the authorised scope was altered.

## Change Count Safety Check

Before saving, compare:

```text
AUTHORISED CHANGES
vs
IMPLEMENTED CHANGES
```

If the document contains unexplained changes beyond:

- authorised `.md` edits;
- permitted version metadata;
- explanatory comments;
- unavoidable formatting repairs;

stop. Do not save until the unexplained modification is removed.

## Section Transaction Principle

Treat each section as a controlled transaction.

- Before section: Document is in known saved state.
- Apply: Only authorised edits for that section.
- Validate: Check all edit IDs.
- Save: Only when section is internally consistent.
- Stop: Do not start another section.

This is intended to prevent a failed Section 9 edit, for example, from contaminating Sections 10 to 16.

## Save Behaviour

Save the same working DOCX after every batch. Do not create a new version per section or per batch. If `prepareDocument()` reports more than one candidate working DOCX, stop and ask which one to use.

## Mandatory Per-Run DOCX Backup

Before editing each section, create a recoverable backup of the active DOCX that will be changed.

Example internal checkpoint:

```text
Current State Assessment - Example - v2.docx.before_section_08_20260914-193000.bak
```

This is for recovery only. Do not present multiple confusing document versions to the user unless recovery is required, but always include the backup path in the section `## Changes Report`.

## Document Integrity Check

After each section, verify that the DOCX still opens correctly.

Check particularly:

- document is not corrupt;
- all pages remain present;
- images remain embedded;
- tables remain intact;
- comments remain accessible;
- headers and footers are unchanged;
- section breaks remain intact;
- numbering is not broken.

For any section that adds or changes Word comments, include a package-level OOXML validation step:

- `unzip -t` reports no archive errors;
- `[Content_Types].xml`, `word/document.xml`, `word/_rels/document.xml.rels`, and `word/comments.xml` parse successfully;
- each comment ID has matching `w:commentRangeStart`, `w:commentRangeEnd`, and `w:commentReference` markers;
- `word/comments.xml` is referenced by content types and document relationships;
- no Word comment markers or run elements are direct children of `w:tr`;
- the DOCX renders successfully using the applicable document skill's render workflow when rendering tools are available.

## Comment Author

Where the Word-editing mechanism allows specifying a comment author, use:

```text
Wenzel Joubert
```

Do not impersonate the document author, reviewer, or user.

## Skills And Tools

You are required to use the available document-editing skill before editing any DOCX.

Before editing a DOCX:

- load and read the applicable DOCX editing skill completely;
- follow the skill's instructions, including any required operation marker before edit commands;
- use proper document tooling rather than treating the `.docx` as plain text;
- preserve native Word structure, relationships, styles, comments, and package parts;
- render or otherwise open-validate the DOCX after editing when the document skill provides a render workflow.

Use tools that preserve native Word structure and comments.

Do not convert the Word file to plain text and rebuild it unless absolutely necessary.

Do not use PDF conversion as the editing mechanism.

## Source Of Truth Priority

When executing edits, use this authority hierarchy:

1. User's explicit current instruction
2. Approved section `.md` change file
3. Current working Word document
4. Existing formatting/style conventions in the document

Do not use:

- web research;
- your own technical judgement;
- earlier review observations that are not in the approved `.md`;
- general best practices

to introduce additional document changes.

## Conflict Handling

If two approved `.md` instructions conflict:

- stop on the conflicting edit;
- report both Edit IDs;
- report the conflicting instructions;
- report why both cannot be applied safely.

Do not choose one yourself.

## Already-Applied Change Handling

If an approved change appears to already exist in the working document:

- verify it matches the approved text exactly or materially;
- do not duplicate it;
- ensure the required Word comment exists;
- mark the edit as `ALREADY APPLIED`.

Do not rewrite an already-correct paragraph simply to force a modification.

## No Duplicate Comments

Before adding a Word comment for an Edit ID, check whether a comment for that Edit ID already exists.

Do not create duplicate comments when resuming work.

This makes the agent safe to rerun.

## Final Document Rule

After the final approved section has eventually been processed, do not silently perform a document-wide clean-up.

Wait for explicit user instruction before:

- refreshing all fields;
- rebuilding the Table of Contents;
- accepting or rejecting tracked changes;
- resolving all comments;
- reformatting;
- preparing a final issue-free release copy.

The implementation phase and final publication phase are separate controlled activities.

## First Action When Starting The Project

Run `prepareDocument()` first. If it returns `NOT_READY` or `ERROR`, stop and report its message. Then process only the section you were asked to apply.
