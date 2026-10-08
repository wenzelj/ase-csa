# CSA Draft Lane: a simpler pre-V1 process (plan and record)

Date: 2026-10-08 · Status: stories 1–7 built and tested, story 8 open, phase 2 (V1 lane) planned

## 1. Why

The framework does two jobs:

1. Index incoming data into the evidence matrix and the host graph.
2. Answer each CSA subsection's questions from the evidence and update the document.

Until now, every answer went through the full V1 change process, even while the document was still being built:

| Step | Model call? |
|---|---|
| Card, answer agent, search round, fix round, optional answer check | 1 to 4 calls |
| Writer pass | 1 call |
| Change file, check-change and autofix (run 2–3 times) | no |
| Apply as tracked changes, two edits per batch, with an approval record each time | no |
| Review agent, Word accept, cleanup agent | 2 calls |

The TETRA run history shows 128 check-change runs, 69 apply batches and 29 approval records.

## 2. Decisions (Wenzel, 2026-10-08)

1. **Reviewer comments before V1:** the card already carries reviewer comments as C questions. The answer covers each one, and the comment goes when the text is replaced.
2. **Change log:** yes. Each draft run adds a line to `csa-work/draft/changes-<date>.md`.
3. **Model:** chosen per run: Claude, Codex or Evo (`--cli claude|codex|evo`).
4. **V1 lane slimming:** yes. See phase 2 below.
5. **Naming rules (all lanes):**
   - Use an IP address only when it describes the system and the host is not named.
   - When a host is named, use the name.
   - Tables that capture the system give both the name and the IP, e.g. `MOTPRDREV101 (10.20.1.5)`.
   - Host names are never renamed: **RevViewer stays RevViewer**. This replaces the earlier "write Reviewer" rule.

## 3. Draft lane (built)

`stage: draft | v1` per project in `PROJECTS.yaml`. A project with no `stage:` is `draft`.

```
csa ingest           discovery index (new/changed files only) -> graph sync (captures -> matrix rows,
                     nodes, edges, host register) -> list of answered subsections whose evidence changed
csa answer N         card (no model) -> ONE draft-agent call: answer sheet with facts AND the finished
  (= csa draft N)    prose (Text:) -> hard checks only -> this run's records applied as PLAIN text ->
                     records removed again -> change log + open-questions list
csa stale            rebuild each answered card (no model) and compare it with the saved answer's inputs
csa refresh-draft    csa answer for every stale subsection
csa freeze v1        baseline copy of the DOCX in "01 Final Version/baseline/", then stage: v1
```

In the draft stage, `csa author N` is routed to the draft lane as well. Use `--legacy` for the old path.

What the draft lane drops:
- the change-file life cycle;
- check-change and autofix;
- the writer pass (merged into the draft agent);
- tracked changes and the two-edit batches;
- approval records;
- the fix-round loop on soft findings;
- review and cleanup.

What it keeps:
- the section card;
- the answer cache, which reuses an answer while its inputs are unchanged and re-asks only the changed questions (`ONLY=`);
- one search round, only if the agent asks for it;
- one fix round, only for hard errors;
- row scaffolding;
- the Word auto-close.

**Hard errors** (the only ones that stop a write): QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, REQUIREMENT_NO_FACTS. Every other finding is printed as a warning.

**Prompt size:** the draft agent definition is about 1 KB, plus a 3.2 KB rules digest and the card. It no longer loads core rules, the app skill, the writing style or the terminology guide.

### Files

| File | What |
|---|---|
| `csa-draft-agent.md` | new short agent definition |
| `references/digests/draft.md` | draft rules digest, including the new naming rules |
| `framework/csa_docx/draft_lane.py` | blocker check, plain apply of this run's records only, change log, open-questions list |
| `framework/csa_docx/answer_sheet.py` | `Text:` field (finished prose used by render); `validate --draft` (hard codes only) |
| `bin/csa` | `project_stage`, routing, `_draft_write`, `ingest`, `stale`, `refresh-draft`, `freeze`, `--cli evo`, stage in the banner, `csa answer` hints in status |
| `cli.yaml` | `evo_*` launch lines. **`codex_headless` is now plain Codex** (it used to run the evo profile). Claude headless runs in a visible window. |
| `registry.yaml` | `draft` verb (then `csa sync`) |
| `PROJECTS.yaml` | `stage:` key documented |
| Naming rule updates | digests answer/author/writer, `csa-writer-agent.md`, `csa-writing-style`, `reveloc-csa-skill`, `section_card.py` (no RevViewer -> Reviewer rewrite) |

### Tested (cloud copy of REVELOC TETRA, stub agent)

`csa answer 3.11`:
- The card was built and the stub sheet passed with 4 warnings.
- 4 records were written as plain text into the requirement rows, the Discovery Information row and Drawbridge Impact.
- No tracked changes, comments or bookmarks were left, and the new change file was removed.
- The change log and open questions were written.

`csa stale` listed 2 of 5 answered subsections as stale. `csa freeze v1` wrote the baseline copy and `stage: v1`. Framework tests: 151 passed. The 2 `test_fact_store` failures are not touched by this work.

Not yet run on real data:
- `csa ingest` (the index build needs the source files on the Mac);
- a real model call through `csa answer`.

### Known gaps / next stories

- **Story 8:** the evidence browser should hide the author, review and cleanup panels while the project is at `stage: draft`.
- **Leftover template placeholder rows:** rows such as `[Aspect] | [What was observed]` and the optional-note placeholder stay in place when the answer has fewer rows. This is existing render behaviour, and the draft lane should delete them.
- **Discovery Required:** `open-questions.md` collects every `Unknown:` line, but writing those rows into Section 8 automatically is still to do.
- **Ingest of unstructured documents:** ingest indexes them but does not yet run one investigator call per new document. Use `csa evidence N` for now.
- **Card digest bug:** the host digest treats sentence words as hosts ("Eleven", "On", "The" listed as hosts with "role not recorded").

## 4. Phase 2: slim the V1 change lane (planned)

1. Apply in one pass per change file (batch of all approved edits) instead of batches of 2. Keep the backup per run, not per batch.
2. Run check-change once, before apply. Drop the second and third runs and fold autofix into render.
3. Merge the review into apply: the deterministic checks (applied text matches, DOCX integrity) run at the end of apply. The review agent becomes optional (`csa review N` on demand).
4. Cleanup becomes framework-only: accept the reviewed tracked changes without an agent call.
5. Writer pass only for an editorial pass, never by default. The V1 author uses the same draft agent with `Text:`.

Target: V1 change = 1 model call + Wenzel's accept/reject in Word.
