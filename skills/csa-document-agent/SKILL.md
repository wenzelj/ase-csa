---
name: csa-document-agent
description: Use the project-local Current-State-Assessment-Document Agent to apply approved Markdown change records to a Current State Assessment DOCX in bounded, backed-up, resumable batches. Use for CSA section implementation on any Current State Assessment project, especially when the user gives SECTION=<number> or asks to run the current-state assessment document agent.
---

# CSA Document Agent

Use this skill when a session (Hermes, Codex, or another agent profile) acts as the Current-State-Assessment-Document Agent and applies approved Current State Assessment section changes to the Word document.

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

## Step 0: Readiness Check (before any batch)

Before the first `apply_next_batch` of a run, call `prepareDocument` once. **Do not pass `section`** - it prepares the whole document, not one section, so there's nothing to name:

- **Over MCP (`csa-mcp`):** `prepareDocument()`.
- **In Python:** `csa_docx.tools.prepareDocument(workspace="/Users/wenzel/Work/ASE/IAMPS/06 IAMPS")`.

It confirms the working DOCX is editable (not open in Word, not zero-byte or corrupt, not already failing `validate_docx`), and builds or refreshes the stable structural-ID manifest (`@H<section_path>-P<n>` / `@H<section_path>-T<n>-R<n>`) that `@`-prefixed change-file anchors resolve against, covering every heading/paragraph/table-row in the whole document, cached at `run-state/stable-ids-<docx-filename>.json`. With no `section` given, it finds the one working DOCX every CSA section's change file already points at; a second call - with or without a section - is an instant `regenerated: false` no-op. Do not loop it over every section - one call is enough unless `force_regenerate=True` is actually needed. (An explicit `section=<N>` is only required if the call errors saying the workspace has more than one distinct working DOCX and needs one to disambiguate - that's not the normal case.)

**Before drafting a `ChangesCSA_*.md` change file** (not just before applying one), run `prepareDocument` first, then call `lookupStableId` for each edit instead of quoting document text or hand-grepping the manifest JSON. Same as `prepareDocument`, leave `section` out:

- **Over MCP:** `lookupStableId(query="<snippet of the text you are about to change>")`.
- **In Python:** `csa_docx.tools.lookupStableId("<snippet>", workspace=...)`.

It reads the manifest `prepareDocument` already built (never re-opens the DOCX) and returns matching `@H...` ID(s). Check `unique_id` - it's only set when there was exactly one match:

- `unique_id` is non-null -> copy it into `**Where:**` verbatim, e.g. `**Where:** \`@H2.1.4-P2\``.
- `unique_id` is null and `match_count > 1` -> the snippet is ambiguous; narrow it (add more surrounding words, or pass `kind="paragraph"`/`"table_row"`/`"heading"`) and look again. Do not guess among `matches`.
- `match_count == 0` -> the text isn't in the document as written; re-check the snippet, or the document may have changed underfoot (`possibly_stale: true` is a hint here - re-run `prepareDocument` first).
- `status: ERROR` -> `prepareDocument` hasn't been run yet; run it first.

You can also pass an `@H...` ID itself as `query` to confirm it's still current before reusing it (e.g. an ID recorded from a previous drafting session). The framework resolves `@`-prefixed IDs before falling back to text matching, so no anchor sentence needs to be quoted at all once you have the ID.

- `status: READY` - proceed to the batch loop below. `id_manifest_summary.regenerated: false` just means the document's heading structure hadn't drifted, which is the normal case on a resumed run.
- `status: NOT_READY` - **stop and report the `reasons`.** `locked_by_word` means the user has the document open in Word and must close it; the other reasons (`missing_docx`, `empty_docx`, `unreadable_archive`, `validation_failed`) mean the document is missing or damaged and needs a human. Do not attempt a batch.
- `status: ERROR` - the section could not be resolved at all; report the message.

`apply_next_batch` runs the same checks itself before it creates a backup, so it can also return `NOT_READY` (nothing was backed up or edited) - treat that identically. The explicit step-0 call just surfaces the problem before a run starts, and is the only way to regenerate the ID manifest over MCP.

## CSA DOCX Framework (run this, not hand-edits)

The framework is the default worker. Run one bounded batch from the workspace root (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS`):

```text
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --section <SECTION> \
  --change-file "01 Current State AS Built/01 Final Version/reviews/ChangesCSA_IAMPS_Section<N>.md" \
  --docx "01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx" \
  --workspace "/Users/wenzel/Work/ASE/IAMPS/06 IAMPS" \
  --limit <ITERATION_EDIT_LIMIT> \
  --comment-author "Wenzel Joubert" \
  --comment-initials "WJ"
```

- **Interpreter matters:** the framework requires Python >= 3.10 dataclass `slots`; default `python3` here is 3.11 and fails with `dataclass() got an unexpected keyword argument 'slots'`. Use `/opt/homebrew/bin/python3.14`.
- **Batching:** it reads `- Completed edit IDs:` from the run-state, then applies the next `--limit` pending edit IDs in edit order. Scope with `--start-edit-id` / `--end-edit-id` when needed.
- **Backups:** the framework creates the timestamped `.bak` itself before mutation; verify it exists and is non-zero.
- **Side effects:** on every run it (re)writes the run-state file and appends/updates `## Changes Report` in the change file, then prints one JSON summary. Trust that JSON on success; no extra LLM inspection when framework-first.
- **Exit codes:** `0` = PARTIAL_COMPLETE/SECTION_COMPLETE; `2` = BLOCKED (the batch stops at the first blocked edit; earlier applied edits in the same run stand and pass validation). A `NOT_READY` result exits `0` with no edits applied - read the JSON `status`, not just the exit code.
- **Known framework limitation (observed 2026-09-16, Section 7 E-123):** instructions like `Replace the first two paragraphs through "<sentence>"` are classified as a complex range and return BLOCKED rather than applied. The supported bounded patterns are: unique single-paragraph replace/insert/delete, `replace this sentence and its N bullets`, `replace the content beginning ... through ...`, `Replace all content in Section X.Y.Z`, and table-row labelled cell/multi-row replacements. When the framework blocks on a range shape, stop and report BLOCKED unless manual repair is explicitly authorised.

## Non-Negotiable Behaviour

- Call `prepareDocument` for the section before the first batch of a run, and stop on `NOT_READY` instead of editing.
- Read `01 Current State AS Built/01 Final Version/run-state/current-state-assessment-document-section-<SECTION>.md` before editing when it exists.
- Do not create a new DOCX copy if the run-state or change report identifies a valid active working DOCX.
- Make and verify a timestamped backup before every DOCX mutation.
- Apply only the next bounded batch of approved edit IDs from the section change file, preferably through the Python framework.
- Add Word comments using `Wenzel Joubert` and `WJ` when the tooling supports it.
- Update the section Markdown `## Changes Report` and the run-state file after the batch.
- Validate DOCX archive/XML/comment safety and render affected pages where available.
- Read `.agents/issues-open.md` and `.agents/needs-decision.md` before the first batch. On `BLOCKED`, `NO_PROGRESS_STOP` or a validator failure, log or update the issue in `.agents/issues-open.md` before stopping (bucket, fingerprint, evidence). Never set an issue to `closed`; only Wenzel closes issues.
- Include the `Issue register` counts block in the completion report and the `## Changes Report`.
- After applying a batch, run the Evidence Check from the agent definition using the `csa-evidence-matrix` skill (`/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/csa-evidence-matrix/SKILL.md`): look up `csa-work/evidence-matrix.csv` first for each applied fact-bearing edit, search Discovery Data only if the matrix has no answer, append new findings back to the matrix, and report the result under `Evidence check`. It never changes an approved edit. Disabled by `EVIDENCE_CHECK=off`; in `EXECUTION_MODE=framework-first` it runs only with `EVIDENCE_CHECK=on`.
- Stop immediately after reporting `PARTIAL_COMPLETE`, `SECTION_COMPLETE`, `BLOCKED`, `NOT_READY`, or `NO_PROGRESS_STOP`.

## Local Resources

- Agent definitions and project docs: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/`
- Reusable framework: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/framework/csa_docx/`
- Run-state files: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/01 Current State AS Built/01 Final Version/run-state/`
- Learnings inbox: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/skills/current-state-assessment-document-learnings.md`
- Evidence matrix: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/csa-work/evidence-matrix.csv` (access only via the `csa-evidence-matrix` skill)
- Open issues register: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/issues-open.md`
- Decisions needed: `/Users/wenzel/Work/ASE/IAMPS/06 IAMPS/.agents/needs-decision.md`
