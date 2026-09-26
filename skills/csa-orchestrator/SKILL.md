---
name: csa-orchestrator
description: Coordinate an evidence-led Current State Assessment for an Operational Technology application or infrastructure service. Use when planning, progressing, or completing a CSA across several technical areas; do not use for a single isolated fact lookup.
---

# CSA Orchestrator

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Drive the assessment to a finished, reviewable result. Work on one bounded section or question set at a time and maintain visible status so analysis does not loop.

## Start

1. Confirm the application or service, program, environment, as-of date, in-scope areas, requested output, and source set. Do not invent missing project facts.
2. If project context or assessment state exists, use it. Otherwise initialise them from the files in `references/`.
3. Select the smallest specialist skill needed for the current section. Do not invoke every specialist by default.

## Control loop

For each section, follow the current-state reasoning loop in `csa-section-writer/references/current-state-reasoning.md`: `Discover -> Extract -> Correlate -> Validate -> Build System View -> Write -> Review`. The write step only starts once the system view is built; a draft that is a tour of the evidence has skipped correlation and must be redone.

1. Define its questions and acceptance criteria.
2. Gather candidate facts through `evidence-investigator`.
3. Route verified evidence to the relevant specialist analysis skill.
4. Record gaps without repeatedly searching the same unchanged source set.
5. Ask only material questions that would change the assessment.
6. Draft through `csa-section-writer` (with `csa-writing-style`) only after the evidence set is stable. The draft must pass `csa-writing-style/scripts/prose_lint.py` before review.
7. Run `csa-quality-review`, including its concision and flow check, and resolve material findings.
8. Mark the section complete, partial, blocked, or not applicable.

To tighten a section that already exists in the working DOCX, route it to the change pipeline's `EDIT_MODE=editorial` pass (`csa-change-authoring.md`), not back through drafting.

Stop when the section definition of done is met. Do not reopen a completed section unless new evidence, a contradiction, or a user correction requires it.

## Evidence boundary

The evidence classes and the current-state boundary live in `csa-section-writer/references/current-state-reasoning.md`. In short: the CSA describes the application and its system, not the evidence; a negative statement must carry its scope; and "not observed" is never written as "does not exist".

Maintain these classes exactly: `VERIFIED`, `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, and `NOT_FOUND`. General technical knowledge may explain significance but may not fill a current-state gap. Keep recommendations and future-state design out of a CSA unless explicitly requested.

## Outputs

Keep the assessment state current and report:

- completed and active sections;
- blockers and material evidence gaps;
- contradictions requiring a decision;
- next concrete action;
- files or sections changed.

Read [ASSESSMENT_STATE_TEMPLATE.yaml](references/ASSESSMENT_STATE_TEMPLATE.yaml) when creating or repairing tracking state. Read [SECTION_COVERAGE.md](references/SECTION_COVERAGE.md) when setting scope or checking overall coverage.
