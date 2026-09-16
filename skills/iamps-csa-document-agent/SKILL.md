---
name: iamps-csa-document-agent
description: Use the IAMPS project-local Current-State-Assessment-Document Agent to apply approved Markdown change records to the IAMPS Current State Assessment DOCX in bounded, backed-up, resumable batches. Use for IAMPS CSA section implementation, especially when the user gives SECTION=<number> or asks to run the current-state assessment document agent.
---

# IAMPS CSA Document Agent

Use this skill when a session (Hermes, Codex, or another agent profile) acts as the IAMPS Current-State-Assessment-Document Agent and applies approved IAMPS Current State Assessment section changes to the Word document.

The project-local agent definition is authoritative:

```text
/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/current-state-assessment-document.md
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

## CSA DOCX Framework (run this, not hand-edits)

The framework is the default worker. Run one bounded batch from the workspace root (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS`):

```text
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --section <SECTION> \
  --change-file "01 Current State AS Built/<n> IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section<N>_E<a>_E<b>.md" \
  --docx "01 Current State AS Built/<n> IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx" \
  --workspace "/Users/wenzel/Work/ASE/IAMPS/06 IAMPS" \
  --limit <ITERATION_EDIT_LIMIT> \
  --comment-author "Wenzel Joubert" \
  --comment-initials "WJ"
```

- **Interpreter matters:** the framework requires Python >= 3.10 dataclass `slots`; default `python3` here is 3.11 and fails with `dataclass() got an unexpected keyword argument 'slots'`. Use `/opt/homebrew/bin/python3.14`.
- **Batching:** it reads `- Completed edit IDs:` from the run-state, then applies the next `--limit` pending edit IDs in edit order. Scope with `--start-edit-id` / `--end-edit-id` when needed.
- **Backups:** the framework creates the timestamped `.bak` itself before mutation; verify it exists and is non-zero.
- **Side effects:** on every run it (re)writes the run-state file and appends/updates `## Changes Report` in the change file, then prints one JSON summary. Trust that JSON on success; no extra LLM inspection when framework-first.
- **Exit codes:** `0` = PARTIAL_COMPLETE/SECTION_COMPLETE; `2` = BLOCKED (the batch stops at the first blocked edit; earlier applied edits in the same run stand and pass validation).
- **Known framework limitation (observed 2026-09-16, Section 7 E-123):** instructions like `Replace the first two paragraphs through "<sentence>"` are classified as a complex range and return BLOCKED rather than applied. The supported bounded patterns are: unique single-paragraph replace/insert/delete, `replace this sentence and its N bullets`, `replace the content beginning ... through ...`, `Replace all content in Section X.Y.Z`, and table-row labelled cell/multi-row replacements. When the framework blocks on a range shape, stop and report BLOCKED unless manual repair is explicitly authorised.

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

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/`
- Reusable framework: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/framework/csa_docx/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/run-state/`
- Learning log: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/current-state-assessment-document-learnings.md`
