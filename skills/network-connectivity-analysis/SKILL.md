---
name: network-connectivity-analysis
description: Analyse evidenced network zones, endpoints, flows, ports, protocols, routing, firewall paths, name resolution, and remote connectivity for an Operational Technology Current State Assessment.
---

# Network and Connectivity Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Build a flow matrix with source, destination, direction, purpose, protocol, port, zone, security device or rule reference, environment, owner, status, and evidence ID.

Check for:

- site-to-site and cross-zone communication;
- client-to-application, application-to-database, interface, management, backup, monitoring, and time/name-resolution flows;
- vendor and remote access paths;
- load balancers, proxies, gateways, firewalls, Virtual Local Area Networks (VLANs), routing, and Network Address Translation (NAT);
- unidirectional requirements or control boundaries where evidenced.

Never infer an open port from a product default, or an allowed firewall path from an intended architecture. Distinguish required, documented, observed, and unconfirmed connectivity. Treat Internet Protocol (IP) addresses and hostnames as sensitive project facts and reproduce them only when needed for the authorised deliverable.

Return the connectivity matrix, a plain-language flow description, conflicts, and targeted questions for missing material flows.

## Public IP egress: `scripts/analyze_public_egress.py`

Where a project has network-monitoring export files (Vantage/Nozomi-style: `export_query_*.xlsx`, `export_query_*.csv`, `nozomi_logs*.xlsx` sitting in that project's `default_source_set` folder), use this script rather than re-deriving the public-destination list by hand each time. It does not replace the flow-matrix work above -- it answers one narrower, recurring question: *which public IP addresses is this OT environment talking to, and which ones are new since last time?*

**Required input:** `PROJECT` -- resolved via `csa-context/PROJECTS.yaml`, same isolation rule as `graph_store.py` / `build_diagram_model.py`. Never inferred from cwd.

```text
S=".agents/skills/network-connectivity-analysis/scripts/analyze_public_egress.py"
python3 "$S" --project utcdtc --write-evidence-row /tmp/new-egress-row.json
```

What it does, in order:

1. Resolves `PROJECT`; refuses if unregistered.
2. Scans that project's `default_source_set` folder (top level only) for the file patterns above.
3. For each file, extracts public-internet source/destination IPs using `to_zone`/`from_zone == "Internet"` (newer export shape) or `is_to_public`/`is_from_public` (older shape).
4. Diffs the combined set against a running baseline at `<work_dir>/analysis/public-egress-baseline.json`, so a re-run after new export files land only reports genuinely new destinations, not the whole list again.
5. With `--write-evidence-row <path|->`, if new IPs were found, writes an `evidence_matrix.py --rows-file` JSON to that path (or stdout) -- **it never calls `evidence_matrix.py append` itself.** Committing evidence is a separate, deliberate step so a human or agent reviews the row first:
   ```text
   python3 ".agents/skills/csa-evidence-matrix/scripts/evidence_matrix.py" \
     --workspace "<that project's project_root>" append --agent analyze_public_egress --rows-file /tmp/new-egress-row.json
   ```
6. With `--commit-baseline`, updates the baseline file to the current total. Without it, nothing on disk changes except `--write-evidence-row`'s output.

**What it never does:** classify intent (SaaS/telemetry/cert-check vs. inadvertent egress). That is a Network SME judgment call, not something this script or this skill should approximate -- every row it produces carries `gap_or_action` saying so explicitly.

**Projects without matching export files:** the script scans and reports `0` files found; it does not error or force a finding. Don't add file-format assumptions here speculatively for a monitoring tool a project doesn't actually use -- extend the glob patterns and the extraction logic only once a real project's export shape is confirmed to differ.

**Tested (23 Sep 2026)** against real UTC/DTC data: found 449 total public IP destinations across the project's 8 real export files (10 of them new relative to a prior manual pass, recorded as evidence row E-056); baseline seeded to 449 via `--commit-baseline`; a re-run immediately after correctly reported 0 new. `python3 -m py_compile` clean.
