---
name: migration-discovery-analysis
description: Establish the migration-relevant current state of an Operational Technology application's system environment -- which hosts it runs on and which of them were examined, installed applications and components, failover and replication behaviour, patch and update tooling, Group Policy, and file transfer / local storage. Use for the Migration Discovery domain of a CSA (legacy Section 6, template section 4).
---

# Migration Discovery Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Write this section as a description of **the application and the systems it runs on, and how they are currently configured**, not as a catalogue of what the discovery data contains. Follow the shared rules in `csa-section-writer/references/current-state-reasoning.md` (subject rule, fact/evidence/gap classes, "not observed" vs "does not exist", correlation, scope, terminology) and the prose rules in `csa-writing-style` before drafting.

## Purpose

Describe, for migration planning, the current state of the application and the systems it runs on: which hosts it runs on (by role and site) and which were examined, what software and application components run on it, how redundancy and failover work, how it is patched and updated, what Group Policy governs it, and how files move and where local storage lives. The goal is that a migration engineer can plan from this section without opening the raw discovery packages.

## Three groups of hosts -- never conflate them

This is the single most important rule for this section. Keep three groups of hosts separate, and scope every statement to the group its evidence covers:

1. **Hosts in the asset list** -- the asset list or inventory of record: every host the system is recorded as having.
2. **Hosts with discovery captures** -- the hosts that were actually examined (a subset of the asset list).
3. **Each discovery run** -- the hosts captured on one date at one site (for example March 2026, April 2026, May 2026 UTC, May 2026 SIGMAP), each of which may have collected different outputs.

Say it in those plain words in the CSA: "the 42 hosts with discovery captures", "hosts captured in May 2026", "hosts in the asset list". Do not write "estate", "declared population", "discovery population", "application sample" or "capture campaign" in the document; they are data-collection terms (`australian-it-ot-terminology`, part 6).

A finding drawn from the May 2026 captures is not a fact about every host in the asset list. If a count appears in prose, the reader must be able to answer "count of what, as of when, from which source" without opening the appendix. A stale or unexplained number (the classic "11 sampled hosts" error) is a `MINOR` finding at minimum and must be corrected to the actual population or removed.

## Questions the section must answer

1. Which hosts make up the application environment (by role and site), and which were examined (which discovery runs, which outputs)?
2. What software and application components run on the captured hosts, and on which hosts?
3. How is redundancy and failover provided -- by the application, by the OS, or not at all? What are the Left/Right or production/DR pairings?
4. How is the environment patched and updated, through what tooling, and how current is it?
5. What Group Policy governs the environment, per host class?
6. How do files move, and where does local storage and log capture live?

## Expected source evidence

- The declared asset list / inventory (with roles, sites, classes).
- Per-host discovery captures: installed software, running processes, services, NIC and resolver config, listening ports, scheduled tasks, shares, mapped drives, OS version and build, installed hotfixes.
- Application module configuration files (partner names, endpoints, ports).
- Patch / update management records (SCCM/MECM collections, deployments, maintenance windows).
- Group Policy results (`gpresult` / applied-GPO lists) per host.
- Network flow / connection data (for the failover and interface observations).
- Prior assessment records describing roles, pairings, and migration treatment.

## How to analyse and correlate

- **Correlate before writing.** Installed software + running processes + module config + network connections together establish what each host actually does and how it pairs with its partner. Do not write "the software list shows X; the process list shows Y; the config shows Z" -- write the one system statement those sources jointly establish (e.g. "TCSI runs as duplicated hot-standby hosts; the partner is named in module configuration").
- **Distinguish the application components from the management and security agents.** The UTC/DTC application modules (identified from running processes) are part of the application. CrowdStrike Falcon, the Configuration Manager client, the Tenable Nessus agent, the Splunk universal forwarder and LAPS are agents of enterprise IT services installed on the hosts. Keep the two groups separate in the table, even though both come from the same capture.
- **Redundancy is a system property, not a per-host fact.** "No Windows Failover Clustering service was found on any captured host" is a finding about the application's redundancy model (the application handles it), not an absence to assert per host.

## Handling conflicting evidence

- If the asset list and the discovery captures disagree on a host name, role, or class (e.g. `ROKTELEFT` vs `ROKTELEFT24`), record it as an assessment gap and add it to the open questions -- do not silently pick one.
- If a host appears in one source (the SCCM collection, the asset list) but not another (the Section 3 table), state the scope exception rather than folding it in.
- Never upgrade an inference (a host is "probably" the Message Redirector because of its address pattern) to a verified fact without a corroborating source.

## Handling gaps and unknowns

State as gaps, scoped to the hosts examined: patch state of hosts in the asset list without captures, MECM collections / deployments / maintenance windows not yet confirmed, App-V package coverage, licensing on hosts without a licence manager, and the output location / retention of continuous captures. "Not observed in the supplied evidence" is not "not implemented" and not "not present on the captured hosts".

## Expected IT/OT terminology

Follow `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`); its table is in `references/terminology.md`. For this section in particular:

- **Hosts and roles:** name each host's role as the application names it (Central Engine, Message Redirector, Telemetry Processor, TCSI, SIGMAP server, operator workstation, engineering workstation), with a plain description on first use.
- **Redundancy:** Left/Right pair (vendor term), duty/standby or hot standby, production and disaster-recovery channels, failover. Say what provides the redundancy (the application, not Windows Failover Clustering).
- **Patching:** Configuration Manager (SCCM/MECM) client, software update point, update collection, deployment, maintenance window, patch level, end of support (with the vendor's date).
- **Group Policy:** Group Policy Object (GPO), organisational unit (OU), applied GPOs, Restricted Groups, security baseline. Keep policy names exactly as written, including DEV/PRD prefixes.
- **Files and storage:** network share (file share), mapped drive, local storage, scheduled task, service account, log copy.
- **IT/OT classification:** the OT hosts run the application; Configuration Manager, the INTERNAL domain and its Group Policy, CrowdStrike, Splunk and the IT file shares are enterprise IT services the hosts depend on. State where each sits when the evidence shows it, and do not call them OT.
- **Keep the template headings** (Installed Applications, Failover and Replication Behaviour, Patch and Update Tooling, Group Policy Observations, File Transfer and Local Storage); name any added subsection from its content.

## Expected section structure

- **Intro**: two or three sentences on the application's hosts that were examined and when. Lead with the hosts the findings are drawn from, because that count bounds the section; the size of the asset list is context that belongs in the asset-inventory section, not here.
- **Application hosts and discovery scope** (not "Estate and Discovery Coverage"): the application's hosts by role and site, with the discovery run(s) that captured each, and a short scope table (asset list, hosts with captures, each discovery run) saying what each group is used for. If the table only lists servers and roles, "Server Environment" may fit better; choose the heading from the content (`australian-it-ot-terminology`, part 6).
- **Installed applications and components**: a table of application / component, category, and the host(s) / evidence scope.
- **Failover and replication behaviour**: the redundancy model, the pairings, and the migration constraint (preserve name resolution or fixed addresses).
- **Patch and update tooling**: the patching mechanism, its currency, and the host-class table.
- **Group Policy observations**: the host-class groups and the applied-GPO matrix.
- **File transfer and local storage**: the shares, the backup / log-capture mechanism, and the engineering-tooling transfer path.
- **Open questions**: the scope exceptions and unresolved conflicts.

## Tables and diagrams that help

- Discovery scope table: host group (asset list, hosts with captures, each discovery run), count and what it counts, what it is used for.
- Installed-applications table: application / component, category (application component, management or security agent, I/O driver, engineering tool, supporting runtime), host(s) where observed.
- Patch / update table: host(s) / scope, update collection, deployment, settings, maintenance window.
- Group-Policy table: GPO grouping, category, observed-in evidence group.
- A small pairing diagram (Left/Right per role across the two sites) where the failover topology is clearer visually.

## How findings are written

Each finding is one short paragraph or a table with a one-line lead. Lead with the system statement, scoped to the population its evidence covers. Examples:

> Patching is managed through the IT-hosted Configuration Manager service. Every host captured in May 2026 runs its client and takes updates from the Software Update Point; the newest update on any of them was installed in early August 2025, nine months before the capture. The patch state of the other hosts in the asset list has not been established.

> Redundancy is handled by the application, not by the operating system: no Windows Failover Clustering service was found on any captured host. The application roles run as Left/Right pairs across the two sites, and each pair keeps working after migration only if the partner names still resolve or the fixed addresses are preserved.

## What belongs and what does not

- **Belongs:** the application's hosts and which were examined, installed applications and components, failover / replication, patch and update tooling, Group Policy, file transfer and local storage, the scope exceptions.
- **Does not belong:** the rating of a requirement against a control standard (goes to the owning domain in the requirement section); the detailed per-domain isolation consequence (goes to each domain's drawbridge impact); future-state migration design (goes to the design / segmentation deliverable). This section is the migration-relevant *current state*, not the migration plan.

## Validation / review checks

Run `csa-writing-style/scripts/prose_lint.py` on the section. Then confirm:

1. The three groups of hosts (asset list, hosts with discovery captures, each discovery run) are never conflated, and every scope-limited statement names its group in plain words.
2. No stale or unexplained count (e.g. an old "N sampled hosts" figure) remains in the prose.
3. The subject of each sentence is the application, the environment, a host, a component, or a service -- not "the discovery data" / "the workbook" / "the table".
4. Application components and management/security agents are kept separate in the installed-applications table.
5. The redundancy model is stated as a system property, with the migration constraint (name resolution / fixed addresses) made explicit.
6. The patch-currency finding is scoped to the capture set, and the uncaptured hosts are declared as not established.
7. Group-Policy observations are scoped to the host classes and the applied-GPO sample.
8. File-transfer and local-storage findings are scoped to the captures that included share / drive output.
9. Every material statement traces to an E-id in the change record / Word comment / evidence matrix.
10. The section agrees with the asset-inventory and the per-domain sections on host names, roles, and pairings.
11. `term_lint.py` has been run and every flag resolved: no "estate", "application sample" or "discovery coverage" wording describing the application; Configuration Manager, INTERNAL domain Group Policy and IT file shares are described as enterprise IT services the OT hosts depend on, not as OT.

## Common failure patterns

- Using one stale sample count ("11 sampled hosts") throughout when the capture set is larger and multi-campaign.
- Presenting a finding from the May 2026 captures as a fact about every host in the asset list.
- Writing the section as a tour of the installed-software list and the gpresult output, with the application and systems only implied.
- Conflating the asset list with the hosts that have captures, or one discovery run with all of them.
- Writing headings and prose in data-collection language ("Estate and Discovery Coverage", "application sample", "not a full-estate absence claim") instead of naming the hosts and saying what was examined.
- Asserting "no failover clustering exists" as a bare fact instead of scoping it to the reviewed outputs and stating the application handles redundancy.
- Folding a host that appears in one source but not another into the main population without flagging the scope exception.

## Completion criteria

The section describes the migration-relevant current state of the application and the systems it runs on -- which hosts it runs on and which were examined, what runs on it, how it fails over, how it is patched and governed, and how its files move -- with every statement scoped to the population its evidence covers, the scope exceptions declared, and the reader able to plan a migration from the section alone. It passes `prose_lint.py` with no evidence-as-subject, evidence-ID, or connector warnings, every `term_lint.py` flag is resolved, and no stale or unexplained count remains.
