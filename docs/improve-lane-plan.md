# CSA Improve Lane: incremental evidence-based answer repair

Status: proposed · 17 November 2026  
Scope: new shared framework module and new Evidence Browser screen. Existing Draft answers, `csa answer`, `csa refresh-draft`, V1 authoring, review and cleanup flows remain unchanged.

## Objective

Add a separate Improve lane for a subsection that already has an answer in the working document.
Improve reads the answer that is actually present, the previous rating and review findings, and the
evidence relevant to identified gaps. It proposes only the smallest evidence-backed corrections or
additions needed to improve that answer over time.

The lane must converge on the existing document. It must not regenerate a subsection from a fresh
card merely because new evidence is available.

## Decisions and boundaries

1. **Draft answers remain unchanged.** `DraftLane.tsx`, `draft_workflow.py`, `csa answer`,
   `csa draft`, `csa stale` and `csa refresh-draft` keep their existing behaviour and labels.
2. **Improve is a new lane, not a mode flag.** Do not add `improve=true` to `answer`, change the
   meaning of `ONLY=`, or route existing commands through the new code.
3. **The current document is the baseline.** The model may change an existing statement only when
   it has a specific correction, contradiction, reviewer finding or supported missing fact.
4. **Evidence discovery is gap-directed.** Improve searches for evidence related to the previous
   run's findings and unresolved questions. It does not freely rebuild the entire card.
5. **No silent document mutation.** Improve always creates a proposal first. The Evidence Browser
   user explicitly approves `Apply improvement`; the proposal can also be discarded.
6. **Draft-stage first.** The first implementation applies a reviewed improvement as plain text to
   a draft-lane working document, with a backup and an append-only run record. V1 tracked-change
   integration is a later extension and is not part of this module's first delivery.
7. **Evidence classes remain unchanged.** VERIFIED, INFERRED, UNCONFIRMED, CONFLICTING and
   NOT_FOUND retain their current meaning. Absence of a new hit cannot by itself justify changing a
   rating or asserting that something does not exist.

## User workflow

The new Evidence Browser screen is named **Improve answers** and is separate from **Draft answers**.

1. Open Improve answers.
2. Choose a subsection with an existing answer.
3. Inspect the current answer, rating, previous improvement attempts, review findings and open
   questions.
4. Start `Find improvement`.
5. The framework builds a bounded improvement context and runs the configured model.
6. The screen shows a side-by-side proposal:
   - current document text;
   - proposed text or structured edit;
   - evidence added or relied on;
   - reason for each change;
   - rating kept or changed, with the decision basis;
   - content deliberately left unchanged;
   - remaining unknowns.
7. The user applies or discards the proposal.
8. After apply, the screen shows the new answer hash, run ID, backup, validation result and next
   improvement opportunity.

The screen should make “no material improvement found” a successful, explicit outcome rather than
forcing a rewrite.

## Proposed module layout

### Framework

Add new files without changing the existing answer path:

| File | Responsibility |
|---|---|
| `framework/csa_docx/improve_lane.py` | Read current subsection state, build the bounded context, validate improvement proposals, apply approved draft improvements, write run records and backups. |
| `framework/csa_docx/improve_contract.py` | Typed proposal schema and edit-operation contract. |
| `framework/csa_docx/improve_context.py` | Read-only assembly of current document text, rating, review findings, prior improve records and scoped evidence. |
| `csa-improve-agent.md` | Small model contract: diagnose the current answer and return a bounded proposal, never a replacement answer sheet. |
| `references/digests/improve.md` | Rules specific to incremental repair. |
| `csa-work/improve/<section>/` | Per-project improvement proposals, run records and accepted snapshots. |

The module may reuse existing read-only section extraction, evidence lookup, document backup,
locking and validation utilities. It must not call `csa answer`, `refresh-draft`, the existing
draft agent, or the V1 author pipeline.

### CLI

Add an additive `csa improve` command through `registry.yaml` and `csa sync`:

```text
csa improve <section>             # build a proposal
csa improve <section> --check     # validate a saved proposal
csa improve <section> --apply     # apply an explicitly approved proposal
csa improve <section> --discard   # discard the pending proposal, retaining the run record
csa improve <section> --json      # machine-readable state
```

The command must refuse to operate when there is no existing answer, the working document is
ambiguous, Word holds the document open, or the proposal is stale. Those conditions must not fall
back to ordinary answering.

### Evidence Browser backend

Add a separate backend module and routes:

| Route | Purpose |
|---|---|
| `GET /api/systems/{system}/improve` | List eligible subsections and improvement state. |
| `GET /api/systems/{system}/sections/{section}/improve` | Return current answer, rating, findings, evidence summary and latest proposal. |
| `POST /api/systems/{system}/sections/{section}/improve` | Start a proposal job. |
| `GET /api/systems/{system}/improve-jobs/{job_id}` | Poll proposal/check/apply outcome. |
| `POST /api/systems/{system}/sections/{section}/improve/check` | Validate a proposal without changing the document. |
| `POST /api/systems/{system}/sections/{section}/improve/apply` | Apply a checked proposal after explicit confirmation. |
| `POST /api/systems/{system}/sections/{section}/improve/discard` | Retire the pending proposal without deleting history. |

Add `improve_workflow.py` and `improve` models. Keep the existing `/draft`, `/pipeline` and
`/jobs` contracts compatible. Improve jobs may use the common job manager and locks, but must have
distinct operation names and history so Draft answers cannot display them as answer runs.

### Evidence Browser frontend

Add:

| File | Responsibility |
|---|---|
| `frontend/src/components/ImproveLane.tsx` | New screen and proposal/apply interaction. |
| `frontend/src/components/improveTypes.ts` or additive entries in `types.ts` | API contracts. |
| `frontend/src/improveApi.ts` or additive API functions | Improve-only API calls. |
| `frontend/src/components/improve.css` | Screen-specific styling. |

Add an **Improve answers** navigation item and view. Do not change the Draft answers component or
its button text. The Improve screen should default to sections with an existing answer and show
unanswered sections as unavailable, with a reason.

## Improvement context contract

The framework should assemble a compact, inspectable context with explicit provenance:

```text
project and section identity
working document identity and content hash
current subsection text, tables and rating
current answer/run identity, if known
previous improve runs and their outcomes
latest reviewer findings, rating explanation and open questions
supporting evidence IDs already cited by the answer
new VERIFIED evidence relevant to the named gaps
related unresolved or conflicting evidence
section requirement and answer-shape rules
```

The context must distinguish:

- current document text from a draft sheet that never reached the document;
- accepted evidence from search hits or leads;
- a failed latest attempt from the last successful improvement;
- a reviewer observation from a model suggestion.

Do not put full source documents or unrestricted Discovery Data into the model context. Use the
existing evidence matrix and bounded index queries, then retain source/line references for review.

## Proposal contract

The model returns JSON or an equivalent parsed structure, not a full answer sheet:

```text
section_key
base_document_hash
base_answer_run_id
status: improve | no_material_change | blocked
diagnosis[]
edits[]
rating_decision: keep | change
new_rating: optional
rating_basis: required when changed
evidence_ids[]
remaining_questions[]
```

Each edit is bounded and addressable:

```text
block_id                  # B1, B2, narrative or table identifier
operation                 # replace_sentence | insert_after | replace_row | keep
before                    # exact current text or stable structural reference
after                     # proposed replacement, absent for keep
reason                    # must identify the finding or gap being repaired
evidence_ids[]
```

Rules enforced before apply:

- the base document hash still matches;
- every changed fact has a valid evidence ID or is an explicitly corrected unsupported statement;
- unchanged blocks are not regenerated;
- a rating change has a valid requirement basis and positive supporting evidence;
- `Not Met` is not inferred solely from missing evidence;
- an edit cannot delete a supported fact without explaining the contradiction or duplication;
- no future-state recommendation is inserted into current-state prose;
- all edits remain within the selected subsection;
- the proposal passes existing CSA prose and document validation.

## State and persistence

Use a separate directory and schema so existing Draft state is untouched:

```text
csa-work/improve/runs.json
csa-work/improve/<section>/current.json
csa-work/improve/<section>/proposal.json
csa-work/improve/<section>/history/<run-id>.json
csa-work/improve/<section>/backups/<timestamp>-before-<run-id>.docx
```

Each run records status independently from the document state:

```text
created -> context_built -> proposing -> proposed
                         -> no_material_change
                         -> blocked | failed | interrupted
proposed -> checked -> applied | discarded | stale
```

An applied improvement records the resulting document hash and the exact accepted edit list. A
failed or discarded proposal remains visible as history but must never be reported as applied.
Legacy draft answers without provenance are valid baselines and should be labelled as legacy rather
than reconstructed.

## Delivery phases

### Phase 1 — contracts and read-only state

- Add the proposal schema, context builder and improve state readers.
- Add fixtures for answered, unanswered, interrupted, no-change, stale and applied cases.
- Add `csa improve --json` and read-only backend endpoints.
- Prove that existing `csa status`, Draft answers and V1 status outputs are byte/behaviour
  compatible for representative snapshots.

### Phase 2 — proposal generation and validation

- Add the Improve agent definition and bounded prompt.
- Add proposal jobs, validation, stale-base detection and no-material-change handling.
- Add Evidence Browser proposal display with current/proposed/evidence panes.
- Use mocked model responses for deterministic tests; do not regenerate project answers as a smoke
  test.

### Phase 3 — explicit draft apply

- Add backup, document lock, bounded plain-text apply and post-apply validation.
- Add apply/discard controls and run history.
- Verify that only the selected subsection changes and that an interrupted apply leaves the document
  recoverable.

### Phase 4 — operational rollout

- Exercise Improve on a disposable project copy first.
- Compare successive passes: the second pass must preserve the first pass's supported facts and
  address only remaining findings.
- Run the complete framework and Evidence Browser tests.
- Add documentation and a short operator guide; leave Draft answers as the documented first-answer
  path.

### Later, separately scoped

V1 integration may eventually translate an accepted Improve proposal into a tracked change record.
That must be a separate design and review decision. It must not be implemented by changing the
existing `csa author`, review or cleanup flows in this work.

## Verification

Framework tests:

- context assembly uses the current document, not a stale card answer;
- evidence IDs and source scopes are preserved;
- unchanged content is not regenerated;
- rating changes require a valid basis;
- no-material-change proposals are accepted without document mutation;
- stale proposals are refused;
- failed/interrupted runs do not become applied;
- backups and document hashes are recorded;
- existing answer/draft tests remain unchanged and pass.

Evidence Browser tests:

- navigation and screen loading;
- section eligibility and state display;
- proposal preview and evidence display;
- apply confirmation, discard and stale-base handling;
- job polling and reload recovery;
- existing Draft answers and Assessment screens remain functional.

Acceptance requires:

1. A first answer can still be created exactly as it is today through Draft answers.
2. Improve can inspect an existing answer without rebuilding it from scratch.
3. A later Improve pass changes only identified, evidence-backed defects or omissions.
4. The user can see and approve every proposed document change.
5. No existing answer, refresh, author, review or cleanup flow changes behaviour.
6. A second pass demonstrably preserves supported content from the first pass and either improves it
   or records that no material improvement was found.
