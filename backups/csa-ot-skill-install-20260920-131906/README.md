# IAMPS CSA Agents

This folder contains project-local agent definitions, run-state files, learning notes, and helper code for the IAMPS Current State Assessment workflow.

These files are intentionally kept inside the IAMPS workspace so each section run can use the same source of truth, change reports, backups, and recovery state.

## Agent Definitions

Three agents form the pipeline, run in this order:

```text
prepareDocument()  ->  csa-change-authoring.md  ->  [human approves]  ->  current-state-assessment-document.md  ->  csa-change-review.md
     step 0              step 1: draft                                     step 2: apply                            step 3: verify
```

- `csa-change-authoring.md`: **step 1**, authoring agent. Drafts the first proposed `ChangesCSA_*.md` for a section by comparing its current text against Discovery Data evidence. Creates the `reviews/` folder the first time it runs against a document that doesn't have one. Never touches the DOCX.
- `current-state-assessment-document.md`: **step 2**, implementation agent for applying approved Markdown change records to the working DOCX.
- `csa-change-review.md`: **step 3**, review agent for checking that the implementation agent applied approved changes correctly.

Before step 1, call `prepareDocument()` (the `csa-mcp` MCP tool -- see `framework/csa_docx/README.md`) with no arguments; it works even when nothing but the raw DOCX exists yet, and builds the stable-ID manifest (`@H...` anchors) both the authoring and review agents resolve edits against via `lookupStableId`.

Start an authoring run with:

```text
Load this agent definition:
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/csa-change-authoring.md

Act as the C-S-A-Change-Authoring Agent.

SECTION=<section-number>
AUTHOR_ITEM_LIMIT=6
RUN_SCOPE=next-authoring-batch

Draft change proposals for the requested section using the agent defaults.
```

Then a human reads the drafted `ChangesCSA_*.md` and decides whether to approve it -- nothing applies it automatically; the file's own `**Status:** Proposed changes for approval` line says so.

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
- `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/`: resumable checkpoints for section authoring, implementation, and review runs (moved out of .agents so it lives next to the document being changed); the shared stable-ID manifest `prepareDocument()` builds also lives here (`stable-ids-<docx-filename>.json`).
- `framework/`: reusable deterministic helper code for repeated DOCX and Markdown mechanics.

## Native Codex Skills

The `.agents` files are project-local prompts. They are not native Codex skills by themselves.

This workspace also contains repo-scoped native Codex skill wrappers:

```text
.agents/skills/csa-change-authoring-agent/SKILL.md
.agents/skills/csa-document-agent/SKILL.md
.agents/skills/csa-change-review-agent/SKILL.md
.agents/skills/it-ot-current-state-assessment/SKILL.md
.agents/skills/docxengine/SKILL.md
```

`it-ot-current-state-assessment` and `docxengine` are different from the other three: they are general reference skills, not wrappers around a project-local execution agent definition.

- `it-ot-current-state-assessment` covers scoping, discovery, Purdue/IEC 62443/NIST CSF/TOGAF/TIME framework mapping, gap analysis, and deliverable structure for IT and OT current state assessments. Use it for framing scope or checking coverage alongside the authoring, document, and review agents.
- `docxengine` documents the vendored DocxEngine library itself (`framework/vendor/docxengine/`) that `csa_docx/engines/docxengine_adapter.py` wraps: its hash-anchored paragraph/table addressing, the 24-tool contract, tracked-changes/comment model, the Python `Document` API, and the validation/repair/save gate. Read it before touching `docxengine_adapter.py` or debugging a DocxEngine `BLOCKED`/error result.

They allow shorter prompts such as:

```text
Use $csa-change-authoring-agent.

SECTION=6
AUTHOR_ITEM_LIMIT=6
RUN_SCOPE=next-authoring-batch
Draft change proposals for the requested section using the agent defaults.
```

then, once a human has approved the drafted change file:

```text
Use $csa-document-agent.

SECTION=6
ITERATION_EDIT_LIMIT=2
RUN_SCOPE=next-batch
Apply the requested section using the agent defaults.
```

and:

```text
Use $csa-change-review-agent.

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

- A drafted `ChangesCSA_*.md` is a proposal, not an authority, until a human approves it -- the authoring agent's `**Status:** Proposed changes for approval` line is the gate; nothing in this framework applies a change file automatically just because it exists.
- Once approved, the Markdown change file is the source of truth for implementation and review.
- The active working DOCX must be backed up before every mutation.
- Process one section at a time.
- For CLI, EVO, or Ollama runs, use small bounded batches and stop immediately after updating the DOCX, report, and run-state.
- Do not create duplicate comments when resuming.
- Do not create another DOCX copy when a valid working DOCX already exists.
