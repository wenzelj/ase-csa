---
name: resilience-analysis
description: Review current availability, redundancy, failover, backup, restore, disaster recovery, capacity, and single points of failure for an Operational Technology application.
---

# Availability and Resilience Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Assess each important service path, not merely whether a backup product or cluster is mentioned. Separate what is designed or claimed from what the evidence shows is in place and what has been demonstrated.

## What this analysis must answer

1. For each important service path, what redundancy exists, and what provides it: the application, the operating system, the virtual platform, or nothing?
2. What is backed up, how often, to where, and when was a restore last demonstrated?
3. What are the recovery targets (Recovery Time Objective (RTO), Recovery Point Objective (RPO)), and what has actually been demonstrated?
4. What are the single points of failure, including shared IT services such as DNS, directory, time and storage?
5. What keeps working, degrades or fails if the OT environment is isolated from IT?

## Where the evidence is

Look up in this order: the evidence matrix (`csa ev lookup`), then the discovery index, then raw files, then design and operational documents.

| Index table | What it answers |
| --- | --- |
| `host_summary` | Hosts, operating system, last boot time (uptime hints at patch and restart practice) |
| `services_inventory` | Cluster, replication, backup and application services, and whether they run |
| `installed_software` | Backup agents and clustering or replication products |
| `scheduled_tasks` | Backup, export and housekeeping jobs |
| `established_connections_raw`, `listening_ports` | Partner connections between redundant pairs, and backup traffic |
| `system_events`, `application_events` | Backup, failover and service-failure events, where captured |
| `local_shares` | File shares that backups or exports land on |

Example queries: `csa index rows services_inventory --where "Name~ClusSvc" --cols Name,State`, `csa index search "backup job"`.

Backup schedules, retention, restore tests and recovery targets are usually in documents or interviews, not host captures. Record `NOT_FOUND` with the scope searched when they are absent.

## Correlate before concluding

- Pair each redundancy claim with the partner host and the mechanism that provides it. A pair with no evidenced mechanism is two hosts, not redundancy.
- Join a backup agent with its schedule or job evidence before saying something is backed up.
- Follow each service path through every dependency. The path is only as resilient as its weakest shared service.
- Scope every claim to the hosts it is established for.

## Traps

- Replication is not backup: it copies corruption and deletion as faithfully as good data.
- A cluster or failover service that is present is not failover that has been tested.
- A backup agent that is installed is not a backup that succeeds; look for job results.
- Default operating-system or hypervisor components (VSS, snapshot providers) are not a backup regime.
- A target (RTO or RPO) is not a demonstrated capability.
- Application-level redundancy (duty and standby pairs) is not operating-system clustering. Say which one provides the redundancy.
- DNS, directory, time and shared storage are single points of failure when they sit outside OT, even when every application host is duplicated.

## Output

A table with exactly these columns:

| Service path | Redundancy | Provided by | Failure domain | Backup (scope, schedule, location) | Last restore test | Single point of failure | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |

Then:

- confirmed protections, each with its evidence and scope;
- limitations and failure scenarios, including under isolation: what fails at once, what degrades, what keeps working;
- the gap between targets and demonstrated capability;
- gaps and targeted evidence requests (for example "the last restore test record for the application database").

Keep improvement recommendations separate unless they are asked for.

## Hand-offs

- Hosting and platform detail to `infrastructure-analysis`.
- Upstream and downstream dependencies to `dependency-analysis`.
- Who runs backups and restores, and how, to `operations-support-analysis`.
- Backup protection as a security control to `security-posture-analysis`.

## Example

Before:

> The software list shows a backup agent and the services list shows a cluster service, so the system is fully resilient and backed up.

After:

> The application runs as a duty and standby pair, APPSRV01 and APPSRV02, with failover handled by the application; no operating-system clustering is configured. A backup agent is installed on both servers, but no job results or restore tests were in the evidence, so recovery capability is not demonstrated. Both servers resolve names through the enterprise DNS servers, so the pair shares a single point of failure outside OT.
