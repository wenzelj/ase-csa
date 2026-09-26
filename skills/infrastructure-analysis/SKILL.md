---
name: infrastructure-analysis
description: Analyse current hosting and infrastructure for an Operational Technology application, including servers, virtualisation, operating systems, databases, storage, platform services, and environments.
---

# Infrastructure Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Build an evidence-backed inventory at the component level: what runs where, on what, and what it depends on. Distinguish logical components from physical placement.

## What this analysis must answer

1. Which hosts make up the system, what role does each have, and in which environment and site does it sit?
2. Is each host virtual or physical, on which platform, with which operating system and version?
3. Which databases, middleware, runtimes and file shares does the system run on?
4. Which platform services (DNS, time, certificates, endpoint protection, management) does it depend on, and where are they hosted?
5. Which host populations apply: hosts in the asset list, hosts with discovery captures, and the hosts in each discovery run?

## Where the evidence is

Look up in this order: the evidence matrix (`csa ev lookup`), then the discovery index, then raw files, then design documents and asset lists.

| Index table | What it answers |
| --- | --- |
| `host_summary` | Host name, operating system caption, version, build, architecture, last boot |
| `installed_software` | Databases, middleware, runtimes and application components |
| `services_inventory` | What actually runs, with executable paths |
| `ip_route` | Interfaces, addresses, default gateways and DNS servers |
| `resolver` | DNS servers per interface |
| `time_status` | Time source |
| `local_shares` | File shares and their paths |
| `run_summary` | Which discovery run captured each host, and when |

Run `csa index hosts` first to see which hosts the index covers, and compare that list with the asset list before writing any count.

Example queries: `csa index rows host_summary --cols Host,Caption,Version`, `csa index rows installed_software --where "DisplayName~SQL" --distinct DisplayName`.

## Correlate before concluding

- Combine host summary, installed software and running services before naming a host's role. The name alone is a hint, not evidence.
- Keep the three host populations apart in every count, and name the population each count refers to.
- Tie each platform dependency to where it is hosted (OT, supporting IT, shared) using the resolver, time and route evidence.
- Map logical components (application tiers, databases) to the hosts that run them, and say where the mapping is inferred.

## Traps

- Do not infer role, environment, co-location or redundancy from host names alone.
- Virtual or physical comes from the manufacturer and model in the host summary or platform records, not from the name.
- An operating system's support status is vendor lifecycle information: cite the vendor source, and keep it separate from observed facts.
- "All hosts" means every host in the stated population, and that population must be named.
- Logical components are not physical placement. Two tiers on one host is a fact to state, not an assumption to make.
- A capture is a point in time. State the capture date with anything that changes (versions, uptime, disk space).

## Output

A table with exactly these columns:

| Host | Role | Environment and site | Platform | Operating system | Key software | Evidence |
| --- | --- | --- | --- | --- | --- | --- |

Then:

- a hosting narrative: where the system runs, on what, and what it depends on;
- observed constraints (unsupported operating systems, shared hosts, capacity limits), each with its evidence;
- gaps, including hosts in the asset list with no capture.

## Hand-offs

- Network flows and zones to `network-connectivity-analysis`.
- Accounts and access to `identity-access-analysis`.
- Redundancy and recovery to `resilience-analysis`.
- Host coverage and migration scope to `migration-discovery-analysis`.
- Name resolution detail to `dns-name-resolution-analysis`.

## Example

Before:

> The discovery data contains eleven hosts, which are the production servers for the application running on Windows Server.

After:

> The asset list names eleven hosts; eight have discovery captures. Six of those run the application: APPSRV01 and APPSRV02 host the application tier and DBSRV01 the database, all on Windows Server 2019. The remaining two captured hosts are operator workstations. The three hosts without captures are not established.
