# Validation sample (after)

## 6 Migration Discovery

The UTC/DTC application runs on Central Engine, Message Redirector, Telemetry Processor and TCSI server pairs, SIGMAP servers, maintenance consoles, and UTC and DTC operator workstations at the Rockhampton and Mackay sites. Discovery captures exist for 42 of these hosts (45 captures taken between March and May 2026); the v0.4 asset list records 108 entries. The outputs collected differ between capture dates, so each finding below applies only to the hosts whose captures include the relevant output.

### 6.1 Application Hosts and Discovery Scope

| Hosts | Count | Used for |
| --- | --- | --- |
| Hosts captured in May 2026 (software, update, share and scheduled-task outputs) | 11 hosts | Sections 6.2, 6.4 and 6.6; not all 42 captured hosts or the asset list |

### 6.2 Installed Applications

The 11 hosts captured in May 2026 run the application components, management and security agents, drivers and tools listed below: six UTC/DTC hosts (CONTROLLER36, MKY-DTC-CWS15, MKYMRLEFT, MKYTCSILEFT, MKYTELEFT and ROKCERIGHT) and five SIGMAP hosts (MKYSIGMAPA4, MKYSIGMAPW5, ROKSIGMAPA1, ROKSIGMAPB2 and ROKSIGMAPW1). The software on the other 31 captured hosts, and on hosts in the asset list without captures, has not been established. The UTC/DTC application modules were identified from their running processes, not from the installed-programs list.

### 6.3 Failover and Replication Behaviour

The TCSI, Message Redirector, Telemetry Processor and Central Engine roles each run as a Left/Right pair at Rockhampton and at Mackay, as recorded in the asset list. Redundancy is provided by the TCS application: no Windows Failover Clustering service was found in the captured system outputs.

### 6.5 Group Policy Observations

Group Policy results were captured on the 12 hosts below. They are grouped by host type for readability; each group shows what applies to the listed hosts, not to every host of that type.

Each setting needs an OT 3.5 equivalent, or a decision to retire it, before cutover. Whether these policies apply to every host in the asset list has not been confirmed.

### 6.6 File Transfer and Local Storage

On the hosts whose captures include share and mapped-drive outputs, only the default administrative shares (ADMIN$, C$ and IPC$) are present and no mapped drive was recorded. Those outputs were not collected on all 42 captured hosts, so this does not establish that the other hosts have no further shares or mapped drives.

Every host captured in May 2026 runs the TCS Backup Script scheduled task. The task runs TCSBackup.ps1 from the INTERNAL domain file share \\internal.qr.com.au\OT\UTC_LOG under the INTERNAL account A_R852750. It moves local error folders and copies the previous day's MA, OIA, CE and DTC replay logs to TCS_LOGS on the same share, as set out in rules.csv. This log copy therefore depends on a file share in the INTERNAL domain namespace and an INTERNAL domain account.

## 5 DNS

The application hosts resolve names through the INTERNAL Active Directory domain (internal.qr.com.au), which uses Active Directory-integrated DNS.

All [count to be confirmed] UTC/DTC hosts examined use the same two DNS servers, configured on their OT-facing network interface (Ethernet 3). Both are INTERNAL domain controllers, one at each site: ROTPRDSRV122 at Rockhampton and MOTPRDSRV122 at Mackay.

On CONTROLLER36, DNS servers are configured on Ethernet 3 only; no other interface has a DNS server.

The INTERNAL domain name resolves to 11 addresses. Two are the Rockhampton and Mackay domain controllers (10.40.228.97 and 10.45.228.97), eight are in the IT data centre range 10.89.x.x, and one (10.192.15.212) is in a range not yet classified. Resolution tests were run from MKYTCSILEFT only.

Most of the domain's DNS records point to the IT side, so the domain spans IT and OT. Where its forest root sits has not been confirmed.

Name resolution is a drawbridge-critical dependency. The v0.4 assessment assumes Active Directory, DNS and NTP stay available on the OT side of the drawbridge, and records that this still needs validation.

### Services That Depend on Name Resolution
