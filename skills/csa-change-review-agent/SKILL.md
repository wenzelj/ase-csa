---
name: csa-change-review-agent
description: Use the project-local C-S-A-Change-Review Agent to verify that approved Markdown change records were correctly applied to a Current State Assessment DOCX, including Word comments, report accuracy, and DOCX integrity. Use for CSA section review on any Current State Assessment project, or csa-change-review tasks.
---

# CSA Change Review Agent

Use this skill when the user wants Codex to act as the C-S-A-Change-Review Agent or review a completed Current State Assessment section implementation.

The project-local review agent definition is authoritative:

```text
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/csa-change-review.md
```

Before acting, read that full agent definition and follow it. Do not copy its instructions from memory.

## Required Invocation Pattern

Treat this skill as a wrapper around the project review agent. If the user supplies `SECTION=<number>`, use that section everywhere in the review.

Default to:

```text
ITERATION_REVIEW_LIMIT=3
RUN_SCOPE=next-batch
```

For Codex CLI, EVO, Ollama, or slow local profiles, prefer `ITERATION_REVIEW_LIMIT=2` unless the user explicitly requests a larger review batch.

## Step 0: Prepare The Document

Before inspecting any DOCX, call `prepareDocument()` (the `csa-mcp` tool, no `section` argument) to confirm the working DOCX is safe to review (not open in Word, not corrupt) and that its stable-ID manifest is current. `status: NOT_READY` -> stop and report the `reasons`. Then, when locating each edit's anchor in the DOCX, call `lookupStableId(query=<the Where field>)` instead of searching by eye -- it resolves an `@H...` ID or a text snippet deterministically against the manifest `prepareDocument` just built. See `## Framework Tools (csa-mcp)` in the full agent definition for the decision tree on `unique_id`/`match_count`.

## Non-Negotiable Behaviour

- Call `prepareDocument()` first; stop on `NOT_READY`.
- Read the approved section Markdown file and its `## Changes Report` before trusting any run-state.
- Identify the working DOCX from the change report or run-state.
- Review the Markdown change file as the source of truth.
- Verify only the requested section and selected review batch unless the user explicitly requests `RUN_SCOPE=full-section`.
- Check required content changes, Word comments, comment author `Wenzel Joubert`, initials `WJ`, report accuracy, and DOCX package integrity.
- Render affected pages where available before claiming visual validation.
- Run the Evidence Check from the agent definition using the `csa-evidence-matrix` skill (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-evidence-matrix/SKILL.md`): for fact-bearing edits in the batch, look up `csa-work/evidence-matrix.csv` first, search Discovery Data only if the matrix has no answer, append new findings back to the matrix (append-only), and report `Evidence` per edit. A matrix row is a lead, not proof.
- Append or update the section `## Change Review Report` in the same Markdown file.
- Update `01 Current State AS Built/01 Final Version/run-state/csa-change-review-section-<SECTION>.md` when the review is partial or resumable.
- Add reusable review lessons to the project learning log when a real lesson is found.
- Stop immediately after reporting `PASS`, `PASS WITH NOTES`, `FAIL`, or `BLOCKED`.

## Local Resources

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/01 Final Version/run-state/`
- Evidence matrix: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/csa-work/evidence-matrix.csv` (access only via the `csa-evidence-matrix` skill)
- Review learning log: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-change-review-learnings.md`
