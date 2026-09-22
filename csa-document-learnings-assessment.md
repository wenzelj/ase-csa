# Assessment: `current-state-assessment-document-learnings.md`

Assessed 2026-09-21. File: `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/current-state-assessment-document-learnings.md` (775 lines, ~93 KB, ~13,000 words, 45 entries written over 4 days: 14 Sep x2, 15 Sep x9, 16 Sep x10, 17 Sep x24). I read the whole file, then checked it against the agent definition, the `csa-document-agent` skill wrapper, the framework README, git history and the current state of the project folder.

## Verdict

The content is high quality but the file is doing four jobs at once, and only one of them is what it was created for. It is a genuine record of hard-won diagnoses, but as an operating aid it is too long to load, partly stale, partly contradictory, and (as far as I can find) never read at the start of a run. The fix is restructuring and promoting lessons into code, not rewriting the lessons themselves.

## What is working well (keep)

- Every entry follows a Problem / Cause / Improved approach / Validation shape, and the validation lines are concrete (validator names, match counts, comment IDs), not aspirational.
- The best entries encode judgement, not just mechanics: "do not guess when the approved locator is absent" (E-150, E-160), "check whether a broader sibling edit already consumed the target" (E-145, E-199), "check the change file's Changes Report before diagnosing a total block" (the Section 3 CORRECTION), "a fix to one text-extraction path must be checked against the other" (blockquote bug).
- The blockquote-corruption entries show the right instinct: find the root cause, scan the rest of the project for the same defect, repair, and record the scan coverage.
- The file is git-tracked (5 commits), so restructuring it is reversible.

## Findings

### 1. It is not consumed
The agent definition (`current-state-assessment-document.md`, "Continuous Skill Improvement", lines ~1012-1030) and `csa-document-agent/SKILL.md` (line 101, "Learning log") only say to *write* to it at the end of a run. Neither says to read it at the start. Compare `csa-change-authoring.md`, which explicitly reads its learnings file first (lines 90, 114). At ~93 KB it would also be too expensive to read on every run, which is probably why nobody is told to. Net effect: hard-won lessons only help if the model happens to rediscover them.

### 2. It breaks its own charter
The agent definition says lessons must be "generic enough to help future Current State Assessment document work" and to "keep project facts and approved technical changes out". The file contains 71 distinct E-numbers, 14 paragraph references (P520, P801...), ~10 named-person mentions, comment IDs, test-pass counts (7, 12, 14, 16, 17, 18, 20, 21, 24), and a few quotes of assessment wording. Those belong in an archive, not in reusable guidance.

### 3. About half the entries are framework changelog, not lessons
Roughly 22 of 45 entries read "framework now handles X / added Y to ooxml.py / N tests pass" (range wording variants, pipe-format rows, DocxEngine adoption, table cell writes, spelling normalisation, `_result_anchor`, bookmark coverage, vendor import order). Those are release notes for `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/framework/`. They go stale the moment the code moves on, and the real lesson is usually one line ("classify edits by structure, not exact phrase").

### 4. Contradictions and superseded guidance, with nothing marking them
- 15 Sep "Framework must block complex range and table operations" is reversed by 16-17 Sep ("move table and range edits into the framework", "stop letting legacy classifier drive normal runs").
- 16 Sep "Run under python3.14, not the default python3" is environment-specific; the 17 Sep device-bridge entry says the opposite works (Python 3.10 plus a `datetime.UTC` shim).
- 17 Sep "Section 3 was 31/31 blocked" is corrected by the CORRECTION entry, and E-150 and E-160 each have a "BLOCKED" entry plus a later "resolved" entry. A reader taking any single entry at face value can get the wrong answer.
- Heading style varies (` - `, `: `, ` — `, a bare date, `(cont.)`), and field names drift ("Improved approach" / "Corrected approach" / "Validate next time"; plain, bold and bullet layouts).

### 5. Environment and path drift since 17 Sep
- `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/run-state/` is cited 5 times, but that directory no longer exists. The 18 Sep "move files" commit deleted it; run-state now lives at `run-state/` in the project root.
- `csa-document-agent/SKILL.md` still points at `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/`, and that folder is gone. The document is now at `01 Current State AS Built/01 Final Version/`.
- The "true remaining work is Sections 10-16 (78 edits, 77% apply rate)" baseline, and the statement that Sections 1-9 are SECTION_COMPLETE, no longer match the folder. Only `run-state/current-state-assessment-document-section-1.md` exists (Status BLOCKED on E-4, "Could not extract a unique anchor from Where"), against a fresh change file set (`ChangesCSA_IAMPS_Section1.md` only). It looks like the project restarted on a new document generation with stable IDs (`prepareDocument` / `lookupStableId`, `@H1-P3`-style anchors). I inferred this from folder state and git; worth confirming.
- Consequently, a large share of the anchor-text failure history (Where-sentence matching, repeated headings) is about a workflow that stable IDs are meant to retire. Still valuable as background, but not as current instructions.
- The agent definition hardcodes `/opt/homebrew/bin/python3.14`, while the file documents that this fails from the Cowork device bridge.

### 6. Open loops never closed
Recorded as "not yet fixed" or "worth a later pass", with no follow-up entry: chained "after the revised text from E-nnn" edits (E-166, E-191); ambiguous generic anchors (E-213, E-224/226/230); E-240/E-241 table and glossary anchors; the promised audit of already-applied insert edits for comments mis-anchored by the `_result_anchor` bug; bookmark coverage on 6 of 8 dispatchers; `/sessions/...` path normalisation done by hand. Several may be moot after the restart, but the file does not say so.

### 7. Prose is doing the job of validators
The most damaging defect class in the file was silent (literal `>` leaking into 7 applied paragraphs, comments landing one paragraph off). Both were found by hand and recorded as lessons. They should be permanent checks.

## Recommendations (in priority order)

1. **Add a read step.** Put "read `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/learnings/csa-document-playbook.md` before the first batch" into the agent definition and the SKILL.md wrapper, mirroring what the authoring agent already does.
2. **Split the file into three, keeping every word.**
   - *Playbook* (new, target 150-200 lines / under ~12 KB): current rules only, grouped by phase (pre-flight, anchoring, blocked triage, tables, comments, validation, environments). This is the only file read at run start.
   - *Archive* (the existing file, renamed `...-archive.md`, moved out of `skills/`): untouched history, each superseded entry tagged `Status: superseded by <entry>`.
   - *Framework changelog* (into `framework/csa_docx/README.md` or a `CHANGELOG.md`): the ~22 "framework now does X" entries, with their test counts.
3. **Build a symptom-indexed triage table in the playbook** (highest-value single artefact). Draft from the file:

| Block message / symptom | First check | Then |
| --- | --- | --- |
| `Anchor match count was 0` | Unscoped `doc.search()` of the locator (or a shortened form) | Exists elsewhere = change-record locator error, send back to author. Text already replaced by a broader sibling edit = reconcile as subsumed, do not touch the DOCX. Check run-state/Changes Report for an already-applied edit. Never pick the "obviously intended" paragraph. |
| `Anchor match count was N>1` | Scope by H1+H2 heading; check spelling-variant headings (-isation/-ization); use structural facts in `Do` (bullet count) | If still ambiguous, stop for a human. No heuristics. |
| `record.text is None` / "no Text" | Is the replacement embedded in `**Do:**` instead of `**Text:**`? | Fix the record structure, not the framework. |
| `anchor_stale` on a comment after insert | Result anchor taken from pre-insert paragraph? | Use `new_anchors` from the insert result. |
| `Range boundaries not unique or out of order` | Start anchor duplicated across subsections? | Prove containment (heading < start < end <= section end), dry-run, then use framework primitives. |
| Total or very high block rate for a section | Does the change file already carry a populated Changes Report? | Backfill run-state instead of re-diagnosing. |
| `Could not extract a unique anchor from Where` | Does the `Where` list several items or use "after the revised X from E-nnn"? | Use stable IDs (`@H...`), or split the edit. |
| Framework fails only writing run-state | Permission error on the write path | Stop retrying; apply the batch manually and write state with the permitted tool. |

4. **Promote lessons into code, then delete the prose.** Add a post-apply lint (validator no. 8) that flags stray `>`, `**`, or backticks in applied paragraph text, and a check that each new comment sits on an inserted or changed paragraph. Fold the run-state completeness gate and partial-completion skip (already in the dry-run harness) into `cli_apply_section.py`. Add `/sessions/...` to real-path normalisation inside the framework. Each promoted lesson becomes a one-line pointer to the code and test.
5. **Fix path and environment drift now.** Update `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/run-state` references, the `7 IAMPS` path in SKILL.md, and the hardcoded interpreter. Replace the Python instructions with a small environment matrix (Mac Terminal vs Cowork device bridge: interpreter, `datetime.UTC` shim, path normalisation, no sudo, no outbound network).
6. **Move open issues to one tracked place** (e.g. a table in `framework-robustness-plan.md`) with owner and status, and mark each as still-relevant or moot after the stable-ID restart.
7. **Standardise the entry schema** for whatever remains: `Date | Scope (document / framework / environment) | Status (active / superseded / historical) | Trigger symptom | Action | Validation`. Drop test counts and E-numbers from active entries; keep them in the archive.
8. **Add a curation trigger** to the agent definition: when the playbook passes ~200 lines or ~12 KB, or an entry is contradicted, consolidate before appending. This resolves the tension with "append-only unless the user asks for cleanup" by having the user grant that permission once, explicitly, for the playbook only.
9. **Review the other two learnings files against the same standard.** `csa-change-authoring-learnings.md` (17 KB) is already growing fast; `csa-change-review-learnings.md` (2.6 KB) is healthy. The newly installed CSA skill pack agents and the cleanup agent have no learnings loop at all, which may be fine, but is worth a deliberate decision.

## Suggested sequence

1. Confirm the restart hypothesis (item 5 above) so the playbook targets the right workflow.
2. Create the archive (rename plus supersession tags) and the changelog extraction. Low risk, fully reversible via git.
3. Draft the playbook from the "durable" entries and the triage table, then wire the read step into the agent definition and SKILL.md.
4. Promote the two silent-corruption lessons into validators and tests.

## Limits of this assessment

I did not run the framework or its tests, and did not open the working DOCX. The 22-of-45 changelog estimate is my classification from reading the entries and is approximate. The "project restarted on a new document generation" reading is inferred from the deleted run-state files, the missing `7 IAMPS` folder, the single Section 1 change file, and the new Section 1 run-state; I have not confirmed it with you.
