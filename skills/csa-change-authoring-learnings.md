# Change-authoring learnings (inbox)

New lessons from authoring runs, one short entry each, appended at the end. Wenzel folds reviewed entries into `csa-change-authoring-playbook.md`. The history before 26 Sep 2026 is in `.agents/docs/archive/csa-change-authoring-learnings-2026-09.md`.

Entry format:

    ## YYYY-MM-DD - <short lesson title>
    Trigger: <what happened>
    Rule: <what to do next time, one or two sentences, no host names or E-numbers>

## Entries

## 2026-09-28 - Integration claims: check both ends and every site
Trigger: a subsection said all integrations terminate "at the same hosts per site" and cited captures from the peer servers, which were held in another project; only one site showed sessions.
Rule: confirm a cross-system flow from the evidence this project holds (listener-side process mapping, network monitoring exports), check each site separately, and treat "no domain authentication on the flow" as different from "unauthenticated".

## 2026-09-28 - Write from the section brief, not from the existing paragraph
Trigger: a Storage & Data Transfer subsection was corrected twice as a network description because the run checked the original paragraph's claims instead of asking what the section needs.
Rule: write the section brief (purpose, requirement IDs, B/C questions from the Must explain line and reviewer comments) before searching evidence; search by question, and treat an unanswered question as a finding.

- 2026-09-29 Patch/update tooling (migration 4.4) -> index tables windows_update_config, installed_hotfixes (InstalledOn is d/m/Y), services_inventory Name~edgeupdate, installed_software DisplayName~Edge; MECM collections and maintenance windows from index tables "tcs - software update configuration/software update groups" and ".../maintenance windows" (use --limit 500; Start Time is an Excel serial). No analysis/draft file helped.

## 2026-09-29 - Interpret Excel maintenance-window dates from the serial
Trigger: a displayed date was transcribed as 7 January 2017 even though Excel serial 42923 and the workbook description resolve to 7 July 2017.
Rule: for indexed workbook dates, reconcile the displayed string with the Excel serial and use Australian day-month ordering; retain the workbook-date/current-state gap separately.

- 2026-09-29 Host-centred evidence -> `csa hosts build/show/group/links` (hosts/*.csv from the discovery index). Workbook rows keyed by collection/row ID must be regrouped by host; MECM maintenance windows match by DeviceName, not collection ID; expand CONTROLLER70 / 73 shorthand before citing. Tables keyed by source IDs were rejected by Wenzel twice (6.4).
