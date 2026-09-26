# Validation sample (before)

## 6 Migration Discovery

This section consolidates migration-relevant discovery while keeping the declared asset inventory separate from the evidence actually collected. The supplied v0.4 assessment records 108 unique asset entries in its Asset List and 45 Section 3 discovery rows covering 42 unique hosts. The discovery set is a sample of the estate, and the available output categories vary between capture dates; findings below therefore remain limited to the stated evidence population.

### 6.1 Estate and Discovery Coverage

| Population | Verified coverage | How it is used in Section 6 |
| --- | --- | --- |
| May 2026 application and update sample | 11 named hosts | Source for the detailed installed-software, update, share and scheduled-task observations in Sections 6.2, 6.4 and 6.6; not the full discovery set or estate. |

### 6.2 Installed Applications

The table below records software and processes found in the May 2026 application sample: six UTC/DTC hosts (CONTROLLER36, MKY-DTC-CWS15, MKYMRLEFT, MKYTCSILEFT, MKYTELEFT and ROKCERIGHT) and five SIGMAP hosts (MKYSIGMAPA4, MKYSIGMAPW5, ROKSIGMAPA1, ROKSIGMAPB2 and ROKSIGMAPW1). It is not a software inventory for all 42 discovered hosts or the 108-entry Asset List. UTC/DTC application modules were identified from running processes rather than the installed-programs list.

### 6.3 Failover and Replication Behaviour

- The Asset List declares Left/Right pairs at Rockhampton and Mackay for TCSI, Message Redirector, Telemetry Processor and Central Engine roles. No Windows Failover Clustering service was found in the reviewed systems-script outputs; the observed redundancy is handled by the TCS application.

### 6.5 Group Policy Observations

The applied-GPO evidence covers the 12 named hosts below. Results are grouped for readability, but a group label means 'observed in the sample hosts listed', not verified across every asset in that class.

Each observed setting requires an OT 3.5 equivalent or an explicit decision to retire it before cutover; full-estate applicability must be confirmed.

### 6.6 File Transfer and Local Storage

- Where the discovery package included local-share and mapped-drive outputs, only the default ADMIN$, C$ and IPC$ shares were observed and no mapped drive was recorded. The script set was not uniform across all 42 discovered hosts, so this is not a full-estate absence claim.
- The TCS Backup Script scheduled task was confirmed on every host in the May application/update sample. It runs TCSBackup.ps1 from \\internal.qr.com.au\OT\UTC_LOG under INTERNAL\A_R852750 and uses rules.csv to move local error folders and copy the previous day's MA, OIA, CE and DTC replay logs to TCS_LOGS on that share.

## 5 DNS

DNS resolvers use the INTERNAL Active Directory domain (`internal.qr.com.au`) for name resolution. Active Directory-Integrated DNS is in use. [E-009]

All 39 sampled UTC/DTC hosts use the identical pair of DNS resolvers, configured on interface Ethernet 3 (the OT-facing NIC):

The raw `Get-DnsClient` output from CONTROLLER36 confirms that DNS servers are configured only on Ethernet 3, with no DNS servers on any other interface: [E-033]

The discovery scripts on MKYTCSILEFT included explicit DNS resolution tests. [E-035]

**Observation:** 8 of 11 A records for the AD domain point to the IT/Data Centre range (10.89.x.x). Only 2 records point to the OT-side DNS servers. This confirms that the AD domain is co-hosted across IT and OT, and that DNS resolution for the domain returns IT-side records. The AD forest root has not been confirmed and may reside on the IT side. [E-035]

DNS is explicitly identified as a drawbridge-critical dependency in the assessment:

### DNS-Adjacent Service Dependencies
