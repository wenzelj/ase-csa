---
name: ot-architecture-analysis
description: Explain and assess the evidenced current architecture of an Operational Technology application across components, sites, trust boundaries, and OT zones. Use for current-state architecture, not future-state design.
---

# OT Architecture Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Create a current-state architecture view from verified components and relationships.

Identify:

- application tiers and deployment boundaries;
- sites and hosting locations;
- Operational Technology (OT), Information Technology (IT), demilitarized zone, and other evidenced network boundaries;
- operator, engineering, vendor, and administrative access paths;
- data acquisition, processing, storage, reporting, and control relationships;
- shared infrastructure and cross-boundary dependencies;
- architectural constraints, unclear boundaries, and evidenced single points of dependency.

Label every inferred relationship. Do not place a component in an OT zone because its function sounds industrial. Do not claim segmentation, trust, or isolation without network or security evidence.

Prefer a small component/dependency table plus a diagram when topology is materially clearer visually. Attach evidence IDs to nodes or relationships. Keep observations separate from recommendations.

## Recording components and relationships in the graph store

When this analysis identifies a component (host, zone, firewall, IdP, collector, ...) or a relationship between two components (a conduit, a trust path, a data flow, a remote-access path, ...), record it in this project's graph store as well as in your component/dependency table -- this is what lets a later diagram agent draw the topology without re-reading your prose. This is additive, not optional: every component/dependency table you produce should have a matching set of graph rows.

Rules:

- Cite the same `evidence_id`(s) you are already citing in your table -- the graph store rejects any row that cites an `evidence_id` not present in this project's `evidence-matrix.csv`, so do not invent one.
- Append every node before the edges that reference it; an edge whose `source_node_id`/`target_node_id` doesn't exist yet is rejected.
- Use the CSA domain/section name you were given (e.g. `SECTION`) as `domain` on every row, so a later reader can filter to just this analysis.
- `node_type` and `relationship_type` must be one of the tool's known values (it lists them in its error message if you get one wrong); pass `--allow-new-type` only if none genuinely fits.
- `purdue_level` is one of `0`, `1`, `2`, `3`, `3.5`, `4`, `5`, `n/a` -- leave it `n/a` for anything not meaningfully placed on the Purdue model (e.g. most identity/dependency nodes).
- Do not guess a relationship's direction or a node's zone from how a diagram in a source document happens to be drawn -- the same evidence discipline as the rest of this skill applies here too.

```text
G=".agents/skills/csa-evidence-matrix/scripts/graph_store.py"
```

Append a node (repeat per component; `--workspace` is this project's `project_root`, the parent of `WORK_DIR`):

```text
python3 "$G" --workspace <project_root> append-node --agent ot-architecture-analysis --context "<SECTION>" --row-json '{
  "domain": "<SECTION>",
  "label": "ROKPRDAMP101",
  "node_type": "host",
  "purdue_level": "2",
  "zone": "OT",
  "evidence_ids": "E-002",
  "confidence": "high"
}'
```

Then append the edge, using the `node_id`s the tool just returned:

```text
python3 "$G" --workspace <project_root> append-edge --agent ot-architecture-analysis --context "<SECTION>" --row-json '{
  "domain": "<SECTION>",
  "source_node_id": "N-001",
  "target_node_id": "N-002",
  "relationship_type": "conduit",
  "evidence_ids": "E-003",
  "confidence": "high"
}'
```

If a row is rejected, fix it and retry -- do not work around the validator, and do not fall back to describing the relationship in prose only. Note in your output which nodes/edges you appended (their IDs), the same way you'd note an evidence ID.
