# Build lane: writing version 1 of a CSA from approved section files

Status: design, 26 Sep 2026 (story S52). Implementation stories: S53–S63 in `improvements/stories/`.

## 1. Why

The framework is built to *correct* a CSA. Its main path edits an existing DOCX one anchored paragraph at a time, through change records that each need authoring, approval, apply, review and cleanup. That is the right control for revising an issued baseline. It is the wrong unit for producing version 1, where every paragraph is new: the ceremony is multiplied by the number of paragraphs, and the writer agent's drafts have nowhere to go.

The build lane adds one direct path for version 1:

```text
BUILD LANE (version 1, template CSAs)                  REVISE LANE (after the baseline, unchanged)
evidence -> analysis -> section files                  csa author N -> csa check-change N
csa check-section / csa qa / csa approve-section       csa approve N -> csa apply N
csa build  ->  working DOCX v1 (no tracked changes)    csa review N -> read in Word -> csa cleanup N
```

Once `csa build` has produced version 1 and Wenzel has issued it, every later change goes through the revise lane. The build lane never edits a document that already has change files.

## 2. Principle: build reuses the apply engine

No new DOCX-writing code. `csa build` turns approved section files into ordinary change records and applies them with the existing `csa_docx.tools.apply_next_batch(..., track_changes=False)`. This was proven on 26 Sep 2026 against a fresh document made from `CSA_Template_v1.1.dotx`:

| Step | Result |
| --- | --- |
| `new_csa.py` creates the document from the template | CREATED |
| `prepareDocument()` builds the manifest | READY: 66 headings, 89 table rows |
| `lookupStableId("SEP-TIME-01")` | one match, `@H4.5-T1-R2` (requirement rows resolve by Req ID) |
| Apply three records (a requirement row as `Observed:` / `Assessment:`, a Discovery Information bullet, the Drawbridge Impact paragraph), `track_changes=False` | SECTION_COMPLETE, all 3 applied |
| Package check | 0 `w:ins`, 0 `w:del`; the Rating cell reads "Not Met" |
| `check_csa.py` | 0 errors (2 warnings: the placeholders still unfilled) |
| Side effect | 3 Word comments added; the build must remove them (S59) |

What the engine cannot do (recorded in `template-structure.md`): add or remove table rows, bullets or headings, or target a whole table. The build therefore runs `scaffold_csa.py` first to set the number of rows and bullets, then replaces each placeholder by stable ID.

## 3. Section files

### Location and names

`WORK_DIR/sections/<order>-<slug>.md`, one file per template block, for example:
- `csa-work/sections/2.1-executive-summary.md`
- `csa-work/sections/3.04-time-synchronisation.md`
- `csa-work/sections/4.3-patch-and-update-tooling.md`
- `csa-work/sections/B-discovery-coverage.md`

The order prefix only sorts the files; the `heading:` front-matter key decides where the content goes.

### Format

Flat front matter (no nesting, parsed without PyYAML, like `PROJECTS.yaml`), then fixed `##` headings. Everything is plain prose or Markdown pipe tables. No evidence IDs, stable IDs or Markdown emphasis appear in rendered text; the same hygiene rules as `csa check-change` apply.

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

- Every captured host runs the Windows Time service as a client of the enterprise time servers.
- No captured host serves time to other OT hosts.

## Drawbridge Impact

If OT is isolated, the hosts keep running on their last synchronised time and drift apart. Authentication fails once the skew passes the Kerberos tolerance; before that, log timestamps lose accuracy.

## Evidence

| Statement | Evidence |
| --- | --- |
| SEP-TIME-01 | E-012, E-044 |
| Discovery Information 1 | E-013 |
| Discovery Information 2 | E-045 |
| Drawbridge Impact | E-012, E-046 |
```

The `## Evidence` table is never rendered. It is the traceability record, and every rendered statement must appear in it. That satisfies "E-ids live in the change record, never in the prose" without a separate sidecar file.

### Block kinds

| `block:` | Template target | Headings in the file | How it fills |
| --- | --- | --- | --- |
| `domain` | a 3.x domain (Heading 2 = `heading:`) | `## Requirements` (every Req ID of that domain, once), `## Discovery Information` (bullets), `## Drawbridge Impact` (one paragraph); 3.1 adds `## Hosts and roles found` (table Host(s) / Environment / Role); 3.2 adds `## Accounts, groups and service accounts found` (table Account / Group / Type / Host(s) / Purpose / Role) | Rows replaced as `Observed:` / `Assessment:`; bullets scaffolded to the count, then replaced; paragraph replaced; tables scaffolded, then rows replaced as pipe rows |
| `executive-summary` | 2.1 Executive Summary | `## Summary` (one to three paragraphs) | The three placeholder paragraphs are replaced in order; unused ones are deleted. The figure placeholder is left for a person (diagrams are out of scope, see section 8). |
| `migration` | a 4.x subsection (Heading 2 = `heading:`) | `## Findings` (bullets) | Bullets scaffolded, then replaced |
| `glossary` | Appendix A | `## Terms` (table Term / Definition) | Standard rows kept; project terms appended by scaffolding the row count up, then replacing the new rows |
| `coverage` | Appendix B | `## Hosts` (table Host / Role / Discovery Script Run / Notes) | Rows scaffolded to the count, then replaced. S61 generates this file from the discovery index. |

Document Control (1.1) and the cover come from the document properties, which `new_csa.py` sets. The build adds one revision-history row (1.2) from its own arguments.

### Rules that `csa check-section` enforces (S55)

- `block:` is one of the kinds above, and `heading:` exists in the template (the list comes from `template-blocks.json`, S55).
- Domain: every Req ID of the domain appears exactly once, and no others; Rating is one of `Met`, `Partially Met`, `Not Met`, `Not Applicable`; Current State is at most 50 words (a warning).
- Every rendered statement has a row in `## Evidence` with at least one existing E-id (checked against the evidence matrix).
- Rendered text is free of E-ids, `@H` IDs, Markdown emphasis and backticks (errors), and `prose_lint.py` / `term_lint.py` run over it (warnings).

## 4. Lifecycle and gates

| Status | Set by | Meaning |
| --- | --- | --- |
| `draft` | the writer agent (`csa write`) | Written from approved evidence; may change freely |
| `reviewed` | `csa qa` on the section file, verdict READY or READY WITH DECLARED GAPS | Content-checked |
| `approved` | **Wenzel**: `csa approve-section <file>` | Hash of the rendered content stored in `<file>.approval.json`, as for change files. Any later edit is refused by `csa build` until it is approved again. |
| `built` | `csa build` | Recorded with the build ID; the file is now history. Changes go through the revise lane. |

`csa approve-section` refuses a file that fails `csa check-section` with errors (unless `--force`), or that has no READY review (unless `--force`). Wenzel remains the approval gate, as in the revise lane.

## 5. `csa build`

```text
csa build [--sections all | 3.04,3.05,...] [--preview] [--system-name ...] [--prepared-for ...] [--version 0.1]
```

Preconditions (refuse with a clear message otherwise):
1. The project uses the CSA template. Projects whose working document is on its own template (UTC DTC today, per `known_constraints` in its context file) use the revise lane only.
2. Without `--preview`: the project has no working DOCX yet, and no `reviews/ChangesCSA_*` files. The build creates version 1 once. With `--preview`, output goes to `csa-work/build/archive/preview-<timestamp>/`. The `archive` folder name keeps it out of `prepareDocument()`'s search.
3. Every selected section file is `approved` and its hash matches, unless `--preview` (which accepts drafts and says so in the file name).

Steps:
1. **Create:** `new_csa.py` with properties from the arguments, falling back to the project context file.
2. **Plan:** `build_plan.py` (S57) reads the section files and the template map and works out, for every block, the rows and bullets needed and the stable ID of each placeholder.
3. **Scaffold:** `scaffold_csa.py rows|bullets` for every count that differs from the template (S58); `prepareDocument()` is run again afterwards.
4. **Records:** the planner writes canonical change files, `reviews/ChangesCSA_<App>_Section<N>.md`, one per framework section. Edit IDs are `S<N>-E<n>`, `Why:` holds the E-ids from the section's Evidence table, and `Note:` reads "Built from approved section file <name>". Each gets an approval record whose `by` is "csa build <build-id> (approved section files)".
5. **Apply:** `apply_next_batch(section, limit=500, track_changes=False)` per section, until SECTION_COMPLETE; a BLOCKED edit stops the build and is reported with its section file and statement.
6. **Clean:** remove the Word comments the apply step added (S59), then move the build change files to `reviews/archive/build-<build-id>/`, so the revise lane starts from an empty `reviews/`.
7. **Check:** `check_csa.py` (placeholders left only where a block had no section file), then `prose_lint.py`, `term_lint.py` and `csa cross-check` over the whole document.
8. **Report:** `csa-work/build/<build-id>.md` lists the sections built, the counts, the check results, any placeholders left, and the next steps (open in Word, refresh fields with Ctrl+A then F9, add figures, issue v1). Each section file's status is set to `built`, and a `build` event goes to `metrics.jsonl`.

A failed build leaves no working DOCX behind: the document is created under a temporary name and renamed only when step 7 passes.

## 6. Agents

- **Writer agent:** a new input `OUTPUT=section-file` (default when the project has no working DOCX) makes it write `WORK_DIR/sections/<order>-<slug>.md` in the format above instead of a free-form draft. It still runs the lints. In revise mode nothing changes.
- **Quality reviewer:** accepts a section file as input; its review goes to `WORK_DIR/reviews/section-<order>-<slug>-review.md` with the verdict on the first line, where `csa approve-section` looks for it.
- **Orchestrator:** after `csa ask` finds evidence and analysis stable for a domain, routes to `write OUTPUT=section-file`, then `qa`, then asks Wenzel to run `csa approve-section`. When all planned sections are approved, it says `csa build` is next.
- **Evidence investigator and analyst:** unchanged.
- **Decision D1** (merge the analysis agents): still open. The build lane gives the analysis side a real destination; look at usage after the first built CSA.

## 7. What stays the same

The revise lane, `csa check-change`, the approval hashes, tracked changes and the cleanup gate are unchanged. The build lane only ever creates version 1. Existing IAMPS and UTC DTC documents are not rebuilt.

## 8. Out of scope for now

- Figures and diagrams: the executive summary's figure placeholder stays for a person, or for a later story using `csa-diagram-generator`.
- Rebuilding after issue: once version 1 is issued, changes go through the revise lane, never a rebuild.
- Non-template documents: use the revise lane.
- Field refresh: the table of contents and fields are refreshed in Word (`new_csa.py` already asks Word to do this on first open).

## 9. Stories

| Story | What |
| --- | --- |
| S53 | Section-file format reference and one example file for each block kind |
| S54 | `csa_docx/section_file.py`: parse a section file into structured data |
| S55 | `template-blocks.json` (template headings, Req IDs, placeholder counts) and `csa check-section` |
| S56 | `csa approve-section` with a hash, and `build` refusing changed files |
| S57 | `csa_docx/build_plan.py`: section files plus manifest, giving scaffold counts and records |
| S58 | Scaffold step in the plan (calls `scaffold_csa.py`, then re-prepares) |
| S59 | Apply step: write the change files, apply without tracked changes, strip build comments, archive the records |
| S60 | `csa build` command: preconditions, temporary name, checks, report |
| S61 | Generate the Appendix B coverage section file from the discovery index |
| S62 | Writer, reviewer and orchestrator changes for `OUTPUT=section-file` |
| S63 | Pilot: build a preview from three real section files (human) |
