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
Related issue: <I-nnn or None>
```

## Entries

## 2026-09-21 - Do not trust a fixed run-state location or a self-reported "complete"

Type: lesson
Scope: framework
Status: new
Trigger symptom: a change file has a populated `## Changes Report` (SECTION_COMPLETE) but no run-state file exists for that section, or the run-state folder has moved or vanished
Action: before any apply run, compare the run-state file (beside the working DOCX) with the change file's Changes Report. If the report says complete and there is no run-state, stop and log an issue; do not let the framework treat the section as pending. Do not diagnose a block until this check is done.
Validation: `get_section_status` returns the expected status, and no edit ID is applied twice.
Related issue: I-006

## 2026-09-21 - Cross-check numbers across a record's inserted and renumbered rows

Type: lesson
Scope: document
Status: new
Trigger symptom: a Document Map or numbered list is renumbered by some edits and extended by others in the same change record
Action: list the final numbers the whole record produces and confirm they are unique and in heading order before approving or applying. Numbers taken from stable IDs (`@H16`) are not section numbers.
Validation: the final map has no duplicate numbers and matches the Heading 1 order.
Related issue: I-007
