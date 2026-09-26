---
name: migration-discovery-analysis
description: Establish the migration-relevant current state of an Operational Technology application's system environment -- the declared asset population versus the hosts actually captured, installed applications and components, failover and replication behaviour, patch and update tooling, Group Policy, and file transfer / local storage. Use for the Migration Discovery domain of a CSA (legacy Section 6, template section 4).
---

# Migration Discovery Analysis

Write this section as a description of **the application and the systems it runs on, and how they are currently configured**, not as a catalogue of what the discovery data contains. Follow the shared rules in `csa-section-writer/references/current-state-reasoning.md` (subject rule, fact/evidence/gap classes, "not observed" vs "does not exist", correlation, scope, terminology) and the prose rules in `csa-writing-style` before drafting.

## Purpose

Describe, for migration planning, the current state of the application and the systems it runs on: what is declared versus what was actually captured, what software and application components run on it, how redundancy and failover work, how it is patched and updated, what Group Policy governs it, and how files move and where local storage lives. The goal is that a migration engineer can plan from this section without opening the raw discovery packages.

## The three populations -- never conflate them

This is the single most important rule for this section. Keep three distinct populations separate, and scope every statement to the one its evidence covers:

1. **The declared population** -- the full asset list / inventory of record (every host the system is supposed to have).
2. **The discovery population** -- the hosts that actually have discovery captures (a subset of the declared population).
3. **Each capture campaign** -- the per-date, per-site subset of the discovery population (e.g. March 2026, April 2026, May 2026 UTC, May 2026 SIGMAP), each of which may have produced a different set of output categories.

A finding drawn from the May application sample is not a fact about the whole declared population. If a count appears in prose, the reader must be able to answer "count of what, as of when, from which source" without opening the appendix. A stale or unexplained number (the classic "11 sampled hosts" error) is a `MINOR` finding at minimum and must be corrected to the actual population or removed.

## Questions the section must answer

1. What is the declared population, and what was actually captured (which campaigns, which hosts, which output categories)?
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
- **Distinguish the application modules from the platform tooling.** The UTC/DTC application modules (identified from running processes) are a different thing from the management, monitoring, and security agents (CrowdStrike, SCCM, Nessus, LAPS, etc.). Keep the two groups separate in the table, even though both come from the same capture.
- **Redundancy is a system property, not a per-host fact.** "No Windows Failover Clustering service was found on any captured host" is a finding about the application's redundancy model (the application handles it), not an absence to assert per host.

## Handling conflicting evidence

- If the declared asset list and the discovery population disagree on a host name, role, or class (e.g. `ROKTELEFT` vs `ROKTELEFT24`), record it as an assessment gap and add it to the open questions -- do not silently pick one.
- If a host appears in one source (the SCCM collection, the asset list) but not another (the Section 3 table), state the scope exception rather than folding it in.
- Never upgrade an inference (a host is "probably" the Message Redirector because of its address pattern) to a verified fact without a corroborating source.

## Handling gaps and unknowns

State as gaps, scoped to the population: patch state of the uncaptured declared hosts, MECM collections / deployments / maintenance windows not yet confirmed, App-V package coverage, licensing on hosts without a licence manager, and the output location / retention of continuous captures. "Not observed in the supplied evidence" is not "not implemented" and not "not present on the captured hosts".

## Expected IT/OT terminology

Use: asset list, discovery capture set, capture campaign, application module, platform tooling, hot-standby, Left/Right pair, production / disaster-recovery channel, patch and update tooling, Software Update Point, maintenance window, applied Group Policy, host class, scheduled task, file share, mapped drive, local storage, log capture. Avoid "estate and discovery coverage" as a heading; use "discovery capture set" or "declared population vs discovery population" for the coverage table.

## Expected section structure

- **Intro**: the discovered hosts (the discovery population) and the capture campaigns, in two or three sentences. Lead with the population the findings are drawn from -- the discovery population -- because it is the count that bounds the section; the declared-inventory size is context that belongs in the asset-inventory section, not here.
- **Discovery coverage**: a table of the three populations (declared population, discovery population, each capture campaign) with what each is used for.
- **Installed applications and components**: a table of application / component, category, and the host(s) / evidence scope.
- **Failover and replication behaviour**: the redundancy model, the pairings, and the migration constraint (preserve name resolution or fixed addresses).
- **Patch and update tooling**: the patching mechanism, its currency, and the host-class table.
- **Group Policy observations**: the host-class groups and the applied-GPO matrix.
- **File transfer and local storage**: the shares, the backup / log-capture mechanism, and the engineering-tooling transfer path.
- **Open questions**: the scope exceptions and unresolved conflicts.

## Tables and diagrams that help

- Discovery-coverage table: population, verified coverage, how it is used.
- Installed-applications table: application / component, category, observed host(s) / evidence scope.
- Patch / update table: host(s) / scope, update collection, deployment, settings, maintenance window.
- Group-Policy table: GPO grouping, category, observed-in evidence group.
- A small pairing diagram (Left/Right per role across the two sites) where the failover topology is clearer visually.

## How findings are written

Each finding is one short paragraph or a table with a one-line lead. Lead with the system statement, scoped to the population its evidence covers. Examples:

> Patching is managed through the IT-hosted Configuration Manager service. Every host in the May 2026 capture set runs its client and points Windows Update at the Software Update Point; the newest hotfix on any of them was installed in early August 2025, nine months before the capture. The patch state of the remaining declared hosts is not established by this capture set.

> Redundancy is handled by the application, not by the operating system: no Windows Failover Clustering service was found on any captured host. The application roles run as Left/Right pairs across the two sites, and each pair keeps working after migration only if the partner names still resolve or the fixed addresses are preserved.

## What belongs and what does not

- **Belongs:** declared-population vs discovery-coverage, installed applications and components, failover / replication, patch and update tooling, Group Policy, file transfer and local storage, the scope exceptions.
- **Does not belong:** the rating of a requirement against a control standard (goes to the owning domain in the requirement section); the detailed per-domain isolation consequence (goes to each domain's drawbridge impact); future-state migration design (goes to the design / segmentation deliverable). This section is the migration-relevant *current state*, not the migration plan.

## Validation / review checks

Run `csa-writing-style/scripts/prose_lint.py` on the section. Then confirm:

1. The three populations (declared population, discovery population, capture campaign) are never conflated, and every scope-limited statement names its population.
2. No stale or unexplained count (e.g. an old "N sampled hosts" figure) remains in the prose.
3. The subject of each sentence is the application, the environment, a host, a component, or a service -- not "the discovery data" / "the workbook" / "the table".
4. Application modules and platform tooling are kept separate in the installed-applications table.
5. The redundancy model is stated as a system property, with the migration constraint (name resolution / fixed addresses) made explicit.
6. The patch-currency finding is scoped to the capture set, and the uncaptured hosts are declared as not established.
7. Group-Policy observations are scoped to the host classes and the applied-GPO sample.
8. File-transfer and local-storage findings are scoped to the captures that included share / drive output.
9. Every material statement traces to an E-id in the change record / Word comment / evidence matrix.
10. The section agrees with the asset-inventory and the per-domain sections on host names, roles, and pairings.

## Common failure patterns

- Using one stale sample count ("11 sampled hosts") throughout when the capture set is larger and multi-campaign.
- Presenting a May-sample finding as a fact about the whole declared population.
- Writing the section as a tour of the installed-software list and the gpresult output, with the application and systems only implied.
- Conflating the declared asset list with the discovery population, or a single capture campaign with the whole capture set.
- Asserting "no failover clustering exists" as a bare fact instead of scoping it to the reviewed outputs and stating the application handles redundancy.
- Folding a host that appears in one source but not another into the main population without flagging the scope exception.

## Completion criteria

The section describes the migration-relevant current state of the application and the systems it runs on -- declared versus captured, what runs on it, how it fails over, how it is patched and governed, and how its files move -- with every statement scoped to the population its evidence covers, the scope exceptions declared, and the reader able to plan a migration from the section alone. It passes `prose_lint.py` with no evidence-as-subject, evidence-ID, or connector warnings, and no stale or unexplained count remains.
