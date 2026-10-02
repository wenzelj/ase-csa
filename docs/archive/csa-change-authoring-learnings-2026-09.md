# C-S-A-Change-Authoring Agent Learnings

This append-only file captures two kinds of reusable lesson learned while drafting Current State Assessment change proposals against Discovery Data evidence:

1. **Evidence-to-topic mappings** -- which Discovery Data file name patterns actually turned out to be useful for which document topics. Recording this is a required step at the end of every authoring run (see `csa-change-authoring.md`, Evidence Mapping), not optional housekeeping -- there is no fixed mapping table anywhere else, so this file is the only place that knowledge accumulates.
2. **General authoring lessons** -- anchor/wording patterns that commonly fail `lookupStableId`, classes of claim that are routinely ambiguous across hosts, governance-field boundaries that came up, etc.

Each entry should use this format:

```text
## YYYY-MM-DD - <short lesson title>

Context:
<section/document/task context>

Issue or risk observed:
<what made authoring harder, failed, or required special handling -- or, for an
evidence mapping, what topic needed a mapping in the first place>

Evidence used:
<what evidence identified or confirmed the issue, or -- for a mapping entry --
the Discovery Data file name pattern(s) that were actually useful>

Improved authoring approach:
<what the agent should do next time>

Validation:
<how to confirm the improved approach worked>
```

## 2026-09-19 - Initial learning log

Context:
Agent created (`csa-change-authoring.md`) to fill the gap between `prepareDocument()` (step 0) and the previously-existing `csa-document-agent` (apply) / `csa-change-review-agent` (verify) agents, which both assumed a `ChangesCSA_*.md` already existed. Nothing had previously drafted the first proposal for a section from a bare, prepared document.

Issue or risk observed:
Without a dedicated append-only place for evidence-to-topic mappings, every authoring run would have to re-derive from scratch which Discovery Data files matter for which document topics (e.g. DNS, time synchronisation, listening ports) -- the exact kind of repeated rework this file exists to prevent.

Evidence used:
Discovery Data at `01 Current State AS Built/IAMPS Discovery Data/` is organised per-host under `PROD/`, `UAT/`, and standalone `tg_discovery_*` runs, with numbered per-topic files inside each host's folder (for example `00_host_summary.txt`, `14_resolver.txt`, `20_listening_ports.txt`, `41_dns_query_tests.txt`, `52_auth_configs.txt`) -- observed directly by listing the folder, not yet correlated against specific document sections.

Improved authoring approach:
After each completed authoring run, record which numbered file(s) were actually useful for the section's topic(s) as a new entry here, and check this file before searching Discovery Data from scratch on every subsequent run.

Validation:
Confirm this file gains at least one evidence-mapping entry per authoring run that found supporting evidence, and confirm the agent's report to the user states either the lesson added or `No new reusable skill lesson identified`.

## 2026-09-20 - Front-matter "map/summary of the document" tables are checkable claims, not narrative

Context:
Re-authoring Section 1 (Document Control). The section's Document Map sub-heading has both narrative paragraphs (genuinely non-factual, "each section presents…") and a table listing every later section's number, title, purpose, and key outcome.

Issue or risk observed:
A prior authoring pass treated the whole "Document Map" element as narrative and left it unchanged with "no factual claim to verify." That was wrong for the table specifically: its **Section** column is a checkable claim against the document's own current heading order. This run found every row's stated number was 1 higher than that section's actual position (confirmed via `word/document.xml` heading order plus `word/styles.xml`/`word/numbering.xml`'s Heading1 auto-numbering definition — decimal, start=1, no restarts). Any document element whose whole purpose is to *summarise the document's own structure* (a Document Map, an in-document table of contents, a "sections at a glance" table) deserves the same document-internal-consistency check A-1 already applies to dates — don't wave it through as "descriptive."

Evidence used:
`word/document.xml` (literal `Heading1`-styled paragraph order), `word/styles.xml` (Heading1 style's `numId`/`abstractNumId`), `word/numbering.xml` (confirms `start=1`, `decimal`, no `lvlOverride`/`startOverride` for that `abstractNumId`) — i.e. the document's own numbering definition, not Discovery Data. Also cross-checked against already-authored `ChangesCSA_..._Section<N>_...md` filenames, which use the same H1-ordinal convention and independently confirm the "actual" column.

Improved authoring approach:
When a section contains a table or list that summarises the document's own other sections (a map, an index, a "document at a glance" table), check its claims (numbers, titles, counts) against the document's *current* actual structure, the same tier-3 evidence used for dates/cross-references — don't classify it as "no factual claim to verify" just because it reads as descriptive prose elsewhere in the same block.

Validation:
Confirm a future full read-through of any front-matter "map"-style table checks its per-row claims against the current heading order, not just its narrative paragraphs.

## 2026-09-20 - `table_rows: 0` manifest gap — root cause found and FIXED same day

Context:
Same Section 1 re-run, then a direct follow-up user request ("fix the framework manifest gap"). The gap first noted 2026-09-19 (`prepareDocument()` reports `table_rows: 0` despite the document having 29 `<w:tbl>` tables) was confirmed still present on 2026-09-20, then root-caused and fixed the same day.

Issue or risk observed:
Without a table-row anchor, `lookupStableId` on a table cell's text either returns no match or (worse) matches an unrelated paragraph elsewhere that happens to contain the same words (e.g. querying "System Assessment Overview" — text that exists in a Document Map table cell — used to resolve *only* to the `@H4` heading, not the table row). Using that as an edit's anchor would have silently pointed an implementation agent at the wrong location.

Root cause:
`tools.prepareDocument` built the manifest via `stable_ids.generate_manifest(editor.doc.paragraphs())`, where `editor.doc` is the vendored `docxengine.Document`. That vendor library's `Document.paragraphs()` deliberately excludes tables entirely — tables are a separate concern in that library (its own docstring: "Tables anchor as `T{ordinal}`... cell text is a projection concern"). So nothing ever fed `stable_ids`'s manifest builder a paragraph-shaped object with a `table_anchor` attribute set, even though `stable_ids.py`'s ID algorithm (`build_id_map`/`generate_manifest`) already handled that case correctly — the gap was entirely upstream, in what fed it, not in `stable_ids.py` itself.

Fix:
Added `DocxEngineEditor.paragraphs_with_table_rows()` (`csa_docx/engines/docxengine_adapter.py`), which walks the vendor library's own `build_anchor_index(package)` (the same body-level paragraph/table ordering the vendor library derives its own anchors from) and, for each `"table"` entry, expands it into per-row synthetic objects using the already-existing `_table_rows()` raw-XML helper (previously only used by the table-edit path) — matching `T{n}` numbering is guaranteed since both walk the same body-level `<w:tbl>` elements in the same order. `tools.prepareDocument` and `cli_apply_section.py --dump-ids` now call this instead of `editor.doc.paragraphs()`.

Evidence used:
Direct read of `word/document.xml`/`word/styles.xml`/`word/numbering.xml` to confirm the document really has 29 tables and no numbering restarts; reading the vendor library source (`vendor/docxengine/_document.py`, `_anchors.py`) to find where tables get excluded; `tools.lookupStableId` calls before and after the fix.

Validation (confirmed working 2026-09-20):
`prepareDocument(force_regenerate=True)` now reports `table_rows: 193` (was 0). `lookupStableId("System Assessment Overview")` now returns 2 matches — `@H2.8-T1-R2` (`kind: table_row`, the Document Map table cell) and `@H4` (the heading) — correctly flagging the ambiguity instead of silently resolving to the wrong one. All 56 existing `csa_docx` unit tests (`pytest csa_docx/tests/`) pass unchanged. A-1's own anchor (`@H0-P20`, a body paragraph before any table) is unaffected, confirming the fix is additive, not disruptive, to existing paragraph-only anchors.

Improved authoring approach going forward:
Table-row anchors now work — draft table-cell edits normally via `lookupStableId`, but since a plain-text query can match both a table cell and a same-text heading/paragraph elsewhere, pass `kind="table_row"` (or a longer, more specific query) to disambiguate before trusting `unique_id`. The "record it as an Open question instead of guessing an anchor" rule still applies for any future manifest/tooling gap, not just this one.


## 2026-09-20 - "Document Control" is Section 1 even though its H1 is `@H2` (cover page is `@H0`)

Context:
Authoring Section 1 (Document Control) on a reorganised IAMPS workspace. `prepareDocument()` resolved fine, but `lookupStableId("@H1")` returned 0 matches, and the first level-1 heading was `@H2` = "Document Control", with the pre-heading cover block (title, "System Name: IAMPS", "Date: ...", "Prepared By: ...") living under `@H0-P*`.

Issue or risk observed:
A literal reading of "Section N = the N-th H1" would put Document Control at **Section 2** (since `@H1` doesn't exist and the H1 ordinal starts at 2). That contradicts the whole established pipeline: the prior learnings entry, the prior run-state, and the document's own Document Map all treat "Document Control" as **Section 1**, and every `ChangesCSA_..._Section<N>_...md` filename from earlier runs used that convention. Naively following the `@H<N>` ID would have mis-numbered every downstream change file.

Evidence used:
`run-state/stable-ids-Current_State_Assessment___IAMPS.json` (cover block is `@H0-P1..P21`, first H1 is `@H2` "Document Control"); the document's own `@H2.8-T1-*` Document Map rows, whose "Section" column uses the `@H<N>` IDs verbatim (System Assessment Overview = "4" = `@H4`, ... Infrastructure Dependencies = "15" = `@H15`), confirming the document itself numbers its technical body by H1-ordinal while the control/cover front matter occupies the "1" slot.

Improved authoring approach:
Treat the **cover page + Document Control front matter as Section 1** and the first *technical* H1 (System Assessment Overview, `@H4`) as Section 4, i.e. "Section N" = the document's own numbering, where the unnumbered cover + control block is N=1. Do not derive the section ordinal by counting level-1 headings and starting at 1; derive it from the `@H<N>` ID the manifest already assigns and cross-check it against the document's own Document Map. When in doubt, the document's own map is the tie-breaker.

Validation:
A future authoring run on any front-matter section of a document that has a cover page should confirm `lookupStableId("@H1")` returns 0 and the first H1 is `@H2`, then confirm the document's own map/front-matter treats that `@H2` section as "Section 1" before drafting.

## 2026-09-20 - `prepareDocument()` fails when >1 non-archived `.docx` exists; remedy is moving the strays into `z_Archive`

Context:
First `prepareDocument()` call on the reorganised IAMPS workspace returned `status: ERROR` (not `NOT_READY`): "4 .docx files found ... expected exactly one at this stage (before any reviews/ change file exists...)." The workspace held the real working DOCX plus three unrelated NetSeg deliverables in separate folders.

Issue or risk observed:
`tools._find_workspace_docx` (the true-step-0 path, taken when no `reviews/ChangesCSA_*.md` exists yet) does `workspace.rglob("*.docx")` and requires **exactly one** candidate, skipping only Word lock files and anything under a directory whose name contains "archive" (case-insensitive) or starts with "old" -- see `manifest._is_archived`. Any other extra `.docx` in the tree is fatal and the call refuses to proceed, naming all the candidates.

Evidence used:
`tools.py` (`_find_workspace_docx`, the "expected exactly one ... move or archive the extra file(s)" error) and `manifest.py` (`_is_archived`: `if "archive" in lowered or lowered.startswith("old")`). The four offenders were `Current State Assessment - IAMPS.docx` (the working doc, under `01 Current State AS Built/01 Final Version/`) plus `NetSeg_HighLevel SolutionDesign and Plan_IAMPS.docx`, `NetSeg_Current_State_Assessment-IAMPS.docx`, `NetSeg_Change_Scope_Options-IAMPS.docx`.

Improved authoring approach:
On a `prepareDocument` ERROR about multiple `.docx`, do NOT delete anything. Move (not copy) the non-working `.docx` files into a `z_Archive/` subfolder next to each -- that is the framework's own stated remedy and `_is_archived` will now exclude them, leaving exactly one candidate. Then re-run `prepareDocument()`. Keep the working DOCX in place; it is the one the section manifest pairs with. This is reversible and safe.

Validation:
After moving the three NetSeg files into per-folder `z_Archive/`, `find . -name '*.docx' -not -path '*/z_Archive/*'` returns exactly the working DOCX, and `prepareDocument()` returns `status: READY` with a fresh manifest and all integrity checks Pass.

## 2026-09-20 - Recurring "HTTP/S (80/443)" protocol string appears in multiple sections; verify per-instance

Context:
Authoring Section 3 (System Assessment Overview). Section 2 had already flagged the same "HTTP/S (80/443)" string at `@H3.3.4-P4` (drafted as E-3). Section 3's "multi-protocol communication" list at `@H4.1.2-P8` contains the identical string.

Issue or risk observed:
A document-wide search for "80/443" or "HTTP/S" shows the string recurs in at least five places (Sections 2, 3, 5, 6, 8 — anchors `@H3.3.4-P4`, `@H4.1.2-P8`, `@H5.1.4-P13`, `@H6.6-T3-R2`, `@H9.4.2-P4`). Authoring each section in isolation risks (a) re-drafting the same correction under a new E- number without noting it is the same finding, or (b) missing the cross-section consistency implication entirely.

Evidence used:
- No discovery capture (ROKPRDAMP101/102 @ 2026-04-27 & 2026-04-29; `tg_discovery_20260317T002440Z` on MKYPRDAMP102) shows port 80 listening; port 443 is present on every host.
- Evidence-matrix E-040 (WebMethods HTTPS, Zentrak HTTP, ViziRail "HTTP+SQL") and E-049 (WebMethods `10.200.100.78:443`, TCP verified) confirm the HTTP integrations are HTTPS:443.
- NetSeg conduit table (E-025) labels ViziRail "HTTP+SQL" and one conduit "IT_OT_File_Transfer (TBD)" without pinning a port — the residual uncertainty that keeps this as an open question rather than a confirmed edit.

Improved authoring approach:
When an identical factual string (same ports, same service names, same host set) recurs across multiple sections, draft the correction in each section's own change file (one E- per section, since each section's file is independently approvable), but in each file's Open questions note that it is the same finding as the other section(s) and that a single human confirmation (e.g. "is port 80 used on any out-of-capture host?") gates all of them. Do not cross-reference E- numbers between files as if they were one edit — they are separate approval units.

Validation:
Section 2's change file (E-3) and Section 3's change file (E-4) each contain the same Open-question bullet about the port-80 scope, and each names the other section's E- number. A workspace-wide `grep -n "80/443"` over the reviews/ folder shows the string only in the change files' own prose (quoting the current document text), not as a residual uncorrected draft.

## 2026-09-20 - Verify "evidence gap" claims by grepping the Discovery Data folder for the claimed hostname

Context:
Section 3's host-set section contains two "evidence gap" notes: `@H4.3.5-P8` ("MKYPRDAMP101 is defined in design but not present in extracted script outputs") and `@H4.3.5-P11` (same claim, different wording).

Issue or risk observed:
An "evidence gap" claim is a negative claim — it asserts the *absence* of evidence. Absence is easy to accept on faith (the document says so, and the design document does list the host), but it is also easy to be wrong about if a capture folder exists that the document's author did not review. Accepting it without checking risks leaving a stale "gap" note in the document when the evidence actually exists.

Evidence used:
`grep -rl "MKYPRDAMP101" "01 Current State AS Built/IAMPS Discovery Data/"` returned zero hits. The only MKY PRD AMP host captured is `MKYPRDAMP102` (in `tg_discovery_20260317T002440Z`). The document's gap note is therefore accurate.

Improved authoring approach:
For any "evidence gap" / "not present in script outputs" / "no capture available" claim in a document, before accepting or editing it, run a workspace-wide `grep -rl <claimed-hostname>` over the Discovery Data folder. If the hostname appears in any capture folder, the gap note is stale and the edit is to *remove* the gap note (and add the host to the confirmed set). If it does not appear, the gap note is accurate and the correct action is to leave it unchanged and record it under "Items intentionally left unchanged" with the grep result as the justification.

Validation:
The grep result is reproducible: `cd "<workspace>" && grep -rl "MKYPRDAMP101" "01 Current State AS Built/IAMPS Discovery Data/"` returns no files. The "Items intentionally left unchanged" bullet in `ChangesCSA_IAMPS_Section3_E4.md` cites this grep as the justification.

## 2026-09-21 - Evidence mapping for Executive Overview / Discovery Summary claims (AD, DNS, NTP, RabbitMQ, agents, integrations)

Context:
Authoring Section 2 (Executive Overview) batch 1. The section's checkable claims are summary statements that repeat findings from later technical sections.

Issue or risk observed:
Needed a topic-to-file mapping for the dependency, agent and integration claims, and found that capture depth differs sharply between runs.

Evidence used:
- Domain membership: `00_host_summary.txt` (April captures) or `52_auth_configs.txt` (`Domain` / `PartOfDomain` table, March captures).
- DNS resolvers: `14_resolver.txt`. NTP source and peers: `03_time_status.txt` (`Source:` line and `Peer:` blocks).
- Listening ports and owning process: `20_listening_ports.txt` plus `10_listeners_by_process.txt` (PID to process name).
- Which application talks to what (remote address, port, process): `23_process_connection_mapping.txt`, then `22_top_remote_endpoints.txt` for counts. `25_netstat_tcp_samples.txt` catches short-lived connections (for example SQL 1433) that the established-connection files miss.
- Dependency reachability tests (AD, DNS, TAS RabbitMQ, email, WebMethods): `57_connectivity_tests.txt` and `49_iamps_integration_validation.txt`.
- Agent presence (MECM, SCOM, Splunk, CrowdStrike): `24_tasklist_services.txt`, `32_services_inventory.txt`, `67_installed_software.txt`, `72_sccm_mecm_check.txt`.
- Host firewall and policy: `31_firewall_profiles.txt`, `33_firewall_rules.txt`, `59_gpresult_computer.txt`, `65_local_security_policy_export.txt`.
Caveat: the `tg_discovery_20260317*` captures are lightweight (about 13 files, no service inventory, no software list, no connectivity tests). Only the April `IAMPS_discovery_ROKPRDAMP10x_*` captures carry the 80+ file set.

Improved authoring approach:
Before accepting or editing a claim of the form "component X is present or configured on the hosts", list which captures actually contain the relevant file. If only some hosts were inspected, propose scoping wording rather than a fact change, and never read a missing file as an absence. Check the file list of each capture folder first.

Validation:
A `grep -rli <service name>` per capture folder shows which captures could have confirmed the claim; the change file names the confirming hosts.

## 2026-09-21 - Identical short bullet paragraphs cannot be anchored by `lookupStableId`; anchor an insertion on a unique neighbour

Context:
Section 2 lists NTP sources as two one-line bullets ("ROTPRDSRV122.internal.qr.com.au", "MOTPRDSRV122.internal.qr.com.au"). The same one-line paragraph text recurs in at least seven places document-wide.

Issue or risk observed:
`lookupStableId` returned `match_count` 7 with `unique_id` null, and a longer snippet cannot help because the paragraph text is identical. The rule is to record such items as open questions, not to pick a match by its `section_path`.

Evidence used:
`lookupStableId("ROTPRDSRV122.internal.qr.com.au")` returned matches in `@H3.3.2-P8`, `@H4-P17`, `@H5.1.4-P7`, `@H10.3.2-P2`, `@H10.4.2-P2` and others. The neighbouring line "Confirms full dependency on enterprise AD, DNS, and NTP" returned a single match (`@H3.3.2-P10`).

Improved authoring approach:
When the paragraph that needs correcting has non-unique text, express the correction as an "Insert before/after" edit on a neighbouring paragraph whose text resolves uniquely, and say in the Why why the original bullets were not edited directly. Do not choose one of several matches.

Validation:
Each `Where:` in the change file has a `lookupStableId` result with `match_count` 1 for its own snippet.

## 2026-09-21 - Correction to the 2026-09-20 "HTTP/S (80/443)" entry, and section-numbering note

Context:
Section 2 re-run after the document was restarted with stable IDs. Two earlier statements were re-checked against the Discovery Data.

Issue or risk observed:
The 2026-09-20 entry says "port 443 is present on every host". Port listeners were re-checked: 443 listens only on ROKPRDAMP101 and ROKPRDAMP102 (`20_listening_ports.txt`, owner PID 4 System), not on MKYPRDAMP102 or the UAT hosts, and no AMP host listens on 80 (only ROKPRDOPS114 does). The outbound port-80 connections seen belong to `CcmExec` (`23_process_connection_mapping.txt`). The earlier conclusion that no capture shows port 80 listening still holds; the "443 on every host" part does not.
Separately, "SECTION=N" means the Nth Heading 1 (Document Control is 1, Executive Overview is 2), while the document's own numbering and its Document Map print Document Control as 2 and Executive Overview as 3, and the stable IDs are `@H<N+1>`.

Evidence used:
`20_listening_ports.txt` and `10_listeners_by_process.txt` across all 12 captures; `ChangesCSA_IAMPS_Section1.md` (Document Map numbering); the manifest heading list.

Improved authoring approach:
Verify listener claims per host from `20_listening_ports.txt` rather than reusing an earlier summary. On any numbered-section request, state which heading is being treated as Section N and raise the offset as an open question in the change file.

Validation:
A per-host port table (host, port, process) reproduces the 443 and 80 result. The change file's open questions name the numbering assumption.

## 2026-09-21 - csa-mcp not exposed in the Cowork session: call the framework functions directly

Context:
The agent definition tells the run to call `prepareDocument()` and `lookupStableId()` as `csa-mcp` tools, but this session had no such tools.

Issue or risk observed:
Without the tools a run either stalls or falls back to hand-typed anchors, which the agent forbids.

Evidence used:
`.agents/framework/csa_docx/tools.py` exposes both functions. Running them from Python 3.10 on the device (with `datetime.UTC = datetime.timezone.utc` set first) and `workspace` set to the project root returned the same JSON the MCP tools would (`status: READY`, `unique_id`, `match_count`).

Improved authoring approach:
When the csa-mcp tools are absent, import `csa_docx.tools` directly through `device_bash` and call `prepareDocument` and `lookupStableId` with the project root as `workspace`. The anchors are still resolved by the framework, never typed by hand. Say in the run-state file that this was done.

Validation:
`prepareDocument` returns `READY` with a manifest path, and every `Where:` ID appears in a `lookupStableId` result.

---

## 2026-09-21 — Section 3: OPC is a family, not a single port

Problem:
The document listed "OPC (5481)" as if OPC were a single well-known port. In the IAMPS captures, OPC traffic appears on multiple data ports depending on the broker version and transport, and 5481 is just one of them (the UA over TCP port seen on the SCADA view interface).

Approach:
When a proposed change mentions a technology family (OPC, SQL Server, a binary protocol), state the design-intent name AND the observed port from the evidence. Do not collapse a family into a single port. The same rule applies to SQL Server (observed 56420, not 1433) and any binary database protocol (observed 6050, not a named port). If the port is version-dependent, say so in the change text and flag the alternate port as an open question.

Validation:
Each edit that names a protocol family carries the observed port from the capture evidence (file + line), and any unconfirmed alternate port is recorded as an open question in the change file.

## 2026-09-21 - Section 4 (Discovery activity) is verified against the capture folder inventory, not a single host's evidence

Context:
Authoring Section 4 (Discovery activity) for IAMPS. The section records which hosts were captured, what outputs were collected, and the key observations the captures "consistently showed".

Issue or risk observed:
Applying the normal per-host evidence pattern (pick a host, cite its files) is wrong for this section: its claims are about the capture set as a whole. "All hosts are domain joined" is only as strong as the weakest capture, and "no evidence was identified for X" is false if any single capture shows X.

Evidence used:
- 12 capture folders across 9 distinct hosts (E-075); full 85-file captures only for ROKPRDAMP101/102, 17-file captures for all others (E-076).
- Port matrix across all 12 captures (E-077): 443 on 3 of 12, port 80 on 1 of 12 (the management host only), 7058/7059 on 4 of 12.
- CrowdStrike/Splunk established only for ROKPRDAMP101; no inventory on the other hosts (E-078).

Improved authoring approach:
For any "discovery activity" / "capture coverage" / "what the scripts collected" section: (1) build the host × capture × file-set matrix first (folder listing + per-folder file counts); (2) evaluate every "all hosts" or "no evidence" claim against the whole matrix, not one host; (3) where a claim is true for some captures and unestablishable for others, draft the replacement as "confirmed on <named hosts>; not established for <named hosts>" rather than a blanket statement; (4) the "no evidence" list is the most error-prone block - check each item against at least one capture that could have shown it before leaving it unchanged.

Validation:
Each edit's Why cites the host-level E-id and names the capture folders that do or do not establish the claim. The change file's Open questions name the hosts whose captures could not decide the point.

## 2026-09-21 - Section 7 (Identity & Authentication): separate the "not primary" conclusion from the "Script absence" evidence cell

Context:
Authoring Section 7 (Identity & Authentication) for IAMPS. The section concludes domain AD is the sole relied-upon authentication path and lists "no evidence of local-only / standalone / alternate authentication".

Issue or risk observed:
A blanket "no evidence of local authentication" claim is tempting but wrong to leave as-is. The full-capture script outputs for ROKPRDAMP101/102 DO capture local (non-domain) user accounts: `44_local_users.txt` shows enabled local accounts `SrvAdmin` (last logon 26/06/2019) and `BladeLogicRSCD` (last logon 01/06/2020), `PrincipalSource: Local`; `46_local_admins_membership.txt` shows `ROKPRDAMP101\SrvAdmin` (Local). So the summary table row's evidence cell "Script absence" is factually contradicted by the captures, even though the conclusion "local auth is not the primary mechanism" is correct.

Improved authoring approach:
For "no evidence of X" claims in an identity/auth section: (1) check the conclusion (is X the primary mechanism?) against the evidence -- if domain AD is primary, that conclusion stands; (2) separately check the *evidence basis* the row cites (e.g. "Script absence") against the actual captures -- if the captures DO show local accounts, the evidence cell is wrong and that is the correct, defensible edit (fix the basis, keep the conclusion); (3) scope the finding to hosts where the evidence exists -- local_users/local_admins files appear only in the full (85-file) captures, not the 17-file tg_discovery captures, so the finding is established only for ROKPRDAMP101/102. Do not draft an edit that asserts local auth is the primary mechanism (not supported), and do not leave a "Script absence" cell that the captures contradict.

Validation:
The single edit (S7-E1) changes only the evidence cell of the Local Authentication row and keeps "not primary"; its Why cites `44_local_users.txt` / `46_local_admins_membership.txt` (E-081, E-043) and names that the 17-file captures have no local_users/local_admins files (E-076). The domain-membership, Kerberos and service-account claims were left unchanged as they check out (E-033, E-042, E-045, E-051).

## 2026-09-21 - Section 8 (Network): distinguish a port *listener* claim from a *client/outbound* connectivity claim

Context:
Authoring Section 8 (Network) for IAMPS. The Findings list `@H9.4.2-P4` "HTTP/S (80/443)" is the recurring cross-section over-statement (identical string in 4 places: @H3.3.4-P4, @H5.1.4-P13, @H6.6-T3-R2, @H9.4.2-P4).

Issue or risk observed:
Two different claims look similar but have opposite evidence status: (a) a *listener* claim -- "the hosts use HTTP/S (80/443)" implies they listen on those ports -- is over-stated because no AMP host listens on 80 (only the mgmt host ROKPRDOPS114) and only 3 of 12 listen on 443 (E-077); (b) a *client/outbound* claim -- `@H9.3.2-P9` "connectivity exists to external endpoints (HTTP/S, SMB)" -- is SUPPORTED because the hosts make outbound connections (e.g. established to 10.40.228.98:443 on ROKPRDAMP101). Conflating them leads to either a wrong edit or a missed one.

Improved authoring approach:
For any protocol/port claim in a network/connectivity section: (1) check whether it is a *listening* statement (does the host listen on that port?) or a *client/outbound* statement (does the host connect out to that port?); (2) a listening statement is checked against `20_listening_ports.txt` / `10_listeners_by_process.txt` (per E-077), and a client statement against `21_established_connections_raw.txt` / `22_top_remote_endpoints.txt`; (3) only the listener claim that is not supported gets an edit; the client claim stays as written. The recurring "HTTP/S (80/443)" string is corrected per-section (each file corrects only its own occurrence and names the others in Open questions so one human confirmation gates all of Sections 2/3/4/8).

Validation:
S8-E1 edits only the Findings listener row `@H9.4.2-P4` (port 80 -> ROKPRDOPS114 only; 443 -> ROKPRDAMP101/102 + MKYPRDAMP102; outbound HTTPS kept), and leaves `@H9.3.2-P9` (client/outbound HTTP/S/SMB) unchanged as it is supported by the outbound-endpoint captures. Its Why cites E-077 and the outbound-endpoint capture.

## 2026-09-21 - Section 9 (Time Synchronization): "no evidence of a local X service" = independence conclusion vs service-presence evidence cell

Context:
Authoring Section 9 (Time Synchronization) for IAMPS. The summary rows `@H10.3.3-T1-R4` (Local NTP | Not present | No service observed) and `@H10.3.3-T1-R5` (Alternate Sources | Not present | Script absence), and Findings `@H10.4.2-P4` (no evidence of local NTP services or alternate time sources).

Issue or risk observed:
The independence conclusion (hosts are not independent of a local time source) is correct -- all 8 captured hosts source time from the two domain NTP servers (ROK-site -> ROTPRDSRV122, MKY-site -> MOTPRDSRV122 per 03_time_status.txt). But the service-presence evidence cells are contradicted: W32Time (Windows Time) is present and Running (Auto-start) on the ROK PRD full captures (32_services_inventory.txt), and UDP 0.0.0.0:123 (NTP port, all interfaces) is listening on ALL 8 captured hosts (20_listening_ports.txt). W32Time is in client mode (ReferenceId -> domain source), so it is not an independent source -- but "No service observed" / "Script absence" is false.

Improved authoring approach:
Generalises the S7-E1/S6-E3 lesson to any "no evidence of a local X service" claim: split (a) the independence conclusion (is the host independent of X? if it sources from an external provider, it holds) from (b) the service-presence evidence cell (is the local X service actually present? often yes, in client mode). The defensible edit corrects the evidence cell and keeps the conclusion. For NTP specifically, W32Time is a standard Windows client-mode service that is present on Windows hosts and listens on UDP 123, so "no local NTP service observed" is nearly always contradicted -- instead state the external source (the two domain NTP servers) and the client-mode service presence.

Validation:
S9-E1 edits the two summary-table rows (Local NTP / Alternate Sources) to record the W32Time service + UDP 0.0.0.0:123 listener evidence while keeping the "not an independent source" conclusion; its Why cites 03_time_status.txt, 32_services_inventory.txt, 20_listening_ports.txt (E-082). The accurate time-source statement @H10.3.2-P1..P3 is left unchanged.

## 2026-09-21 - Section 10 (Security Controls): "no evidence of CrowdStrike/Splunk" is contradicted on both ROK PRD full captures

Context:
Authoring Section 10 (Security Controls) for IAMPS. The observed-security-controls list `@H11.3.2-P1..P5` ("No direct evidence was identified for the following on IAMPS hosts: CrowdStrike (EDR/AV agent), Splunk forwarder or SIEM agent, Nessus, Nozomi").

Issue or risk observed:
The CrowdStrike and Splunk "no evidence" lines are contradicted. Both ROK PRD full-capture hosts (ROKPRDAMP101 AND ROKPRDAMP102) show CrowdStrike components (Sensor Platform, Windows Sensor, Device Control, Firmware Analysis) + CSFalconService, and Splunk Universal Forwarder + SplunkForwarder service (67_installed_software.txt, 32_services_inventory.txt). The 17-file tg_discovery captures have no software/service inventory, so presence is not established there -- absence cannot be claimed either. Also discovered: the same "No direct evidence ... CrowdStrike (EDR/AV agent)" text is DUPLICATED at @H10.8.5 under the anomalous Section 9 "Security Controls" sub-block, making the list-intro anchor non-unique.

Improved authoring approach:
For "no evidence of <security tool>" claims: (1) check the full-capture installed-software/service inventories for the tool on EVERY full-capture host (here both ROKPRDAMP101/102, not just one -- the prior E-078 had it only on ROKPRDAMP101; this run refines it to both); (2) the defensible edit scopes the line to "present on <full-capture hosts>; not established for <17-file hosts>" rather than asserting absence; (3) when the list-intro anchor is non-unique (duplicated elsewhere in the doc), anchor to the individual unique tool lines (CrowdStrike, Splunk) and flag the duplication as a structural/open item -- do NOT draft a cross-section dedup edit.

Validation:
S10-E1 (CrowdStrike line @H11.3.2-P2) and S10-E2 (Splunk line @H11.3.2-P3) both correct the "no evidence" to the confirmed presence on ROKPRDAMP101/102 + not-established scope; their Why cites 67_installed_software.txt/32_services_inventory.txt (E-083, E-032, E-063, E-072, E-078). Nessus/Nozomi lines left unchanged (no capture shows them).

## 2026-09-21 - Section 11 (Operations Monitoring & Procedures): a section can corroborate a sibling section's finding; authored-and-clean is a valid outcome

Context:
Authoring Section 11 (Operations Monitoring and Procedures) for IAMPS. This section lists the monitoring/management agents present on the IAMPS hosts.

Issue or risk observed:
Section 11 is ALREADY ACCURATE -- it correctly lists MECM/SCCM (CcmExec/SMS Agent Host), SCOM (HealthService), Splunk Forwarder (SplunkForwarder) and CrowdStrike Falcon (CSFalconService) as present on the IAMPS hosts, consistent with the full-capture inventories (both ROKPRDAMP101/102). This CORROBORATES the S10-E1/S10-E2 correction (Section 10 had wrongly said "no evidence of CrowdStrike/Splunk"). The "no evidence of local dashboards/alerting/host-based correlation" observations are the correct inference from the centralised agent model.

Improved authoring approach:
When a section's claims are already accurate and supported by the evidence, record it as authored-and-clean with a full "items intentionally left unchanged" rationale (naming the supporting E-ids), rather than forcing a scope edit. Surface any shared per-host-scope nuance (agents present on ROKPRDAMP101/102, not established on the 17-file captures) as an open question ALIGNED WITH the sibling section that actually carries the edit (Section 10), so the reviewer sees the consistent picture. Do not duplicate the edit across sections; each section corrects only its own inaccurate claim.

Validation:
Section 11 change file proposes no edits; its "items intentionally left unchanged" cites E-032/E-063/E-072/E-083 for the agent list and notes the per-host-scope nuance as Open question 1, consistent with Section 10 (S10-E1/S10-E2, E-083/E-078).

## 2026-09-21 - Section 13 (Backup & Recovery): "no backup services/snapshot tooling" conflates third-party agents with default Windows/VMware backup infrastructure

Context:
Authoring Section 13 (Backup & Recovery) for IAMPS. The Host-Level Observations list `@H14.2.2-P2..P6` asserts "No backup agents were directly identified, including: Veeam / NetBackup / Commvault / Windows Backup services (active configuration)", and `@H14.2.2-P11..P14` "No evidence of: local backup repositories / snapshot tooling / host-based backup configuration".

Issue or risk observed:
The absence cells are partially contradicted. The ROK PRD full-capture hosts (ROKPRDAMP101/102) DO run backup-related Windows/VMware services by default: the VSS service (vssvc.exe), the ntfs "Block Level Backup Engine Service", the VMware snapshot-provider services (vmicvss, vmvss -- "VMware Snapshot Provider"), and the default Windows backup scheduled tasks (RegIdleBackup, BackupTask). These are hypervisor-guest Windows components, NOT an installed third-party backup agent or a locally configured backup repository. The no-agent conclusion holds (67_installed_software.txt has no Veeam/Commvault/NetBackup), but "No backup services ... identified" and "No snapshot tooling" as written are false as stated, and the absence was also over-scoped to all hosts when only 2 hosts have an inventory (the 17-file tg_discovery hosts have no services/software inventory).

Improved authoring approach:
Generalises the S9-E1/S7-E1/S10 lesson to the backup domain: (1) distinguish "third-party backup AGENT" (Veeam/Commvault/NetBackup -- correctly absent per installed-software) from "default Windows/VMware backup INFRASTRUCTURE" (VSS, ntfs backup engine, VMware snapshot providers, default backup tasks -- present on hypervisor-guest Windows hosts); (2) the defensible edit states the no-agent/no-active-backup-repository conclusion accurately AND names the default infrastructure that IS present, rather than asserting "no backup services / no snapshot tooling"; (3) scope the absence claim to the hosts that actually carry an inventory (full captures) and record the 17-file hosts as NOT_ESTABLISHED (E-085); (4) the interpretation ("externally / infrastructure-managed") and the OT 3.5 gap conclusion are CORRECT and corroborated by the design's SQLCDNAGL003 "IAMPS Backup Database" destination (E-059) -- leave them unchanged.

Validation:
S13-E1 replaces the Host-Level Observations absence list with a no-third-party-agent + default-infrastructure-present + host-scope statement; its Why cites 67_installed_software.txt / 32_services_inventory.txt / 66_scheduled_tasks.txt (E-084, E-060) and the 17-file-host scope (E-085). The interpretation, findings, drawbridge, operational-behaviour and OT 3.5 gap conclusions are left unchanged (E-059, E-061, E-062).

## 2026-09-22 - Section 12 (Patch & Lifecycle Management): "centrally managed patching" needs the mechanism + measured currency, and E-071 already carries both

Context:
Authoring Section 12 (Patch & Lifecycle Management) for IAMPS. The Observed subsection establishes MECM enrollment (ccmexec Running, WMI ClientVersion 5.00.9122.1019) and concludes patching is "centrally controlled / executed via enterprise infrastructure", but it names neither the actual Windows Update source nor the current patch level, and the Drawbridge/Operational Behaviour consequence uses the unqualified term "current patch level".

Issue or risk observed:
Two verified, directly-observed facts were on record (E-071) but absent from the section: (1) Windows Update is sourced from the corporate WSUS point https://IPTPRDCCM202.internal.qr.com.au:8531 with UseWUServer=1 and NoAutoUpdate=1 (direct online update disabled) -- the concrete mechanism behind "centrally controlled" and the distribution point the Drawbridge subsection later says will be lost; (2) the measured patch currency -- KB5091575 / KB5082137 (Security) / KB5082427 installed 27/04/26 and KB5078763 (Security) 23/03/26, IDENTICAL on both ROKPRDAMP101 and ROKPRDAMP102, i.e. patched within two days of the 29/04/26 capture.

Improved authoring approach:
For a "centrally managed X" section, three insertions/edits anchor the claim to evidence instead of leaving it as an assertion: (1) Insert the X mechanism (the update/management source endpoint + the policy that disables the local/default path) right after the enrollment facts, mirroring the section's existing "From service inspection: / Service: / Status:" line list; (2) Insert a dated, both-host "Observed ... currency" line with the concrete identifiers and the "within N days of capture" currency, noting the two hosts are identical (strengthens, does not overstate); (3) Replace the generic consequence phrase (e.g. "current patch level") with the dated, evidenced level so the Drawbridge reasoning is consistent. Keep the design, the "no local repository / no independent lifecycle" statements, and the Drawbridge/Assessment conclusions unchanged (they are correct and corroborated). Cite E-071 for all three.

Validation:
S12-E1 inserts after @H13.3-P10 (WSUS source + NoAutoUpdate), S12-E2 inserts after @H13.4-P12 (KB currency, both hosts, 27/04/26), S12-E3 replaces @H13.4.3-P2 ("current patch level" -> dated level). All three anchors resolved via lookupStableId with match_count=1. No new matrix row needed (E-071 already VERIFIED and matches both-host source). MECM enrollment left unchanged (E-064).

## 2026-09-23 - Multi-section pass (S1, S2, S3, S14, S15, S16): the "no agents/no security tooling" pattern is NOT universal, and an already-APPLIED edit can itself be the new gap

Context:
Continuing the all-sections (1→16) authoring pass after S4–S13 were drafted. The recurring finding in S4/S5/S9/S10/S13 was the pre-correction "no agents / no security tooling / no backup services" conclusion in Findings/Drawbridge/Assessment text that contradicted the verified agent presence (CrowdStrike, Splunk, MECM, SCOM) and the default Windows/VMware infrastructure present on the ROK PRD full-capture hosts.

Issue or risk observed (two distinct lessons):
(1) The contradiction is section-specific, not global. The OVERVIEW-level sections (S2 Executive Overview, S3 System Assessment Overview) and the consolidation/reference sections (S14 Infrastructure Dependencies, S15 Glossary, S16 Appendixes) already state the agent presence correctly (as "present but centralised / external") and scope the messaging as local-RabbitMQ-plus-external-TAS, the NTP as enterprise-sourced, and the hosting as inferred. They do NOT carry the S4/S5/S9/S10 error. So a section-by-section pass must NOT force an edit where the text is already accurate — S2, S3, S14, S15, S16 were all reviewed-and-clean (authored-and-clean), written as auditable no-op records rather than silently skipped. The S11 "clean" lesson generalises to the overview/consolidation/reference sections.
(2) Re-reviewing an already-APPLIED section can surface that the applied correction was itself wrong. S1 (Document Control) had S1-E1/S1-E2 already APPLIED, renumbering the Document Map's last two rows to 16 and 17 on the assumption the document had 17 Heading-1 sections. A live re-count showed the document has exactly 16 Heading-1 sections (1 Document Control … 14 Infrastructure Dependencies, 15 Glossary and Acronyms, 16 Appendixes), so "Glossary and Acronyms" is H1 #15 and "Appendixes" is H1 #16. The applied 16/17 was an over-correction. S1-E3 (16→15) and S1-E4 (17→16) were drafted to restore the correct numbering — a correction that partially reverses the already-applied S1-E1/S1-E2.

Improved authoring approach:
- Before drafting, count the live Heading-1 order directly from word/document.xml (filter w:pStyle="Heading1", include empty/hidden check, and check outlineLvl=0 as a fallback). Do not assume the section count from a prior run's summary — the count is the ground truth for any Document-Map numbering edit, and it can change between runs (e.g. a section added/removed, or a prior wrong assumption baked in).
- For the recurring "no agents / no local X" theme: fix the CONCLUSION to name what IS present (agents on ROK PRD full captures; default Windows/VMware infra; local RabbitMQ) and keep the genuinely-absent item (third-party agent, local provider, independent source). But apply this only where the section's own text is actually contradictory; where a section already states presence correctly (S2/S3/S14/S15/S16), record authored-and-clean and carry the per-host-scope nuance as an open question aligned with the sibling sections that do carry the edit.
- When re-reviewing an already-APPLIED section per the user instruction ("do the ones that have one and add to it if you find more"), compare the APPLIED result against the live document state, not just the original text. An applied edit can over-correct (as S1 did). Draft the new correction as S<N>-E<next> that explicitly reverses the over-corrected cells, and note in "Expected result if approved" that it partially reverses the prior applied edit, so the reviewer sees the net effect.
- When inserting new edits into an existing change file that already has a "## Changes Report" (apply log) and a populated "## Expected result if approved", insert the new edits under "## Proposed changes" (after the last existing edit), and rewrite "## Expected result if approved" to cover the full current set. Do NOT splice new edits in the middle of an existing prose paragraph — that corrupts the document. (First attempt in this pass split an "Expected result" paragraph; caught and restructured.)
- Reference/placeholder sections (S16 Appendixes: heading only, no body) and glossaries (S15) have few or no checkable claims; for the glossary, verify that platform terms it "lists in the … assessment" (Nessus, Nozomi) actually appear in the named body section (confirmed in S10: "Vulnerability Management – Nessus", "Network Monitoring and Visibility – Nozomi", and "Design-defined security control requirements (e.g. CrowdStrike, Splunk, Nessus, Nozomi)"; E-074 records the scan results as not found). A glossary entry that references a platform not present in the body would be a real inconsistency; here it is not.

Validation:
- S2, S3, S14, S15, S16: change files written as authored-and-clean (no edits), each with "items intentionally left unchanged" citing the supporting E-ids and a per-host-scope open question (E-078/E-085) where relevant. Run-states written (csa-change-authoring-section-2/3/14/15/16.md), all DRAFT_COMPLETE.
- S1: re-review found the already-applied S1-E1/S1-E2 over-corrected (16/17) for a 16-section document. Live H1 count = 16 confirmed (no hidden/empty H1, no outlineLvl=0). S1-E3 (16→15) and S1-E4 (17→16) appended under "## Proposed changes"; "Expected result if approved" rewritten to cover S1-E1..E4 and note the partial reversal of the applied S1-E1/S1-E2. Run-state written (csa-change-authoring-section-1.md, DRAFT_COMPLETE). None applied (drafting only).
- All six sections: DRAFT_COMPLETE. No DOCX mutation, no apply, no Word comments (authoring pass only).

## 2026-09-23 - Editorial mode pilot (UTC DTC, Security Services, framework Section 10)

- Scope: generic (applies to any CSA editorial pass).
- Trigger: first `EDIT_MODE=editorial` run.
- Lessons, now folded into csa-change-authoring.md (Editorial Mode, "Lessons from the first pilot"): number edits bottom-up; the @H range Replace format that parses; Replace keeps List Paragraph style, so bullet share cannot fall; raw log lines become statements plus a source reference, with dropped detail listed for the approver; interpretations get an approver-check line; do not remove file lists the appendix lacks; framework Section<N> counts empty Heading 1s, so use `prose_lint.py --heading`; simulate edits to get after-metrics.
- Environment (Cowork device bridge): csa_docx needs the `datetime.UTC` shim on Python 3.10, and PROJECTS.yaml `/Users/wenzel/Work/ASE/...` roots must be mapped in-process to `~/mnt/...` for the workspace guard. The registry file itself was not changed.
- Validation: 13 records parsed by change_parser (11 ranges, 2 singles); simulated lint 1,043 -> 902 prose words, lead-ins 8 -> 3, nested bullets 40 -> 25.

## 2026-09-24 - UTC DTC Section 10 security evidence mapping

- Topic: endpoint and host security controls.
- Useful evidence patterns: `32_services_inventory.csv` for Nessus, Splunk and WLAN AutoConfig coverage; `59_gpresult_computer.txt` for applied and filtered AppLocker Group Policy Objects.
- Caveat: distinguish the fully inventoried six-host `UTC_discovery_*` sample from the wider fleet. State counts and captured-host exceptions, then say wider fleet coverage is not confirmed.
- Existing analysis: `csa-work/analysis/security-posture-analysis.md` was useful as a topic map, but each drafted claim was checked against the cited evidence-matrix row before use. No matching section draft existed.

## 2026-09-24 - UTC DTC Section 10 complete security-section mapping

- Topic: completing a mixed host-security and network-security section from an existing analysis.
- Useful evidence patterns: `20_listening_ports.txt` plus `32_services_inventory.csv` for service exposure; `67_installed_software.csv` and Edge Update logs for browser currency and policy; `68_certificates_localmachine_my.csv` for certificate expiry and subject names; `31_firewall_profiles.txt` plus `33_firewall_rules.csv` for host-firewall posture; Vantage/Nozomi exports for public egress; `65_local_security_policy_export.txt` for the sampled CIS comparison.
- Caveat: keep sample boundaries explicit. A service observed on six full captures, a lifecycle condition observed on twelve lightweight captures, and network-level traffic across eight exports are different evidence populations and must not be collapsed into one fleet-wide claim.
- Existing analysis: `security-posture-analysis.md` efficiently identified gaps, but the completed authoring pass narrowed several statements to the host or capture where the matrix directly supported them.

## 2026-09-29 - Stable subsection IDs can differ from requirement-domain labels
Trigger: a template subsection request named stable `@H3.2`, while the domain scope helper interpreted `3.2` as the Identity & Authentication requirement domain at a different stable path.
Resolved 2 Oct 2026 (S240, S252): sections resolve by key from the document, so a typed number and the stable path cannot disagree.
Rule: when the user explicitly supplies a stable-ID scope, verify it against the live manifest and use that unit; record the helper mismatch rather than authoring into a different subsection.
