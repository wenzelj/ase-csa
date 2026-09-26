---
name: operations-support-analysis
description: Describe the current operating and support model for an Operational Technology application, including ownership, monitoring, maintenance, patching, incidents, changes, vendors, and documentation.
---

# Operations and Support Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Establish who performs each operational responsibility and what process or tool supports it. Separate formal process, documented process, reported practice and observed configuration: they are different kinds of evidence and often disagree.

## What this analysis must answer

1. Who owns the application, and who operates each layer (application, hosts, network, security, vendor)?
2. How is the system monitored, and where do the alerts go?
3. How are patches, antivirus or Endpoint Detection and Response (EDR) updates, certificates and licences maintained, and by what tool?
4. How are incidents and changes handled, and how does the vendor get in to support the system?
5. Which of these depend on enterprise IT services, and what stops if OT is isolated?

## Where the evidence is

Look up in this order: the evidence matrix (`csa ev lookup`), then the discovery index, then raw files, then documents (support models, runbooks, contracts, change records) and interview notes.

| Index table | What it answers |
| --- | --- |
| `installed_software` | Monitoring, management and remote-support tools |
| `services_inventory` | Whether those agents run |
| `sccm_mecm_check` | Configuration Manager client state and assignment |
| `windows_update_config` | Update source and deferral policy |
| `installed_hotfixes` | When updates were last installed |
| `scheduled_tasks` | Operational jobs (exports, clean-ups, restarts) and their authors |
| `startup_tasks` | Programs started at boot or sign-in |
| `certificates_localmachine_my` | Certificates that someone has to renew |
| `run_summary` | Who ran each discovery capture and when |

Example queries: `csa index rows sccm_mecm_check --cols Name,Status,ClientVersion`, `csa index rows scheduled_tasks --where "TaskPath!~Microsoft" --cols TaskName,Author,State`.

Ownership, support tiers, hours, escalation and contracts are rarely in host captures. Record `NOT_FOUND` with the scope searched, and turn each missing owner into a targeted question.

## Correlate before concluding

- Tie each tool to the process it supports and the team that uses it. A tool with no owning team is a gap, not a control.
- Compare documented process with observed configuration. Where they differ, report both and the difference.
- For patching, combine the mechanism (update source, management client) with the currency (installed-update dates against the capture date).
- Scope every claim to the hosts or documents that support it.

## Traps

- A monitoring agent that is present does not show that alerts are routed to anyone.
- Update settings that point to a management server show the mechanism, not that patching is timely.
- An owner named in a document is not proof of who operates the system day to day.
- Scheduled tasks are operational jobs: say what each does and what it depends on.
- Vendor remote support is both an operational dependency and an access path; record both.
- Do not state that a process is effective because a policy or product exists.

## Output

A table with exactly these columns:

| Responsibility | Owner | Performed by | Tool or process | Depends on IT service | Evidence |
| --- | --- | --- | --- | --- | --- |

Then:

- an operating-process summary (monitoring, patching, incident, change, vendor support);
- constraints, including what stops under isolation;
- unresolved ownership gaps, each as a specific question for a named role.

## Hand-offs

- Remote access controls and accounts to `identity-access-analysis`.
- Backup and restore operations to `resilience-analysis`.
- Security tooling as controls to `security-posture-analysis`.
- Hosting platform ownership to `infrastructure-analysis`.

## Example

Before:

> The software list includes monitoring and SCCM agents, which confirms the system is monitored and patched by IT.

After:

> Both application servers run the enterprise monitoring agent and the Configuration Manager client, and take updates from the enterprise update server; the latest update was installed 12 days before capture. No evidence shows who receives the monitoring alerts or who approves application changes. If OT is isolated, monitoring and patching both stop, because each depends on servers in IT.
