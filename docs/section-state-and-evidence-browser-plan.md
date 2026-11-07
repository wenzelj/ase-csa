# CSA section state, provenance and Evidence Browser implementation plan

Status: proposed, 6 November 2026. Scope: shared `.agents` framework and `.agents/evidence-browser`; no project evidence or working DOCX edits.

## Objective

Give an assessor one consistent account of what answered each section, what the latest attempt did, what reached the working document, what remains to be reviewed, and which action is safe next. The CLI and Evidence Browser must derive those answers from the same framework state. Record enough run provenance to explain an answer without copying sensitive source text into metadata.

## Existing contracts to preserve

- `draft/runs.json` records the latest attempt and `last_ok`; `OK` means the draft sheet reached the document. Preserve these semantics and old records.
- Change files, document run-state and review/cleanup reports remain the authoritative V1 artifacts. Do not replace the Word decision gate or infer acceptance solely from a successful job.
- The Evidence Browser has separate `/draft` and `/pipeline` snapshots, `/prompts` and `/prompt-preview` APIs, a Draft answers page, an Assessment map, and section step controls. Browser jobs and locks remain the authority for a currently running operation.
- `csa status`, `csa next`, and project selection retain their existing command forms and outputs during migration; new JSON fields are additive.
- Draft and V1 lanes have different completion rules. A clean change record is not proof that the section has passed content review. Missing records are unknown, not complete.

## Target contract

Create `csa_docx.section_state`, a read-only projection. Use the visible document number and stable key together for identity; never derive one from the other. Each record should contain:

```text
identity: project key, visible number, stable key, heading, lane, working document
answer: last successful/applied answer, sheet hash, applied time, validation state
attempt: latest run ID, status, phase, time, model, error/interrupt reason
evidence: freshness result, open question count, unresolved conflicts, checked time
document: proposal/change-file identity, validation, applied edits, pending edits
review: verdict, sign-off, cleanup result, Word decision state when observed
readiness: dimensions above, issues with source paths, derived next action
provenance: run ID and manifest path when available; legacy/unknown otherwise
```

Each dimension uses `ready`, `pending`, `blocked`, `unknown`, or `not_applicable` plus a reason and source. The overall label is a presentation convenience, never the only state. A failed latest attempt and an older applied answer coexist. The projection must not mutate files, refresh an index, launch an agent, or assert a human Word decision that has not been observed.

## Delivery sequence

### 1. Specify and test the projection

Owner: framework. Add typed schema and pure readers in `framework/csa_docx/section_state.py`. Read the current `draft/runs.json`, card manifest and result, stale record, document specification, change files, document run-state, review/cleanup reports and Word decision data already used by the CLI. Document precedence, missing-file behaviour, malformed-file issues and timestamp semantics. Use hashes and explicit IDs for identity; modification times may inform freshness but must not alone prove that a sheet reached the DOCX.

Build fixtures for: never answered; successful draft; interrupted draft after success; validated but unapplied draft; stale answer; partial apply; applied awaiting review; review failure; reviewed awaiting Word decision; cleaned; clean change file; orphan or contradictory records. First compare projection results to existing `csa status` and Browser output on read-only project snapshots. No historical data migration.

Gate: every fixture has an unambiguous applied answer and latest attempt, or an explicit `unknown` issue. No case reports complete solely because a model job succeeded or a manifest exists.

### 2. Integrate CLI and backend

Owner: framework and Evidence Browser backend. Make `csa status --json` and `csa next --json` use the projection, preserving existing fields and adding the structured state. Add `csa readiness <section> [--json]` with dimension reasons and source references. Update `backend/draft_workflow.py` and `backend/pipeline.py` to consume the same projection, while retaining their page-specific counts, document metadata, job information and ETags. Add fields to `backend/models.py` and the matching frontend types. Keep existing `/draft` and `/pipeline` routes; avoid parallel readiness rules in the browser.

Gate: for the same project and section, CLI and API agree on last applied answer, latest attempt, review/Word gate and next safe action. An API snapshot refreshes when a relevant state or provenance file changes. Existing clients tolerate the additive fields.

### 3. Update Evidence Browser presentation and controls

Owner: frontend. In `DraftLane.tsx`, show last answer written to the document, latest attempt and its failure/interruption, evidence freshness and open questions as distinct items. In the Assessment map and inspector, present readiness reasons and source links. Adapt `pipelineState.ts` and `sectionSteps.ts` to use backend state for durable stage/next action; continue to overlay the live job state, unsaved proposal edits, validation response and Word lock when rendering a button. Do not enable an action merely because the durable state says it is next: existing backend preflights remain authoritative.

Gate: a page reload after an interrupted job still shows the older applied answer and the interruption. Draft and V1 views give consistent section identity and do not show a false “Complete” label. Button actions remain guarded by the backend.

### 4. Record and display provenance

Owner: framework, then browser. At the start of each answer/author/writer run, write a compact versioned manifest with run ID, UTC time, project/section/lane, selected CLI/model/profile, hashes of card/sheet inputs, effective assembled prompt, agent definition, applicable rules/skills, project context and project prompt overrides. On successful application, bind the applied artifact to the run ID and hashes; on failure, retain the attempt independently. Hash the actual resolved prompt, including project overrides, rather than only shared defaults. Avoid logging source passages, credentials or full prompts in the manifest. Existing artifact links and run logs remain available under their current access rules.

Extend the Prompts panel/preview to show effective source (`shared` or `project`) and hash. Show the applied run and latest attempt in the section inspector, with `legacy provenance unavailable` for old answers. Never imply a historical model or prompt version from current settings.

Gate: an applied answer resolves to exactly one manifest, and the browser can display its model, prompt hash, card hash and validation result. Legacy answers still load normally.

### 5. Consolidate prompt policy

Owner: framework content maintainers. Inventory duplicated rules in `csa-core-rules.md`, `csa-card-rules.md`, agent definitions, skill files, `rules_digest.py`, `prompts/answer/` and generated wrappers. Assign one owning source per rule. Generate derived text where feasible; otherwise add parity tests for deliberate duplication. Preserve project prompt overrides and their history. Run representative cards through the validators before changing answer wording.

Gate: a changed authoritative rule updates its dependent prompt or fails a targeted test. Prompt preview accurately reports the effective text source. No accidental change to evidence classification, rating gates or document mutation policy.

## Verification and rollout

Run framework state/prompt tests and Evidence Browser backend/frontend contract tests after each phase. At the integration gate, run `csa test`, `csa doctor`, browser backend tests and frontend tests/build using installed dependencies. Use read-only snapshots from all registered projects to find lane-specific cases. Exercise a browser reload and job recovery with mocks first, then inspect the local UI for status wording and button behaviour. Do not launch real answer, apply, review or cleanup jobs as a smoke test.

Deploy phases 1–3 together behind additive response fields, then retire the browser's duplicate durable-state calculations after parity checks. Phase 4 is additive. Phase 5 is a separate prompt-behaviour release. Record any discrepancies between CLI and UI as blocking issues for the corresponding phase, not as silently normalised states.

## Completion criteria

- CLI and Evidence Browser report the same durable state and next safe action for a section.
- Latest attempt and last applied answer are visibly distinct, including on failure and interruption.
- Readiness explains unknowns and blockers with the owning artifact, without treating lack of evidence as absence.
- Provenance identifies the actual inputs and prompt for new applied answers; historical answers are labelled honestly.
- Existing DOCX, evidence and Word approval rules remain enforced, and all targeted and full regression checks pass.
