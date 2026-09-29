# Build lane: writing the first draft (version 0.1) of a CSA from reviewed section files, as tracked changes

Status: design, 26 Sep 2026 (story S52; revised the same day: no separate section approval, the first draft is built as tracked changes). Implementation stories: S53–S64 with S55B, S56B, S58B and S58C in `improvements/stories/`. Template: CSA_Template_v1.3 (27 Sep 2026).

**30 Sep 2026 (S185): no step between writing and the document.** A section file is placed in the working DOCX as soon as the writer finishes (`csa write` runs `csa place`), and a change file is applied as soon as the authoring agent finishes (`csa author` runs `csa apply`). The first placement creates version 0.1 from the template; later placements add their records to the same per-section change file (`ChangesCSA_<App>_Section<N>.md`, edit IDs numbered on) and apply them as tracked changes with evidence comments. A rewritten section file is placed again: its new text replaces the old as tracked changes. `csa qa` still reviews each section, but its verdict no longer gates the document; a NOT READY section is rewritten and placed again. `csa build` remains for building every section file at once into a project that has no document yet, and `csa build --preview` for a clean read-only copy. The one human approval is unchanged: Wenzel accepts or rejects the tracked changes in Word, then `csa review N` and `csa cleanup N`. `--no-apply` on `csa write` / `csa author` stops after the agent. See section 4a.

## Versions

The build writes version **0.1** ("Initial draft"). Each peer-review round is made through the revise lane and moves the document to the next 0.x version, with a new revision-history row. It becomes **1.0** only when it is issued after the last review. `--doc-version` overrides the 0.1 default.

## 1. Why

The framework is built to *correct* a CSA. Its main path edits an existing DOCX one anchored paragraph at a time, through change records that each need authoring, approval, apply, review and cleanup. That is the right control for revising an issued baseline. It is the wrong unit for producing the first draft, where every paragraph is new: the ceremony is multiplied by the number of paragraphs, and the writer agent's drafts have nowhere to go.

The build lane adds one direct path for the first draft:

```text
BUILD LANE (first draft 0.1, template CSAs)                  REVISE LANE (after the baseline, unchanged)
evidence -> analysis -> section files                  csa author N -> csa check-change N
csa check-section + csa qa (no human step)             csa approve N -> csa apply N
csa build -> working DOCX 0.1 as TRACKED CHANGES        csa review N -> read in Word -> csa cleanup N
Wenzel accepts / rejects / edits in Word
csa cleanup N  -> clean baseline v1
```

There is one human approval, and it happens in Word: `csa build` writes every statement as a tracked insertion with a Word comment listing its evidence IDs, and Wenzel accepts, rejects or edits each one, as in the revise lane. `csa cleanup` then refuses while tracked changes remain, removes the comments, and the result is the baseline. After that, every change goes through the revise lane. The build lane only runs on a project that has no working DOCX yet.

Table-cell edits (requirement rows, including the Rating dropdown, Discovery Information rows and the other tables) are tracked too since S64 (27 Sep 2026), so every built statement can be accepted or rejected in Word.

## 2. Principle: build reuses the apply engine

No new DOCX-writing code. `csa build` turns reviewed section files into ordinary change records and applies them with the existing `csa_docx.tools.apply_next_batch(..., track_changes=True)`, exactly as `csa apply` does. The mechanics were proven (with `track_changes=False`; tracking only changes how the same edits are marked) on 26 Sep 2026 against a fresh document made from `CSA_Template_v1.1.dotx`:

| Step | Result |
| --- | --- |
| `new_csa.py` creates the document from the template | CREATED |
| `prepareDocument()` builds the manifest | READY: 66 headings, 89 table rows |
| `lookupStableId("SEP-TIME-01")` | one match, `@H4.5-T1-R2` (requirement rows resolve by Req ID) |
| Apply three records (a requirement row as `Observed:` / `Assessment:`, a Discovery Information bullet, the Drawbridge Impact paragraph), `track_changes=False` | SECTION_COMPLETE, all 3 applied |
| Package check | 0 `w:ins`, 0 `w:del`; the Rating cell reads "Not Met" |
| `check_csa.py` | 0 errors (2 warnings: the placeholders still unfilled) |
| Side effect | 3 Word comments added, one per edit, holding its evidence. In a real build they stay for Wenzel's review and `csa cleanup` removes them; a preview strips them (S59) |

What the engine cannot do (recorded in `template-structure.md`): add or remove table rows, bullets or headings, or target a whole table. The build therefore runs `scaffold_csa.py` first to set the number of rows and bullets, then replaces each placeholder by stable ID.

## 3. Section files

### Location and names

`WORK_DIR/sections/<order>-<slug>.md`, one file per template block, for example:
- `csa-work/sections/2.1-executive-summary.md`
- `csa-work/sections/3.04-time-synchronisation.md`
- `csa-work/sections/4-governance.md`
- `csa-work/sections/5.1-discovery-coverage.md`
- `csa-work/sections/5.4-patch-and-update-tooling.md`

The order prefix only sorts the files; the `heading:` front-matter key decides where the content goes.

### Format

Flat front matter (no nesting, parsed without PyYAML, like `PROJECTS.yaml`), then fixed `##` headings. Everything is plain prose, `- ` bullets or Markdown pipe tables with a header row. No evidence IDs, stable IDs or Markdown emphasis appear in rendered text; the same hygiene rules as `csa check-change` apply.

```markdown
---
block: domain
heading: Time Synchronisation
status: draft
---

## Requirements

| Req ID | Current State | Rating |
| --- | --- | --- |
| SEP-TIME-01 | All captured hosts take time from two enterprise time servers; nothing inside OT provides time. | Not Met |

## Discovery Information

| Aspect | Configuration Observed | Coverage / Source |
| --- | --- | --- |
| Time source | Two enterprise time servers, configured by Group Policy | All captured hosts; w32tm output |
| Local time service | Windows Time runs as a client only; no host serves time to others | All captured hosts; listening ports |

## Discovery Notes

The time servers sit in the enterprise IT domain, outside the OT boundary.

## Drawbridge Impact

If OT is isolated, the hosts keep running on their last synchronised time and drift apart. Authentication fails once the skew passes the Kerberos tolerance; before that, log timestamps lose accuracy.

## Evidence

| Statement | Evidence |
| --- | --- |
| SEP-TIME-01 | E-012, E-044 |
| Discovery Information 1 | E-013 |
| Discovery Information 2 | E-045 |
| Discovery Notes | E-047 |
| Drawbridge Impact | E-012, E-046 |
```

The `## Evidence` table is never rendered. It is the traceability record, and every rendered statement must appear in it: a requirement by its Req ID, a table row or bullet as `<section heading> <n>` (numbered from 1 in file order), a single paragraph (such as `Discovery Notes`) by its section heading. That satisfies "E-ids live in the change record, never in the prose" without a separate sidecar file.

### Block kinds

| `block:` | Template target | `##` sections in the file | How it fills |
| --- | --- | --- | --- |
| `domain` | a 3.x domain (Heading 2 = `heading:`) | `## Requirements` (every Req ID of that domain, once); `## Discovery Information` (table Aspect / Configuration Observed / Coverage / Source, at least one row); optional `## Discovery Notes` (one short paragraph for a finding that does not fit the table; never bullets); `## Drawbridge Impact` (one paragraph). 3.1 may add `## Hosts and roles found` (Host(s) / Environment / Role); 3.2 may add `## Accounts, groups and service accounts found` (Account / Group / Type / Host(s) / Purpose / Role) | Requirement rows replaced as `Observed:` / `Assessment:`; table rows scaffolded to the count, then replaced as pipe rows; the optional note paragraph replaced, or deleted when there is no note; paragraph replaced |
| `executive-summary` | 2.1 Executive Summary | `## Summary` (one to three paragraphs) | The three placeholder paragraphs are replaced in order; unused ones are deleted. The figure placeholder is left for a person. |
| `governance` | 4 Governance Note and Next Steps | `## Actions` (bullets: system-specific actions with owner and target date) | The three standard actions stay; the placeholder bullet is scaffolded to the count, then replaced |
| `migration` | 5 Migration Discovery (heading `Migration Discovery`: `## Summary` only) or a 5.2–5.6 subsection | optional `## Summary` (one paragraph: the intro); `## Table` where the template subsection has a table (5.2, 5.4, 5.5), with the template's columns; optional `## Notes` (one short paragraph) under the 5.4 table; `## Findings` (bullets) in 5.3 and 5.6 | Intro paragraph replaced; table rows scaffolded, then replaced; the note paragraph replaced or deleted; bullets scaffolded, then replaced. For 5.5 the `## Table` header row renames the two `[Host group]` columns; a CSA that needs more host-group columns adds them by hand in Word after the build (neither the framework nor `scaffold_csa.py` can add columns) |
| `coverage` | 5.1 Discovery Coverage | optional `## Summary`; `## Hosts` (table Host / Role / Discovery Script Run / Notes) | Rows scaffolded to the count, then replaced. S61 generates this file from the discovery index. |
| `glossary` | Appendix B | `## Terms` (table Term / Definition) | Standard rows kept; project terms appended by scaffolding the row count up, then replacing the new rows |

Document Control (1.1) and the cover come from the document properties, which `new_csa.py` sets. The build adds one revision-history row (1.2) from its own arguments. Appendix A (the OT 3.5 destinations) is pre-filled in the template and is not a block.

### Rules that `csa check-section` enforces (S55, S55B, S58B)

- `block:` is one of the kinds above, and `heading:` exists in the template for that kind (from `template-blocks.json`; straight and curly quotes match).
- Every required `##` section is present, no unknown or repeated `##` section appears, and every table has exactly the template's column count.
- `## Discovery Notes` and `## Notes` are exactly one paragraph: no bullets, no table, not several paragraphs.
- Domain: every Req ID of the domain appears exactly once, and no others; Rating is one of `Met`, `Partially Met`, `Not Met`, `Not Applicable`; Current State is at most 50 words (a warning).
- Every rendered statement has a row in `## Evidence` with at least one E-id that exists in the evidence matrix (coverage files cite captures instead). Unused Evidence rows and a missing matrix are warnings.
- Rendered text is free of E-ids, `@H` IDs, Markdown emphasis and backticks (errors), and `prose_lint.py` / `term_lint.py` run over it (warnings).

## 4. Lifecycle and gates

| Status | Set by | Meaning |
| --- | --- | --- |
| `draft` | the writer agent (`csa write`) | Written from approved evidence; may change freely |
| `reviewed` | `csa qa` on the section file, verdict READY or READY WITH DECLARED GAPS | Content-checked by the system; no human step here |
| `built` | `csa build` | In the document as tracked changes, recorded with the build ID. From now on the text is edited in Word or through the revise lane, never in the section file. |

There is no separate section approval. The human gate is Wenzel's review of the tracked changes in Word, closed by `csa cleanup` for each section (which refuses while tracked changes remain). `csa place` and `csa build` refuse a section that fails `csa check-section`; since S185 neither needs a READY review first (`csa sections` still shows the verdict).

## 4a. Placement: `csa place` (S185)

```text
csa write 3.4        writer agent -> sections/3.04-time-synchronisation.md (status: draft)
  -> csa place 3.04  check-section -> [create 0.1 from the template if there is no document]
                     -> scaffold this section's rows/bullets -> prepareDocument(force)
                     -> plan records -> append to reviews/ChangesCSA_<App>_Section3.md (IDs numbered on,
                        inserted before the ## Changes Report) -> record approval (Status line + .approval.json)
                     -> apply_next_batch(track_changes=True) until SECTION_COMPLETE -> status: built
csa qa 3.4           review; NOT READY -> csa write 3.4 again -> placed again as tracked changes
Word                 Wenzel accepts / rejects -> csa review 3 -> csa cleanup 3
```

- `csa place <file|number>` takes a file name, stem, section number (`3.4` finds `3.04-*.md`; `Executive Summary` is 2.1) or heading. The system name comes from `--system-name`, else the existing document's name, else the project context's `application`; Prepared For from `--prepared-for` or the context's `organisation`.
- Placements run one at a time per document folder (a file lock), so parallel fleet workers or story runs are safe. A document open in Word is saved and closed first (`--keep-open` refuses instead).
- A failed first placement leaves no half-made document behind. A later failure leaves the edits already applied as tracked changes; fix the section file and place it again, or `csa apply N --agent`.
- `csa fleet` queues `place <section>` after every write/summary task and `apply <section> --until-done` after every author task, holding the DOCX and section locks, so the section's qa task waits for it and a failed placement skips it.

## 5. `csa build`

```text
csa build [--sections all | 3.04,3.05,...] [--preview] [--system-name ...] [--prepared-for ...] [--version 0.1]
```

Preconditions (refuse with a clear message otherwise):
1. The project uses the CSA template. Projects whose working document is on its own template (UTC DTC today, per `known_constraints` in its context file) use the revise lane only.
2. Without `--preview`: the project has no working DOCX yet, and no `reviews/ChangesCSA_*` files. The build creates the first draft once. With `--preview`, output goes to `csa-work/build/archive/preview-<timestamp>/`. The `archive` folder name keeps it out of `prepareDocument()`'s search.
3. Every selected section file passes `csa check-section` with no errors and has a READY review newer than the file, unless `--preview` (which accepts drafts and says so in the file name). A preview is a clean read-only copy: no tracked changes, no comments.

Steps:
1. **Create:** `new_csa.py` with properties from the arguments, falling back to the project context file.
2. **Plan:** `build_plan.py` (S57) reads the section files and the template map and works out, for every block, the rows and bullets needed and the stable ID of each placeholder.
3. **Scaffold:** `scaffold_csa.py rows|bullets` for every count that differs from the template (S58); `prepareDocument()` is run again afterwards.
4. **Records:** the planner writes canonical change files, `reviews/ChangesCSA_<App>_Section<N>.md`, one per framework section. Edit IDs are `S<N>-E<n>`, `Why:` holds the E-ids from the section's Evidence table, and `Note:` reads "Built from reviewed section file <name>". Each is approved by the build itself (`by`: "csa build <build-id>"), with the usual per-edit hashes, so `csa status`, `csa review` and `csa cleanup` treat it like any other approved change file.
5. **Apply:** `apply_next_batch(section, limit=500, track_changes=True)` per section, until SECTION_COMPLETE; a BLOCKED edit stops the build and is reported with its section file and statement. The Word comment on each edit (its evidence) stays. A preview uses `track_changes=False`, strips the comments and archives its records.
6. **Check:** `check_csa.py`, then `prose_lint.py`, `term_lint.py` and `csa cross-check` over the whole document (with changes treated as accepted, which is how the checks read a document).
7. **Report:** `csa-work/build/<build-id>.md` lists the sections built, the counts, the check results, any placeholders left, and the next steps: open in Word, refresh fields (Ctrl+A then F9), accept, reject or edit each tracked change, then `csa review N` and `csa cleanup N` for each section; add figures; send version 0.1 for peer review. Each section file's status is set to `built`, and a `build` event goes to `metrics.jsonl`.

A failed build leaves no working DOCX and no change files behind: the document is created under a temporary name and renamed only when step 6 passes.

Rejecting a tracked change in Word brings back the template placeholder (for example `[Observed: …]`); `check_csa.py` flags any left, so fix those in Word or through the revise lane before issue.

## 6. Agents

- **Writer agent:** a new input `OUTPUT=section-file` (default when the project has no working DOCX) makes it write `WORK_DIR/sections/<order>-<slug>.md` in the format above instead of a free-form draft. It still runs the lints. In revise mode nothing changes.
- **Quality reviewer:** accepts a section file as input; its review goes to `WORK_DIR/reviews/section-<order>-<slug>-review.md` with the verdict on the first line, where `csa sections` and `csa build` look for it.
- **Orchestrator:** after `csa ask` finds evidence and analysis stable for a domain, routes to `write OUTPUT=section-file`, then `qa`. When every planned section is reviewed READY, it says `csa build` is next, then tells Wenzel to review the tracked changes in Word and run `csa cleanup` per section.
- **Evidence investigator and analyst:** unchanged.
- **Decision D1** (merge the analysis agents): still open. The build lane gives the analysis side a real destination; look at usage after the first built CSA.

## 7. What stays the same

The revise lane, `csa check-change`, the approval hashes, tracked changes and the cleanup gate are unchanged; the build lane uses the last three itself. The build lane only ever creates the first draft. Existing IAMPS and UTC DTC documents are not rebuilt.

## 8. Out of scope for now

- Figures and diagrams: the executive summary's figure placeholder stays for a person, or for a later story using `csa-diagram-generator`.
- Rebuilding after issue: once version 0.1 exists, changes go through the revise lane, never a rebuild.
- Non-template documents: use the revise lane.
- Field refresh: the table of contents and fields are refreshed in Word (`new_csa.py` already asks Word to do this on first open).

## 9. Stories

| Story | What |
| --- | --- |
| S53 | Section-file format reference and one example file for each block kind |
| S54 | `csa_docx/section_file.py`: parse a section file into structured data |
| S55 | `template-blocks.json` (template headings, Req IDs, placeholder counts) and `csa check-section` |
| S56 | `csa approve-section` and `csa sections` (done; approval later dropped) |
| S56B | Remove `approve-section`; `csa sections` shows each file's review verdict and whether it is out of date |
| S57 | `csa_docx/build_plan.py`: section files plus manifest, giving scaffold counts and records |
| S58 | Scaffold step in the plan (calls `scaffold_csa.py`, then re-prepares) |
| S59 | Apply step: write and approve the change files, apply as tracked changes with evidence comments (a preview: clean, comments stripped, records archived) |
| S60 | `csa build` command: preconditions (check-section clean, current READY review), temporary name, checks, report |
| S61 | Generate the Appendix B coverage section file from the discovery index |
| S62 | Writer, reviewer and orchestrator changes for `OUTPUT=section-file` |
| S58B | Section files for template v1.2: template map, parser and `check-section` (Discovery Information tables, governance, migration tables, Discovery Coverage) |
| S58C | Build plan and scaffold for template v1.2 |
| S63 | Pilot: build a preview from three real section files (human) |
| S64 | Tracked changes for table-cell edits, so every built statement can be accepted or rejected in Word |
