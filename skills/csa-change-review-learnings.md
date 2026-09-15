# C-S-A-Change-Review Agent Learnings

This append-only file captures reusable lessons learned while reviewing Current State Assessment DOCX changes against approved Markdown change files.

Each entry should use this format:

```text
## YYYY-MM-DD - <short lesson title>

Context:
<section/document/task context>

Issue or risk observed:
<what made the review harder, failed, or required special handling>

Evidence used:
<what evidence identified or confirmed the issue>

Improved review approach:
<what the agent should do next time>

Validation:
<how to confirm the improved approach worked>
```

## 2026-09-14 - Initial learning log

Context:
Agent instruction update.

Issue or risk observed:
Reusable review lessons can be lost between runs if they are only mentioned in chat or buried in one reviewed section file.

Evidence used:
The review agent previously had no dedicated append-only place for review-method improvements.

Improved review approach:
After each completed review, record reusable lessons in this file and mention whether a lesson was added in the `## Change Review Report`.

Validation:
Confirm this file is updated when a review produces a reusable lesson, and confirm the change review report records either the lesson update or `No new reusable skill lesson identified`.

## 2026-09-15 - Use bounded review iterations for large sections

Context:
Agent instruction improvement after CSA review runs sometimes took too long trying to verify an entire large section and all document integrity checks in one pass.

Issue or risk observed:
A review can spend hours re-reading the same DOCX, retrying render/open checks, or rebuilding global comparison evidence without writing a partial review result.

Evidence used:
The review workflow previously had one-section scope but no review batch size, time box, run-state checkpoint, or no-progress stop condition.

Improved review approach:
For sections with more than 8 approved edit IDs, default to bounded review iteration mode. Parse the full verification inventory, select the next unreviewed batch, verify that batch's edits/comments/report claims, run the necessary DOCX integrity checks, update the `## Change Review Report`, and write `.agents/run-state/csa-change-review-section-<SECTION>.md` with the next edit ID.

Validation:
Confirm every review iteration writes durable evidence: reviewed DOCX path, current review edit IDs, statuses, integrity checks run, limitations, next edit ID, and status. If no durable review evidence changes during an iteration, stop with `NO_PROGRESS_STOP` rather than continuing indefinitely.
