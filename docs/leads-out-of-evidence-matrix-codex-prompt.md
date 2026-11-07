# Codex CLI Prompt — Move Gap Leads Out of the Evidence Matrix

Work in:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments
```

Implement the complete plan in:

```text
.agents/docs/leads-out-of-evidence-matrix-plan.md
```

Objective: change the shared CSA framework so discovery-index hits found while checking open questions are stored as append-only leads, not UNCONFIRMED evidence-matrix rows. Update gap lookup/sweep, settlement, CLI orchestration, Evidence Browser, tests and documentation, then perform the guarded `tetra-reveloc` migration described in the plan.

Mandatory constraints:

1. Read the applicable `AGENTS.md` files and the complete implementation plan before acting. Use the CSA framework guide and evidence-matrix instructions selected by the repository.
2. Start with live state: run `csa projects`, bounded `csa -p tetra-reveloc status`, `csa -p tetra-reveloc next`, and `git status --short` inside `.agents`.
3. The `.agents` repository already has substantial uncommitted work, including changes in files this task must modify. Preserve and integrate with it. Do not stash, reset, checkout, discard, switch branches or commit existing work unless I explicitly authorise it. Inspect targeted diffs before editing.
4. Do not change a working DOCX. Do not run apply, author, review, cleanup or other DOCX-writing commands.
5. Keep NOT_FOUND records in the matrix. Migrate only recognised gap-lookup candidate rows. Do not globally remove the UNCONFIRMED class.
6. Keep gap verdict names compatible (`ANSWERED`, `CANDIDATES`, `NOT_FOUND`) while separating `answer_evidence_ids`, `related_evidence_ids` and `lead_ids`.
7. Only source-checked VERIFIED rows may satisfy `answer_evidence_ids` and trigger an answer repair.
8. Build the lead store with locking, validation, deterministic deduplication, idempotent retries, verification, migration manifest and append-only rollback. Do not create a one-off migration script.
9. `confirm_gap` must settle the exact saved lead IDs and search scope; it must not rerun lookup or create fresh leads.
10. Keep the browser’s settlement panel, but use a lead-specific API route and separate evidence/lead counts. Rebuild and test the frontend `dist/`.
11. Use `apply_patch` for edits. Use targeted reads and tests, preserve unrelated changes and keep output concise. Do not install or upgrade dependencies or change model/runtime/plugin settings.
12. For this long-running framework change, maintain `.agent-state/framework/STATE.md` if continuation state becomes useful. Keep it concise and update it at meaningful milestones.

Execution requirements:

- Follow the plan phase by phase: baseline, lead store, gap readers, settlement/CLI, browser, documentation, guarded TETRA migration, final validation.
- Write failing targeted tests before or with each behaviour change, then make them pass.
- Recalculate all live migration counts. The plan’s 2026-10-29 figures are evidence for comparison, not constants.
- Dry-run the migration first. Apply it only if every legacy candidate is mapped, reviewed candidates are classified deterministically, source references are durable, rollback data is complete and all pre-migration tests pass.
- If the live baseline is unchanged, the nine reviewed candidates must not all become resolved: E-1362/E-1367/E-1368 resolve to E-488; E-2827–E-2832 are not answers. If their latest review records have changed, follow the live records and report the drift.
- Tombstone migrated matrix candidates through append-only evidence review records after the lead files verify. Never delete or edit matrix CSV rows.
- Verify rollback in dry-run form after migration.
- Run targeted Python tests, backend tests, frontend typecheck/build/tests, `csa test` and `csa doctor` as applicable. Do not dismiss existing baseline failures; distinguish them from regressions.
- Do not stop after implementing only the storage module. Continue until every reader/writer, browser surface, documentation reference and the TETRA migration are complete, unless a stated stop condition in the plan is reached.

Stop and report rather than guessing if:

- an existing edit would be overwritten;
- a reviewed candidate is ambiguous;
- a source reference cannot be preserved durably;
- migration mapping or verification is incomplete;
- any step unexpectedly requires a DOCX write;
- tests show a data-integrity risk.

When finished, provide an evidence-backed completion report containing:

- implementation summary and changed files;
- tests run with actual results;
- pre/post matrix, NOT_FOUND and lead counts;
- migration manifest, backup and rollback-verification paths;
- unresolved warnings or follow-ups;
- explicit confirmation that no matrix row or DOCX content was deleted or directly edited.

