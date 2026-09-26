---
name: security-posture-analysis
description: Describe evidenced current security controls, exposures, exceptions, and uncertainty for an Operational Technology application without turning the Current State Assessment into a future-state security design.
---

# Security Posture Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Describe the security controls that are in place today, where they are established, what they depend on, and what the evidence shows is exposed. Use neutral, precise language. Do not assign compliance, maturity, severity or risk ratings unless the governing method and inputs are supplied.

## What this analysis must answer

1. Which security controls are in place on the system's hosts and boundaries today, and on which hosts is each established?
2. Which of those controls depend on enterprise IT services (management consoles, log collectors, update servers, certificate authorities)?
3. What exposures does the evidence show (listening services, permissive rules, legacy protocols, spread of local administrator rights, expired certificates)?
4. What stops working, or stops being visible, if OT is isolated from IT?

## Where the evidence is

Look up in this order: the evidence matrix (`csa ev lookup`), then the discovery index, then raw files, then policies and documents.

| Index table | What it answers |
| --- | --- |
| `installed_software` | Endpoint protection, SIEM forwarders, vulnerability scanner agents, management clients |
| `services_inventory` | Whether each security agent's service runs, and its start mode |
| `listening_ports` | Services exposed on each host, and on which addresses |
| `firewall_rules` with `firewall_port_filters`, `firewall_address_filters` | Host firewall rules, direction, action, ports and addresses |
| `dependency_summary` | Firewall profile defaults (`DefaultInboundAction`, `DefaultOutboundAction`) |
| `windows_update_config` | Update source (`WUServer`) and deferral settings |
| `installed_hotfixes` | Installed updates with dates, for patch currency |
| `gpresult_computer`, `legacy_security_settings` | Applied security policy |
| `local_admins_membership` | Spread of local administrator rights |
| `certificates_localmachine_my` | Certificates and their expiry |

Example queries: `csa index rows services_inventory --where "Name~CSFalcon" --cols Name,State`, `csa index rows listening_ports --distinct LocalAddress`.

## Correlate before concluding

- Count an agent as "in place" only when its service runs and, where it can be seen, its configuration points somewhere. Installed plus running plus configured is the claim; anything less is stated as what it is.
- Join each listening port with its owning process before naming the exposed service.
- Read the firewall rules, not only the profile state, before describing host firewall posture.
- Scope every claim to the hosts, captures or network exports that support it. Host captures and network monitoring exports are different evidence populations.

## Traps

- No evidence found does not mean the control is absent. Record the scope that was searched.
- An agent that is installed is not a control that works; check that the service runs and, where visible, that it reports.
- A firewall profile that is enabled can still have permissive rules; read the rules.
- Patch currency comes from installed-update dates relative to the capture date, not from the presence of an update tool.
- Enterprise security tools (EDR, SIEM forwarders, vulnerability scanners) are dependencies under isolation: they keep running locally but lose management, updates and reporting.
- Do not rate compliance or maturity, and do not turn an observation into a recommendation.

## Output

A table with exactly these columns:

| Control area | Observed | Hosts in scope | Depends on IT service | Isolation effect | Evidence |
| --- | --- | --- | --- | --- | --- |

Then:

- current-state observations, each scoped to the hosts or captures that support it;
- uncertainties, with the scope searched;
- items that need specialist validation (for example a penetration test or a rule review).

Keep recommendations in a separate output, and only when they are asked for.

## Hand-offs

- Accounts, privileged access and remote access to `identity-access-analysis`.
- Network flows, zones and boundary firewalls to `network-connectivity-analysis`.
- Patch and vulnerability management processes to `operations-support-analysis`.
- Backup protection and recovery assurance to `resilience-analysis`.

## Example

Before:

> The capture shows CrowdStrike and Splunk, so security monitoring is in place and effective across the environment.

After:

> The endpoint protection agent and the log forwarder are installed and running on all six fully captured hosts; neither was established on the lightweight captures. Both report to consoles in enterprise IT. If OT is isolated, the agents keep enforcing their last policy locally, but alerts and logs stop reaching the security team.
