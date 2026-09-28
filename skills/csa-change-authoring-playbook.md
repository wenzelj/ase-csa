# Change-authoring playbook

Current rules distilled from .agents/docs/archive/csa-change-authoring-learnings-2026-09.md. Read this at the start of every authoring run. The archive is history; do not read it unless a rule here points to it.

## Evidence-to-topic mappings

Numbered discovery files, as named in the full (80+ file) captures. Query the discovery index first (`csa index rows|search`); these names tell you which table or file answers which topic.

| Topic | Discovery files or index tables that answer it | Caveat |
| --- | --- | --- |
| OS, host role, domain membership | `00_host_summary.txt`; `52_auth_configs.txt` (`Domain` / `PartOfDomain`) | Older lightweight captures hold only the second. |
| DNS resolvers and resolution | `14_resolver.txt`, `41_dns_query_tests.txt` | Resolver order is per interface; check every adapter. |
| Time source and peers | `03_time_status.txt` (`Source:` line, `Peer:` blocks), `32_services_inventory` (W32Time) | The Windows Time client listens on UDP 123 even in client mode. |
| Listening services | `20_listening_ports.txt` with `10_listeners_by_process.txt` (PID to process) | A listener says nothing about outbound use. |
| Outbound connections and dependencies | `23_process_connection_mapping.txt`, `22_top_remote_endpoints.txt`, `21_established_connections_raw.txt`, `25_netstat_tcp_samples.txt` | Short-lived connections (for example SQL) appear only in the netstat samples. |
| Reachability of AD, DNS, messaging, email, integrations | `57_connectivity_tests.txt`, application integration validation files | Tests show reachability at capture time, not configuration. |
| Agents and management tools (EDR, SIEM forwarder, MECM, monitoring) | `24_tasklist_services.txt`, `32_services_inventory`, `67_installed_software`, `72_sccm_mecm_check.txt` | Installed is not the same as running; check the service state. |
| Host firewall and policy | `31_firewall_profiles.txt`, `33_firewall_rules`, `59_gpresult_computer.txt`, `65_local_security_policy_export.txt` | Applied and filtered Group Policy Objects are listed separately in gpresult. |
| Local accounts and administrators | local users and local administrators files (full captures only) | Absent from lightweight captures; never read their absence as "none". |
| Patching and update source | update settings in gpresult and the registry export, installed-updates list | The update source shows the mechanism; currency needs the update dates against the capture date. |
| Backup | installed software, services, scheduled tasks | Separate third-party backup agents from default Windows and hypervisor components (VSS, snapshot providers). |
| Certificates | `68_certificates_localmachine_my` | Report expiry against the capture date. |
| Network-level traffic and public egress | network monitoring exports (for example Nozomi or Vantage) | A different evidence population from host captures. |

## Scoping claims across hosts and captures

- Before accepting or editing "X is present / configured on the hosts", list which captures actually contain the file that could show X. Capture depth differs sharply between discovery runs.
- Keep evidence populations apart: hosts in the asset list, hosts with full captures, hosts with lightweight captures, and network-level exports. Never collapse them into one fleet-wide claim.
- Where a claim holds for some hosts and cannot be established for others, write "confirmed on the full captures; not established for the others" rather than a blanket statement.
- A missing file is not an absence. Record the scope searched.
- Before accepting an "evidence gap" note, search the whole Discovery Data folder (or the index) for the host name. If it appears, the gap note is stale and the edit removes it.
- Split a "no evidence of a local X service" claim into two parts: the conclusion (is the system independent of X?) and the evidence cell (is the service present?). Usually the service is present in client mode and the conclusion stands; correct the evidence cell and keep the conclusion.
- For identity claims, separate "is X the primary mechanism?" from the evidence basis the row cites. Fix a wrong evidence basis without overturning a correct conclusion.
- Check a listening claim against the listener files and a client or outbound claim against the connection files. Edit only the claim that is not supported.
- When a technology is a family (OPC, SQL Server, binary database protocols), state the design name and the observed port. Do not collapse a family into one well-known port; raise alternate ports as open questions.
- For "centrally managed X" claims, anchor the claim with the mechanism (the management endpoint and the policy that disables the local path) and the measured currency (dated, per host).
- A section whose claims are already accurate is authored-and-clean. Record why under "Items intentionally left unchanged" and carry shared scope questions in the section that holds the edit.

## Anchoring and stable IDs

- Resolve every anchor with `lookupStableId`. When the target paragraph's text is not unique (identical short bullets), anchor an Insert before or after on a unique neighbour and say why in `Why`. Never pick one of several matches.
- If the csa-mcp tools are not available, import `csa_docx.tools` and call `prepareDocument` and `lookupStableId` directly with the project root as `workspace`. Say so in the run-state file.
- If `prepareDocument()` fails because more than one working DOCX exists, do not delete anything. Ask Wenzel to move the non-working copies into a `z_Archive/` folder, then run it again.

## Section numbering

- The framework's `Section<N>` counts every Heading 1, including empty or hidden ones, so it can differ from the document's own numbering. Resolve the section from the manifest (`@H<N>`), state both numbers in the change-file header, and use `--heading "<title>"` rather than `--section` for the lints.
- Count the Heading 1 order again on every run. Do not reuse a count from an earlier run.
- A front-matter table that summarises the document's own sections (a document map) is a checkable claim. Check its titles, numbers and counts against the current structure.

## Change-file structure

- When adding edits to a change file that already has a `## Changes Report`, add them at the end of `## Proposed changes` and rewrite `## Expected result if approved` for the full set. Never splice text into the middle of an existing paragraph.
- An applied edit can itself over-correct. Compare the applied result with the live document, and draft the correction as a new edit that says it partly reverses the earlier one.
- The same wrong string in several sections is corrected in each section's own change file, one edit per file. Name the other sections under Open questions so one human confirmation covers all of them; do not cross-reference edit IDs between files.
- Run `csa check-change <N>` before finishing and fix every ERROR.

## Other

- An analysis file in `WORK_DIR/analysis/` is a good topic map, but check every claim against its cited evidence-matrix row before relying on it. Analyses sometimes overreach.
- Editorial passes: read `.agents/references/authoring-editorial-mode.md`. The pilot lessons are in its "Lessons from the first pilot" section.
