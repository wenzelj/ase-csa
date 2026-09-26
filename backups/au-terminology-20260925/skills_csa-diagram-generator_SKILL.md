---
name: csa-diagram-generator
description: Turns an application's graph-store rows (csa-work/graph/nodes.csv + edges.csv) into a rendering-ready diagram model, for one CSA domain at a time, applying the Part 1b routing table and its evidence thresholds. Use whenever the diagram agent needs to decide whether a domain gets a figure and, if so, build the model framework/csa_docx/diagrams.py renders.
---

# CSA Diagram Generator (graph rows -> diagram model)

This skill is the middle stage of the diagram pipeline:

```text
graph_store.py append  -->  <work_dir>/graph/nodes.csv + edges.csv
        |
        v   (this skill)
build_diagram_model.py build  -->  <work_dir>/diagrams/<domain-slug>.yaml
        |
        v
framework/csa_docx/diagrams.py  -->  <work_dir>/diagrams/<domain-slug>.png + .svg + .gv
```

It does no evidence interpretation of its own. It reads rows a technical-analyst skill already appended to the graph store (via `graph_store.py`, each row already citing real `evidence_id`s), counts and filters them against a fixed routing table, and writes a model file in exactly the schema `diagrams.py` expects -- nothing more.

## Required input

- `PROJECT` -- the project key from `csa-context/PROJECTS.yaml` (`iamps`, `utcdtc`). **Always required, never inferred** from the current directory or file contents -- this is Part 1a's application-isolation rule enforced the same way `graph_store.py` enforces it: the script looks up `PROJECT` directly in the registry and derives every path (`work_dir`, `graph/nodes.csv`, `graph/edges.csv`, `diagrams/`) from that one block. An unregistered key is refused outright (`UNKNOWN_PROJECT`), so there is no path by which this script can read or write a different application's data.
- `DOMAIN` -- the exact domain string as it appears in the graph store's `domain` column for that application (e.g. `"3.6 Network / Segmentation"`), or the domain's routing-table name. Matched against the [Part 1b table](../../../claude/csa-diagram-agent-plan.md) by leading section number (`"3.6"`) first, then by exact domain name.

## Script

```text
S="/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-diagram-generator/scripts/build_diagram_model.py"
python3 "$S" list-domains --project iamps
python3 "$S" build --project iamps --domain "3.6 Network / Segmentation" [--dry-run]
```

`list-domains` prints the full routing table for that project (section, domain name, diagram type) -- use it to see what's routed before running `build`.

`build` does, in order:

1. Resolves `PROJECT` via `PROJECTS.yaml`; refuses if unregistered.
2. Looks up `DOMAIN` in the routing table. `diagram_type: None` (most "tabular" domains -- inventories, registers) -> `SKIPPED`, nothing written, exit 0.
3. Reads that project's `graph/nodes.csv` + `graph/edges.csv`, filters to `(project, domain)` rows.
4. Evaluates that domain's threshold (see below). Not met -> `SKIPPED`, nothing written, exit 0. **This is the normal, safe outcome for every domain that has no graph rows yet, or not enough** -- "no data" and "not enough data" resolve to the same outcome on purpose.
5. Met -> writes `<work_dir>/diagrams/<domain-slug>.yaml` (or prints it without writing, with `--dry-run`) with `project`, `domain`, `diagram_type`, `title`, `nodes[]`, `edges[]` -- the exact fields `diagrams.py` validates and renders.

Every result is JSON on stdout. `status` is one of `BUILT`, `DRY_RUN`, `SKIPPED`, or `ERROR` (exit code 2 for `ERROR`).

## The routing table and its thresholds

The full table lives in the plan doc's Part 1b and is duplicated as data inside `build_diagram_model.py` (`ROUTING`) -- the two must be kept in sync if either changes. Where Part 1b's prose threshold names a concrete `node_type` or `relationship_type` that already exists in `graph_store.py`'s enums (`ntp_source`, `dns_server`, `collector`, `backup_target`, `vendor_path`, `firewall`; `conduit`, `data-flow`, `remote-access`, `hosting`, `replication`), the script checks that field directly -- e.g. domain 3.6's threshold (`>=2 distinct Purdue levels with >=1 conduit edge`) is checked exactly as written.

**Where the prose doesn't map to an existing enum value** (`"identity-related"` nodes, an `"isolation-boundary"` edge, and a few others), the script falls back to a generic node/edge count for that domain and marks the result `"generic_fallback_threshold": true`. This is a known simplification, not a silent guess dressed up as precision -- **a human should re-check any domain that reports `generic_fallback_threshold: true` once real graph data exists for it**, the same way the real 3.6 rows themselves were flagged for review in Part 5 Step 2. Domains currently on the generic fallback: 3.2, 3.5, 3.11, 3.12, 3.16.

## Executive Summary (2.1) is special

2.1 doesn't read graph rows directly -- it waits until at least one other domain already has a diagram file under `<work_dir>/diagrams/*.yaml`, then aggregates every non-executive model it finds there (deduplicating nodes/edges by id) into one `executive_overview` model. If no domain diagram exists yet, it's `SKIPPED` with that reason. **Aggregating already-drawn domain diagrams into one overview is a judgment call about what belongs in an executive figure, not a mechanical count** -- review the result before trusting it, same as any other diagram.

## Tested (23 Sep 2026)

Against the real IAMPS registry and real IAMPS domain-3.6 graph rows (device-bridge sandbox, registry temporarily repointed to the sandbox mount and restored byte-for-byte afterward -- see the plan doc's environment note):

- `list-domains --project iamps` -- printed the full 18-row table.
- `build --project iamps --domain "3.6 Network / Segmentation" --dry-run` -- correctly found the real 4 nodes / 3 edges, 3 distinct Purdue levels, 3 conduit edges, threshold met, model preview correct, nothing written.
- `build --project iamps --domain "3.2 Identity & Authentication"` -- correctly `SKIPPED` (0 graph rows for that domain yet).
- `build --project iamps --domain "3.1 General / Asset Inventory"` -- correctly `SKIPPED` (routing table: `None`).
- `build --project iamps --domain "2.1 Executive Summary"` -- correctly `SKIPPED` (no domain diagram existed yet at that point).
- `build --project iamps --domain "9.9 Not A Real Domain"` -- correctly `ERROR: UNKNOWN_DOMAIN`, exit 2.
- `list-domains --project bogus` -- correctly `ERROR: UNKNOWN_PROJECT`, exit 2.
- **Real, non-dry-run build**: `build --project iamps --domain "3.6 Network / Segmentation"` wrote the real `IAMPS/06 IAMPS/csa-work/diagrams/3-6-network-segmentation.yaml`.
- **End-to-end handoff proof**: fed that real model file straight into `framework/csa_docx/diagrams.py` and rendered it -- the resulting `.gv` was structurally identical to the one built from a hand-typed model in Part 5 Step 3 (only the free-text title string differed), confirming the schema contract between this skill and the renderer holds for real, not just hand-built, data.

`python3 -m py_compile` clean.
