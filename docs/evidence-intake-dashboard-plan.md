# Evidence Intake Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **Evidence intake** page to the Evidence Workspace. In five plain steps it brings new data into the index, turns new documents into evidence, checks the open questions against that evidence, has a person settle what was found, and shows which subsections can now be answered.

**Architecture:** The framework gets three small capabilities. First, the index build records what came in. Second, a gap check runs the existing `gap_lookup` over every open question. Third, the evidence agent gains an intake mode for new documents. The browser exposes them through its existing allowlisted job runner (`commands.py` → `csa …`), plus one read-only snapshot route, and the new page drives them. Every matrix or graph write still goes through `evidence_matrix.py` / `graph_store.py` (append-only, source-checked). Model work runs as a framework agent in its own visible window.

**Tech Stack:** Python 3.11+ (framework, FastAPI backend), stdlib-only skill scripts (3.8+), SQLite discovery index, React + TypeScript (Vite), pytest.

**Spec:** The investigation findings below (from the 12 Oct 2026 REVELOC Confluence ingest, recorded in `claude/csa-reveloc-confluence-ingest-record.md`). Read both.

### Investigation findings (what happens today)

| Step | What exists | What is missing |
|---|---|---|
| Index new files | `csa ingest` → `discovery_index.py build` (new or changed files only; txt/csv/xlsx/docx/pdf. .doc, .pptx and images are skipped as binary) | No record of *which* files were new, changed or removed, or which could not be read |
| Captures → evidence | `graph_sync.py`: host captures become matrix rows, nodes and edges. The host register (`csa hosts build`) reads structured workbook rows (e.g. the OU inventory) | Nothing |
| Documents → evidence | Only by hand (`csa ev append`, or the one-row form on *Claims and gaps*) or by the `csa evidence SECTION` agent working one section at a time | No document-driven step. The Draft answers button says "update the evidence matrix", but documents never become matrix rows on their own |
| Search | `/search`: matrix first, then the index | Nothing (works today) |
| Use in answers | The section card offers index hits only as *unverified candidates*. `answer_sheet` rejects any evidence ID not on the card (`EVIDENCE_NOT_ON_CARD`) | Facts must be matrix rows before `csa answer` can use them |
| Close gaps | `gap_lookup.lookup_gap` searches the matrix, then the index, for one gap and adds UNCONFIRMED candidate rows. `confirm_gap` records NOT_FOUND | Nothing runs it over `draft/open-questions.md`. No place to settle candidates |
| Graph | `graph_store.py append-node/append-edge` (cites matrix IDs). `graph_sync` adds edges only for capture-grammar link rows | Document facts (e.g. CUCM SIP trunks, firewalls) need the agent |
| Fixed on 12 Oct | `evidence_matrix.py` source check and `verify` now accept `.pdf`, spaced file names, and a document cited next to a capture | Nothing |

Out of scope (follow-up): `answer_cache` marks **every** answer stale when `hosts.csv` changes at all (12 Oct: 25 of 25 subsections). This plan works around it: it decides which subsections are affected from the gap check, not from staleness.

## Global Constraints

- Every matrix write goes through `evidence_matrix.py append` / `review`. Every graph write goes through `graph_store.py append-node` / `append-edge` / `review`. No CSV is edited directly. The matrix and graph stay append-only.
- Never infer: VERIFIED rows quote the cited source (the source check must pass). Readings that depend on table layout carry `confidence: medium` and an `inference_reason`.
- Model work runs only as a framework agent launched through `csa <verb> --headless` in the invoking process. The model is chosen per run: `claude | codex | evo`.
- This page never writes the working DOCX. Answering stays on Draft answers (draft lane) or Assessment (V1).
- Framework skill scripts are stdlib only and Python 3.8+. `csa_docx` modules use Python 3.11+.
- Projects allowlist stays `{"iamps-08", "utcdtc", "tetra-reveloc"}`. The server stays loopback only.
- UI copy is plain Australian English. Host names are shown exactly as the sources write them (RevViewer stays RevViewer).
- Work on branch `feature/evidence-intake` in the `.agents` git repo (it has uncommitted work on `develop`: commit or stash it first, with the user's say-so).

## Review Focus

1. **Ingest with nothing new:** the latest intake record is kept, not overwritten with an empty one, and the page says "Nothing new since <time>" (Task 1 test `test_build_without_changes_keeps_latest`).
2. **New files the index cannot read** (.doc, .pptx, .png, scanned PDF with no text): these are listed as "not readable, supply a text or PDF copy" and never counted as evidence (Task 1 `test_record_lists_unreadable_files`, Task 4 `test_snapshot_flags_unreadable`).
3. **Gap check run twice:** this must not add duplicate candidate rows. The second run reuses the IDs (Task 2 `test_sweep_is_idempotent`).
4. **A rejected candidate:** it is never offered again on the page or by the next gap check (Task 4 `test_snapshot_hides_settled_candidates`, Task 2 `test_sweep_skips_rejected`).
5. **`open-questions.md` missing or malformed** (no `(KEY)` in a heading, a bullet without `[QID]`): no crash. Malformed lines are skipped and the page says there are no open questions yet (Task 2 `test_parse_skips_malformed`).

---

### Task 1: Intake record from the index build

**Files:**
- Modify: `.agents/skills/csa-discovery-index/scripts/discovery_index.py` (`cmd_build`, around lines 487–620)
- Test: `.agents/framework/csa_docx/tests/test_discovery_intake.py`

**Interfaces:**
- Produces: `write_intake(work_dir: Path, changes: dict, built_at: str, matrix_last_id: str) -> Path | None` in `discovery_index.py`.
- Produces: `changes = {"added": [FileChange], "changed": [FileChange], "removed": [str]}`, where `FileChange = {"rel_path", "ext", "status", "reason", "source_class", "host"}`.
- Produces: the record file `work_dir/intake/<YYYYMMDDTHHMMSSZ>.json` and a copy at `work_dir/intake/latest.json`, shaped `{"built_at_utc", "matrix_last_id", "added", "changed", "removed", "unreadable": [FileChange where status in ("skipped","error")]}`. The build JSON output gains `"intake": <record path or null>`.

- [ ] **Step 1: Write failing tests.** These build a two-file source folder through `CSA_PROJECTS_FILE` pointing at a temp `PROJECTS.yaml` (pattern from `test_evidence_source_check.py`):
  - `test_first_build_records_added_files`: add `a.txt` and `b.png` → `latest.json` has `added` rel_paths `{"a.txt","b.png"}`, `unreadable == [b.png]` with reason `"binary type .png"`.
  - `test_record_lists_unreadable_files`: the same as above, plus `status == "skipped"`.
  - `test_change_and_remove_are_recorded`: rebuild after editing `a.txt` and deleting `b.png` → `changed == [a.txt]`, `removed == ["b.png"]`.
  - `test_build_without_changes_keeps_latest`: rebuild with no change → output `intake` is null and `latest.json` is byte-identical.
  - `test_matrix_last_id_is_recorded`: with `csa-work/evidence-matrix.csv` holding E-001…E-003 → `matrix_last_id == "E-003"`.
- [ ] **Step 2: Run and verify the tests fail.** `cd .agents && .venv/bin/python -m pytest framework/csa_docx/tests/test_discovery_intake.py -q` → 5 failed.
- [ ] **Step 3: Implement.** Collect `added` (no `prev`), `changed` (`prev` existed) and `removed` (the existing `stale` list) inside the loop. Call `write_intake` after the final commit, only when `done` and at least one list is non-empty. When `--stage-dir` is used, write it under the real `work_dir`.
- [ ] **Step 4: Run the tests and verify they pass.** Same command → 5 passed. Also run `test_evidence_source_check.py` (expect the two known `WORKSPACE_NOT_REGISTERED` append failures only).
- [ ] **Step 5: Commit.** `git commit -m "index: record added, changed, removed and unreadable files per build"`

### Task 2: Gap check over the open questions

**Files:**
- Create: `.agents/framework/csa_docx/gap_sweep.py`
- Modify: `.agents/bin/csa` (new subcommand `gap-check`, next to `cmd_stale`)
- Test: `.agents/framework/csa_docx/tests/test_gap_sweep.py`

**Interfaces:**
- Consumes: `gap_lookup.lookup_gap(workspace, dr_id, text) -> {"verdict", "evidence_ids", "matrix", "index", "searched"}`.
- Produces: `parse_open_questions(text: str) -> list[OpenQuestion]`, where `OpenQuestion = {"number", "title", "key", "qid", "dr_id", "text"}`. `dr_id` is the bracket id when it starts `DR-`, otherwise `f"DR-{key}-{qid}"`.
- Produces: `sweep(workspace: Path, section_key: str | None = None) -> dict`, which writes `csa-work/intake/gap-check-<ts>.json` and `gap-check-latest.json`, shaped `{"checked_at", "questions": [OpenQuestion + {"verdict","evidence_ids"}], "affected": [{"number","key","title","answered","candidates"}]}`.
- Produces: the CLI `csa gap-check [SECTION]`, which prints a one-line-per-question summary and exits 0 (the browser's JSON comes from the file).

- [ ] **Step 1: Write failing tests.**
  - `test_parse_open_questions`: the fixture holds `## 3.11 Backup & Recovery (BAK)\n\n- [B1] the product…\n## Figure for 2.1 Executive Summary\n\n- [DR-EXECUTIVE_SUMMARY-F01] MOTPRDLOG103: role not recorded`. It expects 2 questions: (`"3.11"`, `"BAK"`, `"B1"`, `"DR-BAK-B1"`) and (`"2.1"`, `"EXECUTIVE_SUMMARY"`, `"F01"`, `"DR-EXECUTIVE_SUMMARY-F01"`). The figure heading maps to the key whose number matches. Without a match the key is `"FIGURE-<number>"`.
  - `test_parse_skips_malformed`: a heading without `(KEY)` that has no number, and a bullet without `[..]` → skipped, with no exception.
  - `test_sweep_writes_affected_sections`: monkeypatch `lookup_gap` to return `CANDIDATES` for BAK-B1 and `NOT_FOUND` otherwise → `affected == [{"key":"BAK","candidates":1,"answered":0,…}]`.
  - `test_sweep_is_idempotent`: two sweeps on a tmp workspace with a real matrix and index (one indexed text file matching a question) → the second sweep returns the same `evidence_ids` and the matrix row count is unchanged.
  - `test_sweep_skips_rejected`: after `evidence_matrix.py review <id> --state rejected`, the next sweep's verdict for that question is `NOT_FOUND`.
- [ ] **Step 2: Run the tests and verify they fail.** `.venv/bin/python -m pytest framework/csa_docx/tests/test_gap_sweep.py -q`
- [ ] **Step 3: Implement** `parse_open_questions`, `sweep` and `main(argv)`. Add `cmd_gap_check` to `bin/csa` calling `_fw_json("csa_docx.gap_sweep", ...)` with `--workspace local_path(p["project_root"])`, and register it in the argparse table with help "check every open question against the matrix and index (no model)".
- [ ] **Step 4: Run the tests and verify they pass.** Then run `bin/csa -p tetra-reveloc gap-check` and expect a summary that includes `DR-EXECUTIVE_SUMMARY-F04 … ANSWERED` (E-494 exists since 12 Oct).
- [ ] **Step 5: Commit.** `git commit -m "gap-check: run gap_lookup over every open question"`

### Task 3: Evidence agent intake mode

**Files:**
- Modify: `.agents/csa-evidence-investigator-agent.md` (new section "Intake mode")
- Modify: `.agents/registry.yaml` (new verb `intake`), then run `csa sync` (this regenerates AGENTS.md and CSA-COMMANDS.md)
- Test: `.agents/framework/csa_docx/tests/test_intake_verb.py`

**Interfaces:**
- Consumes: `csa-work/intake/latest.json` (Task 1).
- Produces: the verb `csa intake [INTAKE=latest] [--cli X] [--headless]`, with registry inputs `INTAKE=latest, MODE=INTAKE`, `locks: none`, `tier: local`, file `csa-evidence-investigator-agent.md`.
- Produces: the agent output `csa-work/intake/<record-stem>.evidence.md` (rows added, conflicts, graph items, unreadable files to request).

- [ ] **Step 1: Write a failing test.** `test_intake_prompt_names_the_record_and_rules` runs `bin/csa -p tetra-reveloc intake --print` and asserts the output contains `MODE=INTAKE`, `intake/latest.json`, `evidence_matrix.py append`, `graph_store.py append-node` and `"never infer"`.
- [ ] **Step 2: Run the test and verify it fails** (unknown verb).
- [ ] **Step 3: Write the Intake mode rules** in the agent file. These are the rules the 12 Oct ingest followed:
  - Read only `added` and `changed` files whose status is `indexed`, using `csa index search` / the file's indexed text.
  - Write one atomic claim per row, with an exact quote. Join quote parts with `" | "`. `source_title` is the file's path under its source folder.
  - Use existing `csa_area` names (`csa ev stats`). Use `--allow-new-area` only with an area name another project already uses.
  - A table-layout reading gets `confidence: medium` and an `inference_reason`. A disagreement with captures, the OU inventory or another document becomes a CONFLICTING row naming every source, with the capture stated as authoritative in `gap_or_action`.
  - Dry-run every batch first (`--dry-run`), then append.
  - Graph: add a node for each new host, service, firewall or external system the documents name, and an edge only for a relationship a row states. Every item cites the new IDs. Run `graph_store.py verify` at the end.
  - List unreadable files and the format to ask for. Never infer, never use the previous assessment as the subject, no semicolons in claims.

  Add the registry entry and run `csa sync`.
- [ ] **Step 4: Run the test and verify it passes.** `csa agents | grep intake` shows the verb.
- [ ] **Step 5: Commit.** `git commit -m "evidence agent: intake mode for new documents"`

### Task 4: Backend operations and intake snapshot

**Files:**
- Modify: `.agents/evidence-browser/backend/commands.py` (`OPERATIONS`, the `build_argv` cli check and the no-`--json` set)
- Create: `.agents/evidence-browser/backend/intake_workflow.py`
- Modify: `.agents/evidence-browser/backend/app.py` (routes)
- Modify: `.agents/evidence-browser/frontend/src/types.ts`, `frontend/src/api.ts`
- Test: `.agents/evidence-browser/tests/test_intake_workflow.py`

**Interfaces:**
- Consumes: the Task 1 record, the Task 2 `gap-check-latest.json`, and the Task 3 `*.evidence.md`.
- Produces: operations `gap_check` (`("gap-check",)`, target optional section, `workspace_write`, timeout 1800) and `intake` (`("intake", "--headless")`, options `{"cli": "identifier"}`, `workspace_write`, lock `none`, timeout 3600, cli checked against `DRAFT_CLIS`). Ingest stays the existing `ingest` operation.
- Produces: `intake_workflow.snapshot(project: dict) -> dict` = `{"index": {"built_at_utc", "files_by_status"}, "intake": record | None, "nothing_new_since": str | None, "matrix": {"rows", "by_status", "pending_review", "added_since_intake": [row]}, "graph": {"nodes", "edges"}, "candidates": [row + {"dr_id"}], "gap_check": gap-check-latest | None, "stale": int, "agent_summary": {"path", "text"} | None}`.
- Produces: routes `GET /api/systems/{system_key}/intake`, and `POST /api/systems/{system_key}/evidence/{evidence_id}/review`, with body `{"state": "rejected" | "accepted", "note": str}`, which calls `evidence_matrix.py review <id> --by "evidence workspace" --state … --note …`.
- Produces: in the frontend, `fetchIntake(system): Promise<IntakeSnapshot>` and `reviewEvidence(system, id, state, note)`.

- [ ] **Step 1: Write failing tests** (with a tmp `csa-work` built in the fixture):
  - `test_gap_check_and_intake_argv`: `build_argv(..., "intake", CommandRequest(options={"cli":"evo"}))[1][3:] == ["intake","--headless","--cli","evo"]`. `cli: "gpt"` → 422.
  - `test_snapshot_lists_added_rows_since_intake`: with `matrix_last_id "E-002"` and the matrix at E-001…E-004 → `added_since_intake` IDs are `["E-003","E-004"]`.
  - `test_snapshot_flags_unreadable`: the record's `unreadable` passes through, with `reason`.
  - `test_snapshot_hides_settled_candidates`: UNCONFIRMED rows whose claim starts `"Possible answer to DR-"` are listed, except those with a `rejected` or `accepted` entry in `evidence-reviews.jsonl`. `dr_id` is parsed from the claim.
  - `test_snapshot_without_intake`: no `intake/` folder → `intake is None` and no exception.
  - `test_review_route_refuses_other_states`: `state: "reviewed"` → 422.
- [ ] **Step 2: Run the tests and verify they fail.** `cd .agents/evidence-browser && uv run pytest tests/test_intake_workflow.py -q`
- [ ] **Step 3: Implement.** The snapshot reads the index with `sqlite3` in read-only mode (`file:…?mode=ro`), reads `draft/stale.json` for the stale count, and counts graph rows from `graph/nodes.csv` and `edges.csv`. `nothing_new_since` is the latest record's `built_at_utc` when the index's `built_at_utc` is newer and no newer record exists.
- [ ] **Step 4: Run the tests and verify they pass.** Run the whole backend suite `uv run pytest -q` and expect no new failures.
- [ ] **Step 5: Commit.** `git commit -m "evidence browser: intake snapshot, gap-check and intake jobs, candidate review"`

### Task 5: Evidence intake page

**Files:**
- Create: `.agents/evidence-browser/frontend/src/components/intakeSteps.ts`
- Create: `.agents/evidence-browser/frontend/src/components/EvidenceIntake.tsx`
- Create: `.agents/evidence-browser/frontend/src/__tests__/intakeSteps.test.ts`
- Modify: `.agents/evidence-browser/frontend/src/App.tsx` (`View` adds `"intake"`, a `NAV` entry after the portrait shown in both stages, and the render branch). Modify `styles.css`, reusing the `draft-*` classes where they fit.

**Interfaces:**
- Consumes: Task 4 `fetchIntake`, `reviewEvidence`, the existing `submitJob` / `fetchJob` / `cancelJob`, App's `openFile(file_id)`, `prepare(hit)` (opens the existing evidence draft form) and `setView`.
- Produces: `deriveIntakeSteps(snap: IntakeSnapshot, job: ReviewJob | null) -> {steps: IntakeStep[], next: StepKey}`, where `StepKey = "ingest" | "documents" | "gaps" | "settle" | "use"` and `IntakeStep = {key, title, status: "done" | "current" | "waiting" | "blocked", detail: string}`.
- Produces: `<EvidenceIntake system openFile prepare navigate investigate />`.

Page layout (one column, a step rail like Draft answers):
1. **Bring in new data**, button *Ingest new data* → `ingest`. This shows added, changed and removed files with their status. Unreadable files sit in their own warning list, labelled "Not readable: supply a text or PDF copy".
2. **Turn new documents into evidence**, with a model select (`claude | codex | evo`, remembered like `csa-draft-cli`) and the button *Run the evidence agent* → `intake`. The agent runs as one tracked job and streams output in the page. This step lists `added_since_intake` rows (ID, status, claim, source) and shows the agent summary.
3. **Check open questions**, button *Check open questions* → `gap_check`. This shows a table of each question with its verdict (Answered / Possible answer found / Not found) and evidence IDs.
4. **Settle what was found**: one card per candidate with excerpt, source (*Open source* → `openFile`) and two buttons. *Not an answer* → `reviewEvidence(id,"rejected",…)`. *Write the fact* → `prepare` prefilled from the candidate (status VERIFIED, quote, source, location, question). On commit the page calls `reviewEvidence(id,"accepted","superseded by E-…")`.
5. **Use it in the document**: the `gap_check.affected` sections, with *Open in Draft answers* (draft stage, focuses the row) or *Open in Assessment* (V1). The page does not run answers itself.

- [ ] **Step 1: Write the failing test** `intakeSteps.test.ts` in the `sectionSteps.test.ts` assert style:
  - No intake record → step 1 current, the others waiting.
  - A record with added indexed files and `added_since_intake` empty → step 2 current.
  - Rows added and no `gap_check`, or a `gap_check` older than the newest row → step 3 current.
  - One unsettled candidate → step 4 current, with detail `"1 to settle"`.
  - Candidates settled and `affected` non-empty → step 5 current, with detail `"<n> subsections can be answered again"`.
  - A running job → that step is `blocked` and the others' actions are disabled.
  - A record with only unreadable files → step 2 shows `"Nothing readable came in"`.
- [ ] **Step 2: Run the test and verify it fails.** `cd frontend && npx tsx src/__tests__/intakeSteps.test.ts`
- [ ] **Step 3: Implement** `deriveIntakeSteps`, then `EvidenceIntake.tsx`. Use the job polling pattern from `DraftLane.tsx` (2 s poll, reload on a terminal state) and the App wiring.
- [ ] **Step 4: Verify.** `npx tsx src/__tests__/intakeSteps.test.ts` prints "intake step fixtures passed". `npm run typecheck` and `npm run build` pass. Run `npx tsx src/__tests__/sectionSteps.test.ts` too.
- [ ] **Step 5: Commit.** `git commit -m "evidence browser: Evidence intake page"`

### Task 6: Docs and end-to-end check on REVELOC TETRA

**Files:**
- Modify: `.agents/evidence-browser/README.md` (an "Evidence intake" section) and the Draft answers button copy in `DraftLane.tsx` (from "update the evidence matrix" to "update hosts and graph from captures. Documents: use Evidence intake").
- Modify: `.agents/README.md` / `CSA-COMMANDS.md` (via `csa sync`) for `csa gap-check` and `csa intake`.

- [ ] **Step 1:** Run `csa -p tetra-reveloc browse`, open **Evidence intake**, and verify step 1 lists the 12 Oct files. The record is written on the next build, so drop a test `.txt` file into `revloc-tetra`, ingest, check it appears, then remove it and ingest again.
- [ ] **Step 2:** Run **Check open questions**. Expect the DR-EXECUTIVE_SUMMARY-F01/F02/F04 rows to come back Answered or Possible answer found, and 3.11 BAK to be Not found.
- [ ] **Step 3:** Settle one candidate each way, and check `evidence-reviews.jsonl` and the matrix (`csa ev verify` shows no new issues).
- [ ] **Step 4:** Commit the docs. `git commit -m "docs: evidence intake"`

## Self-review notes

- Coverage: every "missing" cell in the findings table maps to a task. Intake record → T1, documents → T3, gap check → T2, candidates and use → T4/T5, misleading button copy → T6.
- Type names checked across tasks: `write_intake`, `parse_open_questions`, `sweep`, `deriveIntakeSteps`, `IntakeSnapshot`, `fetchIntake`, `reviewEvidence`.
