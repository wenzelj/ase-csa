# Topic analysis for 3.7 Storage & Data Transfer: assessment and improvement plan

15/10/2026. Question from Wenzel: can the framework analyse a subsection topic such as Storage & Data Transfer the way an IT/OT analyst would, across hosts, applications and services, in every direction and across zones? How can it be made stronger?

## 1. What 3.7 has to cover

Storage & Data Transfer is about **data stores and data flows**, not about hosts on their own. A flow can start or end at a host, an application or a service. It can run into or out of a host, and it can cross a zone boundary in either direction (OT to IT, IT to OT, OT to the internet or cloud, OT to a vendor). For each flow the CSA has to say:

| Field | Question |
| --- | --- |
| Data | What moves (operational records, recordings, configuration, backups, telemetry, alerts, files) |
| Ends | Which host, application or process sends it, and which host, address or service receives it |
| Zones | Which zone each end is in (OT site, IT, IT-hosted part of the system, internet or cloud, vendor) |
| Direction and initiator | Which way the data goes and which side opens the connection (push from OT, or pull into OT) |
| Mechanism | File or share (SMB), database (SQL, AG replication), message or API (HTTPS, Service Bus, DAMM API), mail, admin tool (WinSCP, FileZilla, TFTP), removable media, backup agent |
| Path and controls | Direct, through a DMZ or proxy, inspected or scanned, encrypted, authenticated |
| Storage | Where the data is held at each end, and for how long |
| Recovery | Whether the held data could rebuild or restore the function after an outage |

The scope map already says almost exactly this for 3.7 (Must explain). The framework does not yet turn it into evidence or into the agent's work.

## 2. How the framework handles 3.7 today

| # | Gap | Effect |
| --- | --- | --- |
| G1 | The draft agent reads only the card and the rules digest. The analysis skills (dependency, network, the technical analyst) are never used in the draft lane. | The agent answers three requirement questions from keyword-matched evidence rows. Nobody analyses the topic first. |
| G2 | There is no data-flow inventory. `host_links.csv` holds only register-to-register links with a verified listener and is empty for TETRA. Process-to-connection captures (`23_process_connection_mapping`) are not structured. The declared flow map (`02_reveloc_expected_flow_map`) is never reconciled with what was observed. | Flows reach the agent only if an evidence row happens to mention them. Direction and initiator are guessed from prose. |
| G3 | Data stores per host are not extracted: SQL instances, availability groups and databases, log-server recording stores, shares, application paths. | "Where operational data lives" depends on old answers. |
| G4 | Transfer tools and removable-media controls are not extracted (`67_installed_software`, Group Policy, `65_local_security_policy`, firewall rules for file ports). | The current 3.7 misses ad hoc transfer tools that are installed on the Jump Hosts (see section 3). |
| G5 | Peers are not classified into zones (OT site, IT, internet or cloud, vendor), apart from host-name sites. | "Between IT and OT" and "push or pull" cannot be decided from data. |
| G6 | The card asks the same generic question for every requirement. The Must explain points are listed but not asked one by one. | Coverage depends on the model remembering the scope text. |
| G7 | Background knowledge (the system reference, vendor documents) is used only as "Look for" lines. It is not used to interpret capture signals such as an `agentService` listener on 7000. | Signals stay "role not recorded" even when the knowledge store could say what to confirm. |
| G8 | Facts carried from earlier answers anchor the agent to old content. Counts are fixed (Facts to keep now asks for a restatement), but the old framing remains. | New angles are not explored. |

The framework is **well equipped on rules and evidence discipline**: evidence IDs, no inference, host-centred, the role register, the knowledge store kept apart. It is **under-equipped on topic analysis**: it has no model of flows, stores and zones, and no step that works through the topic before writing.

## 3. What the TETRA captures already show for 3.7 (not in the current text)

Read from the latest capture per host on 15/10/2026. These still need evidence rows before they go in the CSA.

| Observation | Hosts | Capture |
| --- | --- | --- |
| WinSCP 5.9.5 and PuTTY tools (ExtraPuTTY, SuperPuTTY) installed: ad hoc file transfer capability | both RevViewer Jump Hosts | 67_installed_software |
| FileZilla client, PuTTY 0.83 and **Tftpd64** (a TFTP server) installed as well | ROKPRDOPS110 | 67_installed_software |
| No Group Policy setting restricting removable storage found | captured hosts | 61_gpresult_verbose |
| No mapped network drives | captured hosts | 43_mapped_drives |
| SMB (TCP 445) outbound from the System process | MOTPRDCLU103, ROTPRDCLU103, ROTPRDCLU104, ROKPRDOPS110 | 23_process_connection_mapping |
| Inbound `agentService` on TCP 7000 (from ROTPRDPDM101 per earlier evidence): a pull into the OT hosts by a system outside them, likely the backup platform (to confirm) | SQL Server cluster nodes, Reveloc Application / TGOIP | 23_process_connection_mapping |
| HTTPS (443) outbound from TetSen, tet-main and TetEnfC (Cisco Secure Workload / Tetration agent, not Sepura software) to public addresses | Sepura Radio Manager server | 23_process_connection_mapping |
| HTTPS (443) outbound from RevBroadcast (to Azure, per the flow map) | RevBroadcast Application | 23_process_connection_mapping, 02 flow map |
| Inbound HTTPS to Apache, and an outbound tomcat connection | ROKPRDOPS110 | 23_process_connection_mapping |
| Downstream FCC data pulled from the Reveloc SQL database by IAMPS (a cross-zone pull) | Reveloc SQL | system model (knowledge, needs capture evidence) |

## 4. What the guidance says the analysis should test

- **ACSC with CISA, NSA and partners, *Principles of operational technology cyber security* (Oct 2024).**
  - Principle 3: OT data is extremely valuable and needs to be protected. Keep it apart from corporate and internet environments, and know who accesses it, when and how.
  - Principle 4: segment and segregate OT from all other networks, including the internet, IT and vendors.
  - Aurizon is Australian critical infrastructure, so this is the most relevant baseline.
- **IEC 62443-3-2 zones and conduits.** Every path between zones should be a designed conduit with a stated purpose, a stated protocol set and its own controls. A path nobody designed is a finding. This maps directly to SEP-STOR-02 (a defined, controlled pattern).
- **NIST SP 800-82r3 and the US EPA's OT/IT segmentation guidance.**
  - IT, OT and a DMZ between them.
  - Deny connections from IT into OT unless explicitly allowed.
  - A firewall or jump host at the boundary, monitored and logged.
  - The three-zone point is cited through secondary sources. Check it against NIST before quoting it.
- **Push versus pull.** Pull protocols need a listener on the OT side, so inbound ports have to be opened. Connections that OT opens outbound avoid that. This is the test for SEP-STOR-03. A listener on an OT host that a system outside OT connects to (like `agentService` on 7000) is evidence of a pull.
- **LLMs and data-flow analysis.** A 2024 study found LLM help raised recall of real threats but also raised false positives, and novices accepted the first answer. Lesson: give the model the flow model as structured input, make every claim cite evidence, and check coverage. The framework's evidence rules already do the second part.

## 5. Improvements, in order

1. **Data-flow inventory (framework, no model).**
   - New `csa-work/hosts/flows.csv` with one row per observed or declared flow: source host, role, zone and process; destination host or address and zone; port and protocol; direction; initiator; mechanism class; observed or declared; capture citations.
   - The initiator is worked out from listener and local or remote port.
   - Built from `23_process_connection_mapping`, `20_listening_ports`, `21`/`25` connection samples, the declared flow map and `80_dependency_summary`.
   - Declared flows not observed, and observed flows not declared, are both listed.
   - Shared by 3.6 Network, 3.7, 3.13 Perimeter and 3.17 Internet & SMTP.
2. **Zone model per project.**
   - A small `zones.csv`: zone name, kind (OT site, IT, IT-hosted system part, internet or cloud, vendor), subnets or name patterns.
   - Used to classify every flow end, so "IT to OT" and "push or pull" become facts, not guesses.
   - Seeded from the existing subnet rules in `roles.csv`.
3. **Storage and transfer-control extraction.** Extend `host_settings.py`:
   - data stores (SQL instances, availability groups and databases from `52_reveloc_sql_cluster_evidence` and services; shares from `42_local_shares`; mapped drives);
   - transfer tools from `67_installed_software`;
   - removable-media policy from Group Policy and the local security policy;
   - proxy setting;
   - firewall rules that allow file ports.
4. **Topic analysis frame per section.**
   - A reference file per topic, like the topic-table profiles. It turns Must explain and the guidance tests into explicit sub-questions: data stores, flows by mechanism, cross-zone flows, initiator, controls, removable media, ad hoc tools, retention, recovery.
   - Each sub-question names the inventory slice that answers it.
   - The card shows a filled "analysis frame": what the inventory found for each sub-question, with citations, and the slots that stay empty.
   - The agent must answer every slot or write Unknown. A new check (`FRAME_UNCOVERED`) blocks an answer that skips one.
   - This gives the draft agent topic depth without loading the skills.
5. **Role tables for 3.7.** Two framework-built tables, using the topic-table mechanism:
   - **Data stores** by role group.
   - **Data flows**, grouped by mechanism and role, with cross-zone flows marked.
   - Points that are not per flow (no defined transfer pattern, no removable-media policy) stay in the Aspect table.
6. **Knowledge that interprets signals.** Knowledge passages for common service signatures (backup agents and their ports, DDBoost, vendor telemetry processes). They appear on the card as "what to confirm" next to the observation, never as evidence.
7. **Coverage check after writing.** Every cross-zone flow in `flows.csv` must appear in 3.7 or carry a `Dropped:` reason (`FLOW_NOT_COVERED`, a warning in the draft lane).
8. **Optional analyst pass for complex sections.** Run the technical analyst with the dependency and network skills over `flows.csv` before the draft agent, and put its evidence-cited notes on the card. Use it only where the frame leaves gaps, because it costs another model call.

## 6. Plan

| Story | Size | Notes |
| --- | --- | --- |
| S1 `zones.csv` and zone classifier | small | seed TETRA from `roles.csv` subnets, then IT, IPT, internet |
| S2 `flows.csv` builder | medium | process mapping, listeners, flow map, dependency summary |
| S3 storage and transfer-control extraction | medium | `host_settings.py` attributes plus capture citations |
| S4 analysis frame for 3.7 plus `FRAME_UNCOVERED` | medium | card section and check, reusable for every topic |
| S5 3.7 role tables (stores, flows) | small | reuse `topic_tables.py` |
| S6 knowledge signatures | small | separate knowledge store, never evidence |
| S7 `FLOW_NOT_COVERED` | small | |
| Pilot | | re-answer TETRA 3.7 on a copy, compare with the current text, then 3.6 and 3.17 |

S1 and S2 come first because everything else reads from them. Each story is small enough for the improvement pipeline (one fresh Codex session per story).

## Sources

- ACSC, CISA, NSA and partners, Principles of operational technology cyber security (Oct 2024): https://www.cyber.gov.au/business-government/secure-design/operational-technology-environments/principles-of-operational-technology-cyber-security , summary https://www.darkreading.com/ics-ot-security/nsa-releases-6-principles-ot-cybersecurity , PDF https://media.defense.gov/2024/Oct/01/2003556960/-1/-1/0/PRINCIPLES_OF_OPERATIONAL_TECHNOLOGY_CYBER_SECURITY.PDF
- IEC 62443 zones and conduits explained: https://www.trout.software/blog/iec-62443-zones-and-conduits-explained
- NIST SP 800-82r3: https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf , secondary summary https://industrialmonitordirect.com/blogs/knowledgebase/it-ot-convergence-reference-network-architecture-and-security
- US EPA, Segment OT and IT: https://www.epa.gov/system/files/documents/2024-07/segment-ot-and-it.pdf
- Moving process data across segmented networks (push versus pull): https://www.automation.com/en-us/articles/may-2023/moving-process-data-across-segmented-networks
- Data flow diagrams and LLMs for security threat validation (2024): https://arxiv.org/html/2408.07537v2

## 7. Implemented (15/10/2026)

| Story | Status | Where |
| --- | --- | --- |
| S1 zones | Done. TETRA seeded and adjusted: OT site subnets, IPT 10.89.162.0/24 as IT, the three enterprise directory and time servers as IT. **All `reviewed=no`: Wenzel to confirm.** | `framework/csa_docx/zones.py`, `csa-work/hosts/zones.csv`, `csa flows zones-seed` / `csa flows zones` |
| S2 flows | Done. TETRA: 138 flows, of which 44 carry data, 25 cross zones and 12 are declared but not seen. Observed flows are written from the side that opens the connection. Declared flows are matched to observed ones. SMB to a domain controller is classed as Group Policy, and Windows' own internet traffic as platform services. | `flows.py`, `csa-work/hosts/flows.csv`, `csa flows build`/`show`, runs inside `csa hosts build` |
| S3 storage and transfer controls | Done: database services and availability groups, shares beyond the defaults, file transfer tools, removable storage policy, proxy. | `host_settings.py` |
| S4 analysis frame and FRAME_UNCOVERED | Done. The 3.7 frame has 9 slots, and its findings become evidence rows (47 for TETRA, all accepted by the source check). The card shows the frame, the agent answers it in a `## F1 Analysis frame` block, and FRAME_UNCOVERED blocks a sheet that skips a slot. | `topic_frames.py`, `references/topic-frames/storage-data-transfer.json`, `answer_sheet.py`, `section_card.py`, `csa-draft-agent.md` |
| S5 3.7 tables | Done. The role table has Database, Shares and Transfer tools, with removable storage and proxy in the shared line. The flows table groups by mechanism and shows which side opens each connection, the zones, and the flow-map status. Both are placed under Discovery Information, above the Aspect table. | `topic_tables.py` (`build_all`, `build_flows`), `references/topic-tables/storage-data-transfer.json` |
| S6 signatures | Done. These are "Likely … Confirm …" notes on the card, never evidence. | `references/signal-signatures.json` |
| S7 FLOW_NOT_COVERED | Done, as a warning. | `answer_sheet.py` |
| S8 analyst pass | Not built (optional, costs a model call). | |

What the TETRA captures now put in front of the agent for 3.7, all citable:

- the whole C: drive shared as `CAcom` on ROKPRDOPS110, plus `CNMS-NG R7 Archive` and a user's Music folder;
- `temp` and `Users` shared on MOTPRDREV101;
- a SQL Server instance (`SEPURA2014`) on the Sepura Radio Manager;
- WinSCP, FileZilla, PuTTY and the Tftpd64 TFTP server on the Jump Hosts;
- no removable storage restriction in applied Group Policy;
- a probable PowerProtect backup pull into the SQL nodes on TCP 7000;
- SMB to two unnamed 10.89.163.x addresses;
- the RevBroadcast Azure flow (declared as RB2 and seen);
- 12 declared flows not seen in the sampled connections, including IAMPS reading the Reveloc SQL database.

Tests: `tests/test_storage_flows.py` (9) and `tests/test_topic_tables.py` (10). The existing note, answer-quality, doc_spec, hostmodel and answer-cache tests still pass.

Next: confirm `zones.csv`, then run `csa draft 3.7` (the agent answers with the frame and the tables are placed). Reuse the flow inventory for frames for 3.6 Network, 3.13 Perimeter and 3.17 Internet & SMTP.
