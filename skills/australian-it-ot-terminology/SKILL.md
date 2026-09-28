---
name: australian-it-ot-terminology
description: Shared terminology and Australian English standard for every agent that analyses, writes, edits or reviews a Current State Assessment (CSA) of an OT application and its IT/OT environment. Load it before naming a component, service, dependency, interface, network, site or piece of OT equipment in CSA text or a CSA heading, and before any terminology review. Covers choosing the most specific technical term the evidence supports, classifying things correctly as OT, supporting IT, shared, platform or external, current-state phrasing, when evidence language is warranted, Australian spelling, and the terminology lint (term_lint.py). Not a word-substitution list.
---

# Australian IT/OT Terminology

> The CSA writer is describing an application and the IT/OT system in which it currently operates. Evidence is used to establish, verify and qualify that current-state description. The CSA is not a report about the evidence itself.

> Use the terminology that an Australian IT/OT engineer would naturally use to describe the component, service, dependency, interface or operational relationship being assessed.

Write as an experienced Australian OT application specialist, infrastructure or systems engineer, network engineer, OT engineer, architect or operations person would write a system description for colleagues: plain, specific, and in Australian English. Not like a data-analysis report, an audit report, a consulting deck or a machine-generated summary.

## Where this skill sits

| Skill / file | Owns |
| --- | --- |
| `csa-section-writer/references/current-state-reasoning.md` | What the CSA is about: the subject rule, fact / evidence / gap classes, correlation, scope of a statement |
| `csa-writing-style` | How sentences read: answer first, each fact once, human voice |
| **this skill** | Which words: the technical term for each thing, IT/OT classification, headings, evidence phrasing, Australian English |
| `references/terminology.md` | The controlled terminology table (preferred term, meaning, avoid / use carefully, example) and the terms that need review |
| `references/sources.md` | The Australian sources researched, what each contributed, and the source hierarchy |
| `scripts/term_lint.py` | The terminology lint: flags, never replaces |

Section and analysis skills point here. They do not copy the terminology table.

## 1. Choose the term from what is being described

This is a decision, not a lookup. For every heading and every important technical statement, answer these six questions before choosing a word:

1. **What object is being described?** One thing, or a relationship between things?
2. **What kind of thing is it?** Application, application component, system, server, virtual machine, service, interface, network or network segment, site, platform, or OT equipment.
3. **What role does it perform?** Application server, database server, domain controller, jump host, historian, engineering workstation, operator workstation, message router, and so on.
4. **Is it part of the application, or something the application depends on?** Components are part of it. Dependencies are things it needs from elsewhere.
5. **Is it OT, supporting IT, shared infrastructure, a platform service or an external system?** (Part 2.)
6. **What is the most technically precise term the evidence supports?** (Part 3.)

Then write the sentence with that term, and keep using the same term for the same thing (`csa-writing-style`: one term per thing).

Worked example. The evidence lists a host `ROTPRDSRV122` that answers DNS queries, issues Kerberos tickets and serves time.
1. Object: one server. 2. Kind: Windows server. 3. Role: Active Directory domain controller that also provides DNS and time. 4. Dependency, not an application component. 5. Enterprise IT service (the INTERNAL domain), even though it sits at an operational site. 6. "domain controller".
Result: "The application servers authenticate against, resolve names through and take time from the INTERNAL domain controllers ROTPRDSRV122 and MOTPRDSRV122." Not "the OT DNS assets" and not "the authentication infrastructure items".

## 2. Classify IT and OT correctly

Do not call something OT because it supports an OT application. Name what it is and state the relationship.

| Class | What it is | How to say it |
| --- | --- | --- |
| OT application | Software that monitors or controls the physical process or directly supports its operation (train control, SCADA master, historian, DCS application) | "The UTC application ...", "the SCADA master ..." |
| OT system | The OT application together with its servers, workstations, OT equipment and networks, as one operating whole | "The UTC/DTC system comprises ..." |
| OT equipment | Devices that sense or act on the physical process or carry its signals: PLCs, RTUs, IEDs, protection relays, I/O modules, serial servers, field devices (ISM: "OT equipment") | "The telemetry processors poll the RTUs over serial links" |
| OT network | A network or network segment that carries OT traffic, defined by zone, VLAN or subnet | "the OT network segment 192.168.34.0/24" |
| Supporting IT infrastructure | Servers, virtualisation, storage and network equipment that host or carry the OT system but are standard IT technology | "The application runs on virtual machines in the Rockhampton VMware cluster" |
| Enterprise IT service | A corporate service the OT system uses: Active Directory, DNS, NTP, Configuration Manager, PKI, email, backup, SIEM | "The application depends on the INTERNAL Active Directory domain for Windows authentication" |
| Shared infrastructure | Infrastructure used by both IT and OT, or by several systems (shared firewalls, shared SAN, shared domain) | "The firewalls at the IT/OT boundary are shared with the corporate network" |
| Platform service | A service the operating platform provides to the application (Windows Time, IIS, SQL Server instance, message broker) | "Messages pass through the local RabbitMQ broker on each application server" |
| External system | A system outside the assessed application that exchanges data with it, OT or IT, internal or third party | "The application sends train-plan updates to the external TCS" |

Rules:

- **Say where it sits when the evidence shows it.** "The domain controllers are located at the Rockhampton and Mackay sites on OT-side address ranges, but belong to the enterprise INTERNAL domain." Location and ownership are different facts; state both when both are known.
- **Say the relationship, not membership.** "The application depends on Active Directory for authentication", not "Active Directory is part of the application".
- **Never upgrade an enterprise service to OT** because the OT system uses it (DNS, NTP, AD, SCCM/MECM, PKI, backup, virtualisation, Windows infrastructure), and never call OT equipment "IT assets".
- **Program terms are allowed** when the program defines them (for example "drawbridge", "OT 3.5", "BASE_INFRA", "OT-resident"). Use them as defined, and do not coin new ones.
- **When the classification is not established, say so.** "The ownership of the SIGMAP servers (OT engineering or IT operations) has not been confirmed."

## 3. Use the most specific term the evidence supports

Use the narrowest correct term. Go broader only when the evidence does not establish the narrower one, and then say what is known.

| Known from evidence | Write | Not |
| --- | --- | --- |
| It runs Windows Server | Windows server (or "Windows Server 2019 host") | technology asset, compute asset |
| It hosts application services | application server | compute resource, node |
| It is a VM | virtual machine | infrastructure item |
| It is a domain controller | domain controller | authentication asset, identity infrastructure |
| It answers DNS queries | DNS server / DNS service | network service asset |
| It is an SMB share | network share (file share) | storage resource |
| It is a VMware ESXi host managed by vCenter | ESXi host, vCenter-managed cluster | virtualisation platform asset |
| It polls field devices over DNP3 | SCADA front-end / telemetry processor (as the application names it) | data collection component |
| Only its OS and IP are known | "a Windows 10 host at 192.168.34.20 whose role has not been confirmed" | a generic label that implies a role |

Prefer the name the application and its owners use (Central Engine, Message Redirector, TCSI) with a one-time plain description on first use. Keep vendor and product names exactly as the vendor writes them.

## 4. Current-state phrasing

Write the application and its environment as the subject, in the present tense, with verbs that say what the system does:

operates, is hosted on, runs on, consists of, comprises, performs, communicates with, connects to, interfaces with, depends on, provides, is provided by, authenticates against, resolves names through, takes time from, is backed up to, is patched through, is monitored by, is distributed across, is supported by, is configured to.

Examples of the register (vary them; do not turn them into a template):

- "The application is hosted on four virtual machines at the Rockhampton site."
- "Authentication is provided by the INTERNAL Active Directory domain."
- "Name resolution is provided by the two domain controllers, one at each site."
- "The Central Engines communicate with the Message Redirectors over TCP/6003."
- "Backup is limited to a scheduled task that copies the previous day's logs to an IT file share."

## 5. Evidence language: only where qualification matters

Evidence wording is right when the strength or the limit of the evidence changes what the reader should conclude:

- "Observed traffic confirms communication between the Central Engines and the Message Redirectors over TCP/6003."
- "The current configuration shows both hosts using the same two resolvers."
- "The supplied architecture documentation identifies a third DNS server that was not observed in use."
- "No dedicated backup server was identified in the available evidence."
- "The backup retention period has not been confirmed."

Rules:

- The system relationship stays the subject; the evidence phrase qualifies it.
- Do not open paragraphs with "The evidence shows", "The data shows", "The table shows", "The documentation shows", "Information provided indicates". One qualified evidence phrase in a subsection is normal; several in a row means the section is describing the evidence (see `current-state-reasoning.md`, subject rule).
- Traceability (E-ids, file names) stays in the change record and the Word comment, not in the sentence.

## 6. Headings name the subject

A heading says what the section describes, in the words an engineer would use to look it up. Do not choose a heading because it sounds professional.

Test: could an engineer find this heading in a contents list when looking for the thing it describes? "Estate and Discovery Coverage" fails: nobody looks up "estate". Read the content, work out what it is about, then name that.

| Heading found | Read the content, then choose, for example |
| --- | --- |
| Estate and Discovery Coverage | A list of the application's hosts with which ones were examined: "Application Hosts and Discovery Scope". Servers and roles only: "Server Environment". Hosting platform: "Hosting Environment". Parts of the application: "Application Components" |
| Technology Footprint / Technology Landscape | "Application Environment", "Infrastructure Overview", "System Components" |
| Data Coverage / Evidence Coverage | "Discovery Scope" (if it really describes which hosts were examined), or remove if it is methodology already stated once |
| Evidence Landscape | Usually belongs in Methodology; otherwise name what the evidence is about |
| Key Observations (Derived from Table) | Name the subject: "Name Resolution", "Server Roles and Sites" |

"Discovery" is the right word when the subject really is the discovery activity, for example 5.1 "Discovery Coverage" (Appendix B "Workstation and Server Discovery Coverage" in template v1.1), which lists where the discovery script ran. It is the wrong word for describing the application.

## 7. Australian English

Use Australian spelling and conventions (Macquarie Dictionary; Australian Government Style Manual: Australian dictionaries allow both forms but the British form is preferred).

- `-ise` / `-isation`: organisation, authorisation, centralised, virtualisation, optimisation, standardisation, synchronisation, prioritise, recognise, summarise, analyse.
- `-our`: behaviour, colour, favour. `-re`: centre, metre (unit). `defence`, `catalogue`, `analogue`, `judgement`, `enrol`, `fulfil`, `modelling`, `labelled`, `cancelled`, `travelled`.
- `licence` (noun), `license` / `licensed` (verb, adjective): "a Sentinel licence", "licensed per server".
- `program` for software and for a body of work ("the OT 3.5 program"). `practice` (noun), `practise` (verb).
- "cyber security" (two words) in prose, as in ACSC publication titles; keep "Cybersecurity" where it is part of a proper name (for example AESCSF domain names).
- Dates: `4 August 2025` in prose; `04/08/2025` (day/month/year) in tables. State the time zone where it matters (AEST, AWST).
- **Do not change** product names, protocol names, commands, configuration keys, registry values, file names, quoted text or vendor terminology: "Windows Server Update Services", "Get-DnsClient", `NoAutoUpdate`, "Group Policy", "Authorization Manager", "Center for Internet Security" stay as written.

## 8. Keep established technical terms

Australian English does not mean inventing local alternatives. Keep internationally established terms: server, client, host, virtual machine, hypervisor, firewall, router, switch, VLAN, subnet, TCP/IP, DNS, DHCP, NTP, Active Directory, Group Policy, domain controller, certificate authority, application server, database server, file server, SCADA, DCS, PLC, RTU, HMI, historian, OPC, Modbus, DNP3, network segmentation, high availability, failover, redundancy. Expand an abbreviation on first use in a section.

## 9. Source hierarchy for terminology

When sources disagree, prefer in this order (details and links in `references/sources.md`):

1. Organisation or program terminology where formally defined (for example the OT 3.5 program's zone and treatment names, the application vendor's module names).
2. Australian legislation and regulatory terminology where it applies (Security of Critical Infrastructure Act 2018 terms such as "critical infrastructure asset").
3. ASD / ACSC terminology, including the ISM glossary and the OT guidance.
4. The relevant Australian industry framework, such as AESCSF for energy.
5. Applicable IEC / ISO standards (IEC 62443 zones and conduits, IACS).
6. Established vendor and product terminology.
7. Established industry technical terminology.

Do not force cyber security framework terms onto architecture or application sections where normal infrastructure and application terms are clearer. The aim is natural Australian IT/OT technical writing, not a copy of a security standard.

## 10. Terminology review (for reviewers)

Run the lint, then read the section. The lint only proposes.

```text
python3 .agents/skills/australian-it-ot-terminology/scripts/term_lint.py <draft.md | working.docx> [--heading "<Heading 1 title>"] [--json]
```

Codes: `TERM_REVIEW_REQUIRED` (consulting or data-analysis phrase: decide what technical concept is meant), `EVIDENCE_CENTRIC` (evidence phrase as a subject or opener, or used too often), `SPECIFICITY_REVIEW` (vague generic term such as "technology asset"), `IT_OT_REVIEW` (an enterprise service described as part of the OT application or as OT), `AU_SPELLING` (US spelling outside code, quotes and product names).

Check, in this order:

1. **Australian English** — spelling and conventions (part 7).
2. **IT/OT terminology** — terms match `references/terminology.md` for what is being described.
3. **Technical specificity** — no generic term where a specific one is supported (part 3).
4. **IT versus OT classification** — nothing labelled OT that is enterprise IT, and the reverse; relationships stated (part 2).
5. **Application/system focus** — the application or system is the subject.
6. **Artificial or consulting language** — headings and prose that sound generated, abstract or corporate (part 6; `csa-writing-style` tells).
7. **Evidence-centric writing** — evidence as the subject rather than the support (part 5).

Severity: `MAJOR` for an IT/OT misclassification that changes the dependency picture, evidence-as-subject across a whole subsection, or a heading that misnames the section's subject; `MINOR` for a vague term where a specific one is supported, a single consulting phrase, or a lone evidence opener; `EDITORIAL` for spelling. For each item give the location, the problem, and the corrected wording. Reviewers suggest the correction; the writer or `csa-change-authoring` applies it (as an editorial edit with a `Note`, or inside an evidence edit already touching that text).

## 11. Examples

| Before | After |
| --- | --- |
| The discovery data identified two domain controllers. | The environment is supported by two Active Directory domain controllers. |
| The evidence matrix lists DNS and NTP dependencies. | The application hosts depend on DNS for name resolution and NTP for time synchronisation. |
| The network data identifies connections to the backup environment. | The application servers use the network-accessible backup service for backup operations. |
| The table below provides the server estate. | The application is hosted across the following servers. |
| The server inventory identifies four servers at the ROT site. | The application is hosted on four servers at the Rockhampton (ROT) site. |
| The network capture shows traffic between Server A and Server B over TCP port 443. | Server A communicates with Server B over HTTPS (TCP/443). Where the qualification matters: "Observed network traffic confirms communication between Server A and Server B over HTTPS (TCP/443)." |
| Active Directory is part of the OT application stack. | The application depends on the INTERNAL Active Directory domain for Windows authentication; the domain is an enterprise IT service. |
| The OT DNS servers ROTPRDSRV122 and MOTPRDSRV122 ... | The INTERNAL domain controllers ROTPRDSRV122 and MOTPRDSRV122, which also provide DNS, ... |
| Platform tooling (CrowdStrike, SCCM, Nessus, LAPS) | Management and security agents: CrowdStrike Falcon, the Configuration Manager client, the Tenable Nessus agent and LAPS |
| This is not a full-estate absence claim. | This does not establish that the shares are absent on hosts outside those captures. |
| Heading: Estate and Discovery Coverage | Heading: Application Hosts and Discovery Scope (for a table of the application's hosts and which were examined) |
| The solution leverages a robust centralized authorization model. | Access is authorised through INTERNAL domain groups, managed centrally by IT. |

More examples by domain are in `references/terminology.md`.
