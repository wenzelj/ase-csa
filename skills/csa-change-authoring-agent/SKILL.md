---
name: csa-change-authoring-agent
description: Use the project-local C-S-A-Change-Authoring Agent to draft the first proposed Markdown change record for a Current State Assessment section, comparing the document's current text against Discovery Data evidence. This is step 1 -- it runs after prepareDocument and before the Current-State-Assessment-Document Agent applies anything. Use for CSA section authoring/drafting on any Current State Assessment project, or when asked to propose changes, draft ChangesCSA files, or author a section review.
---

# CSA Change Authoring Agent

Use this skill when the user wants Codex to act as the C-S-A-Change-Authoring Agent, draft a section's proposed change file from scratch, or otherwise start the CSA change pipeline for a section that has no `ChangesCSA_*.md` yet.

The project-local authoring agent definition is authoritative:

```text
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/csa-change-authoring.md
```

Before acting, read that full agent definition and follow it. Do not copy its instructions from memory.

## Position In The Pipeline

```
prepareDocument()  ->  THIS AGENT (draft ChangesCSA_*.md)  ->  [human approves]  ->  csa-document-agent  ->  csa-change-review-agent
```

This agent creates the `reviews/` folder and its first content when none exists yet. It never opens the DOCX for writing -- it only reads it (via `prepareDocument`/`lookupStableId`) and writes Markdown.

## Required Invocation Pattern

Treat this skill as a wrapper around the project authoring agent. If the user supplies `SECTION=<number>`, use that section everywhere in the run.

Default to:

```text
AUTHOR_ITEM_LIMIT=10
RUN_SCOPE=next-authoring-batch
```

For Codex CLI, EVO, Ollama, or slow local profiles, prefer `AUTHOR_ITEM_LIMIT=6` unless the user explicitly requests a larger batch.

## Step 0: Prepare The Document

Before reading the DOCX or searching Discovery Data, call `prepareDocument()` (the `csa-mcp` tool, no `section` argument) to confirm the working DOCX is safe to read and that its stable-ID manifest is current. `status: NOT_READY` -> stop and report the `reasons`. Then, for every edit drafted, call `lookupStableId(query=<the current text being replaced>)` to get its `@H...` anchor -- never hand-type or guess one. See `## Framework Tools (csa-mcp)` in the full agent definition for the `unique_id`/`match_count` decision tree.

## Non-Negotiable Behaviour

- Call `prepareDocument()` first; stop on `NOT_READY`.
- Every proposed edit's `Where:` field is an `@H...` ID resolved via `lookupStableId`, never a hand-typed or quoted-text anchor.
- Evidence is matrix-first: for every technical fact, use the `csa-evidence-matrix` skill (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-evidence-matrix/SKILL.md`) to look up `csa-work/evidence-matrix.csv` before searching Discovery Data; search Discovery Data only for what the matrix does not answer; append every new finding (and NOT_FOUND with its scope) back to the matrix; cite E-ids in each edit's `Why`.
- Only propose an edit backed by specific cited Discovery Data evidence (file + host) or the document's own control page -- never a stylistic opinion.
- Never propose changes to Document Owner, Reviewer(s), Approver(s), signatures, or distribution-list placeholders unless explicitly authorised.
- Record ambiguous or unsupported findings under `## Open questions`, never as a guessed edit.
- Write the change file in the required structure (see the full agent definition's Output Format) -- including the `**Status:** Proposed changes for approval. This file is an approval record only.` line, which is the approval gate; nothing downstream applies a change file automatically.
- Never open the working DOCX for writing, and never touch Word comments -- that is `csa-document-agent`'s job after a human approves.
- Update the section run-state file (`run-state/csa-change-authoring-section-<SECTION>.md`).
- Record evidence-to-topic mapping lessons (required, every run) and any other reusable lesson in `.agents/skills/csa-change-authoring-learnings.md`.
- Stop immediately after reporting `PARTIAL_DRAFT_COMPLETE`, `DRAFT_COMPLETE`, `BLOCKED`, or `NO_PROGRESS_STOP`.

## Local Resources

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/`
- Discovery Data evidence: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/IAMPS Discovery Data/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/01 Final Version/run-state/`
- Evidence matrix: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/csa-work/evidence-matrix.csv` (access only via the `csa-evidence-matrix` skill)
- Authoring learning log: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-change-authoring-learnings.md`
