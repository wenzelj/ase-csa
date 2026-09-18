---
name: iamps-csa-change-review-agent
description: Use the IAMPS project-local C-S-A-Change-Review Agent to verify that approved Markdown change records were correctly applied to the IAMPS Current State Assessment DOCX, including Word comments, report accuracy, and DOCX integrity. Use for IAMPS CSA section review or csa-change-review tasks.
---

# IAMPS CSA Change Review Agent

Use this skill when the user wants Codex to act as the IAMPS C-S-A-Change-Review Agent or review a completed IAMPS Current State Assessment section implementation.

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

## Non-Negotiable Behaviour

- Read the approved section Markdown file and its `## Changes Report` before trusting any run-state.
- Identify the working DOCX from the change report or run-state.
- Review the Markdown change file as the source of truth.
- Verify only the requested section and selected review batch unless the user explicitly requests `RUN_SCOPE=full-section`.
- Check required content changes, Word comments, comment author `Wenzel Joubert`, initials `WJ`, report accuracy, and DOCX package integrity.
- Render affected pages where available before claiming visual validation.
- Append or update the section `## Change Review Report` in the same Markdown file.
- Update `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/csa-change-review-section-<SECTION>.md` when the review is partial or resumable.
- Add reusable review lessons to the project learning log when a real lesson is found.
- Stop immediately after reporting `PASS`, `PASS WITH NOTES`, `FAIL`, or `BLOCKED`.

## Local Resources

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/7 IAMPS/01 Final Version/run-state/`
- Review learning log: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-change-review-learnings.md`
