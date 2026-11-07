# Leads Out of the Evidence Matrix Implementation Plan

**Written:** 2026-10-29  
**Scope:** Shared CSA framework, implemented and migrated on `tetra-reveloc` first  
**Status:** Owner implementation plan; no DOCX changes

## Goal

Move gap-search hits out of `csa-work/evidence-matrix.csv` into an append-only lead store. A search hit remains a lead until its original source is read. Only source-checked evidence, analysis records and scoped NOT_FOUND search records remain in the matrix.

The completed change must:

- stop gap checks from appending UNCONFIRMED candidate rows;
- preserve the rule that a rejected hit is never offered again for the same question and source version;
- keep source-checked VERIFIED rows flowing through `evidence_matrix.py append`;
- keep NOT_FOUND rows in the matrix for this phase;
- expose evidence and leads as separate concepts in the CLI, gap-check record and browser;
- migrate `tetra-reveloc` without deleting or renumbering matrix rows;
- provide a verified rollback path.

## Live baseline

The baseline must be recalculated immediately before implementation and again before migration. At the design review on 2026-10-29, TETRA held:

- 2,792 matrix rows;
- 1,517 gap-search candidates;
- 1,247 rejected candidates;
- 261 pending candidates;
- 9 reviewed candidates;
- 347 NOT_FOUND rows;
- 1,506 unique candidate identities under `(dr_id, source, location)`, meaning 11 duplicate groups collapse during migration.

The 9 reviewed candidates cannot all become resolved leads:

- E-1362, E-1367 and E-1368 were settled by E-488 and map to `resolved`;
- E-2827 to E-2832 were read but did not answer their question and map to `not_an_answer`.

Treat these figures as acceptance evidence, not hard-coded migration constants. The migration must calculate the live figures, report drift and stop on an unclassified state.

## Fixed decisions

1. **NOT_FOUND stays in the matrix.** Moving it is a later change because Discovery Required uses its E-ID.
2. **The browser keeps the existing settlement panel.** It is retargeted to leads, with a lead-specific backend route.
3. **Phase one migrates gap-lookup candidates only.** Match both `csa_area == gap_lookup` and the recognised `Possible answer to DR-...` claim shape. Do not globally remove the UNCONFIRMED class.
4. **Gap-check verdict names remain compatible.** Keep `ANSWERED`, `CANDIDATES` and `NOT_FOUND`; a CANDIDATES result carries `lead_ids`.
5. **Answers remain VERIFIED-only.** INFERRED and CONFLICTING rows may be related evidence, but they do not enter `answer_evidence_ids`.
6. **No working DOCX is changed.** This is an evidence-workflow and browser migration only.
7. **Existing uncommitted framework work is preserved.** Do not stash, reset, discard, switch branches or commit it without owner instruction.

## Data model

### `csa-work/intake/leads.jsonl`

Append-only, one JSON object per lead:

```json
{
  "lead_id": "L-000001",
  "dr_id": "DR-DNS-B3",
  "qid": "B3",
  "question": "Which resolver is configured on the host?",
  "question_fingerprint": "sha256:...",
  "source_title": "REVELOC_discovery_HOST_20260605T001739Z: 41_dns_query_tests.txt",
  "source_ref": "stable original source reference",
  "rel_path": "01 Current State AS Built/revloc-tetra/.../41_dns_query_tests.txt",
  "source_version": "capture 2026-06-05T00:17:39Z",
  "source_class": "capture",
  "page_or_location": "41_dns_query_tests.txt lines 10-18",
  "excerpt": "...",
  "excerpt_hash": "sha256:...",
  "terms": ["resolver", "DNS"],
  "found_at": "2026-10-29T00:00:00Z",
  "legacy_evidence_ids": ["E-744"]
}
```

Rules:

- `source_ref` is always required and must remain usable for audit even when `rel_path` cannot be recovered.
- `rel_path` may be null only for an unresolved historical source. New leads must have it.
- timestamps are UTC ISO 8601;
- IDs are monotonic and never reused;
- excerpts retain the current 1,200-character maximum and secret checks;
- `legacy_evidence_ids` is present only for migrated leads and may contain several E-IDs.

### `csa-work/intake/leads-reviews.jsonl`

Append-only; the last valid record for a lead wins:

```json
{
  "lead_id": "L-000001",
  "state": "open",
  "evidence_ids": [],
  "by": "gap lookup",
  "at": "2026-10-29T00:00:00Z",
  "note": ""
}
```

Allowed states:

- `open`: not yet adjudicated;
- `not_an_answer`: the source was read and does not answer this exact question;
- `resolved`: the source or existing evidence resolved the lead; `evidence_ids` is required and every ID must exist;
- `retired`: the question was removed, renumbered or superseded; the note must explain why.

The review API validates the state transition and lead existence. Reopening is permitted only by appending `open` with an explicit note and reviewer.

### Identity and deduplication

Canonical lead identity is:

```text
(question_fingerprint, canonical rel_path or source_ref,
 source_version or excerpt_hash, page_or_location)
```

This intentionally permits a new lead when the question changes or the source content/version changes. A repeated hit for the identical identity returns the existing lead ID and does not append another object. A prior `not_an_answer`, `resolved` or `retired` lead is not reopened automatically.

## Result contracts

`gap_lookup.lookup_gap` returns:

```json
{
  "verdict": "ANSWERED | CANDIDATES | NOT_FOUND",
  "answer_evidence_ids": ["E-..."],
  "related_evidence_ids": ["E-..."],
  "lead_ids": ["L-..."],
  "queries": [],
  "searched": "...",
  "kind": "system | policy | owner",
  "owners": []
}
```

Compatibility rules:

- gap-check records gain `schema_version: 2`;
- `evidence_ids` may be emitted temporarily as an alias of `answer_evidence_ids` for read compatibility, but no new code may put lead IDs in it;
- `csa resolve-gaps --latest` refuses a schema-1 record with a clear instruction to rerun `csa gap-check`;
- `answered_blocks` consumes verified `answer_evidence_ids` only.

## Implementation sequence

### Phase 0 — Protect and baseline the live tree

- [ ] Read the root `AGENTS.md`, this plan and the applicable CSA framework/evidence-matrix skills.
- [ ] Run `csa projects`, `csa -p tetra-reveloc status`, `csa -p tetra-reveloc next` and `git status --short` inside `.agents`.
- [ ] Inspect diffs in every file this plan will touch. Integrate with the live edits; do not overwrite them.
- [ ] Record the current candidate and review counts with a read-only script.
- [ ] Run the smallest existing gap-lookup, gap-sweep, browser-backend and frontend tests to establish a baseline.
- [ ] If the work will span sessions, create or update `.agent-state/framework/STATE.md` with the objective, changed files, tests and next action.

Acceptance:

- the existing dirty state is documented;
- no unrelated file is changed;
- baseline failures are distinguished from new failures.

### Phase 1 — Add the lead store

**Create:**

- `framework/csa_docx/leads.py`
- `framework/csa_docx/tests/test_leads.py`

Required Python API:

```python
add_leads(workspace, dr_id, qid, question, hits) -> list[str]
open_leads(workspace, dr_id=None) -> list[dict]
review(workspace, lead_ids, state, by, note, evidence_ids=None) -> dict
already_read(workspace, dr_id) -> set[str]
verify(workspace) -> dict
```

Required CLI:

```text
python3 -m csa_docx.leads list --workspace W [--dr DR-ID] [--state open]
python3 -m csa_docx.leads review --workspace W L-... --state ... --by ... [--evidence E-...]
python3 -m csa_docx.leads verify --workspace W
python3 -m csa_docx.leads migrate --workspace W [--apply]
python3 -m csa_docx.leads rollback --workspace W --manifest FILE
```

Implementation requirements:

- registered-workspace validation;
- stdlib-only implementation compatible with the framework runtime;
- exclusive lock covering ID allocation, deduplication and append;
- atomic, flushed appends and recovery from an interrupted final line;
- JSON schema/type/length validation;
- secret detection equivalent to matrix excerpts;
- deterministic ordering from readers;
- last-review-wins overlay;
- `resolved` evidence-ID existence validation;
- idempotent retry behaviour;
- dry-run and verification output in JSON.

Tests:

- first ID and monotonic allocation;
- exact deduplication returns the same ID;
- changed question and changed source version create new IDs;
- terminal states are not reopened by `add_leads`;
- review overlay and valid/invalid transitions;
- resolved leads require existing evidence IDs;
- malformed/truncated JSONL is reported without silently losing earlier records;
- concurrent writers cannot allocate the same ID;
- unresolved legacy source references remain readable;
- verify reports duplicate IDs, unknown reviews and bad evidence links.

### Phase 2 — Switch gap lookup and gap sweep

**Modify:**

- `framework/csa_docx/gap_lookup.py`
- `framework/csa_docx/gap_sweep.py`
- `framework/csa_docx/tests/test_gap_lookup.py`
- `framework/csa_docx/tests/test_gap_sweep.py`
- any current focused candidate-ranking tests affected by the live uncommitted work

Changes:

- replace `_add_candidates` with `leads.add_leads`;
- retain existing ranking, vocabulary, owner/policy classification and query limits;
- split matrix results into verified answers and related evidence;
- return `lead_ids` separately;
- replace `pending_candidates` with `open_leads`;
- update `judge_pending`/triage behaviour to operate on leads or remove it if the lead store makes it redundant;
- make repeat sweeps idempotent;
- write schema-2 gap-check records;
- keep verdict counts and affected-section counts compatible;
- retire leads only after a successful complete sweep:
  - a full sweep may retire leads for questions absent from the complete active set;
  - a section-scoped sweep may retire only leads in that checked section;
  - never retire anything when `open-questions.md` is missing, empty because of an error or malformed.

Redesign `confirm_gap` so it does **not** call `lookup_gap` again. It accepts the exact lead IDs and saved search scope from the gap-check record, then:

1. validates that each lead belongs to the DR ID;
2. appends or reuses the scoped NOT_FOUND row;
3. marks the leads `not_an_answer`;
4. remains idempotent after interruption.

Tests:

- a matching index hit appends a lead and leaves matrix row count unchanged;
- a second sweep reuses the same lead IDs and appends nothing;
- rejected/resolved/retired leads are not offered again;
- changed question/source version can be offered again;
- answer evidence and related evidence are separated;
- lead IDs never appear in `evidence_ids`;
- confirm does not run a new search or create a new lead;
- scoped and full retirement rules;
- missing/malformed question input causes no retirement;
- existing ranking and SUPPLY/DNS/TIME focused tests remain green.

### Phase 3 — Switch settlement and CLI orchestration

**Modify:**

- `csa-evidence-investigator-agent.md`
- `bin/csa` (`cmd_resolve_gaps`, help text and any candidate triage command)
- `cli.yaml` or `registry.yaml` only if the owning configuration requires it
- relevant CLI/prompt tests

Settlement rules:

- read the lead and its original source, never the excerpt alone;
- check existing VERIFIED evidence first;
- if existing or new evidence answers the question, append/source-check any new VERIFIED rows first, then mark the lead `resolved` with the E-IDs;
- if the source does not answer, use schema-2 `confirm_gap` and mark the lead `not_an_answer`;
- if the question disappeared, mark the lead `retired`, not resolved;
- write lead IDs and resulting E-IDs in the settlement report;
- do not edit answer sheets or a DOCX during settlement;
- after settlement, rerun the gap check and only repair blocks with verified `answer_evidence_ids`.

The workflow must recover idempotently if it stops between the matrix append and lead review. Existing matrix duplicate detection should find the E-ID on retry, after which the lead is marked resolved.

Tests:

- printed settlement prompt names `leads.py`, lead IDs and source-read rules;
- schema-1 saved gap checks are rejected with a rerun instruction;
- resolved leads name existing E-IDs;
- a failed settlement changes no answer or DOCX;
- affected-answer routing uses verified evidence only.

### Phase 4 — Switch the Evidence Browser

**Modify:**

- `evidence-browser/backend/intake_workflow.py`
- `evidence-browser/backend/app.py`
- `evidence-browser/tests/test_intake_workflow.py`
- `evidence-browser/tests/test_backend.py`
- `evidence-browser/frontend/src/types.ts`
- `evidence-browser/frontend/src/api.ts` or the current API owner
- `evidence-browser/frontend/src/App.tsx`
- `evidence-browser/frontend/src/components/intakeSteps.ts`
- relevant frontend tests and styles
- rebuild `evidence-browser/frontend/dist/`

Backend contract:

- `snapshot()` reads leads through `leads.py`, not by regex-scanning matrix rows;
- return `open_leads` separately from matrix evidence;
- expose separate counts for:
  - evidence rows by evidence status;
  - NOT_FOUND search records;
  - open/resolved/not-answer/retired leads;
  - legacy candidate tombstones;
- add `POST /api/systems/{system_key}/leads/{lead_id}/review`;
- retain `/evidence/{evidence_id}/review` for actual evidence review;
- optionally keep a temporary candidate-review compatibility alias, but do not accept L-IDs as evidence IDs.

Frontend contract:

- keep the existing settlement panel and controls;
- label records as lead IDs;
- “Not an answer” writes `not_an_answer`;
- “Write the fact” opens the existing evidence-draft workflow, and after a successful E-ID commit marks the lead `resolved` with that ID;
- do not mark a lead resolved if evidence creation fails;
- show verified evidence and open leads as separate counts;
- do not present raw historical matrix row count as the evidence count.

Tests:

- snapshot lists only open active leads in the settlement panel;
- retired leads are counted but not offered;
- lead and evidence review routes validate ID type and state;
- write-fact success links the E-ID; failure leaves the lead open;
- intake-step state derives settlement from open leads;
- TypeScript checks and production build pass;
- built `dist/` contains the new API and labels.

### Phase 5 — Update shared rules and documentation

Update all live references found by targeted search, including:

- `.agents/README.md` and `CSA-COMMANDS.md` through their owning generator where applicable;
- `evidence-browser/README.md`;
- `csa-core-rules.md`;
- `skills/evidence-investigator/SKILL.md`;
- `skills/csa-evidence-matrix/SKILL.md`;
- `skills/csa-orchestrator/SKILL.md`;
- `skills/csa-framework-guide/SKILL.md`;
- `csa-evidence-investigator-agent.md`;
- any generated wrapper or digest owned by `registry.yaml`.

Documentation rules:

- a gap-search hit is a lead, not evidence;
- evidence lookup never searches the lead store;
- UNCONFIRMED remains a supported legacy/non-gap class in phase one;
- NOT_FOUND remains in the matrix and is scoped search history, not proof of absence;
- only source-checked VERIFIED rows can answer a document question;
- run `csa sync` only after editing the owning source, then inspect generated changes;
- update CLI help text that currently promises UNCONFIRMED candidate rows.

### Phase 6 — TETRA migration

Implement migration inside `csa_docx.leads`, not as an ad hoc script.

Dry run must:

- scan only recognised gap-lookup candidates;
- overlay the last evidence review state;
- resolve `rel_path` from the discovery index, including archived files, where possible;
- preserve `source_ref` and report every unresolved path;
- calculate duplicate collapses and every E-ID → L-ID mapping;
- classify:
  - pending → `open`;
  - rejected → `not_an_answer`;
  - reviewed with an unambiguous `settled by E-...` note → `resolved` with those IDs;
  - reviewed with an unambiguous non-answer note → `not_an_answer`;
  - anything else → `needs_manual_classification`, causing apply to stop;
- report current counts and drift from this plan;
- create a proposed manifest without changing files.

Apply must:

1. acquire a migration lock;
2. back up the lead files and evidence review log;
3. append leads and lead reviews;
4. run `leads verify` and assert every candidate has a mapping;
5. write a manifest containing file hashes, counts, mappings, duplicate groups, source warnings and every candidate’s prior latest evidence-review record;
6. append a `rejected` evidence-review tombstone for every migrated candidate, with `migrated to lead L-...; not an evidence row`;
7. verify the matrix, leads, gap readers, browser snapshot and host/graph consumers;
8. leave all matrix CSV rows untouched.

Rollback must consume the manifest, append restoring evidence-review records and append lead review records that retire the migrated leads as rolled back. It must never delete JSONL or CSV lines.

Migration acceptance for the reviewed baseline, if unchanged:

- 1,517 E-IDs are mapped;
- 1,506 leads are created;
- 261 leads are open;
- 1,242 are `not_an_answer`, including E-2827–E-2832;
- three reviewed candidates resolve to E-488;
- no reviewed candidate is classified by guesswork;
- 347 NOT_FOUND rows remain in the matrix;
- raw matrix row count is unchanged;
- all legacy candidate rows are tombstoned from live matrix readers.

### Phase 7 — Validation and completion

Run targeted tests during each phase, then the broadest applicable checks:

```text
cd /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents
.venv/bin/python -m pytest framework/csa_docx/tests/test_leads.py -q
.venv/bin/python -m pytest framework/csa_docx/tests/test_gap_lookup.py framework/csa_docx/tests/test_gap_sweep.py -q
cd evidence-browser && uv run pytest -q
cd frontend && npm run typecheck && npm run build
cd /Users/wenzel/Work/ASE/CurrentStateAssessments
.agents/bin/csa test
.agents/bin/csa doctor
```

Use the repository’s actual supported runners if these paths have changed; do not install or upgrade dependencies without approval.

End-to-end checks:

- [ ] On a registered temporary fixture, a SUPPLY gap check creates leads and does not change matrix row count.
- [ ] Repeating the check returns the same lead IDs.
- [ ] Settling one lead as not an answer records NOT_FOUND once and never reoffers it.
- [ ] Settling one lead through a source-checked fact creates/reuses VERIFIED evidence and links the lead.
- [ ] Browser counts verified evidence and open leads separately.
- [ ] `csa ev lookup` never returns an L-ID.
- [ ] `csa hosts`, graph sync and answer-card evidence contain no legacy candidate tombstones.
- [ ] TETRA migration manifest and rollback dry-run both verify.
- [ ] No DOCX timestamp, hash, tracked change or review state changed.

## Stop conditions

Stop without applying the migration if:

- the live candidate counts cannot be explained;
- a reviewed candidate cannot be classified deterministically;
- any candidate lacks a durable source reference;
- the manifest does not map every legacy candidate E-ID;
- lead verification, matrix verification or targeted tests fail;
- an existing uncommitted edit would be overwritten;
- a DOCX operation is unexpectedly requested.

## Completion report

Report:

- files changed and material design decisions;
- baseline and post-migration counts;
- manifest and backup paths;
- tests and actual results;
- unresolved source-path warnings;
- whether rollback was dry-run verified;
- confirmation that no matrix rows or DOCX content were deleted or edited;
- any follow-up work, especially a later decision about moving NOT_FOUND records.

