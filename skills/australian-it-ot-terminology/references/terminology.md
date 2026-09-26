# CSA controlled terminology (Australian IT/OT)

Part of `australian-it-ot-terminology`. Choose the term from what is being described (SKILL.md part 1), then check it here. This is guidance for choosing words, not a find-and-replace list. Sources are in `sources.md`; "ISM" means the ASD Information Security Manual glossary, "OT principles" means ASD/ACSC *Principles of operational technology cyber security*, "OT architecture" means ASD/ACSC *Creating and maintaining a definitive view of your OT architecture*.

`scripts/term_lint.py` reads two tables in this file: **Terms that need review** and **Australian spelling**. Keep their column layout.

## 1. Application and its parts

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Application | The software system being assessed, as its owners name it | "solution", "platform" (unless it is one), "workload" | The UTC application controls train movements on the Central Queensland network. |
| Application environment | The application together with the systems and infrastructure that support it | "estate", "landscape", "footprint" | The application environment spans the Rockhampton and Mackay sites. |
| Application component / module | A functional part of the application (a service, process or module), named as the vendor names it | "element", "artefact" | The Central Engine is the application component that ... |
| System | The application plus its servers, workstations, OT equipment, networks and supporting services, as one operating whole (ISM: "system") | "ecosystem" | The UTC/DTC system comprises ... |
| System component | A technical part of the overall system (a server, a network segment, a device) | "asset" as a generic label | Each system component is listed in Table 3. |
| Application server | A server that hosts application components or services | "compute node", "compute asset" | The application runs on two application servers per site. |
| Database server / database instance | A server, or SQL Server instance, that hosts the application's databases | "data store" when the product is known | The application database is hosted on the SQL Server instance SQLCDNAGL003. |
| Operator workstation | A workstation used by operators or controllers to run the application client | "endpoint", "user device" | Controllers use operator workstations at each control desk. |
| Engineering workstation | A workstation used to configure, build or maintain the OT system (build tools, PLC/RTU programming software) | "admin device" | Release packages are copied to the engineering workstation CONTROLLER36. |
| Application client | The client software on workstations that connects to the application servers | "front end" when the product names it otherwise | The UTC Workstation client (ws.exe) connects to both Message Redirectors. |
| Current configuration | How a system or component is configured at the time of the assessment | "as-is state" | In the current configuration, the partner address is fixed in te.cfg. |
| Current operational state | How the system operates today, including manual workarounds | "status quo" | |

## 2. Environment and classification

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| OT environment | The technology environment that directly monitors or controls physical processes (ISM: OT "detect or cause a direct change to the physical environment") | Calling everything the OT application touches "OT" | The application servers sit within the OT environment. |
| Operational technology (OT) | Systems that detect or cause a direct change to the physical environment through monitoring or control of devices, processes and events (ISM) | "industrial IT" | |
| Corporate IT environment / corporate network | The enterprise IT environment and network (ASD remote access guidance: "corporate environment") | "business side", "IT world" | Operators reach the jump host from the corporate network. |
| Enterprise IT service | A corporate IT service used by the OT system (AD, DNS, NTP, Configuration Manager, PKI, email, SIEM, backup) | "OT service" for these | The application depends on the enterprise Configuration Manager service for patching. |
| Supporting infrastructure | Infrastructure required by the application but not part of it | "underlying stack" | |
| Shared infrastructure | Infrastructure used by IT and OT, or by several systems | "common assets" | The IT/OT firewalls are shared infrastructure. |
| Platform service | A service provided by the operating platform to the application (Windows Time, IIS, a message broker) | | |
| External system | A system outside the assessed application that exchanges data with it | "third-party asset" unless it is a third party's | The application exchanges train plans with the external TCS. |
| Upstream system / downstream system | A system that supplies data to, or receives data from, the application | Use only when the direction is established | SCADA is upstream of IAMPS for rail-state data. |
| Third party / vendor | An organisation outside the owner that supplies, supports or connects to the system (OT architecture: manufacturers, integrators, MSPs) | "partner" (ambiguous) | The vendor connects through the vendor remote access service. |
| Critical infrastructure asset | An asset as defined under the Security of Critical Infrastructure Act 2018 | Use only in its legal sense | |
| Vital OT system | Program term (OT 3.5 separation requirements) for OT systems that must keep running when isolated | Use as the program defines it | |
| Industrial automation and control system (IACS) | IEC 62443 term for the collection of OT systems, equipment and people | Prefer "OT system" in prose; use IACS when citing IEC 62443 | |

## 3. Servers, hosting and virtualisation

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Server | A computer that provides services to users or other systems (ISM) | "box", "instance" when a physical or VM server is meant | |
| Host | A server or workstation on the network, when the role is not the point | "machine", "node" | Each host has two network interfaces. |
| Windows server / Windows Server 2019 host | A server identified by its operating system | "technology asset" | |
| Workstation | A single-user computer (ISM) | "endpoint" outside security-agent context | |
| Physical server | Bare-metal hardware running one operating system | "tin" | |
| Virtual machine (VM) | A server running on a hypervisor | "infrastructure item", "instance" | The Message Redirectors are VMs on the Rockhampton cluster. |
| Hypervisor / ESXi host | The software, or the physical host running it, that runs VMs | "virtualisation asset" | |
| Virtualisation cluster / vCenter | The managed group of hypervisor hosts and its management server | "virtual estate" | |
| Hosting environment | Where and on what the application runs (sites, physical or virtual, cluster) | "hosting footprint" | The application's hosting environment is two VMware clusters. |
| Server environment | The set of servers supporting the application, with their roles | "server estate" | |
| Storage array / SAN | Shared block storage used by hypervisors or servers | "storage resource" | |
| Local storage | Disks attached to the server itself | | Logs are written to local storage on each application server. |
| Operating system (OS) version and build | e.g. Windows 10 Enterprise LTSC 2021 (build 19044) | "OS flavour" | |
| End of support | The date the vendor stops security updates for a product | "end of life" unless the vendor uses it | Windows 10 LTSB 2016 reaches end of support on 12 January 2027. |

## 4. Networks, zones and communications

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Network segment / network zone | A defined portion of the network (subnet, VLAN, or zone in the program's zone model) | "network area" | The application servers sit in network zone Z3. |
| Zone and conduit | IEC 62443 terms: a group of assets with common security requirements, and the controlled communication path between zones (OT architecture) | Use when the program uses the zone model | |
| Network segmentation / segregation | Dividing the network and controlling traffic between parts (OT principles: "segment and segregate OT networks") | "network isolation" unless isolation is meant | |
| IT/OT boundary | The boundary between the corporate IT network and the OT environment | "interface" (ambiguous) | |
| Demilitarised zone (DMZ) | A network between the corporate network and the OT environment that hosts boundary services such as the first jump host (ASD remote access guidance) | "perimeter network" in Australian OT documents | |
| Network connectivity | Communications between components or systems | "data flows" when network paths are meant | |
| Data flow | The movement of data between systems, often shown as a data flow diagram (OT architecture) | For network paths use "network connection" | |
| Network connection | A specific communication path: source, destination, protocol and port | "session", "traffic" in running prose | The TCSI connects to both Message Redirectors on TCP/6005. |
| Protocol and port | e.g. HTTPS (TCP/443), Modbus TCP (TCP/502), DNP3 | "comms" | ROKSIGMAPW1 polls ROKPRDSCA103 over Modbus TCP (TCP/502). |
| Firewall / firewall rule | A boundary device and its rules | "security appliance" | |
| Router / switch / VLAN / subnet | Keep the standard terms | | |
| Gateway | A system managing data flows between networks of different security domains (ISM) | "bridge" | |
| Serial link / serial server | A serial connection to OT equipment, or the device converting serial to IP | | The telemetry processors reach the RTUs through Digi serial servers. |
| Network interface (NIC) | A network adapter on a host | "port" (ambiguous) | Each host has an OT-facing network interface (Ethernet 3). |
| Site | A physical operating location (Rockhampton, Mackay) | "location" is fine; avoid "facility estate" | |
| Control centre / control room | Where operators run the system | "operations hub" | |

## 5. Interfaces and dependencies

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Interface / external system interface | A defined connection through which the application exchanges data with another system | "integration touchpoint" | The application has an interface to the TCS over RabbitMQ. |
| Application interface | An interface provided or consumed by the application | | |
| Application dependency | A system or service the application needs to operate | "reliance" | |
| Infrastructure dependency | A platform or infrastructure service needed for operation (AD, DNS, NTP, virtualisation, storage) | | |
| Depends on ... for ... | The standard way to state a dependency: what and why | "leverages", "relies upon" (fine but vaguer) | The application depends on DNS for name resolution. |
| Single point of failure | A component whose failure stops the service with no alternative | Use only when shown | |
| Isolation / drawbridge | Program term: the OT environment cut off from IT | Use as the program defines it | |

## 6. Supporting services

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Active Directory domain | The AD administrative and security boundary, named (INTERNAL) | "the directory", "identity fabric" | The hosts are members of the INTERNAL domain. |
| Active Directory forest / domain trust | Forest and trust relationships | | |
| Domain controller | A server running AD Domain Services | "authentication asset", "AD server" | |
| Domain joined / domain member | A computer that is a member of an AD domain | | |
| Organisational unit (OU) | AD container for computers and users, used to target Group Policy | Keep AD spelling "Organizational Unit" only when quoting an LDAP path | The hosts are in the TCS OU. |
| Group Policy / Group Policy Object (GPO) | Windows configuration delivered through AD | "policy objects" | |
| Name resolution | The DNS function | "DNS coverage" | Name resolution is provided by the domain controllers. |
| DNS server / DNS resolver | The server answering queries / the servers a host is configured to use | "DNS asset" | |
| Active Directory-integrated DNS | DNS zones stored in AD | | |
| Time synchronisation / time source | NTP or Windows Time service providing time | "time sync coverage" | The hosts take time from the domain controllers. |
| Windows Time service (W32Time) | The Windows service performing time synchronisation | | |
| Public key infrastructure (PKI) / certificate authority (CA) | Certificate issuance and validation | | |
| Certificate revocation list (CRL) / OCSP | Revocation checking | | |
| Configuration Manager (SCCM/MECM) | Microsoft Endpoint Configuration Manager, used for patching and software deployment | "management tooling" alone | Patching is managed through the enterprise Configuration Manager service. |
| Software update point / WSUS | The update source hosts are directed to | | |
| Management and security agents | Agents installed on hosts for management or security (CrowdStrike, Configuration Manager client, Nessus, Splunk forwarder, LAPS) | "platform tooling" | |
| Email / SMTP relay | Mail delivery used for alerts | | |
| Proxy (web proxy) | HTTP/S proxy for outbound access | | |

## 7. Identity and access

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Authentication / authorisation | Proving identity / granting permissions | "auth" in prose | Authorisation is by membership of INTERNAL domain groups. |
| User account / service account | Account for a person / for automated tasks (ISM: service accounts perform automated tasks without manual intervention) | "identity" as a noun for an account | The application services run under the service account INTERNAL\_sUTC. |
| Privileged account / privileged access | Accounts that can change system configuration, privileges, event logs or security configuration (ISM) | "super user" | |
| Local administrator | Member of the local Administrators group | | |
| Restricted Groups | The Group Policy setting controlling local group membership | | |
| Local Administrator Password Solution (LAPS) | Microsoft product managing local admin passwords | | |
| Jump host / jump server | A computer used to manage systems in another security domain (ISM: jump server); ASD remote access guidance describes a jump host in the DMZ and a second inside the OT environment | "bastion" (acceptable but less common in Australian OT documents) | Administrators reach the servers through the jump host in the DMZ. |
| Remote access | Access that originates outside the organisation's network and enters through a gateway (ISM) | "remote connectivity" | |
| Vendor remote access | Remote access used by a vendor or integrator | "third-party connectivity" | |
| Multi-factor authentication (MFA) | | "2FA" in formal text | |

## 8. Backup, recovery, availability and resilience

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Backup and recovery | Backup arrangements and the ability to restore | "data protection coverage" | |
| Backup job / backup target / backup server | What is backed up, where to, by what | "backup resource" | |
| Retention period | How long backups are kept | | The retention period has not been confirmed. |
| Restore / rebuild | Recovering data / rebuilding a server from known-good media | "recovery capability" when a test was done: say "restore test" | |
| High availability | Architecture intended to maintain service availability | "always-on" | |
| Redundancy | Duplicate components, paths or services | "resiliency" (US-leaning noun; prefer "resilience") | |
| Duty/standby (hot standby) pair | Two servers where one runs and the other takes over; common in Australian OT | "active-passive" is fine where the vendor uses it | The TCSI runs as a duty/standby pair across the two sites. |
| Left/Right pair | Vendor term for the paired UTC servers | Use as the vendor names it | |
| Failover | The switch from a failed component to its partner | | |
| Resilience | Ability to keep operating or recover under failure or isolation | | |
| Disaster recovery (DR) | Recovery at another site after loss of a site | | |
| Business continuity | Keeping the business function going during disruption (OT principles: part of safety and continuity) | | |

## 9. Monitoring, patching and system management

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| Monitoring | Watching health and performance of systems | "observability" | |
| Event logging / log forwarding | Recording and sending logs (ISM: event logging) | "telemetry" for logs (telemetry is an OT term for field data) | Windows event logs are forwarded to Splunk by the universal forwarder. |
| Security information and event management (SIEM) | Central security log platform | | |
| Endpoint detection and response (EDR) / antivirus | Host security agents | | |
| Patching / patch management | Applying updates | "remediation" when patching is meant | |
| Patch level / patch currency | How up to date a host is | "patch posture" | The newest update installed was from August 2025. |
| Maintenance window | Approved time for changes | | |
| System management | Administering, patching and configuring systems (ISM guideline title) | "operations tooling" | |
| System hardening | Reducing attack surface through configuration (ISM guideline title) | | |
| Change management | Controlling changes to the system | | |
| Configuration management | Recording and controlling configuration | | |

## 10. OT equipment and industrial control

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| OT equipment | Any device that can process, store or communicate data or signals within OT environments, such as PLCs and RTUs (ISM) | "OT assets" in prose; "IoT devices" | |
| Industrial control system (ICS) | Control systems for industrial processes, as a group | Prefer "OT system" unless ICS is the established term | |
| SCADA | Supervisory control and data acquisition: gathers data from and supervises remote sites in real time (AESCSF glossary) | | |
| Distributed control system (DCS) | Process control system with distributed controllers, common in plants | | |
| Programmable logic controller (PLC) | | | |
| Remote terminal unit (RTU) | Field device collecting data and executing controls at remote sites | | |
| Intelligent electronic device (IED) / protection relay | Energy-sector field devices | | |
| Human-machine interface (HMI) | Operator display and control interface | "UI" | |
| Historian | Time-series store of process data | "data lake" | |
| Field device / field equipment | Sensors, actuators, instruments at the process | | |
| Safety instrumented system (SIS) | Independent safety control system | | |
| Physical process | What the OT system monitors or controls (OT principles) | | |
| Signalling / train control | Rail terms (Australian spelling "signalling") | "signaling" | |
| Wayside equipment | Rail trackside equipment | "field assets" | |
| Telemetry | Data from field equipment (rail, energy, water) | Not a synonym for IT log data | |

## 11. Operational support and ownership

| Preferred term | Meaning / context | Avoid / use carefully | Example |
| --- | --- | --- | --- |
| System owner | The person or role accountable for the system (ISM: the executive responsible) | "stakeholder" when an owner is meant | |
| Application owner / technical owner | | | |
| Operational support | Processes and teams that support operation | "support model" (fine), "operating model" (consulting) | Level 2 support is provided by OT Engineering. |
| Support arrangement / support contract | Vendor or internal support terms | | |
| Operations personnel / operators / controllers | People running the system | "users" when operators are meant | |
| OT engineering / IT operations | Teams | | |

## 12. Terms that need review

The lint reports these as `TERM_REVIEW_REQUIRED` in CSA narrative. They are not banned: each can be right when it really describes the subject. The writer or reviewer decides what technical concept is meant and names it. Column 1 is matched case-insensitively as a whole phrase.

| Phrase | Why it needs review | Ask |
| --- | --- | --- |
| estate and discovery coverage | Consulting and data-collection framing for what is usually the application's hosts | Is this the application's hosts, servers, components, or the discovery scope? |
| discovery coverage | Describes the data collection, not the system | Is the subject really the discovery activity (appendix), or the application's hosts? |
| discovery footprint | Data-collection jargon | Which hosts were examined? |
| technology footprint | Consulting jargon | Application environment? Infrastructure overview? |
| technology estate | Asset-management jargon | Application environment? Server environment? |
| estate | Portfolio / real-estate term, not IT/OT language for an application's hosts | Hosts in the asset list? Application servers? The application environment? |
| evidence landscape | Consulting jargon | What does the evidence describe? Belongs in Methodology? |
| landscape | Consulting and AI tell | Name the environment or the systems |
| ecosystem | Consulting and AI tell | Name the systems |
| data coverage | Describes the data set | Which hosts or components were examined? |
| evidence coverage | Describes the evidence | Which hosts or components were examined? |
| dataset | Data-analysis framing | Name the source (asset list, discovery captures) or the system it describes |
| data set | Data-analysis framing | As above |
| discovery population | Framework term for hosts with captures | "hosts with discovery captures", "captured hosts" |
| declared population | Framework term for the asset list | "hosts in the asset list" |
| capture campaign | Framework term | "discovery run (date)" |
| platform tooling | Vague | Management and security agents? Name them |
| compute asset | Vague | Application server? VM? |
| technology asset | Vague | Name the kind of equipment |
| infrastructure item | Vague | VM? Server? Switch? |
| authentication asset | Vague | Domain controller? |
| network service asset | Vague | DNS server? DHCP server? |
| storage resource | Vague | Network share? SAN? Local disk? |
| footprint | Consulting tell | Name what occupies what |
| solution | Consulting word for a system | Name the application or system |
| stakeholder landscape | Consulting | Name the owners and teams |
| as-is state | Consulting | Current state, current configuration |
| application sample | Data-analysis framing for hosts examined on one date | "hosts with May 2026 discovery captures" |
| evidence sample | Data-analysis framing | "the hosts whose Group Policy results were captured" |
| sampled hosts | Data-analysis framing; often a stale count | "hosts with discovery captures (date)" |
| sampled | Data-analysis framing ("39 sampled hosts"); often a stale count | Which hosts, captured when? |
| to-be | Consulting | Target state (program term) |

## 13. Evidence-centric phrases

The lint counts these per section and flags them as `EVIDENCE_CENTRIC` when they open a sentence or appear three or more times in one section. One qualified use is often right (SKILL.md part 5). Column 1 is a regular expression, matched case-insensitively.

| Phrase |
| --- |
| the evidence shows |
| evidence shows |
| evidence indicates |
| the data shows |
| data shows |
| the table shows |
| table shows |
| the table demonstrates |
| the table below provides |
| information provided |
| documentation shows |
| the dataset shows |
| the discovery data |
| the capture shows |
| the spreadsheet |
| the workbook |
| the script output |
| the evidence matrix lists |
| the table below records |
| source workbook |
| the evidence covers |
| the raw [^.]{0,40}? output |
| \S+ output (?:from\|on) \S+ (?:confirms\|shows) |
| the discovery scripts? |
| the capture set shows |

## 14. Australian spelling

The lint flags the US form as `AU_SPELLING` outside code spans, quotes, file names and the product names listed in its allow-list. Column 1 is a regular-expression stem matched as a word start.

| US form (regex) | Australian form |
| --- | --- |
| organiz | organis- (organisation, organise) |
| authoriz | authoris- |
| centraliz | centralis- |
| virtualiz | virtualis- |
| optimiz | optimis- |
| standardiz | standardis- |
| synchroniz | synchronis- |
| recogniz | recognis- |
| prioritiz | prioritis- |
| summariz | summaris- |
| categoriz | categoris- |
| customiz | customis- |
| minimiz | minimis- |
| maximiz | maximis- |
| utiliz | utilis- (or "use") |
| characteriz | characteris- |
| normaliz | normalis- |
| initializ | initialis- |
| analyz | analys- |
| behavior | behaviour |
| color | colour |
| favor | favour |
| labor | labour |
| center | centre |
| defense | defence |
| catalog\b | catalogue |
| modeling | modelling |
| labeled | labelled |
| labeling | labelling |
| canceled | cancelled |
| traveled | travelled |
| enroll\b | enrol |
| fulfill\b | fulfil |
| judgment | judgement |
| signaling | signalling |
| license holder | licence holder |
| licenses\b | licences (noun) |
