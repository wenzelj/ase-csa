---
name: identity-access-analysis
description: Assess current authentication, authorisation, accounts, roles, privileged access, certificates, and remote access for an Operational Technology application.
---

# Identity and Access Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Describe how people and processes prove who they are to the system, what they may then do, and what happens to that when the OT environment is isolated from IT. Work from approved evidence. Do not design a future identity model.

## What this analysis must answer

1. Which identity sources does the application depend on (Active Directory (AD) domain, local accounts, application-internal users, certificates), and which of them sit outside OT?
2. How does each user group (operators, engineers, administrators, vendors) sign in, and to what?
3. Which service, scheduled-task, database and integration accounts does the system run under, and who owns them?
4. Who holds privileged access, and through which path (local Administrators group, domain groups, jump host, vendor remote access)?
5. What happens to sign-in, service start-up and remote access if OT is isolated from IT: what fails immediately, what degrades, and what keeps working?

## Where the evidence is

Look up in this order: the evidence matrix (`csa ev lookup`), then the discovery index, then raw files for what the index does not cover.

| Index table | What it answers |
| --- | --- |
| `auth_configs` | Domain membership (`Domain`, `PartOfDomain`) per host |
| `local_users` | Local accounts, whether enabled, last logon |
| `local_admins_membership` | Who is in the local Administrators group, and whether each member is local or domain (`PrincipalSource`) |
| `local_groups`, `remote_desktop_users_membership` | Other local groups, and who may use Remote Desktop |
| `services_inventory` | The account each service runs under (`StartName`) |
| `scheduled_tasks` | Tasks and their authors; the run-as account where captured |
| `dcom_application_settings` | Components that run as a named user (`RunAsUser`) |
| `gpresult_computer`, `gpresult_verbose` | Applied Group Policy, including user rights and security group membership |
| `certificates_localmachine_my` | Machine certificates, issuers and expiry |
| `logs_dns_ntp_auth` | Authentication events, where the capture kept them |

Example queries: `csa index rows local_admins_membership --distinct Name`, `csa index rows services_inventory --where "StartName!~LocalSystem" --cols Name,StartName`.

Application-level users and roles are rarely in host captures. Look in application configuration, vendor documentation and interview notes, and record `NOT_FOUND` with the scope searched when they are absent.

## Correlate before concluding

- Join each service with its log-on account before naming service accounts. A service running as `LocalSystem` or `NetworkService` is not a named service account.
- Join local group membership with domain group names before saying who is an administrator. A domain group in the local Administrators group means every member of that group is an administrator; name the group, not guessed people.
- Tie each access path end to end: who connects, from where, through what, authenticated against which source.
- A claim about "all hosts" needs the same evidence on every host in scope. Otherwise name the hosts it holds for and say where it is not established.

## Traps

- An AD-joined server does not mean the application authenticates users against AD. Look for application configuration or sign-in evidence.
- Membership of the local Administrators group is not evidence of who actually signs in.
- LAPS installed does not show that passwords rotate; that needs policy or attribute evidence.
- Claims of MFA, least privilege or password rotation need policy or configuration evidence, never product presence alone.
- Kerberos and NTLM depend on domain controllers and on accurate time. Under isolation, new domain sign-ins and services that start under domain accounts fail immediately; cached credentials keep some interactive sign-ins working for a while; clock skew breaks Kerberos later.
- Remote access (jump host, vendor VPN, Remote Desktop) is an identity path too. Record who can use it and how it is authenticated.
- Never reproduce passwords, secrets, hashes or unnecessary personal details. Name accounts only as far as the deliverable needs.

## Output

A table with exactly these columns:

| Access path | Who | Identity source | Authentication | Privilege | Isolation effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- |

Then:

- a short narrative that answers the four questions in `csa-section-writer` (what is in place, does it meet the requirement, what happens under isolation, what is not known);
- exposures stated as facts with their scope ("the domain group X is a local administrator on all six full captures");
- gaps and targeted questions (for example "Which accounts does the application itself use to connect to its database?").

Cite evidence IDs on every factual field of the analysis. Keep recommendations out unless they are asked for.

## Hand-offs

- Network paths and firewall rules to `network-connectivity-analysis`.
- Domain controller, DNS and time dependency detail to `dns-name-resolution-analysis`.
- Controls, exposures and hardening to `security-posture-analysis`.
- Account lifecycle and support processes to `operations-support-analysis`.

## Example

Before:

> The local admins file shows that several accounts have administrator rights and the servers are domain joined, so all users authenticate with Active Directory.

After:

> Operators sign in to APPSRV01 and APPSRV02 with domain accounts; the application has no local user store in the captured configuration. The domain group OT-App-Admins is a member of the local Administrators group on both servers. If OT is isolated, new sign-ins and the two services that run as svc-app fail at once, because both depend on the domain controllers in IT.
