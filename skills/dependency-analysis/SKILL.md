---
name: dependency-analysis
description: Map upstream, downstream, shared-service, data, vendor, and operational dependencies for an Operational Technology application Current State Assessment.
---

# Dependency Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Build a dependency register containing the assessed component, dependency, direction, purpose, data exchanged, interface or mechanism, site/environment, availability effect, owner, evidence ID, and confidence.

Consider:

- source and destination applications;
- databases, file transfers, message brokers, Application Programming Interfaces (APIs), and manual exchanges;
- identity, Domain Name System (DNS), time, Public Key Infrastructure (PKI), virtualisation, storage, backup, monitoring, and endpoint management;
- field, telemetry, historian, reporting, and enterprise-system relationships;
- vendor services, licensing, remote support, and people/process dependencies.

Distinguish a technical connection from an operational dependency. State whether the consequence of failure is evidenced or inferred. Do not assume interface direction from a diagram arrow without checking its legend or supporting text.

Return the dependency register, critical dependency chains, contradictions, and gaps.

## Recording dependencies in the graph store

Every row you add to the dependency register that has a clear source and destination component should also become a node/edge pair in this project's graph store -- this is what lets a later diagram agent draw the dependency topology without re-reading the register. Skip a row only when it's genuinely not a component-to-component relationship (e.g. a purely people/process dependency such as "vendor provides 4-hour support SLA" has no second node to connect to).

Rules:

- Cite the same `evidence_id` you recorded in the register's evidence-ID column -- the graph store rejects any row citing an `evidence_id` not present in this project's `evidence-matrix.csv`.
- Append both endpoint nodes (source and destination component) before the edge between them; an edge whose `source_node_id`/`target_node_id` doesn't exist yet is rejected. If a node for that component already exists from an earlier append in this run, reuse its `node_id` rather than creating a duplicate.
- Use `relationship_type: dependency` for a normal upstream/downstream dependency; use `data-flow`, `trust`, `remote-access`, `hosting`, or `replication` when the register's "interface or mechanism" column makes one of those a better fit than the generic `dependency`.
- Use the CSA domain/section name you were given (e.g. `SECTION`) as `domain` on every row.
- State direction the same way you state it in the register (source -> destination) -- do not let the edge imply a direction the evidence doesn't support (see this skill's rule on not assuming interface direction from a diagram arrow).

```text
G="/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-evidence-matrix/scripts/graph_store.py"
```

Append the two endpoint nodes if they don't already exist this run (`--workspace` is this project's `project_root`, the parent of `WORK_DIR`):

```text
python3 "$G" --workspace <project_root> append-node --agent dependency-analysis --context "<SECTION>" --row-json '[
  {"domain": "<SECTION>", "label": "IAMPS SQL Processor", "node_type": "service", "evidence_ids": "E-010", "confidence": "high"},
  {"domain": "<SECTION>", "label": "Historian DB", "node_type": "host", "evidence_ids": "E-011", "confidence": "high"}
]'
```

Then the edge, using the returned `node_id`s:

```text
python3 "$G" --workspace <project_root> append-edge --agent dependency-analysis --context "<SECTION>" --row-json '{
  "domain": "<SECTION>",
  "source_node_id": "N-003",
  "target_node_id": "N-004",
  "relationship_type": "dependency",
  "evidence_ids": "E-012",
  "confidence": "medium"
}'
```

If a row is rejected, fix it and retry -- do not work around the validator, and do not fall back to describing the dependency in prose only. Note in your output which nodes/edges you appended (their IDs), the same way you'd note an evidence ID.
