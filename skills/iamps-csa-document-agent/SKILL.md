---
name: iamps-csa-document-agent
description: Use the IAMPS project-local Current-State-Assessment-Document Agent to apply approved Markdown change records to the IAMPS Current State Assessment DOCX in bounded, backed-up, resumable batches. Use for IAMPS CSA section implementation, especially when the user gives SECTION=<number> or asks to run the current-state assessment document agent.
---

# IAMPS CSA Document Agent

Use this skill when the user wants Codex to act as the IAMPS Current-State-Assessment-Document Agent or apply approved IAMPS Current State Assessment section changes to the Word document.

The project-local agent definition is authoritative:

```text
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/.agents/current-state-assessment-document.md
```

Before acting, read that full agent definition and follow it. Do not copy its instructions from memory.

## Required Invocation Pattern

Treat this skill as a wrapper around the project agent. If the user supplies `SECTION=<number>`, use that section everywhere in the run.

Default to:

```text
ITERATION_EDIT_LIMIT=3
RUN_SCOPE=next-batch
```

For Codex CLI, EVO, Ollama, or slow local profiles, prefer `ITERATION_EDIT_LIMIT=2` unless the user explicitly requests a larger batch.

When the prompt includes `EXECUTION_MODE=framework-first`, act as a thin controller: run one CSA DOCX framework batch, inspect its JSON status, and stop. Use LLM reasoning only when the framework reports `BLOCKED` or its output is invalid.

## Non-Negotiable Behaviour

- Read `.agents/run-state/current-state-assessment-document-section-<SECTION>.md` before editing when it exists.
- Do not create a new DOCX copy if the run-state or change report identifies a valid active working DOCX.
- Make and verify a timestamped backup before every DOCX mutation.
- Apply only the next bounded batch of approved edit IDs from the section change file, preferably through the Python framework.
- Add Word comments using `Wenzel Joubert` and `WJ` when the tooling supports it.
- Update the section Markdown `## Changes Report` and the run-state file after the batch.
- Validate DOCX archive/XML/comment safety and render affected pages where available.
- Stop immediately after reporting `PARTIAL_COMPLETE`, `SECTION_COMPLETE`, `BLOCKED`, or `NO_PROGRESS_STOP`.

## Local Resources

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/.agents/`
- Reusable framework: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/.agents/framework/csa_docx/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/.agents/run-state/`
- Learning log: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/.agents/skills/current-state-assessment-document-learnings.md`
