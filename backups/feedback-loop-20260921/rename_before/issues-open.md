# CSA Open Issues Register

The single place where blocked edits, defects and recurring problems are tracked until they are closed. Agents write here (rules are in `current-state-assessment-document.md`, section "Continuous Skill Improvement And Issue Feedback Loop"). Reusable lessons go to the learnings inbox instead: `skills/current-state-assessment-document-learnings.md`. Questions only Wenzel can answer go to `needs-decision.md`.

Register started: 2026-09-21.

## How this register works

**Lifecycle:** `open` -> `investigating` -> `needs-decision` or `fixed-pending-verify` -> `closed`.

**Buckets** (triage every issue into exactly one):

| Bucket | Meaning | Who acts |
| --- | --- | --- |
| framework-defect | The framework or DocxEngine adapter behaves wrongly | Fix in code, add a regression test |
| change-record-defect | The approved change record is malformed or its locator/text is wrong (missing `**Text:**`, non-unique `Where`, locator absent from the document) | Back to the authoring agent / Wenzel |
| document-mismatch | The document, run-state or Changes Report disagrees with the record (edit already applied, target subsumed by a broader edit, stale state) | Reconcile state, do not touch the DOCX |
| environment | Interpreter, paths, permissions, execution environment (Mac Terminal vs Cowork bridge) | Update the environment note or the tooling |
| process | A gap in the workflow or documentation itself | Update the agent definitions or playbook |
| needs-decision | Only Wenzel can decide; it has an entry in `needs-decision.md` | Wenzel |

**Fingerprint:** the normalised block message plus the edit shape, for example `Anchor match count was 0` on a paragraph replace. Before adding an issue, search this file for the fingerprint. If it exists, increment `Seen`, update `Last seen` and add the run reference. Do not create a duplicate.

**Promotion ladder:** first sighting = issue only. `Seen: 2` = propose a playbook rule. `Seen: 3`, or any silent-corruption class (wrong text applied without a block), = propose a validator or test.

**Closing:** an issue closes only with one of: (a) a code fix plus a named regression test or commit, (b) a playbook rule that is linked, or (c) an explicit won't-fix with a reason. Agents may set `fixed-pending-verify` with evidence but never `closed`; Wenzel closes. Closed issues move to the Closed section at the bottom.

**Never** resolve an issue by guessing (Anchor Mismatch Rule still applies).

## Entry format

```text
### I-<nnn> - <short title>
- Status: open | investigating | needs-decision | fixed-pending-verify
- Bucket: framework-defect | change-record-defect | document-mismatch | environment | process | needs-decision
- Source: <agent or person, and run/date>
- Fingerprint: <normalised symptom>
- Where: <section, edit ID, file>
- First seen: YYYY-MM-DD | Last seen: YYYY-MM-DD | Seen: <n>
- Symptom / evidence: <what was observed>
- Action: <next step, and who>
- Decision: <D-nnn in needs-decision.md, or None>
- Closes when: <evidence that would close it>
```

## Open issues

### I-001 - Stale Section 1 run-state points at a change file that no longer exists
- Status: fixed-pending-verify
- Bucket: document-mismatch
- Source: assessment 2026-09-21
- Fingerprint: `Could not extract a unique anchor from Where` (Section 1, E-4), raised from a stale run-state
- Where: `run-state/current-state-assessment-document-section-1.md` (workspace root)
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 1
- Symptom / evidence: The run-state reported BLOCKED on `E-4` from a change file (`..._DocumentMap_E3_E4.md`) that no longer exists. On 2026-09-21 (~04:59 UTC) the whole workspace-root `run-state/` folder was gone, including this file, so the stale state no longer exists. D-001 (archive it) was answered yes but became moot.
- Action: None for the stale file. The consequence (no run-state for a section that is now applied) is tracked in I-006.
- Decision: D-001 (answered)
- Closes when: Wenzel confirms; superseded by I-006.

### I-002 - Documented paths still point at the old `7 IAMPS` folder layout
- Status: fixed-pending-verify
- Bucket: process
- Source: assessment 2026-09-21
- Fingerprint: documentation path drift after the 2026-09-18 file move and document restart
- Where: see Remaining work below
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 1
- Symptom / evidence: Documents gave the run-state location as `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/` and used example paths with `<n> IAMPS/...` and `... - v1.docx`. That folder never existed in the current layout. Actual layout: DOCX `01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx`, change file `.../reviews/ChangesCSA_IAMPS_Section<N>.md`.
- Done (2026-09-21, per D-002 = run-state beside the DOCX): framework now resolves run-state and the stable-ID cache from the DOCX's folder; the six active documents (README.md, current-state-assessment-document.md, csa-change-authoring.md, csa-change-review.md, skills/csa-document-agent/SKILL.md, framework/csa_docx/README.md) now use `01 Current State AS Built/01 Final Version/...` and the current DOCX name; `dry_run_all_sections.py` paths corrected; two regression tests added (58 pass).
- Remaining work: (1) done: the four obsolete one-off scripts (`manual_e123.py`, `manual_e140.py`, `manual_e147.py`, `fix_e147_bullets.py`) were deleted on 2026-09-21 at Wenzel's request (nothing referenced them; recoverable from git if committed); (2) done 2026-09-21 (Wenzel: new filenames carry no numbers): canonical name is `ChangesCSA_<slug>_Section<N>.md`; examples in SKILL.md, the agent definition, the review agent and the framework README were updated; `manifest.py` still matches the legacy `_E<a>_E<b>` form so old files resolve, and a regression test covers both; (3) historical docs (`framework-robustness-plan.md`, `qwen-mcp-factory-plan.md`) keep the old paths on purpose; (4) done: the `csa-change-review.md` example path was updated.
- Decision: D-002 (answered)
- Closes when: a real framework run writes its run-state into `01 Final Version/run-state/`, and the remaining items above are done or dropped.

### I-003 - Execution environment: hardcoded Python 3.14 and Cowork bridge behaviour
- Status: open
- Bucket: environment
- Source: archived learnings (2026-09-17, in git history); not re-verified since the restart
- Fingerprint: `/opt/homebrew/bin/python3.14` not found, or `ImportError: cannot import name 'UTC' from 'datetime'`
- Where: `current-state-assessment-document.md` (~383-408), `skills/csa-document-agent/SKILL.md` (~66-78)
- First seen: 2026-09-17 | Last seen: 2026-09-17 | Seen: 1
- Symptom / evidence: The agent definition and SKILL.md hardcode the Mac Homebrew interpreter. From the Cowork device bridge that interpreter does not exist (the VM had Python 3.10; DocxEngine 1.0.0 needs 3.12+, and `datetime.UTC` needed a shim). Runs through the bridge also wrote bridge-internal `/sessions/<id>/mnt/...` paths into run-state and the Changes Report.
- Action: Decide which execution environments are supported. If Cowork is one, add a short environment note (interpreter, shim, path normalisation) and move the path normalisation into the framework. Re-verify first; this may already be resolved.
- Decision: None
- Closes when: an environment note exists in the playbook and the agent definition no longer hardcodes a single interpreter, or Cowork is declared unsupported.

### I-004 - Verify the framework end to end on the new change-record format
- Status: open
- Bucket: framework-defect (unverified hypothesis)
- Source: assessment 2026-09-21
- Fingerprint: not yet observed
- Where: `framework/csa_docx/change_parser.py`, `ooxml.py`, `run_state.py`; `reviews/ChangesCSA_IAMPS_Section1.md`
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 0
- Symptom / evidence: The new Section 1 change file uses `S1-E<n>` and `S1-A<n>` IDs and positional table-row anchors such as `@H2.8-T1-R2`. Older code and run-state used `E-<n>`. Also, S1-E1, S1-E2 and S1-E3 share the same `Where` (`@H2.8-T1-R2`), and S1-E13 and S1-E14 share `@H2.8-T1-R13`. Row insertions shift positional row numbers, so if the manifest is regenerated between edits, later edits could resolve to the wrong row. This is a hypothesis to test, not an observed failure.
- Action: Run `framework/csa_docx/tools/dry_run_all_sections.py` (or a scratch-copy batch) against Section 1 and record whether IDs parse, anchors resolve and the shared-anchor edits apply in order to the intended rows.
- Decision: None
- Closes when: the dry run passes, or each failure found has its own issue. If the row-shift hazard is real, the promotion ladder applies immediately (validator or test).

### I-005 - No curated playbook: lessons from the cleared learnings log exist only in git
- Status: open
- Bucket: process
- Source: assessment 2026-09-21; learnings cleared by Wenzel 2026-09-21
- Fingerprint: agents have no durable operating rules to read at the start of a run
- Where: `skills/current-state-assessment-document-learnings.md` (previous log: 45 entries, 14-17 Sep, last committed in `3492f3b`); summary in `csa-document-learnings-assessment.md`
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 1
- Symptom / evidence: The durable lessons (do not guess when a locator is absent, check for a subsuming broader edit, check the Changes Report before diagnosing a total block, blockquote handling, triage table) are no longer in any file agents read.
- Action: Draft `.agents/csa-document-playbook.md` (target 150-200 lines) from the assessment's recommendations and the git history, then add a read step to the agent definition.
- Decision: None
- Closes when: the playbook exists and the agent definition and SKILL.md tell agents to read it at the start of a run.

### I-006 - Section 1 applied without a run-state, and the old run-state files are gone
- Status: needs-decision
- Bucket: needs-decision
- Source: assessment 2026-09-21
- Fingerprint: change file reports SECTION_COMPLETE but no run-state exists for the section
- Where: `reviews/ChangesCSA_IAMPS_Section1.md` (Changes Report), `01 Final Version/run-state/`
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 1
- Symptom / evidence: The Changes Report says Section 1 was applied on 2026-09-21 (15 edits, backup `backups/Current State Assessment - IAMPS.before_apply_s1_20260921-140000.bak`). The DOCX confirms it: Document Map rows for Sections 2 and 3 added, rows renumbered and retitled, Glossary and Appendixes rows appended, one tracked insertion and one deletion. But no Section 1 run-state file exists anywhere. The workspace-root `run-state/` folder (16 authoring run-states, the stable-ID cache and the old Section 1 apply state) was also gone at ~04:59 UTC; I did not remove it, and it was outside the git repo, so it cannot be restored from git. Deviations from the agent definition in that apply: 2 comments for 15 edits (a comment per edit with its ID is required), 3 validation checks reported (the framework runs 7), a hand-shaped backup timestamp (`140000`), and no run-state. It probably did not go through the framework. Risk: with no run-state the framework treats Section 1 as pending and would replay `S1-E1` to `S1-E14`, duplicating rows.
- Action: Wenzel to choose how to protect Section 1 (D-003). Do not start a Section 1 apply run until then.
- Decision: D-003
- Closes when: Section 1 has a run-state that shows it complete (or it is re-applied through the framework), and the framework's behaviour on a missing run-state with a populated Changes Report is guarded or documented.

### I-007 - Approved Section 1 record gives Glossary and Appendixes the same numbers as Backup and Infrastructure
- Status: needs-decision
- Bucket: change-record-defect
- Source: assessment 2026-09-21
- Fingerprint: duplicate section numbers within one change record's inserted and renumbered rows
- Where: `S1-E11`, `S1-E12`, `S1-E13`, `S1-E14` in `ChangesCSA_IAMPS_Section1.md`; Document Map table (`@H2.8-T1`)
- First seen: 2026-09-21 | Last seen: 2026-09-21 | Seen: 1
- Symptom / evidence: E11/E12 renumber Backup & Recovery to 16 and Infrastructure Dependencies to 17 (ordinal positions, +2 offset). E13/E14 insert Glossary and Acronyms as 16 and Appendixes as 17, taking the numbers from the stable IDs `@H16`/`@H17`. The applied map lists 16 and 17 twice. In the DOCX the Heading 1 order is Backup & Recovery, Infrastructure Dependencies, Glossary and Acronyms, Appendixes, so the two inserted rows should follow Infrastructure Dependencies (likely 18 and 19; confirm against the numbers Word renders).
- Action: Wenzel to decide (D-004). Any correction needs a new approved edit; agents do not edit the approved record.
- Decision: D-004
- Closes when: a corrective edit is approved and applied and the Document Map numbers are unique. Candidate pre-flight lint: flag duplicate numbers across a record's Text fields.

## Closed issues

None yet.
