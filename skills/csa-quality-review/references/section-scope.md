# CSA section scope map

The single reference for **what belongs where** in a Current State Assessment (CSA). It is read by:

- `csa-quality-review` check 12 (Section fit), to judge whether text sits in the right section and subsection;
- `csa-section-writer` and `csa-change-authoring`, so new text is written in the right place in the first place.

`scripts/section_fit_scan.py` parses this file: the `### ` domain headings, and the `Legacy headings:` and `Signal terms:` lines under each. Keep those three shapes when you edit it.

Each domain block's **Must explain** line lists the questions the section, and every subsection under it, exists to answer. Writers and authoring agents build their section brief from it (see `csa-change-authoring`, Section brief).

Contents: 1. How to decide; 2. Subsection jobs; 3. Document-level sections; 4. Requirement domains; 5. Shared topics (tie-breaks); 6. Legacy documents; 7. Verdicts and severity.

## 1. How to decide

Judge one unit at a time: a paragraph, a bullet, or a table row. For each unit, answer two questions.

1. **Topic: which requirement is its main claim evidence for?** Use the domain blocks in part 4 and the tie-breaks in part 5. The unit's home is the domain that owns that requirement.
2. **Job: what is the unit doing?** Classify it as one of the kinds below. The subsection it sits in must accept that kind (part 2).

| Kind | What it does | Typical wording |
| --- | --- | --- |
| `REQUIREMENT` | States the design intent or reference requirement | "is designed to", "the design defines", "shall", "expected" |
| `FACT` | States what was observed in this system | "is configured to", "points to", "runs", counts, names, versions |
| `FINDING` | Interprets facts against the requirement: condition, criteria, consequence | "does not meet", "depends on", "single point of failure", "gap" |
| `CONSEQUENCE` | Says what happens when OT is isolated from IT | "on isolation", "would fail", "continues to", "degrades after" |
| `POSITION` | Gives the rating or overall position | "Met", "Partially Met", "Not Met", "overall" |
| `RECOMMENDATION` | Proposes an action or future state | "recommend", "should implement", "consider", "target state" |
| `EXPLANATION` | Explains general technology, not this system | "NTP is a protocol that", "in general", "typically" |
| `METHOD` | Says how evidence was collected, or its coverage | "the discovery script", "captured on", "collected from" |
| `RAW` | Pastes evidence: log lines, command output, file paths | timestamps, process IDs, `C:\...` paths |

A unit may **mention** another domain's topic when that topic is the cause or context of this domain's condition. Keep the mention to one clause or one sentence, with no detail of its own. The test: delete the sentence. If this section's rating or isolation consequence loses its basis, the sentence belongs here. If it doesn't, and the sentence describes another domain, it belongs in that domain.

Example in 3.5 DNS: "Both resolvers are the IT domain controllers" fits, because it is why DNS fails on isolation. A paragraph on the domain controllers' OS versions and FSMO roles does not fit: that belongs in 3.2 and 3.15.

## 2. Subsection jobs

### Template domain block (CSA template v1.x, 3.1 to 3.17)

| Subsection | Accepts | Rejects |
| --- | --- | --- |
| Requirement table, Current State cell | One or two sentences: condensed `FACT` against the requirement | Lists, `RECOMMENDATION`, `EXPLANATION`, `CONSEQUENCE` |
| Requirement table, Rating cell | `POSITION` only: Met, Partially Met, Not Met, Not Applicable | Anything else |
| Discovery Information | `FACT` only (short table or up to five bullets) | `FINDING`, `CONSEQUENCE`, `RECOMMENDATION`, `REQUIREMENT`, `RAW` |
| Drawbridge Impact | `CONSEQUENCE`, with just enough `FINDING` to explain it | Restated `FACT`s, `RECOMMENDATION` |

The template has no Recommendations subsection, on purpose: a CSA describes the current state and its gaps, and the roadmap is a separate deliverable. A `RECOMMENDATION` anywhere in a template CSA is `OUT_OF_SCOPE`; its target is the roadmap, not another section.

### Legacy domain structure (Expected / Observed / Findings ...)

| Subsection (heading variants) | Accepts | Rejects |
| --- | --- | --- |
| Design and functionality expected | `REQUIREMENT` | `FACT`, `FINDING`, host-level observations, "Interpretation" |
| Observed Configuration and Functionality | `FACT`; `METHOD` only as a short source line | `FINDING`, `REQUIREMENT`, `RECOMMENDATION`, `RAW` blocks |
| Findings | `FINDING`, one paragraph each | New `FACT`s not stated in Observed, `RECOMMENDATION` |
| Drawbridge Impact, Operational Behaviour | `CONSEQUENCE`, stated once across both | Restated `FACT`s, `RECOMMENDATION` |
| Assessment | `POSITION`, one sentence plus the rating | New `FACT`s or `FINDING`s |
| Recommendations (Short-Term, Medium-Term, Target State) | `RECOMMENDATION`, each tied to a finding | `FACT`, `FINDING` |
| Finding comments, recommendations ... (container heading) | Nothing directly: content goes in its child subsections | Direct body text mixing kinds (verdict `SPLIT`) |
| Drawing | Figure, caption, source line | Prose |
| Evidence Appendix | `METHOD`, `RAW`, evidence file lists | `FINDING`, `RECOMMENDATION` |

## 3. Document-level sections

These sections are not requirement domains. Topic signals do not apply to them; check only the kind of content.

| Section (template / legacy names) | Accepts | Rejects, and where it goes |
| --- | --- | --- |
| Document Control (all subsections) | Controlled fields, revision history, approvals, distribution, document map | Any assessment content |
| Executive Summary / Executive Overview | The overall position across domains, key risks, isolation outcome in brief | Host-level `FACT`s (go to the domain); any fact not stated in a body section (orphan fact: add it to the domain first) |
| Discovery Summary and its children (legacy) | One-line summaries that point to the domain sections | New facts, full findings (go to the domain) |
| System Assessment Overview, System Function and Purpose, Business Functional Overview, Who Relies on, What Happens if it Fails, Core Components (legacy) | Purpose, users, criticality, components, business impact of failure | Requirement-level `FINDING`s or ratings (go to the domain) |
| Objectives, Scope, Assumptions, In/Out of scope | What is and is not assessed, and on what assumptions | Findings |
| Methodology | `METHOD` | Findings, facts about the system |
| Discovery activity | `METHOD`: sources, captures, coverage, limitations of the evidence | Findings about the system (go to the domain) |
| Architectural Review (legacy) | Design intent and the as-built overview: components, zones, asset list, drawings | Per-domain findings (go to the domain); migration planning (goes to Migration Discovery or out of scope) |
| 4 Governance Note and Next Steps (template v1.2) | The three standard OT 3.5 next steps, then system-specific actions with owner and target date | Findings, ratings or evidence (they belong in the domains) |
| 5 Migration Discovery, 5.1 to 5.6 (template v1.2; 4, 4.1 to 4.5 in v1.1) | Section skill: `migration-discovery-analysis`. `FACT` inventories needed for migration planning, on the subsection's own topic: 5.1 discovery coverage (`METHOD`, host coverage), 5.2 installed applications, 5.3 failover and replication, 5.4 patch and update tooling, 5.5 Group Policy, 5.6 file transfer and local storage | `POSITION`, `FINDING` against a requirement (goes to the owning domain in section 3) |
| Glossary and Acronyms | Term and definition | Anything else |
| Discovery Coverage (5.1 in v1.2, Appendix B in v1.1) / Evidence Appendix / Appendices | `METHOD`, `RAW`, host coverage | `FINDING` |

## 4. Requirement domains

Requirement IDs and wording come from the OT35 checklist in the CSA template. **Owns** lists what the domain carries. **Not here** names the owner of each nearby topic. **Legacy headings** are the Heading 1 titles in pre-template CSAs that host this domain (part 6). **Signal terms** are the scanner's keywords: comma-separated, case-insensitive, whole words.

### 3.1 General / Asset Inventory
- **Requirements:** SEP-GEN-01 classified inventory of OT assets and enabling systems (type, role, location, IT/OT dependencies); SEP-GEN-03 dependencies of vital OT systems, including connections outside the OT environment, documented and understood.
- **Must explain:** What vital OT assets and enabling systems exist, what role each plays, where each sits (site, IT or OT), and which systems outside the OT environment each depends on or exchanges data with.
- **Owns:** the asset and host inventory; each asset's role, environment and location; the consolidated list of dependencies at summary level; whether that list is documented.
- **Not here:** the detail of each dependency goes to its own domain (DNS to 3.5, time to 3.4, and so on); 3.1 keeps a one-line entry and points to that domain.
- **Legacy headings:** Architectural Review
- **Signal terms:** asset inventory, asset register, asset list, cmdb, classified inventory, asset type, serial number, hardware model, criticality

### 3.2 Identity & Authentication
- **Requirements:** SEP-ID-01 OT-resident authentication for human users, independent of IT AD (no shared forest or trust); SEP-ID-02 service accounts, processes and devices authenticated independently of IT-domain service accounts; SEP-ID-03 remote and administrative access via OT-resident jump hosts, monitored and authenticated.
- **Must explain:** How people, services and devices prove who they are; which directory or account store does it; whether that store is OT-resident; and what stops working if the IT directory is unreachable.
- **Owns:** domain membership, forests and trusts; how users and service accounts authenticate; local authentication fallback; the authentication used on remote and admin access.
- **Not here:** the jump host as a host, and the route to it, go to 3.8; local admin group membership goes to 3.8; hypervisor management accounts go to 3.15; backup administration accounts go to 3.11; vendor accounts go to 3.16; certificates go to 3.3; domain controllers as DNS or time sources go to 3.5 or 3.4.
- **Legacy headings:** Identity & Authentication, Identity and Authentication
- **Signal terms:** active directory, domain join, domain joined, domain-joined, domain controller, forest, trust relationship, kerberos, ntlm, ldap, ldaps, logon, authentication, authenticate, service account, gmsa, user account, mfa, password, credential, sso

### 3.3 PKI / Certificates
- **Requirements:** SEP-PKI-01 certificates from an OT-resident PKI or a tested fallback; SEP-PKI-02 issuance, renewal and revocation checking without IT-hosted CA, CRL or OCSP.
- **Must explain:** Which certificates the system relies on, who issues and renews them, where revocation is checked, and what breaks as certificates expire during isolation.
- **Owns:** which CA issues each certificate; certificate templates and expiry; CRL and OCSP locations; what happens to validation when the CA is unreachable.
- **Not here:** LDAPS or TLS as an authentication mechanism goes to 3.2; the certificate part stays here.
- **Legacy headings:** Identity & Authentication, Identity and Authentication
- **Signal terms:** certificate, certificates, pki, certificate authority, root ca, issuing ca, intermediate ca, crl, ocsp, adcs, certificate template, revocation, expiry

### 3.4 Time Synchronisation
- **Requirements:** SEP-TIME-01 time from an OT-resident authoritative source, independent of the IT domain hierarchy.
- **Must explain:** Where each host takes its time from, what hierarchy sits above that source, and how fast drift becomes a problem if the source is lost.
- **Owns:** each host's time source and hierarchy, stratum, drift, and behaviour without the source.
- **Not here:** log integrity as a monitoring control goes to 3.9 (keep only the time dependency here).
- **Legacy headings:** Time Synchronization, Time Synchronisation
- **Signal terms:** ntp, sntp, w32time, time source, time sync, time synchronisation, time synchronization, stratum, clock, drift, pdc emulator, gps clock, ptp

### 3.5 DNS
- **Requirements:** SEP-DNS-01 OT-resident DNS resolvers, independent of IT DNS, or a tested fallback.
- **Must explain:** Which resolvers each host uses, which zones it must resolve to work, where those zones are hosted, and what fails when they cannot be reached.
- **Owns:** configured resolvers, zones and suffixes; hosts files; name resolution behaviour when IT DNS is unreachable.
- **Not here:** the domain controllers themselves go to 3.2; host inventory goes to 3.1.
- **Section skill:** `dns-name-resolution-analysis`
- **Legacy headings:** DNS
- **Signal terms:** dns, resolver, resolvers, name resolution, nameserver, dns suffix, hosts file, conditional forwarder, forward lookup, reverse lookup, dns zone

### 3.6 Network / Segmentation
- **Requirements:** SEP-NET-01 assets in defined zones (Z0 to Z6) with an SL-T, inter-zone traffic only through defined conduits; SEP-NET-02 boundary protection at every IT/OT and inter-zone boundary, no undocumented cross-zone flows; SEP-NET-03 general-purpose IT services restricted from vital OT zones.
- **Must explain:** Which zones and networks the system's components sit in, which flows cross zones and through which conduits, and where the flows differ from the design.
- **Owns:** zone placement, subnets and VLANs, the conduit list, observed flows across zones, general IT services present in OT zones.
- **Not here:** the firewall or boundary device itself, its rule quality and who administers it go to 3.13; internet and SMTP paths go to 3.17; file transfer patterns go to 3.7.
- **Legacy headings:** Network
- **Signal terms:** zone, zones, conduit, conduits, vlan, subnet, subnets, segmentation, purdue, security level, sl-t, inter-zone, cross-zone, routing, route, dmz, network flow, flows

### 3.7 Storage & Data Transfer
- **Requirements:** SEP-STOR-01 OT-resident storage for operational data, or a fallback; SEP-STOR-02 IT-to-OT file transfer only through a defined, controlled pattern; SEP-STOR-03 OT pushes data out rather than IT pulling data in.
- **Must explain:** For each data flow in or out of the system: what data moves, which direction, which side starts the transfer, how it moves (file, share, message stream), where the data is held on each side and for how long, whether anything controls, inspects or scans it on the way, and whether the held data could be used to recover or rebuild after an outage.
- **Owns:** where operational data lives; file shares used; file transfer mechanisms and direction.
- **Not here:** backup storage goes to 3.11; storage arrays and SAN hardware go to 3.15.
- **Legacy headings:** Infrastructure Dependencies
- **Signal terms:** file share, file shares, smb, unc path, sftp, ftp, ftps, file transfer, data transfer, data diode, local storage, nas, mapped drive, data export, push, pull

### 3.8 Management & Administrative Access
- **Requirements:** SEP-MGT-01 administrative and SaaS-bound access through OT-resident jump or management hosts and gateways, not the general IT proxy; SEP-MGT-02 local administrator and remote-access group membership defined in the OT domain.
- **Must explain:** How administrators reach the system, through which jump or management hosts, who holds local administrator and remote-access rights, and whether any of that depends on IT.
- **Owns:** jump and management hosts, the admin access path, RDP and RDS gateways, local Administrators and Remote Desktop Users membership.
- **Not here:** how the admin authenticates goes to 3.2; vendor access goes to 3.16; firewall management goes to 3.13; hypervisor management goes to 3.15.
- **Legacy headings:** Identity & Authentication, Identity and Authentication
- **Signal terms:** jump host, jump server, jumphost, bastion, management host, rds, rds gateway, remote desktop, rdp, privileged access workstation, paw, local administrators, administrators group, remote desktop users, admin access

### 3.9 Monitoring & Logging
- **Requirements:** SEP-MON-01 logs to an OT-resident monitoring capability that can federate to IT SIEM; SEP-MON-02 monitoring coverage (EDR/AV, patch compliance, central logging) verified across all vital hosts; SEP-MON-03 log sources, retention and tamper protection defined and applied.
- **Must explain:** Which logs and security events the system produces, where they go and are kept, which monitoring and endpoint agents run, and what visibility is lost on isolation.
- **Owns:** log forwarding and where logs go, monitoring agents and tools, alerting, retention, and whether coverage is verified.
- **Not here:** whether AV/EDR and application whitelisting are deployed goes to 3.14 (3.9 keeps only whether their telemetry reaches monitoring); patch mechanism and cadence go to 3.10.
- **Legacy headings:** Operations Monitoring and Procedures, Operations Monitoring
- **Signal terms:** siem, syslog, event log, event logs, log forwarding, windows event forwarding, wef, splunk, sentinel, scom, solarwinds, prtg, monitoring agent, monitoring, alerting, alert, log retention, logging

### 3.10 Patch & Lifecycle Management
- **Requirements:** SEP-PATCH-01 patching and configuration management through an OT-resident capability, independent of IT SCCM/MECM; SEP-PATCH-02 documented, OT-appropriate cadence with an escalation path for urgent patches.
- **Must explain:** How software and security updates reach the hosts, from which source and with which tooling, how current the hosts are, and what happens to patching during isolation.
- **Owns:** patch source and tooling, patch levels, cadence, OS and application end of support.
- **Not here:** the tooling inventory for migration goes to 4.3; vulnerability scanning goes to 3.14.
- **Legacy headings:** Patch & Lifecycle Management, Patch and Lifecycle Management
- **Signal terms:** patch, patches, patching, wsus, sccm, mecm, windows update, hotfix, cumulative update, end of life, end of support, eol, lifecycle, firmware update

### 3.11 Backup & Recovery
- **Requirements:** SEP-BAK-01 working backup independent of IT backup infrastructure, not administered by privileged corporate IT accounts; SEP-BAK-02 complete, rapid rebuild from offline, known-good, tested backups.
- **Must explain:** What is backed up, by which tool, to where, under whose accounts, how often, whether a restore has been proven, and whether a rebuild could be done from OT-held copies alone.
- **Owns:** backup tools, jobs and their state; backup storage; who administers backup; restore and rebuild testing.
- **Not here:** failover and replication as availability features go to 4.2 (template) or 3.15.
- **Legacy headings:** Backup & Recovery, Backup and Recovery
- **Signal terms:** backup, backups, restore, restored, veeam, commvault, snapshot, rebuild, recovery point, rpo, rto, known-good, golden image, offline copy

### 3.12 Isolation & Resilience Validation ("Drawbridge")
- **Requirements:** SEP-ISO-01 a graduated, tested plan to isolate vital OT for at least three months; SEP-ISO-02 thresholds for isolation risk and the manual processes that replace automated IT/OT interactions.
- **Must explain:** Which isolation scenario is assumed, which functions keep running and for how long, which manual processes replace automated IT/OT interactions, and whether any of this has been tested.
- **Owns:** whether an isolation plan exists and has been tested; thresholds; manual workarounds.
- **Not here:** each domain's own isolation consequence stays in that domain's Drawbridge Impact. 3.12 does not repeat them; it may summarise them in one table.
- **Legacy headings:** Executive Overview & Discovery Summary, Executive Overview
- **Signal terms:** isolation plan, isolation test, isolation exercise, graduated plan, manual process, manual processes, manual workaround, three months

### 3.13 Perimeter / Firewall & Network Boundary Validation
- **Requirements:** SEP-PERIM-01 boundary devices at every zone boundary enforcing only approved conduits, no any-any rules; SEP-PERIM-02 internet-facing and external exposure identified and validated; SEP-PERIM-03 boundary devices administered from the OT side, never from a privileged IT account.
- **Must explain:** Which boundary devices sit between the system and other zones, what their rules allow, what external exposure exists, and who administers the boundary from where.
- **Owns:** firewalls and boundary devices, rule quality, external exposure and scanning, firewall administration.
- **Not here:** which zones and flows exist goes to 3.6 (the what); 3.13 is the device that enforces it and who manages it (the how and who).
- **Legacy headings:** Network
- **Signal terms:** firewall, firewalls, firewall rule, rule base, any-any, acl, access control list, boundary device, external scan, internet-facing, exposure, palo alto, fortigate, check point

### 3.14 Vulnerability Management
- **Requirements:** SEP-VULN-01 recurring OT vulnerability assessment independent of IT tooling, feeding an OT vulnerability register; SEP-VULN-02 AV/EDR and application whitelisting deployed and centrally verified on all vital hosts.
- **Must explain:** How vulnerabilities are found and tracked, which endpoint protection and application control run on the hosts, and who verifies coverage.
- **Owns:** vulnerability scanning and the register; AV/EDR and whitelisting deployment state on each host.
- **Not here:** endpoint telemetry reaching monitoring goes to 3.9; patching goes to 3.10.
- **Legacy headings:** Security Services, Security Controls
- **Signal terms:** vulnerability, vulnerabilities, cve, vulnerability scan, tenable, nessus, qualys, antivirus, anti-virus, edr, defender, crowdstrike, sentinelone, trend micro, application whitelisting, allowlisting, applocker, vulnerability register

### 3.15 Infrastructure Dependencies (Virtualisation / Hardware)
- **Requirements:** SEP-INFRA-01 virtualisation hosting vital OT not managed only by privileged corporate IT accounts.
- **Must explain:** Which platforms (hypervisors, hardware, storage) the hosts run on, who manages them with which accounts, and what depends on IT to keep them running.
- **Owns:** hypervisors, vCenter, physical servers and storage hardware, who manages them, and the OS and platform they provide.
- **Not here:** operational data storage goes to 3.7; backup goes to 3.11.
- **Legacy headings:** Infrastructure Dependencies
- **Signal terms:** esxi, vcenter, vmware, hypervisor, hyper-v, virtual machine, virtualisation, virtualization, host cluster, san, storage array, physical server, blade, ilo, idrac, operating system

### 3.16 Supply Chain & Third-Party / Vendor Access
- **Requirements:** SEP-SUPPLY-01 vendor and third-party remote access through the same controlled, monitored architecture as internal admin access, with no direct OT-to-internet connections.
- **Must explain:** Which vendors and third parties access or support the system, how their access works, how it is controlled and monitored, and whether any path bypasses the internal admin route.
- **Owns:** vendor and third-party access paths, vendor accounts, remote support tools, vendor-managed components.
- **Not here:** the shared jump host itself goes to 3.8 (3.16 names it and points there).
- **Legacy headings:** Identity & Authentication, Identity and Authentication
- **Signal terms:** vendor, vendors, third-party, third party, supplier, contractor, vendor access, remote support, teamviewer, anydesk, vendor account

### 3.17 Internet Access & Communications (Proxy / SMTP)
- **Requirements:** SEP-INET-01 outbound HTTP/S only through the OT35 proxy; SEP-INET-02 outbound SMTP through the OT35 proxy, not direct or an IT relay.
- **Must explain:** Which hosts reach the internet or send email, by which route (proxy, relay, direct), and what stops if those routes are closed.
- **Owns:** proxy configuration, direct internet connections, cloud and SaaS endpoints reached, SMTP relays.
- **Not here:** admin access to SaaS goes to 3.8 (SEP-MGT-01); person-to-person communications in OT zones go to 3.6 (SEP-NET-03).
- **Legacy headings:** Network
- **Signal terms:** proxy, web proxy, http proxy, internet access, outbound internet, direct internet, smtp, mail relay, email relay, cloud service, saas

## 5. Shared topics (tie-breaks)

When a unit fits two domains, the owner below wins. The other domain may keep a one-sentence pointer.

| Topic | Owner | Pointer only |
| --- | --- | --- |
| Service accounts: existence, domain, how they authenticate | 3.2 | 3.8 if they hold local admin |
| Local Administrators and Remote Desktop Users membership | 3.8 | 3.2 |
| Jump host: the host and the route to it | 3.8 | 3.2 (how it authenticates), 3.16 (vendors use it) |
| Vendor remote access | 3.16 | 3.8 |
| Domain controllers as DNS resolvers | 3.5 | 3.2 |
| Domain controllers as time source | 3.4 | 3.2 |
| Certificates used by LDAPS/TLS | 3.3 | 3.2 |
| AV/EDR and whitelisting deployment | 3.14 | 3.9 (telemetry coverage) |
| Patch compliance reporting | 3.10 | 3.9 (only as a monitoring coverage item) |
| SCCM/MECM | 3.10 (patch and config delivery) | 3.9 (only if it is the monitoring source) |
| Zones, conduits, observed flows | 3.6 | 3.13 |
| Firewall rules, exposure, firewall administration | 3.13 | 3.6 |
| Internet proxy, SMTP | 3.17 | 3.6 |
| File shares for operational data | 3.7 | 3.15 |
| Backup storage and backup admin accounts | 3.11 | 3.2, 3.7 |
| Hypervisor and vCenter admin accounts | 3.15 | 3.2 |
| Per-domain isolation consequence | that domain's Drawbridge Impact | 3.12 (summary table only) |
| Host list | 3.1 (template) or Architectural Review / Appendix B (legacy) | every domain may name hosts in its own table |

## 6. Legacy documents

Pre-template CSAs (for example UTC DTC v0.4 and IAMPS) have fewer domain sections. Each legacy Heading 1 hosts the domains whose `Legacy headings:` line names it, and those domains' content is correct there. Where no legacy section hosts a domain, the `Legacy headings:` line gives the fallback host. Do not propose adding a new Heading 1 through change records: raise it as a `Structural suggestion`.

| Legacy Heading 1 | Hosts |
| --- | --- |
| Architectural Review | 3.1 |
| DNS | 3.5 |
| Identity & Authentication | 3.2, 3.3, 3.8, 3.16 |
| Network | 3.6, 3.13, 3.17 |
| Time Synchronization | 3.4 |
| Security Services / Security Controls | 3.14 |
| Operations Monitoring and Procedures | 3.9 |
| Patch & Lifecycle Management | 3.10 |
| Backup & Recovery | 3.11 |
| Infrastructure Dependencies | 3.7, 3.15 |
| Executive Overview (Drawbridge Impacts) | 3.12 |

## 7. Verdicts and severity

| Verdict | Meaning | Severity |
| --- | --- | --- |
| `FITS` | Right topic, right job | none (not reported) |
| `WRONG_SECTION` | Topic belongs to another domain or document-level section | `MAJOR` if it is the only statement of that fact, so a reader of the owning section would miss it; `MINOR` if it is a shared topic resolved by part 5, or the owner already states it (then prefer `DUPLICATE`) |
| `WRONG_SUBSECTION` | Right domain, wrong job | `MAJOR` for `FINDING`, `POSITION` or `REQUIREMENT` inside Discovery Information / Observed, `FACT` or `FINDING` inside Expected, or a rating outside the Rating cell / Assessment; `MINOR` otherwise |
| `SPLIT` | One unit does two jobs, or belongs to two sections | the severity of the misplaced part |
| `DUPLICATE` | Stated in full here and in its owning section | as check 10 rates it; name the owner |
| `OUT_OF_SCOPE` | No home in a CSA: a recommendation in a template CSA, general technology explanation, future-state design, copied prior-assessment text | `MAJOR` for a `RECOMMENDATION` inside a `FACT` or `POSITION` subsection; `MINOR` otherwise |
| `MISPLACED_HEADING` | A heading and everything under it sits under the wrong parent | `MAJOR` |

Raise to `BLOCKER` only when the misplaced content contradicts the owning section's rating, so the document gives two answers to one requirement.

**Corrective action** always names the target: the stable ID or heading path of the owning subsection, or "roadmap (not this document)". The fix is carried out by `csa-change-authoring`, never by the reviewer:

- move = insert first, delete second, because an authoring run only writes its own section's change file. The source section's run records a `Relocation` open question naming the unit's stable ID and the target. The target section's run inserts the fact. The source section's next editorial run then deletes it, with a `Why` naming the target's stable ID. If the target already states the fact, the delete alone is enough;
- split = a replace record that keeps the part that fits, with the rest handled as a move;
- a heading move, a missing section or a merge = `Structural suggestion` under Open questions, because change records cannot move headings.
