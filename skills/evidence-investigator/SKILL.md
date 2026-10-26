---
name: evidence-investigator
description: Find, extract, classify, and reconcile source evidence for an Operational Technology Current State Assessment. Use for document review and fact verification; do not draft unsupported narrative.
---

# Evidence Investigator

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Build a defensible evidence set before analysis or writing.

## Method

1. Define the precise question and relevant source set.
2. Search headings, tables, diagrams, appendices, metadata, and surrounding text. For Discovery Data, use the discovery index first where the project has one (`csa index rows` / `csa index search`; see `csa-discovery-index/SKILL.md`) and cite the original capture file and line it returns.
3. Record atomic claims in the evidence matrix. Split compound statements when their support differs.
4. Capture source title, document identifier or version, section, page or location, exact supporting excerpt where permitted, and retrieval date when relevant.
5. Classify each claim:
   - `VERIFIED`: directly supported by an authoritative source.
   - `INFERRED`: reasoned from verified facts; record the reasoning.
   - `UNCONFIRMED`: asserted but not adequately supported.
   - `CONFLICTING`: credible sources disagree.
   - `NOT_FOUND`: absent after a proportionate search of the stated source set.
6. Compare duplicate claims across sources and preserve disagreements.

Never upgrade an inference because it is technically plausible. Do not use prior knowledge to complete hostnames, addresses, versions, ownership, topology, control status, or dates. A diagram may establish relationships but not undocumented implementation details. When a diagram's concrete value (address, hostname, port, version, role) disagrees with a live capture, connection log, resolver/DNS or asset/inventory record, the log/inventory value is authoritative and the diagram is out of date: record the log/inventory value as `VERIFIED` and reject the diagram row as superseded (do not carry it as `CONFLICTING`). See the Evidence section of `.agents/csa-core-rules.md`.

## Host-outward method (every captured host gets a full picture)

Questions about a host, its role, its dependencies or who uses it start from the host, not from a keyword. Take one known host and look outwards:

1. **What it is**: the capture's addresses, installed application packages (32B) and non-Windows services (32), plus the role recorded in the host register (`hosts/hosts.csv`) or a client document such as `system_matrix.xlsx`.
2. **What it listens on**: every port and the process that owns it (10_listeners_by_process).
3. **Who connects to it (inbound)**: connections whose local port is one the host listens on (23_process_connection_mapping, then 25_netstat_tcp_samples). The peer is a client of this host.
4. **What it connects to (outbound)**: every other connection, with the local process. When the peer is itself captured, name the service it runs on that port.
5. **Name every peer from captured resolution only**: the host register, 12_ip_interface_config, 48A, 41 and 03_time_status. An address without a captured name stays an address and becomes an open question (resolve it); never guess it.
6. **Follow the edges**: each named peer that has its own capture is profiled the same way, so links are seen from both ends. A peer without a capture is listed as a discovery request.

The script does steps 1-6 and records the results:

```text
H=.agents/skills/evidence-investigator/scripts/host_profile.py
python3 "$H" --workspace <project_root> list                    # captured hosts
python3 "$H" --workspace <project_root> profile <HOST>          # writes csa-work/hosts/cards/<HOST>.md
python3 "$H" --workspace <project_root> record <HOST> --agent csa-evidence-investigator-agent [--dry-run]
python3 "$H" --workspace <project_root> record --all --agent csa-evidence-investigator-agent
```

`record` appends one VERIFIED matrix row per role fact and per peer link, each quoting the exact capture line (source-checked), then adds the host and peer nodes and one graph edge per link (`data-flow`, or `remote-access` for RDP/WinRM/SSH) carrying that row's E-id. Re-running skips duplicates, and the graph sync runs afterwards (pruning removed evidence, rebuilding the host index); new captures are picked up automatically on the next matrix append. Read the host card before writing about a host; it also lists the capture files that are missing and the addresses still to resolve.

Peers seen only by address are kept in `csa-work/hosts/addresses.csv` (built with the host register; the graph sync rebuilds it): address, private or public, which captured hosts talk to it, direction, ports, processes and E-ids. `csa hosts show <address>` lists its evidence and `csa hosts unresolved` is the name-lookup request list, ranked by how many hosts use each address. When a later capture or lookup names an address, it moves to the host register and the graph node is relabelled on the next sync.

Limits to state, never paper over: connection samples cover a short window, so periodic or batch peers may be absent; a missing capture file means "not captured", not "not present"; an inbound connection proves the peer used the service at capture time, not why.

## Search stopping rule

Stop when the named sources have been searched in the locations likely to contain the answer and further passes would repeat the same search. Record `NOT_FOUND` with the searched scope. Escalate only material gaps.

## Output

Use [EVIDENCE_MATRIX_TEMPLATE.csv](references/EVIDENCE_MATRIX_TEMPLATE.csv). Give every row a stable evidence ID so writers can cite it and reviewers can trace it.
