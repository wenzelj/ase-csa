# IAMPS CSA Agents

This folder contains project-local agent definitions, run-state files, learning notes, and helper code for the IAMPS Current State Assessment workflow.

These files are intentionally kept inside the IAMPS workspace so each section run can use the same source of truth, change reports, backups, and recovery state.

## Agent Definitions

- `current-state-assessment-document.md`: implementation agent for applying approved Markdown change records to the working DOCX.
- `csa-change-review.md`: review agent for checking that the implementation agent applied approved changes correctly.

Start an implementation run with:

```text
Load this agent definition:
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/current-state-assessment-document.md

Act as the Current-State-Assessment-Document Agent.

SECTION=<section-number>
ITERATION_EDIT_LIMIT=2
RUN_SCOPE=next-batch

Apply the requested section using the agent defaults.
```

Start a review run with:

```text
Load this agent definition:
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/csa-change-review.md

Act as the C-S-A-Change-Review Agent.

SECTION=<section-number>
ITERATION_REVIEW_LIMIT=2
RUN_SCOPE=next-batch

Review the requested section using the agent defaults.
```

## Folder Roles

- `skills/`: append-only project learning notes used by the agents after each task.
- `run-state/`: resumable checkpoints for section implementation and review runs.
- `framework/`: reusable deterministic helper code for repeated DOCX and Markdown mechanics.

## Native Codex Skills

The `.agents` files are project-local prompts. They are not native Codex skills by themselves.

This workspace also contains repo-scoped native Codex skill wrappers:

```text
.agents/skills/iamps-csa-document-agent/SKILL.md
.agents/skills/iamps-csa-change-review-agent/SKILL.md
.agents/skills/it-ot-current-state-assessment/SKILL.md
```

`it-ot-current-state-assessment` is different from the other two: it is a general reference methodology skill (scoping, discovery, Purdue/IEC 62443/NIST CSF/TOGAF/TIME framework mapping, gap analysis, deliverable structure) for IT and OT current state assessments, not a wrapper around a project-local execution agent definition. Use it for framing scope or checking coverage alongside the document and review agents.

They allow shorter prompts such as:

```text
Use $iamps-csa-document-agent.

SECTION=6
ITERATION_EDIT_LIMIT=2
RUN_SCOPE=next-batch
Apply the requested section using the agent defaults.
```

and:

```text
Use $iamps-csa-change-review-agent.

SECTION=6
ITERATION_REVIEW_LIMIT=2
RUN_SCOPE=next-batch
Review the requested section using the agent defaults.
```

User-level native Codex skills can also live under:

```text
/Users/wenzel/.codex/skills/<skill-name>/SKILL.md
```

The native skill wrappers for this workspace should load these project-local agent definitions instead of duplicating their full contents.

## Safety Rules

- The Markdown change file is the source of truth.
- The active working DOCX must be backed up before every mutation.
- Process one section at a time.
- For CLI, EVO, or Ollama runs, use small bounded batches and stop immediately after updating the DOCX, report, and run-state.
- Do not create duplicate comments when resuming.
- Do not create another DOCX copy when a valid working DOCX already exists.
