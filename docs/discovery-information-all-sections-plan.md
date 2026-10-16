# Discovery Information for every subsection: investigation and plan

15/10/2026. Wenzel asked how the Discovery Information of all subsections (3.1 to 3.17) can be improved in the way 3.4 Time Synchronisation, 3.5 DNS and 3.7 Storage & Data Transfer were. Investigated on the live REVELOC TETRA document and its captures.

## 1. What the Discovery Information looks like today

| Section | Rows | Rows counting hosts | Rows listing 3+ hosts | Role table |
| --- | --- | --- | --- | --- |
| 3.1 General / Asset Inventory | 16 | 4 | 2 | no |
| 3.2 Identity & Authentication | 13 | 2 | 2 | no |
| 3.3 PKI / Certificates | 5 | 3 | 0 | no |
| 3.4 Time Synchronisation | 8 | 6 | 2 | yes (old rows not yet redrafted) |
| 3.5 DNS | 7 | 4 | 0 | yes (old rows not yet redrafted) |
| 3.6 Network / Segmentation | 9 | 4 | 1 | no |
| 3.7 Storage & Data Transfer | 9 | 6 | 1 | pilot copy only |
| 3.8 Management & Admin Access | 5 | 5 | 0 | no |
| 3.9 Monitoring & Logging | 7 | 4 | 1 | no |
| 3.10 Patch & Lifecycle | 6 | 5 | 0 | no |
| 3.11 Backup & Recovery | 7 | 6 | 0 | no |
| 3.12 Isolation ("Drawbridge") | 7 | 5 | 0 | no |
| 3.13 Perimeter / Firewall | 6 | 3 | 2 | no |
| 3.14 Vulnerability Management | 7 | 4 | 0 | no |
| 3.15 Infrastructure Dependencies | 6 | 5 | 1 | no |
| 3.16 Supply Chain / Vendor Access | 5 | 3 | 0 | no |
| 3.17 Internet & SMTP | 7 | 6 | 1 | no |

Across all sections:

- **Counts.** About 72 of 120 rows count hosts ("six SQL Server cluster nodes", "all twelve captured hosts").
- **Mixed points.** Per-host settings and system-level points sit in the same list. In 3.1 and 3.2, host names and account names are even used as aspect labels.
- **Same evidence, different words.** Several sections restate the same evidence: the enterprise directory dependency appears in 3.1, 3.2, 3.6, 3.12 and 3.15.
- **Agent depth.** The agent sees keyword-matched evidence rows, so a section is only as good as the matrix rows that happen to match its words.

## 2. The pattern that works (3.4, 3.5, 3.7)

Each section gets up to three framework-built parts, then the agent's part:

1. **Role table.** Per-host settings for the topic, with rows as role groups and no counts. Uncaptured hosts are assumed to match their role (marked †). Values shared by every host move into one line.
2. **Flows table.** For topics about connections: grouped by mechanism, showing which side opens each connection, zones, and declared versus seen.
3. **Analysis frame.** The topic's sub-questions on the card, each finding citable. The agent answers every slot (FRAME_UNCOVERED).
4. **Aspect table.** Written by the agent, only for system-level points: what exists or is missing across the system, what was not tested.

What makes this scale is **shared inventories**: a handful of extractors each feed several sections, so most sections need only a profile and a frame file, not new code.

## 3. Shared inventories

| # | Inventory | Status | Captures | Feeds |
| --- | --- | --- | --- | --- |
| I1 | Host register (role, site, in scope) | exists | inventory, roles.csv | every section |
| I2 | Host settings (time, DNS, storage, transfer) | exists, to extend | 03, 14, 15, 42, 52, 61, 67 | 3.4, 3.5, 3.7, 3.17 |
| I3 | **Product and agent catalogue (new)**: every service, process and installed product classified as EDR, AV, log forwarding, monitoring, backup, patch/config management, vulnerability scanner, application control, remote support, file transfer, virtualisation tools, database, web server | new | 32 services (Name, DisplayName, PathName, StartName, State), 24 tasklist, 67 installed software, 32A/32B | 3.9, 3.10, 3.11, 3.14, 3.15, 3.16, plus 3.1 and 3.7 |
| I4 | Flows and zones | exists | 23, 20, 02 flow map, zones.csv | 3.6, 3.7, 3.12, 3.13, 3.16, 3.17, and 3.8 (admin paths), 3.9 (log destinations), 3.11 (backup paths) |
| I5 | **Identity inventory (new)** | new | 54 auth configs, 55 DC discovery, 56 Kerberos, 44 local users, 45 groups, 46 local admins, 47 RDP users, 32 StartName | 3.2, 3.8, 3.16 |
| I6 | **Platform and patch facts (new)** | new | 00 host summary, 70 WU policy, 71 hotfixes, 72 MECM, 67 VMware Tools, inventory Physical/Virtual | 3.1, 3.10, 3.15 |
| I7 | **Certificates (new)** | new | 68 machine store, 69 root store, 58 certificate-service mapping | 3.3 |
| I8 | **Host firewall and exposure (new)** | new | 31 profiles, 33 to 39 rules, 20 listeners on all interfaces | 3.13 (host level only; boundary devices are not in the captures) |
| I9 | **Isolation dependency matrix (derived)** | new | flows, agents and settings combined | 3.12 and every Drawbridge Impact |

I5 details:
- domain membership and the domain controller that answered;
- which services run as domain accounts (for example `internal\_sSQLCDNCLU002` runs SQL on the cluster nodes);
- local Administrators and Remote Desktop Users members and their source (AD or local);
- enabled local users.

I9 details:
- rows are role groups;
- columns are the IT services each group depends on (directory, DNS, time, MECM, monitoring, log forwarding, backup, internet/cloud, mail);
- each cell says what the captures show.

I3 is the biggest lever. The captures already name the products: Dell PowerProtect agent (`DPSAPPS\AgentService`, which confirms the 3.7 backup hint), CrowdStrike Falcon, Defender for Endpoint (Sense), SCOM HealthService and AdtAgent, MECM CcmExec, Splunk, Cisco Secure Workload, VMware Tools, AppID. A catalogue file (product, category, matching names and paths) also replaces the signature list, so "what is this?" hints come from one place.

## 4. Each subsection

| Section | Role table columns | Flows table | Frame slots (main) | Inventories | Not in captures (Discovery Required) |
| --- | --- | --- | --- | --- | --- |
| 3.1 General / Asset Inventory | OS, physical or virtual, site, main application software | external dependencies summary (cross-zone flows by mechanism) | assets and roles; non-Windows layers (radios, gateways, base stations); dependencies outside OT; is an inventory maintained | I1, I3, I4, I6 | base stations, RoIP gateways, radios, licence dongles |
| 3.2 Identity & Authentication | domain, answering DC, domain service accounts, local Administrators sources, enabled local users | (authentication flows to DCs) | how people, services and devices authenticate; application logins (SQL, cluster); what fails without IT AD | I5, I4 | SQL logins and application accounts inside the databases |
| 3.3 PKI / Certificates | machine certificates (issuer, expiry), services bound to certificates | none | which certificates the application itself uses; issuer; CRL/OCSP location; expiry during a three-month isolation | I7 | CRL/OCSP endpoints if not in the certificates |
| 3.4 Time | done | none | add frame: application time source, records depending on clock agreement | I2 | holdover behaviour |
| 3.5 DNS | done (add search suffix, hosts-file overrides) | name-resolution flows | add frame: names the application uses, host names versus IP addresses | I2, I4 | hosts-file capture |
| 3.6 Network / Segmentation | subnet, zone, gateway, interfaces | **all cross-zone flows** (every mechanism), declared versus seen | zone placement; conduits; undocumented flows; general IT services present in OT (MECM, Splunk, SCOM, Secure Workload) | I4, interfaces 11/12 | VLANs, SL-T per zone |
| 3.7 Storage & Data Transfer | done (pilot) | done | done | I2, I4 | retention, restore use |
| 3.8 Management & Admin Access | local Administrators, Remote Desktop Users, RDP/WinRM listening | inbound admin flows (3389, 5985, 22) and who opens them | admin paths through jump hosts; rights from IT groups; dependence on IT | I5, I4 | PAM or RDS gateway, if any |
| 3.9 Monitoring & Logging | EDR, log forwarder, monitoring agent, AV | log and telemetry flows with destinations | what logs exist; where they go; retention; visibility lost on isolation | I3, I4 | retention and tamper protection |
| 3.10 Patch & Lifecycle | OS and build, last hotfix date, update source (WSUS/MECM URL), MECM client version | patch and management flows | source, tooling, currency, end of support, patching during isolation | I6, I3, I4 | cadence and urgent-patch process |
| 3.11 Backup & Recovery | backup agent, SQL backup target, VSS writer | backup flows (who pulls, from where) | what is backed up, by which tool, to where, under whose account; restore tested; rebuild from OT copies | I3, I4, I2 | job schedules, restore tests |
| 3.12 Isolation | **isolation dependency matrix** (I9) | none | which functions stop or keep running; manual workarounds; tested | I9 | the plan and tests themselves |
| 3.13 Perimeter / Firewall | host firewall profiles and default actions, inbound rules allowing any, services listening on all interfaces | inbound flows from outside the zone | boundary devices; rule quality; external exposure; administration | I8, I4 | boundary firewalls and their rules |
| 3.14 Vulnerability Management | AV/EDR, application control (AppLocker/WDAC), vulnerability scanner agent | none | how vulnerabilities are found and tracked; coverage verified by whom | I3, Group Policy | vulnerability register |
| 3.15 Infrastructure | platform (VMware VM or physical model), VMware Tools, OS | management flows to vCenter (if seen) | platforms; who manages them with which accounts; dependence on IT | I6, I3, I4 | vCenter, hosts, storage arrays |
| 3.16 Supply Chain / Vendor Access | remote support tools, vendor-looking accounts | external and vendor flows | vendors; how access works; controlled and monitored; bypass paths | I3, I5, I4 | vendor contracts and access approvals |
| 3.17 Internet & SMTP | proxy setting, SMTP configured | internet and mail flows | which hosts reach the internet or send mail, by which route; what stops | I2, I4 | the OT35 proxy, if not yet in place |

## 5. Order

1. **I3 product and agent catalogue**, plus profiles and frames for 3.9, 3.14 and 3.11. Three sections from one extractor.
2. **I5 identity inventory**, plus profiles and frames for 3.2 and 3.8, then 3.16 (with I3 and I4).
3. **I6 platform and patch facts**, plus 3.10, 3.15 and 3.1.
4. **Flows reused** for 3.6, 3.13 (with I8) and 3.17: profiles and frames only, plus the host firewall extractor.
5. **I7 certificates**, plus 3.3.
6. **I9 isolation dependency matrix**, plus 3.12. The same matrix gives every section's Drawbridge Impact its facts.
7. **Frames for 3.4 and 3.5.**

Each step is one extractor (with tests), one profile JSON and one frame JSON per section, then a pilot on a copy of the TETRA document. The engines (`topic_tables.py`, `topic_frames.py`, `flows.py`) are already generic. The frame engine needs one more source type, "agents", for the catalogue.

Then redraft the sections with `csa draft`. The new checks (NO_TOTALS, ROLE_TABLE_REPEAT, FRAME_UNCOVERED) make the agent drop the old per-host aspect rows.

## 6. Already visible in the TETRA captures (for the sections above)

These are not yet evidence rows:

- **3.2 / 3.8.** SQL services on the cluster nodes run as a domain account (`internal\_sSQLCDNCLU002`). Local Administrators include AD groups such as Domain Admins, Aurizon Core System Administrators, Aurizon Server MOE Administrators, Domain SQL Admins and OCDN_SQL_Ladmin_PRD, plus a local SrvAdmin user.
- **3.9 / 3.14.** CrowdStrike Falcon, Defender for Endpoint (Sense), SCOM (HealthService; AdtAgent installed but disabled), Splunk and Cisco Secure Workload are present. AppID service is present, but no AppLocker policy was found in the applied Group Policy of the host checked.
- **3.10.** Windows Update policy points to a local MECM source (`UpdateServiceUrlAlternate http://localhost:8005`, dual scan disabled). MECM client 5.00.9141.1030. Latest hotfix 30/05/2026 on ROTPRDCLU101.
- **3.11.** Dell PowerProtect agent (`C:\Program Files\DPSAPPS\AgentService`) on the SQL nodes, pulled from ROTPRDPDM101 on TCP 7000.
- **3.13.** Host firewall profiles are all enabled, with default inbound and outbound actions "NotConfigured".
- **3.15.** VMware Tools runs on the captured hosts.

## 7. Progress

### Step 1 done (15/10/2026): product and agent catalogue, 3.9, 3.14, 3.11

- **Catalogue.** `references/product-catalogue.json` covers 43 products in 15 categories. It matches the service Name, DisplayName or PathName, or the installed software name. A Windows component that is on every host (AppLocker, Windows Defender) counts only while it runs.
- **Extractor.** `host_settings.agent_settings` writes `agent.<category>` for every host, plus `agent.backup_account` (the account each backup service runs as) and `appcontrol.policy` (from applied Group Policy). Each value quotes the capture's service Name line. An absence is "None found", which becomes a not-found evidence row.
- **Profiles and frames.**
  - `monitoring-logging` (3.9): role table plus log, monitoring and telemetry flows; 5 frame slots.
  - `vulnerability-management` (3.14): role table; 5 slots.
  - `backup-recovery` (3.11): role table plus backup flows; 5 slots.
- **Generic improvements.** Flow mechanism filters for tables and frames. Value-column widths now follow content, with a minimum from the header's longest word. A shared value of "None found" reads "have no <thing> found".
- **TETRA pilot.** Done on a copy. All frame evidence rows were accepted: 19 for 3.9, 24 for 3.14, 14 for 3.11.
- **Tests.** `tests/test_agents.py` (3). The other 78 framework tests still pass.

What the TETRA captures show:

- CrowdStrike Falcon runs on every captured host. Defender for Endpoint (Sense) is installed but stopped, except on MOTPRDREV101.
- Defender Antivirus runs only on the Jump Hosts.
- SCOM HealthService runs everywhere. SCOM Audit Collection is installed but disabled.
- Splunk is only on the Jump Hosts and the Sepura Radio Manager.
- Cisco Secure Workload is only on the Sepura Radio Manager.
- PowerProtect runs as LocalSystem on the SQL nodes, the Reveloc server and the TETRA log server. The log server also has the Dell VM Direct (vSphere file-level restore) agent.
- No vulnerability scanning agent and no application control policy were found.
- UltraVNC, Cisco Security Manager, Tomcat and Apache are on the Jump Hosts. ROKPRDOPS110 also has the SafeNet Sentinel licence service. These feed 3.13 and 3.16 later.

**Correction for the document.** The current 3.14 Discovery Information says "No endpoint-protection product running on any captured host was identified". The service captures show CrowdStrike Falcon running on every captured host. Redrafting 3.14 with the new card corrects this.

### Step 2 done (15/10/2026): identity inventory, 3.2, 3.8, 3.16

- **Extractor.** `host_settings.identity_settings` writes, per host:
  - `identity.domain` (54 auth configs);
  - `identity.kdc`, the domain controller that issued the Kerberos tickets (56, else 54);
  - `identity.kerberos`, the ticket encryption;
  - `identity.local_users`, the enabled local accounts (44);
  - `identity.service_accounts`, the non-built-in accounts services log on as (32 StartName);
  - `admin.local_admins` (46) and `admin.rdp_users` (47);
  - `admin.listeners`: RDP, WinRM, SSH, Telnet and VNC ports listening (20).
- **Membership parsing.** The group-membership tables are read by the dash underline's column positions, so a group name with single spaces keeps every word. A local member reads "SrvAdmin (local)".
- **Empty captures.** An empty Remote Desktop Users listing means the group has no members ("No members"). Other empty captures still count as not captured, because an empty services listing means the capture failed.
- **List columns (generic).** A profile column marked `"list": true` moves the members every captured host shares into the common line. Each cell then shows only what differs, or "No others".
- **Profiles and frames.**
  - `identity-authentication` (3.2): role table plus directory flows; 6 slots.
  - `management-admin-access` (3.8): Administrators, Remote Desktop Users and admin listeners, plus remote administration flows; 5 slots.
  - `vendor-access` (3.16): remote control tools, enabled local accounts and admin listeners, plus remote administration flows; 5 slots.
- **Flows.** WinRM (5985, 5986) and VNC (5800, 5900) are now classed as remote administration, not management.
- **Frame evidence fix.** A finding that feeds two slots was sent twice in one batch. Its second copy came back as "(same batch)" and replaced the real ID. Rows are now sent once and matched back by position. Every finding in all seven frames now carries a real E- ID (3.9 now cites 22 rows, not 19).
- **Column widths.** A column is never narrower than its longest word in any cell, with capitals and digits counted wider. Role and Hosts give up width when the value columns need it.
- **TETRA pilot.** "CSA REVELOC TETRA - 3.2 3.8 3.16 pilot.docx" validates. Evidence rows: 18 IDs for 3.2, 22 for 3.8, 12 for 3.16.
- **Tests.** `tests/test_identity.py` (4). All topic-table, flow, agent, optional-note, answer-quality and fact-check tests pass.

What the TETRA captures show:

- Every captured host is in internal.qr.com.au and gets its Kerberos tickets (AES-256) from an enterprise IT domain controller. The Rockhampton hosts use ROTPRDSRV122, the Mackay hosts MOTPRDSRV122, and the Sepura Radio Manager IPTPRDSRV123.
- The SQL instances run as domain accounts: `internal\_sSQLCDNCLU002` (RevServer) and `internal\_sSQLCDNCLU003` (RevBroadcast). RevBroadcast runs as `internal\_sRevBroadCastServ`. Everything else runs as built-in accounts.
- Every captured host has these in local Administrators: Aurizon Core System Administrators, Aurizon Server MOE Administrators and Domain Admins (all IT groups), plus a local SrvAdmin account. Domain SQL Admins is on most hosts. The Delinea discovery account `_sDelineadiscovery` is an administrator on the Reveloc server, the RevBroadcast server and most SQL nodes.
- Remote Desktop Users holds **Everyone** on MOTPRDREV101. It is empty on the SQL nodes and the Sepura Radio Manager.
- Nothing listens on RDP 3389 on any captured host, while the old 3.8 text says the Jump Hosts provide an RDP path. Every captured host listens on WinRM 5985. The Jump Hosts also listen on VNC (5900 and 5800), and ROKPRDOPS110 on SSH 22.
- Enabled local accounts include DammBackup, DammUser and Radio_Admin on the Reveloc server, casuser on the Jump Hosts, BladeLogicRSCD on ROKPRDOPS110 and the Sepura Radio Manager, and CliTest2 on ROTPRDCLU104. Who owns them (vendor or internal) is a Discovery Required point for 3.16.
- Password policy and NTLM settings were not captured (the secedit export failed). This is a capture gap for the discovery script.


### Step 3 done (15/10/2026): platform and patch facts, 3.1, 3.10, 3.15

- **Extractor.** `host_settings.platform_settings` writes, per host:
  - `platform.os`, the OS and build (00 host summary);
  - `platform.support`, the Microsoft extended support end, from the new `references/os-lifecycle.json`;
  - `platform.hardware`: VMware VM, Hyper-V VM, or physical with maker and model;
  - `patch.latest`, the latest installed update and its date (71);
  - `patch.source`, the WSUS server and port (70);
  - `patch.auto`, Automatic Updates on or off (70);
  - `patch.client`, the MECM client version (72).
- **Lifecycle reference.** `references/os-lifecycle.json` holds Windows Server 2008 to 2025, checked 15/10/2026 against the published Microsoft lifecycle dates. ESU is not counted. Review it when a new release ships.
- **Hotfix dates.** Day/month order is worked out per file, because the captures mix 30/05/2026, 5/22/2026 and 03-Jun-26. With no clue in the file, dates are read day first. All dates are written dd/mm/yyyy.
- **Flows.**
  - WSUS 8530/8531, MECM 10123 and the CcmExec process signature are now "patch management", not "management".
  - Table flow filters gained `cross_zone` and `exclude_mechanisms`.
  - A cell with more than four destination addresses shows three and "other addresses". The full list stays in the sources.
- **Profiles and frames.**
  - `asset-inventory` (3.1): platform and OS role table plus every zone-crossing flow except unclassified ones; 4 slots.
  - `patch-lifecycle` (3.10): OS, support end, latest update, update source, client and Automatic Updates, plus patch management flows; 6 slots.
  - `infrastructure-platform` (3.15): platform, guest tools, OS and support; 5 slots.
  - The 3.14 frame now also reads patch management flows.
- **TETRA pilot.** "CSA REVELOC TETRA - 3.1 3.10 3.15 pilot.docx" validates. Evidence rows: 15 IDs for 3.1, 29 for 3.10, 14 for 3.15.
- **Tests.** `tests/test_platform.py` (2). All topic-table, flow, agent, identity, optional-note, answer-quality and fact-check tests pass (66).

What the TETRA captures show:

- The Reveloc server MOTPRDREV101 is a physical Dell PowerEdge R730 on Windows Server 2016, whose extended support ends 12/01/2027. Its latest update is from 13/01/2026, the oldest of the captured hosts. Its role assumes the same for ROTPRDREV101, 102 and 103.
- The TETRA log server ROTPRDLOG102 is a VMware VM on Windows Server 2022. Every other captured host is a VMware VM on Windows Server 2019 (support to 09/01/2029), with VMware Tools.
- Every captured host takes updates from WSUS on IPTPRDCCM202 port 8531 (enterprise IT), runs MECM client 5.00.9141.1030, and has Automatic Updates turned off by policy.
- The MECM clients talk to 10.89.161.67 on 10123 and 443, and to 10.40.228.98 and 10.45.228.98 on 443. These addresses are not in zones.csv yet.
- The other latest updates range from 22/05/2026 to 25/06/2026.
- The Sepura Radio Manager (IPTPRDAPP137, IT zone) reaches internet addresses directly for Windows services, Cisco Secure Workload telemetry and one web/API endpoint.


### Step 4 done (15/10/2026): network, host firewall and internet, 3.6, 3.13, 3.17

- **Network extractor.** `net.address` (IPv4 and prefix, link-local left out, from 12), `net.gateway` (default route, 11) and `net.zone` (zones.csv, from the first address).
- **Host firewall extractor (I8).**
  - `fw.profiles` (31): on or off, and the default actions.
  - `fw.custom_inbound` (33): enabled inbound Allow rules that are not stock Windows rules.
  - `fw.exposed`: what listens on every interface (20, with process names from 10 and services from 24). Windows' own processes count only on their well-known ports. Dynamic ports from 49152 up are left out, except RDP.
- **Rule ports not joined.** The rule list (33) and port filters (34) are separate dumps in different orders, so rules are not joined to their ports.
- **Alternate RDP port (correction to step 2).**
  - RDP is now found by the Remote Desktop service (TermService) owning the listening port, from the tasklist (24). Before, only port 3389 counted.
  - `admin.rdp_port` records the port. `admin.listeners` now shows "RDP 56403" for every TETRA host. The step 2 finding "nothing listens on RDP 3389" was a symptom of this, and the 3.8 and 3.16 tables now show RDP.
  - Flows on a recorded RDP port are now remote administration, not "other".
- **Netstat samples (25) in flows.**
  - Connections to public addresses that the process map (23) missed are now added. An established state makes them "observed".
  - Only SYN_SENT makes them "attempted", a new status: the host asked and no reply was seen. Tables say "Attempted, no reply seen", and frames say SYN_SENT.
  - Attempted rows merge per mechanism and port.
- **Directory RPC.** Dynamic-port connections to a domain controller are "directory (RPC)", not "other".
- **Shared flow filter.** `flows.select` serves tables and frames alike. New keys: `direction` (inbound or outbound, against the host register), `dst_zones`, and `any_of`.
- **Profile options.**
  - `keep` holds a column in the table even when every host shares its value.
  - `flows` fills a column per host from the flow inventory. This drives the 3.17 "Internet connections (samples)" column.
- **Frames.** A finding's quoted excerpt is trimmed to whole lines within the matrix limit. A batch the matrix rejects is resent without the rejected rows (it matches the script's 100-character claims).
- **Profiles and frames.**
  - `network-segmentation` (3.6): zone, address and gateway, plus the flows that cross recorded zones; 5 slots, including connections to unrecorded zones and IT services reaching OT.
  - `perimeter-firewall` (3.13): host firewall, added inbound rules and what listens on every interface, plus inbound flows from outside the system; 6 slots.
  - `internet-smtp` (3.17): proxy and internet connections per host, plus internet and mail flows; 4 slots.
  - 3.1 and 3.6 also include attempted flows.
- **TETRA pilot.** "CSA REVELOC TETRA - 3.6 3.13 3.17 pilot.docx" (also re-placing 3.1) validates. Evidence rows: 72 IDs for 3.6, 22 for 3.13, 17 for 3.17.
- **Tests.** `tests/test_network_firewall.py` (6). The suite has 72 tests, all passing.

What the TETRA captures show:

- Every captured host runs Remote Desktop on port 56403, not 3389. MOTPRDREV101 has local "Allow Alternate RDP (TCP/UDP 56403)" rules.
  - Internal addresses outside the system connect in on 56403 to the Jump Hosts and the Sepura Radio Manager: 10.40.104.118, 10.40.96.108, 10.40.97.19, 10.60.245.4 and 10.60.252.48.
  - ROKPRDOPS110 connects out on 56403 to 10.40.228.132 and 10.40.228.211.
  - The flow map entry GP2 still says 3389.
- The Windows Firewall is on for every profile on every captured host. Default actions are not set (the Windows defaults apply), except on MOTPRDREV101, where inbound is set to block.
- Added inbound allow rules: BigFix (BES Client) on the Jump Hosts, the Dell PPDM agent on the SQL nodes and the Reveloc server, and Bonjour on the RevBroadcast server.
- The Jump Hosts listen on every interface for SSH (FreeSSHD on ROKPRDOPS110), VNC, Apache/Tomcat, the Sentinel and HASP licence services and several Java services. The Reveloc server exposes RevAdmin, Tilemine, RoIP and Dell OpenManage.
- No host has a WinHTTP proxy. Ten captured hosts only tried to reach Microsoft and Azure internet addresses (SYN_SENT, no reply in the samples), on 443 and 80. Only the Sepura Radio Manager (IT zone) made established internet connections (Windows services, Cisco Secure Workload telemetry, web/API).
- **Correction for the document.** The current 3.17 and 3.13 text says eleven captured hosts had *established* outbound HTTP/HTTPS connections to the internet. The netstat samples show only connection attempts with no reply for ten of them. One host, the Sepura Radio Manager, connected.
- Many internal peers (MECM 10.89.161.67, SCOM 10.89.165.73, Splunk 10.89.165.176/177, file shares 10.89.163.66/73, 10.40.254.6:8080) have no zone in zones.csv. Recording them would move those flows from "zone not recorded" to definite crossings.


### Step 5 done (15/10/2026): certificates, 3.3

- **Extractor (I7).** `host_settings.cert_settings` writes, per host:
  - `cert.machine`: the host's own certificate with a private key, its issuing CA and expiry (68);
  - `cert.other`: other machine-store certificates with issuer and expiry, "expired" when past the capture date. The failover cluster's CLIUSR certificates are named once.
  - `cert.private_roots`: Trusted Root entries that are not public roots (69). Cluster ClusInfraCert roots are left out.
- **Public roots.** The new `references/public-roots.json` lists public root CA name patterns. Anything else in the root store is a private root: an enterprise or OT PKI, a product CA, or a TLS inspection CA. Add a pattern when a public root shows up as private by mistake.
- **Dates.** The certificate dates use the same per-file day/month detection as the hotfixes, and are written dd/mm/yyyy.
- **Profile and frame.** `pki-certificates` (3.3) shows machine certificate, other certificates and private roots (a list column, so the roots every host trusts go to the common line); 5 slots, including the application's own TLS use, CRL/OCSP reachability and renewal during isolation.
- **TETRA pilot.** "CSA REVELOC TETRA - 3.3 pilot.docx" validates. Evidence rows: 10 IDs for 3.3.
- **Tests.** `tests/test_certificates.py` (1). The suite has 73 tests, all passing.

What the TETRA captures show:

- Every captured host's machine certificate comes from the enterprise IT CA: Aurizon Online Issuing CA, or Aurizon Online Issuing CA EMP on ROTPRDCLU101 and 102.
- As captured (June and July 2026), the machine certificates of MOTPRDREV101, MOTPRDCLU101, MOTPRDCLU103, ROTPRDCLU103 and ROTPRDCLU104 expire on 29/10/2026. The Jump Hosts expire 20/11/2026, and the others 09/03/2027 and 20/03/2027. Renewal needs the IT CA, so they may have been renewed since. This is a 3.3 isolation point.
- ROKPRDOPS110 holds a Cisco Manufacturing CA device certificate (00175Affb406) that expired on 18/11/2025.
- Every captured host trusts these private roots: Aurizon Offline Root CA, the QR roots, APPSENSE-CA, td-ca and "Microsoft Forefront TMG HTTPS Inspection Certificate Authority" (a TLS inspection CA).
- The six SQL nodes also trust "Aurizon Network OT Root CA". **Correction for the document:** the current 3.3 text says no standalone OT certificate authority was documented, but an OT root CA is trusted on the SQL nodes. Whether it issues anything the system uses is a Discovery Required point.
- The TETRA log servers have no certificate capture, so they are a gap.


### Step 6 done (16/10/2026): isolation dependency matrix, 3.12

- **New module (I9).** `isolation.py` builds, per host, the services the host depends on outside its own zone. It uses only what the other extractors already hold, and reads no captures itself:
  - directory, time and DNS together (identity.kdc, time.source, dns.primary). One provider when they agree, else "directory and time X, DNS Y".
  - patching (patch.source);
  - monitoring and logs (the monitoring, log forwarding and telemetry flows the host opens);
  - who takes the backup (backup-agent flows into the host);
  - the certificate issuer (cert.machine).
- **Zones.** Every provider is tagged with its zone from zones.csv: (IT), (internet), (OT) or (zone not recorded). Providers in the same zone share one tag.
- **Storage.** Rows go to `hosts/isolation.csv`. `host_settings.load` merges them as `iso.*` attributes, and `hostmodel.build` rebuilds the matrix after the flows.
- **Profile and frame.** `isolation-dependencies` (3.12) has the five matrix columns; 6 slots. The frame cites the underlying settings and flows, so every claim keeps its exact quote. Its manual slots are application functions that keep running, manual workarounds and thresholds, and whether an isolation plan exists and was tested.
- **TETRA pilot.** "CSA REVELOC TETRA - 3.12 pilot.docx" validates. Evidence rows: 32 IDs for 3.12.
- **Tests.** `tests/test_isolation.py` (1). The suite has 74 tests, all passing.

What the TETRA matrix shows:

- Every OT host takes directory, time and DNS from an enterprise IT domain controller: ROTPRDSRV122 at Rockhampton, MOTPRDSRV122 at Mackay. The Reveloc server and MOTPRDCLU103 split them across both DCs.
- The Sepura Radio Manager uses IPTPRDSRV123 for directory, IPTPRDSRV224 for time, and 10.89.160.11 for DNS.
- Every captured host takes updates from IPTPRDCCM202, sends SCOM monitoring to 10.89.165.73, and holds a machine certificate from the enterprise IT CA. The Jump Hosts also send Splunk logs to 10.89.165.176 and 10.89.165.177.
- ROTPRDPDM101 backs up the SQL nodes, and 10.45.229.194 the Reveloc server. No backup connection was seen for the Jump Hosts, the TETRA log server or the RevBroadcast server.
- Most of these providers have no zone in zones.csv: IPTPRDCCM202, IPTPRDSRV123, 10.89.165.73, 10.89.165.176/177, ROTPRDPDM101, 10.45.229.194 and 10.89.160.11. Recording them would turn "zone not recorded" into a definite IT or OT dependency.
- The old 3.12 Aspect row repeats the "eleven hosts had established internet connections" statement that step 4 corrected (attempts only, except the Sepura Radio Manager).


### Step 7 done (16/10/2026): frames for 3.4 and 3.5; all sections covered

- **Frames.**
  - `time-synchronisation` (3.4), 5 slots: time source, service and stratum; fallback peer and poll interval; time flows; the hierarchy above the source; whether the application keeps its own time and which records depend on the clocks.
  - `dns` (3.5), 5 slots: resolvers; name resolution flows; which zones must resolve; host names or IP addresses in the application's connections; what fails without IT DNS and whether a fallback has been tested.
- **Labels.** Frame labels were added for the time and DNS attributes. Earlier 3.4 and 3.5 evidence rows written with raw attribute names stay in the matrix; they are accurate and simply worded differently.
- **Hosts file and search suffix.** No capture holds these (14_resolver has server addresses only), so they are asked in the frame (S5) rather than tabled. A hosts-file and suffix capture would be a discovery script improvement.
- **Coverage.** All 17 subsections (3.1 to 3.17) now have a topic table profile and an analysis frame. Every frame builds on the TETRA data with each finding cited by an evidence ID. 74 tests pass.

Summary of the seven steps:

| Step | What it added | Sections |
| --- | --- | --- |
| 1 | product and agent catalogue | 3.9, 3.11, 3.14 |
| 2 | identity inventory, list columns | 3.2, 3.8, 3.16 |
| 3 | platform and patch facts, OS lifecycle list | 3.1, 3.10, 3.15 |
| 4 | network, host firewall, alternate RDP, netstat samples (attempted flows), shared flow filter | 3.6, 3.13, 3.17 |
| 5 | certificates, public-root list | 3.3 |
| 6 | isolation dependency matrix | 3.12 |
| 7 | frames for time and DNS | 3.4, 3.5 |

Corrections the new tables make to the current TETRA document:
- 3.14: CrowdStrike Falcon runs on every captured host.
- 3.8 and 3.16: RDP is on port 56403 on every host.
- 3.13, 3.17 and 3.12: ten hosts only attempted internet connections; only the Sepura Radio Manager connected.
- 3.3: an OT root CA is trusted on the SQL nodes.

Next:
1. Place the tables in the real document and redraft each section with `csa draft`, so the Aspect rows and prose match the new tables and frames.
2. Review zones.csv and add the unrecorded providers (MECM, SCOM, Splunk, backup servers, IPTPRDSRV123, IPTPRDCCM202).
3. Add hosts-file, DNS suffix and security policy (secedit) captures to the discovery script.
