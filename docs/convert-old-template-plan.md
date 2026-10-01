# Plan: `convertOldTemplateToNew` — move a pre-template CSA into the CSA template, one subsection at a time

Status: PLANNED, stories S186-S202 in `improvements/` (30 Sep 2026). Decisions D1-D4 settled (section 10). Pilot project: `tetra-reveloc` (old: `TETRA/05 Revloc Tetra/02 Current State Assessment/NetSeg_Current_State_Assessment_REVELOC_TETRA.docx`; new: `TETRA/06 REVELOC TETRA/01 Current State AS Built/01 Final Version/Current State Assessment - REVELOC TETRA.docx`).

## 1. Goal and principles

Take everything in an old-format CSA that has a home in the template and put it, as tracked changes, into the right template subsection, with every statement traced to evidence. Content with no home is parked, never lost and never forced in.

- **Unit of work = one template subsection** (a Heading 2 block: `3.4 Time Synchronisation` including its requirement table, `3.4.1 Discovery Information` and `3.4.2 Drawbridge Impact`; or `5.3 Failover and Replication Behaviour`). The requirement rows, discovery table and Drawbridge paragraph of one block are about the same thing, so they are written together from one focused brief. The CLI resolves the visible number, same as `csa author 5.3`.
- **Framework first.** Extraction, mapping, briefs, evidence pre-pass, the coverage ledger and status are deterministic Python. Agents only do what needs judgement: corroborating old claims against discovery data, and writing the prose. This keeps each agent run small enough for the local models.
- **Reuse, do not rebuild.** Mapping reuses the section scope map (`section-scope.md`: `Legacy headings`, `Signal terms`, `Must explain`, `Owns`, `Not here`). Writing reuses `csa write` → section file → `csa check-section` → `csa place` (tracked changes). Evidence reuses the evidence matrix and its automated source check.
- **Existing rules hold.** Never infer. Every statement carries an E-id. No copying stale text: an old claim becomes an evidence row first; where discovery data disagrees, discovery wins (project context rule). No recommendations in the CSA body. Host-centred tables. No approval step between writing and the document; the one approval is accept/reject in Word. Short, plain Word comments.
- **Generic.** Nothing TETRA-specific in code. Per-document differences live in one editable map file (`csa-work/legacy/legacy-map.csv`), so the same function converts the old IAMPS or UTC DTC documents.

## 2. Command surface

Python entry point `convertOldTemplateToNew(section, *, workspace, legacy_docx=None, stage=None)` in `framework/csa_docx/convert.py` (camelCase like `prepareDocument` / `lookupStableId`). CLI verb `csa convert`:

```text
csa convert --prepare              once per project: extract the old CSA, map every block, write the map report
csa convert --map [3.4]            show what maps where (all targets, or one), and what is unmapped or parked
csa convert 3.4                    convert one subsection: brief -> evidence -> write -> place -> ledger
csa convert 3.4 --stage brief      run one stage only (brief | evidence | write | ledger)
csa convert 3.4 --no-apply         stop after the section file (place later with csa place 3.4)
csa convert --status               every subsection: legacy blocks, evidence rows, written/placed, ledger complete, next
csa convert --parked               everything that has no home (recommendations, scores, drawings) for the roadmap
csa fleet "convert 3.4" "convert 3.5" ...   parallel, one fresh session per subsection
```

## 3. Stages

### Stage 0 — prepare (framework, once per project; re-run when the old document or map changes)

1. **Register the old document.** New optional keys: `legacy_docx:` in `PROJECTS.yaml` and `legacy_document:` in the project context. `csa doctor` checks the file exists.
2. **Extract** (`legacy_extract.py`): walk the old DOCX in order and write `csa-work/legacy/blocks.jsonl`. One record per paragraph, list item, table row (with its header row) and image/caption, each with a stable legacy ID (`L-0001`), the full heading path (`Network > Observed Configuration and Functionality`), the kind (`para | bullet | table_row | figure`), the text, and the index line range so the source check can find it. Also write readable `csa-work/legacy/<nn>-<old-heading>.md` files for humans. Read-only on the old DOCX.
3. **Classify the job of each block** (framework, from the old sub-heading and wording, using the kinds in `section-scope.md` part 1): `FACT/FINDING/CONSEQUENCE` → convertible; `RECOMMENDATION` (all "Finding comments, recommendations" subsections, Operational Recommendations) → parked; `RAW` / Evidence Appendix → evidence-only (feeds the matrix, never printed); `figure` → figure list; Document Control → controlled fields (not converted).
4. **Map each block to a target subsection** (`legacy_map.py`), first match wins, rule recorded:
   1. moved blocks from earlier ledgers (`csa-work/legacy/moved.csv`), then per-document overrides in `csa-work/legacy/legacy-map.csv`, then the generic defaults in `.agents/skills/csa-document-template/references/legacy-map-default.csv` (heading-path regex → target, job);
   2. the old Heading 1 via `Legacy headings` in `section-scope.md` (for example DNS → 3.5);
   3. inside a multi-domain old section (Identity & Authentication hosts 3.2, 3.3, 3.8, 3.16; Network hosts 3.6, 3.13, 3.17; Infrastructure Dependencies hosts 3.7, 3.15) split by `Signal terms` scored per block; ties go to the section's primary domain and are flagged.
   Output `csa-work/legacy/map.csv` (L-id, heading path, kind, target, rule, confidence) and `map-report.md` (per target: block count and headings; unmapped; parked).
5. **Seed map for TETRA** (first `legacy-map.csv`, from the review of the old document):

| Old CSA | Target |
| --- | --- |
| Architectural Review > Reveloc Application Services, Tetra Log Services, SQL Infrastructure, Radio Management Services, TGOIP and Radio Gateway Integration | 3.1 General / Asset Inventory |
| Architectural Review > Operational Access and Support | 3.8 Management & Administrative Access |
| Architectural Review > Enterprise Service Dependencies | 3.15 Infrastructure Dependencies |
| Identity & Authentication | 3.2 (certificates → 3.3) |
| Time Synchronization | 3.4 |
| DNS | 3.5 |
| Network; System Assessment Overview > Traffic Flow Analysis | 3.6 (boundary → 3.13, proxy/SMTP → 3.17) |
| Operations Monitoring and Procedures | 3.9 |
| Patch & Lifecycle Management | 3.10; tooling detail → 5.4 |
| Backup & Recovery | 3.11 |
| Drawbridge Impacts > Dependency impact table (per row, by signal terms) | the owning domain's x.2 Drawbridge Impact |
| Drawbridge Impacts > Overall drawbridge assessment | 3.12 |
| Security Controls | 3.14 |
| Security Controls > Group Policy Objects | 5.5 Group Policy Observations |
| Infrastructure Dependencies | 3.15 (storage → 3.7) |
| Discovery Summary > SQL cluster architecture, Integrations, Always-On replication, survivability | 5.3 Failover and Replication Behaviour |
| Discovery activity; Methodology | 5.1 Discovery Coverage |
| Traffic Flow Analysis > Discovery scope gaps requiring follow-up | Appendix E Discovery Required |
| Glossary / Acronyms | Appendix B |
| Executive Summary; Business Functional Overview; Objectives; Scope | 2.1 (rewritten last, from the converted sections) |
| All "Finding comments, recommendations" subsections; Operational Recommendations; Drawbridge readiness score | parked |
| Drawing subsections, figures | figure list (added by hand in Word) |
| Evidence Appendix subsections | evidence-only |

### Stage 1 — brief (framework, per subsection)

`csa-work/convert/<nn>/brief.md`, the only thing the agents read about the old document:

- the subsection's scope entry: Req IDs and requirement text (from `template-blocks.json`), Must explain, Owns, Not here;
- the mapped legacy blocks, verbatim, with L-ids and heading paths, grouped by old sub-heading, recommendations and raw blocks left out;
- the hosts in play: rows from `csa-work/hosts/hosts.csv` (role, site) for hosts the blocks or the scope's signal terms name;
- pointers, not dumps, to the discovery index tables that match the signal terms (`csa index tables` output filtered);
- evidence rows already in the matrix for this subsection (`csa ev lookup`);
- a context budget check (`context_budget.py`); over budget → split the legacy blocks into two briefs and say so.

### Stage 2 — evidence (framework pre-pass, then the evidence investigator in CONVERT mode)

1. **Pre-pass (no LLM):** for every convertible legacy block, append an evidence row quoting the old CSA line itself (`source_title` = the old CSA, `page_or_location` = heading path and index lines, `gap_or_action` = `legacy L-0123`). The automated source check approves these because the old CSA is indexed. This makes every old fact citable at low cost.
2. **Corroborate (agent, one subsection):** for each legacy row, look for the same fact in the discovery captures and append the discovery row (preferred for the write). Where discovery disagrees, append a `CONFLICTING` row that names both; the writer uses the discovery value. For each Must explain question with no source at all, append `NOT_FOUND`; these become Appendix E candidates.
3. New instruction block `MODE=convert` in `csa-evidence-investigator-agent.md` (inputs: `BRIEF=`), nothing else changes in that agent.

### Stage 3 — write and place (existing writer, one new input)

`csa write <nn> BRIEF=csa-work/convert/<nn>/brief.md`: the writer reads the brief's scope and the evidence rows (never the legacy text as a source of wording), writes the section file in the template shape (requirement rows with ratings, Discovery Information table centred on hosts, optional note, Drawbridge Impact), runs `csa check-section` and prose lint, and `csa place` applies it as tracked changes with the usual short comments; converted text and comments never mention the old document (D4). Nothing new in placement.

### Stage 4 — coverage ledger (framework)

`csa-work/convert/<nn>/ledger.csv`: every legacy block mapped to this subsection gets exactly one outcome:

| Outcome | Meaning |
| --- | --- |
| USED | the fact is in the section; E-id and statement key from the section file's `## Evidence` table |
| SUPERSEDED | discovery data says otherwise; the CONFLICTING E-id |
| MOVED | belongs to another subsection (section-fit scan); re-queued to that target's map |
| PARKED | recommendation, score or out of scope; listed in `convert/parked.md` |
| DUPLICATE | same fact already USED from another block |
| NOT_USED | a fact the subsection's Must explain does not ask for; reason required |

The USED / SUPERSEDED outcomes are filled automatically by matching `legacy L-nnnn` rows to the section file's Evidence table; the writer reports the rest. `csa convert` reports `INCOMPLETE` while any block has no outcome. This is the check that nothing relevant was lost and nothing irrelevant went in.

### Stage 5 — check (existing, non-gating)

`csa qa <nn>` and `section_fit_scan.py` on the placed text; `csa convert --status` shows the verdict next to the ledger state.

## 4. Document-level parts (not domain blocks)

| Part | Handling |
| --- | --- |
| 1 Document Control | Properties already set by `new_csa.py`. Old revision history is not carried (the new document starts at 0.1); decision D3 |
| 2.1 Executive Summary | `csa summary` after the domain blocks are placed, from the new sections only |
| 4 Governance Note and Next Steps | Not converted: old recommendations are parked, not actions. Actions with owner and date only if you supply them |
| 5.1 Discovery Coverage | Generated by the existing `coverage_section.py` from the discovery index; old Discovery activity text only adds method notes |
| Appendix B Glossary | Table-row merge: old terms added to the template's standard terms, duplicates dropped (framework, no LLM) |
| Appendix E Discovery Required | From NOT_FOUND rows plus the old "Discovery scope gaps" blocks |

## 5. Order of conversion (pilot)

1. 3.4 Time Synchronisation (small, evidence already in the matrix) — pilot and eval.
2. 3.5, 3.2, 3.9, 3.10, 3.11, 3.14, 3.15, 3.7, 3.8, 3.3, 3.13, 3.17, 3.16.
3. 5.2 to 5.6.
4. Host-heavy blocks once roles and sites are settled: 3.1, 3.6, 5.1.
5. 3.12 (draws on every domain's Drawbridge Impact), Appendix B, Appendix E.
6. 2.1 Executive Summary.

## 6. Setup needed before the first run

- Old document registered (`legacy_docx`).
- Host register settled: RevViewer jump-host role for MKYPRDOPS110 / ROKPRDOPS110; the Mackay site question for MOTPRDCLU101 / MOTPRDREV101 (the old CSA puts MOTPRDCLU101 in Mackay).
- Evidence rows E-006, E-007, E-009, E-011 decided.
- The working document closed in Word, or left to the existing auto-close.

## 7. Stories for the improvements register (small, one fresh session each)

| # | Story | Model | Depends on |
| --- | --- | --- | --- |
| C1 | `legacy_extract.py`: old DOCX → `blocks.jsonl` + readable files; tests on a small fixture DOCX | evo | — |
| C2 | Parse `section-scope.md` into a reusable module (share with `section_fit_scan.py`, do not duplicate) | evo | — |
| C3 | `legacy_map.py`: job classification + three-rule mapping + `legacy-map.csv` overrides; `map.csv`, `map-report.md`; tests | evo | C1, C2 |
| C4 | `legacy_docx` key in PROJECTS.yaml/context; `csa doctor` check; seed TETRA `legacy-map.csv` | evo | C3 |
| C5 | Brief builder with context budget and split | evo | C3 |
| C6 | Evidence pre-pass (legacy rows through the source check) | evo | C1 |
| C7 | Investigator `MODE=convert` instructions | cowork | C5, C6 |
| C8 | Writer `BRIEF=` input and comment wording | cowork | C5 |
| C9 | Ledger: auto USED/SUPERSEDED, INCOMPLETE rule, `parked.md` | evo | C6 |
| C10 | `csa convert` verb, `--prepare/--map/--status/--parked/--stage`, registry entry, fleet locks (section lock; placement holds the DOCX lock), `csa sync` | evo | C3–C9 |
| C11 | Document-level handlers: glossary merge, Appendix E from NOT_FOUND, 5.1 via coverage_section | evo | C10 |
| C12 | Pilot on TETRA 3.4: run, review in Word, fix, record learnings; eval of ledger completeness and section-fit | human + cowork | C10 |
| C13 | Docs: CSA-COMMANDS.md, `.agents/README.md`, build-lane spec section | evo | C12 |

## 8. Success criteria (per subsection)

- `csa check-section` passes, prose lint clean, no evidence or stable IDs in the text.
- Every rendered statement has an E-id; every legacy block mapped here has a ledger outcome.
- Section-fit scan finds no content that belongs to another subsection and no recommendation.
- Discovery tables are centred on hosts (rows = hosts sharing a configuration).
- The tracked changes read as a story for that subsection's purpose when opened in Word.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Old headings are generic ("Observed", "Design and functionality expected") | Map by the parent Heading 1 first, then signal terms; flag low-confidence blocks in the map report |
| Old text copied as-is | The writer reads evidence rows and the brief's scope, and the ledger shows each block's fate; prose lint and section-fit catch pasted narrative |
| Stale old facts | Discovery corroboration first; CONFLICTING rows; discovery wins |
| Tables and figures lost in extraction | Table rows extracted with their header; figures listed with captions for manual insertion |
| Brief too big for the model | Context budget; split the brief |
| Mapping mistakes | One editable `legacy-map.csv`; `csa convert --map` before writing; MOVED outcome re-queues |

## 10. Decisions (Wenzel, 30 Sep 2026)

- **D1** Unit = the whole Heading 2 block (3.4 with 3.4.1 and 3.4.2).
- **D2** Parked content (recommendations, readiness score) goes to `csa-work/convert/parked.md` for the roadmap deliverable.
- **D3** The old revision history is not carried; the new document starts at 0.1.
- **D4** Converted text and its Word comments do not mention the old document.

## 11. Data contracts (shared by the stories)

**`csa-work/legacy/blocks.jsonl`** (legacy_extract, S186): one JSON object per line, document order.

| Key | Value |
| --- | --- |
| `id` | `L-0001`, `L-0002`, ... in document order, headings included |
| `order` | 1, 2, ... |
| `kind` | `heading`, `para`, `bullet`, `table_row`, `figure` |
| `level` | heading level 1-9 for `heading`, else 0 |
| `path` | list of heading texts from Heading 1 down; for a heading it ends with the heading itself |
| `text` | the text; a `table_row` is its cell texts joined with ` | `; a `figure` is its caption text (or empty) |
| `cells`, `header` | `table_row` only: the row's cell texts and the table's first row (the header row is not a block) |

Skipped: empty paragraphs, table-of-contents paragraphs (style starting `TOC`), caption paragraphs that follow a figure (they become the figure's text).

**`csa-work/legacy/map.csv`** (legacy_map, S189): columns `id,path,kind,job,target,rule,confidence`; `path` is the heading path joined with ` > `.

| Column | Values |
| --- | --- |
| `job` | `convert`, `context` (feeds 2.1 only), `parked`, `evidence-only`, `figure`, `controlled`, `skip` (headings) |
| `target` | framework section number: `3.1`-`3.17`, `5.1`-`5.6`, `2.1`, `7` (Glossary), `8` (Discovery Required), or empty (unmapped / no home) |
| `rule` | `moved`, `project:<row>`, `default:<row>`, `legacy-heading`, `signal-terms`, `none` |
| `confidence` | `high` (moved, project, default, single legacy host), `medium` (signal terms decided), `low` (split tie, fell back to the primary domain) |

**Map files** (`legacy-map-default.csv`, project `legacy-map.csv`): columns `pattern,target,job,note`. `pattern` is a case-insensitive Python regex searched in the heading path joined with ` > `. First matching row wins. `target` may be empty (for parked, evidence-only, controlled), a section number, or `signal` (choose the 3.x domain whose signal terms score highest on the block's path and text). An empty `job` means `convert`.

**Evidence rows from conversion** carry `legacy L-nnnn` in `gap_or_action` (pre-pass rows, and corroborating or conflicting rows the investigator adds).

**`csa-work/convert/<target>/`**: `brief.md` (and `brief-2.md` when split), `outcomes.csv` (writer: `id,outcome,target,reason`), `ledger.csv` (`id,path,outcome,evidence_ids,target,reason`). Project-wide: `convert/parked.md`, `convert/figures.md`, `legacy/moved.csv` (`id,target`).

## 12. Stories

S186 legacy extract · S187 scope map module · S188 default legacy map · S189 legacy map · S190 `legacy_docx` project key · S191 conversion brief · S192 evidence pre-pass · S193 `discovery-required` section-file block · S194 agent instructions (investigator MODE=convert, writer BRIEF=) · S195 coverage ledger · S196 `convertOldTemplateToNew` orchestration · S197 `csa convert` CLI and fleet · S198 document-level targets (glossary, Discovery Required, 5.1) · S199 section-fit scan uses the scope map · S200 TETRA setup (cowork) · S201 TETRA pilot 3.4 (human) · S202 docs. Section 7 above is the earlier draft of this list.

## 13. Requirement-led conversion (revision, 30 Sep 2026)

**Why.** The first TETRA map routed legacy blocks by old section. It selected useful material but gave some destinations whole narratives (2.1: 167 blocks, 3.1: 126, 5.3: 80) and left others with weak or mismatched evidence (3.3: 1 block for two requirements, 3.7 fed by general dependency text, 3.16 and 5.2/5.4/5.6 empty). The test is per requirement: **does the selected evidence let us answer each requirement accurately, concisely and with the correct uncertainty?**

**Transformation rules.**
- Move facts, not narratives; consolidate repeated observations into one current-state statement.
- Separate observed configuration, evidence scope, requirement assessment, gap or unknown, and recommendation.
- Recommendations never enter a current-state field: their factual basis becomes a finding, the action goes to the roadmap (`convert/parked.md`) or, when it is an unanswered question, to Discovery Required.
- Keep qualifiers (not observed, not tested, not confirmed); legacy absolutes ("no X exists") become "not evidenced" plus a Discovery Required row unless a capture proves absence.
- Every finding carries a requirement ID (SEP-DNS-01), not only a section number.
- Coverage / Source names the actual host set and evidence type; legacy scope claims are corrected to the captures (TETRA: "all six hosts" is the June wave only; role-aware DNS tests exist on 5 hosts, not 12).
- The legacy readiness score is replaced by an evidence-backed rating per requirement.
- Parked content is mined: factual sentences in recommendation subsections are kept; evidence appendices are referenced through Coverage / Source; figures only where they explain topology or dependencies the section needs.

**Mapping record.** `csa-work/convert/<N>/answer-plan.csv`: legacy IDs → requirement ID → statement type → fact → evidence scope → destination field → confidence → transformation → gap generated. Destinations: `REQ <id> / Current State|Rating`, `<N>.1 Discovery Information / <Aspect>`, `<N>.2 Drawbridge Impact`, `5.x ...`, `2.1 Executive Summary`, `8 Discovery Required`, `MOVED <N>`, `roadmap`, `none`. Validated by `answer_plan.py` (S207).

**Pipeline.** prepare: extract → map (recommendation subsections now `mine`) → facts (S204) → requirement IDs and duplicate clusters (S205) → requirement audit (S206). Per subsection: requirement-led brief (S208) → evidence pre-pass → evidence agent writes the answer plan (S209) → plan-check → writer writes from the plan (S210) → requirement-level ledger (S211) → Appendix E rows from all plans' gaps (S212).

**Reference material (TETRA).**
- `csa-work/convert/requirement-audit.md`: all 35 requirements with legacy facts by type, what the captures hold, verdict and action (kept; the framework writes `requirement-audit.generated.md` beside it).
- `csa-work/convert/3.5/answer-plan.csv` + README: hand-built 3.5 DNS plan checked against the captures; the pilot (S214) compares the agent's plan with it.
- `.agents/skills/csa-document-template/references/requirement-map.csv` (S203): per requirement, answer terms, what answers it, what does not (for example CrowdStrike answers SEP-VULN-02 coverage, not a SEP-VULN-01 register; Availability Group replication is not a backup; product names are not vendor access paths), Discovery Information aspects and capture tables.

**Section treatments** (from the review): 2.1 concise overview written last (system, assessed scope, critical dependencies, isolation posture, major gaps, evidence limits); 3.1 from the host register; 3.2 enterprise AD dependence, domain service accounts, Kerberos, jump-host authentication, VNC/SSH paths, unknown PAM coverage; 3.3 certificate source, renewal, CRL/OCSP and isolation behaviour recorded as not established with targeted discovery rows; 3.4 and 3.5 consolidated once; 3.6 zoning, conduits, cross-zone flows (internet/SMTP to 3.17, firewall-control evidence to 3.13); 3.7 reassessed from shares, SMB, transfer mechanisms, scanning, push/pull; 3.8 jump hosts, RDP/VNC/SSH, admin groups, PAM gaps; 3.9 SCOM, Splunk, EDR coverage, retention and tamper as unknown; 3.10 tooling, MECM dependency, versions, cadence, windows (detail to 5.4); 3.11 PPDM on SQL nodes versus unconfirmed backup of the application hosts, offline rebuild and testing as gaps; 3.12 a tested three-month plan, thresholds and manual fallback stated precisely or raised as discovery; 3.13 boundary devices, rule review, external exposure, management-plane ownership; 3.14 endpoint protection separate from a vulnerability-assessment process; 3.15 virtualisation hosting and hypervisor management; 3.16 only vendor support and remote-access evidence; 3.17 direct versus proxy, public HTTPS, Azure private endpoints, telemetry, Windows Update, corporate SMTP relay; 5.2 compact component inventory; 5.3 summarised; 5.4 and 5.6 from observed tooling and transfers; 8 structured rows.

**Stories:** S203-S215 (register phase "Convert (requirement-led)"). S201 (block-led 3.4 pilot) is skipped in favour of S214 (3.5 DNS).
