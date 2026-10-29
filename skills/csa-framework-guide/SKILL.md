---
name: csa-framework-guide
description: Operate the shared ASE Current State Assessment (CSA) skills, agents, evidence stores, command-line framework, and Word-document pipeline. Use when asked to start, inspect, progress, repair, review, or explain CSA work across IAMPS, UTC DTC, REVELOC TETRA, or another project registered in the shared CSA framework.
---

# CSA Framework Guide

Use the shared framework as the control plane for CSA work. Do not reproduce its prompts or infer pipeline state from memory.

## Authoritative installation

The live framework is:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents
```

Use its CLI directly when `csa` is not on `PATH`:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/bin/csa
```

Treat these as authoritative, in this order:

1. Live CLI output and working files.
2. `.agents/csa-context/PROJECTS.yaml` and the selected project's context file.
3. `.agents/registry.yaml` for agents, inputs, locks, and wrapper-skill routing.
4. The agent definition or skill loaded for the current task.
5. `.agents/README.md` and `CSA-COMMANDS.md` for explanatory documentation.

Historical reports, prior chat state, and memory help locate work but do not prove its current status.

## Establish live state first

Before making or proposing a CSA change:

1. Run `csa projects` and `csa status [SECTION]`. Confirm the project key, project root, working DOCX, lane or stage, and current pipeline state.
2. Prefer `csa -p <key> ...` for a bounded command. Use `csa use <key>` only when intentionally changing the shared active project.
3. Read the selected entry in `.agents/csa-context/PROJECTS.yaml` and its `project_context` file. Respect `known_constraints`, evidence scope, template constraints, and document selection.
4. Run `csa next` for the next framework-supported action. For environment or integration doubt, run `csa doctor`.
5. Before a DOCX mutation, confirm Word is closed and the framework has selected exactly one authoritative working document. Stop on a Word lock, ambiguous document selection, `NOT_READY`, `BLOCKED`, or a section-mapping error.

Never assume that a proposal, process exit, prior apply, or earlier review means a section is complete. Read the live change record, review report, run state, and Word-decision state.

## Route through the CLI

Use the smallest command or skill that owns the requested result:

- Status or explanation: `csa status`, `csa next`, `csa agents`, `csa help`, `csa brief`, or another read-only helper.
- Evidence: `csa evidence <section>`; gaps: `csa gaps <section>`.
- Specialist analysis: `csa analyse <skill> SECTION=<section>`.
- Evidence-led coordination across several areas: `csa ask <section>`.
- Draft-stage subsection: `csa answer <section>` or `csa draft <section>`, only when the project is in the draft lane.
- V1 tracked-change authoring: `csa author <section>`.
- Apply an existing change file: `csa apply <section>`; use the document agent only when the deterministic framework reports a blocked edit that needs it.
- Applied-change verification: `csa review <section>`.
- Finalise reviewed tracked changes: `csa cleanup <section>`, only after review sign-off and the user's Word decision.
- New template-based CSA: `csa new ...`, but only when the project context permits the shared template.
- Old-document migration: use `csa move` or `csa convert` only when that lane is configured; do not improvise a migration through ordinary authoring.

For an agent task, prefer the CLI command. It resolves the active project and generates the current prompt from the registry. Use `--print` when the present assistant will execute the prompt itself:

```text
csa <verb> <argument> --print
```

Read the printed agent definition and every required skill in full. Do not load every CSA skill: the registry and orchestrator deliberately select one task-specific agent and the smallest required specialist skill set.

## Preserve the document pipeline

For a V1 section, the normal flow is:

```text
live status -> author/change record -> tracked apply -> framework review
-> user reads and decides in Word -> cleanup -> final checks
```

Important invariants:

- `csa author` normally applies the resulting change file immediately as tracked changes. Add `--no-apply` only when the user wants authoring to stop before the DOCX changes.
- Never hand-edit the DOCX, unzip and patch OOXML, or bypass the change record because an anchor is awkward. Repair the record, mapping, scaffold, or framework path that owns the problem.
- Use stable IDs from the live manifest. Run `csa prepare` after structural changes and `csa lookup "<text>"`; never derive an `@H...` ID from a visible section number.
- Let the framework create backups and serialise DOCX operations. Do not run apply, review, cleanup, placement, conversion, or other DOCX writers concurrently.
- Preserve pending tracked changes, comments, unrelated sections, and uncommitted framework work.
- Cleanup is not a substitute for review or the user's Word acceptance gate.

## Use evidence correctly

Keep evidence, analysis, and document prose separate.

1. Query the evidence matrix first with `csa ev lookup "<question>"`.
2. Query indexed Discovery Data second with `csa index rows ...` or `csa index search "<terms>"`.
3. Read raw source files only for sources that `csa index status` identifies as unindexed or when exact source context is required.
4. Use project/application knowledge skills as terminology or interpretation aids, never as evidence of the deployed current state.

Retain the framework evidence classes: `VERIFIED`, `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, and `NOT_FOUND`. Scope negative findings. “Not observed in the reviewed sources” is not proof that something does not exist.

When `csa gap-check` finds a discovery-index hit, it records an append-only L-ID in `csa-work/intake/leads.jsonl`; the hit is not evidence and must not enter matrix lookup. Settlement reads the original source, then resolves the lead to source-checked VERIFIED E-IDs or marks it `not_an_answer`. Only VERIFIED answer IDs may trigger a document-answer repair. NOT_FOUND remains scoped search history in the matrix; UNCONFIRMED remains supported outside the gap-lookup lead workflow.

## Verify in proportion to the action

After framework or document work, use the applicable checks rather than declaring success from a zero exit code:

- `csa check-change <section>` before applying a change file.
- `csa validate <section>` and `csa review <section>` after tracked application.
- `csa lint <section>` for CSA prose.
- `csa check` after document batches and `csa check --final` only as a pre-issue gate.
- `csa test` after changing the shared framework.
- `csa status <section>` and `csa next` to confirm the resulting state.

Report the selected project and document, action completed, checks and their actual results, unresolved evidence gaps or blockers, Word decision still required, and the next concrete command. State uncertainty explicitly.

## Maintain integrations

The project-local agent wrappers and Claude commands are generated from `.agents/registry.yaml`. After changing registry entries, run:

```text
csa sync
```

Do not manually edit generated wrapper skills, `.claude/commands/csa-*.md`, `AGENTS.md`, or `CLAUDE.md`. Edit the registry or generator instead, then sync and run `csa doctor`.
