# Change-authoring learnings (inbox)

New lessons from authoring runs, one short entry each, appended at the end. Wenzel folds reviewed entries into `csa-change-authoring-playbook.md`. The history before 26 Sep 2026 is in `.agents/docs/archive/csa-change-authoring-learnings-2026-09.md`.

Entry format: `## YYYY-MM-DD - <title>`, then `Trigger:` (what happened) and `Rule:` (one or two sentences, no host names or E-numbers).

## Entries

## 2026-10-01 - Exclude localhost from DNS-zone generalisations
Trigger: DNS query-test captures included `localhost` alongside names in the assessed domain, making an unqualified all-names statement inaccurate.
Rule: when describing zones resolved from DNS query tests, inspect loopback targets separately and qualify the domain statement; `41_dns_query_tests.txt` provides the deciding evidence.

## 2026-10-01 - Correct pending content through a new bounded record
Trigger: a targeted factual correction was requested while the live DOCX still contained applied, unreviewed tracked changes from an earlier section-placement run.
Rule: resolve anchors against the refreshed live manifest, quote the intended current wording from the authoritative section source when revision text is fragmented, and author the correction as new sequential edits without modifying the earlier change file.

## 2026-09-28 - Integration claims: check both ends and every site
Trigger: a subsection said all integrations terminate "at the same hosts per site" and cited captures from the peer servers, which were held in another project; only one site showed sessions.
Rule: confirm a cross-system flow from the evidence this project holds (listener-side process mapping, network monitoring exports), check each site separately, and treat "no domain authentication on the flow" as different from "unauthenticated".

## 2026-09-28 - Write from the section brief, not from the existing paragraph
Trigger: a Storage & Data Transfer subsection was corrected twice as a network description because the run checked the original paragraph's claims instead of asking what the section needs.
Rule: write the section brief (purpose, requirement IDs, B/C questions from the Must explain line and reviewer comments) before searching evidence; search by question, and treat an unanswered question as a finding.

- 2026-09-29 Patch/update tooling (migration 4.4): index tables windows_update_config, installed_hotfixes (InstalledOn is d/m/Y), services_inventory, installed_software; MECM collections and maintenance windows from the "tcs - software update ..." tables (--limit 500; Start Time is an Excel serial).

## 2026-09-29 - Interpret Excel maintenance-window dates from the serial
Trigger: a displayed date was transcribed as 7 January 2017 even though Excel serial 42923 and the workbook description resolve to 7 July 2017.
Rule: for indexed workbook dates, reconcile the displayed string with the Excel serial and use Australian day-month ordering; retain the workbook-date/current-state gap separately.

- 2026-09-29 Host-centred evidence: use `csa hosts build/show/group/links`. Regroup workbook rows by host; match MECM maintenance windows by DeviceName; expand CONTROLLER70 / 73 shorthand before citing. Tables keyed by source IDs were rejected twice (6.4).

## 2026-09-29 - Do not author an executive summary from unreviewed placeholders
Trigger: the executive-summary placeholders were ready for text, but every detailed requirement-domain section was still blank.
Rule: leave the executive summary unchanged until reviewed body sections support its scope, overall position, principal gaps and isolation outcome; do not introduce orphan facts directly from the evidence matrix.

## 2026-10-01 - PROSE_UNSUPPORTED and PROSE_LINT have distinct mechanics
Trigger: `check-change` flagged `PROSE_UNSUPPORTED` for gap sentences and `PROSE_LINT` for long sentences; both needed different fixes.
Rule: `PROSE_UNSUPPORTED` (fact_checks.py) exempts sentences matching `GAP_RE` (e.g. "not found", "not captured", "was not"); use that vocabulary for gap statements. `PROSE_LINT` (prose_lint.py) enforces `MAX_SENTENCE_WORDS=35` and `MAX_AVG_SENTENCE_WORDS=24` as hard caps; check both before drafting.

## 2026-10-02 - Evidence-to-topic mapping for Network / Segmentation requirement rows
Trigger: subsection 3.6 (SEP-NET-01/02/03) requirement rows were empty templates and each rating needed an evidenced basis; check-change rejected `basis: not found` and a 3-cell row.
Rule: map each requirement to its evidence topic before drafting - zone placement to the discovery target host map captures, inter-zone conduits to the expected flow map + design zone/conduit tables, and boundary-control enforcement to "not found" in the current sources. A requirement row must be exactly `<current state> | <rating>` (2 cells, rating last and in the dropdown set). Gap statements go on an `Unknown:` fact line (skips the basis gate) using GAP_RE vocabulary ("not found", "not captured"), never `{basis: not found}` (FACT_INFERRED) and never an inference word like "therefore" (PROSE_LINT).

## 2026-10-03 - Storage & Data Transfer requirement rows: evidence map + NOT_FOUND prose rule
Trigger: subsection 3.7 (SEP-STOR-01/02/03) requirement rows were empty templates; check-change kept flagging `PROSE_UNSUPPORTED` on any prose sentence whose only support was a NOT_FOUND row, even when the sentence used GAP_RE vocabulary ("was found in the sources").
Rule: map each requirement to its evidence topic before drafting - OT-resident storage and IT-file-share independence to the SQL cluster services capture and the local-shares inventory, the controlled file-transfer pattern to the expected flow map plus a "not found" proxy/AV control search, and the push-only direction to the expected flow map's outbound flows. A NOT_FOUND row does not satisfy the prose fact gate: keep the document Text cell positive/evidenced and carry the "not found" point on an `Unknown:` fact line (which skips the basis gate) instead of a body sentence.

## 2026-10-03 -- Section 3.8 Management & Administrative Access (REVELOC TETRA)

- **Topic:** jump host role and zone, OT-domain admin group membership, PAM tooling absence
- **Answered by:** system_matrix.xlsx (jump host role), 01_reveloc_target_host_map.txt (zone), 60_gpresult_user.txt (group membership), previous CSA (PAM absence, RD Users)
- **Caveat:** E-140 (gpresult IT domain groups on SQL cluster) is UNCONFIRMED; E-152 (OT_Reveloc_Administrators on jump hosts) was appended this run as VERIFIED after direct verification of the raw gpresult file. The gpresult user section shows group membership of the *captured user*, not the full group membership list -- the full list of who is in OT_Reveloc_Administrators is not captured.
- **No analysis or draft file helped for this topic.**

## 2026-10-03 - UNCONFIRMED rows: carry as Unknown fact lines, not observed facts
Trigger: a change file for 3.8 cited E-140 (UNCONFIRMED) as an `observed` fact ("member of IT domain groups") and listed E-140 in a Why section where the finding was actually backed by E-152 (VERIFIED). `check-change` does not flag either case - it only checks review_state for EVIDENCE_PENDING - so both slipped through.
Rule: before citing an evidence row as a fact, check its `status` column, not just its existence. If a row is UNCONFIRMED/CONFLICTING/INFERRED, carry it on an `Unknown:` fact line (GAP_RE vocabulary) and name the confirming owner; do not write the claim as established in the document Text. And when a fact's support comes from one VERIFIED row, cite that row in Why - do not let a related UNCONFIRMED row drift into the Why of a different record and into the Word comment's evidence list.
