#!/usr/bin/env python3
"""
build_diagram_model.py -- csa-diagram-generator's script.

Given PROJECT and DOMAIN, resolves that application's work_dir via
csa-context/PROJECTS.yaml (mirrors evidence_matrix.py / graph_store.py's
cross-project guard exactly -- same registry parser, same hard failure with
no override flag if the workspace isn't a registered project), reads ONLY
that project's <work_dir>/graph/nodes.csv + edges.csv, looks up the domain
in the Part 1b routing table (hard-coded below, IAMPS-shaped), applies the
domain's evidence threshold, and -- only if the threshold is met -- writes
a model file at <work_dir>/diagrams/<domain-slug>.yaml in the exact schema
framework/csa_docx/diagrams.py expects:

    {
      "project": "...", "domain": "...", "diagram_type": "purdue" | "dependency" | "executive_overview",
      "title": "...",
      "nodes": [{"node_id", "label", "node_type", "purdue_level", "zone", "evidence_ids"}, ...],
      "edges": [{"edge_id", "source_node_id", "target_node_id", "relationship_type", "evidence_ids"}, ...]
    }

This script does NO evidence interpretation of its own. It only counts and
filters rows that a technical-analyst skill already appended to the graph
store (via graph_store.py), citing evidence_ids that already exist in the
evidence matrix. If a domain has no graph rows, or not enough to clear its
threshold, the safe and correct outcome is the same either way: SKIPPED,
nothing written. This script never invents a node, an edge, or a diagram.

The Part 1b thresholds are written in prose ("≥3 identity-related nodes
with ≥2 edges between them"). Where the prose names a concrete node_type or
relationship_type that graph_store.py's enums already carry (ntp_source,
dns_server, collector, backup_target, vendor_path, firewall; conduit,
data-flow, remote-access, hosting, replication), this script checks that
field directly. Where it doesn't (e.g. "identity-related", "isolation-
boundary edge"), this script falls back to a generic node/edge count for
that domain and flags the approximation in its own docstring below, next
to that domain's entry in ROUTING -- a human should re-check any generic
fallback threshold once real data exists for that domain, the same way the
Part 5 Step 2 graph rows for 3.6 were flagged for review.

Commands:
    python3 build_diagram_model.py build --project iamps --domain "3.6 Network / Segmentation"
    python3 build_diagram_model.py build --project iamps --domain "3.6 Network / Segmentation" --dry-run
    python3 build_diagram_model.py list-domains --project iamps
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML -- already a dependency of diagrams.py
except ImportError:
    yaml = None

NODE_COLUMNS = ["node_id", "project", "domain", "label", "node_type",
                "purdue_level", "zone", "evidence_ids", "confidence", "review_state"]
EDGE_COLUMNS = ["edge_id", "project", "domain", "source_node_id", "target_node_id",
                "relationship_type", "evidence_ids", "confidence", "review_state"]

# ---------------------------------------------------------------------------
# Part 1b routing table (IAMPS-shaped; UTC and DTC need their own pass --
# see the plan doc). "generic_fallback": true marks a threshold that could
# not be expressed exactly in terms of graph_store.py's enums and is
# approximated by a plain node/edge count -- flagged for human re-check.
# ---------------------------------------------------------------------------
ROUTING = {
    "2.1": {
        "domain_name": "Executive Summary",
        "diagram_type": "executive_overview",
        "spec": {"kind": "executive_summary"},
    },
    "3.1": {"domain_name": "General / Asset Inventory", "diagram_type": None, "spec": None},
    "3.2": {
        "domain_name": "Identity & Authentication",
        "diagram_type": "dependency",
        "spec": {"kind": "generic", "min_nodes": 3, "min_edges": 2, "generic_fallback": True},
    },
    "3.3": {"domain_name": "PKI / Certificates", "diagram_type": None, "spec": None},
    "3.4": {
        "domain_name": "Time Synchronisation",
        "diagram_type": "dependency",
        "spec": {"kind": "fanout", "source_node_type": "ntp_source", "min_sources": 2, "min_edges": 2},
    },
    "3.5": {
        "domain_name": "DNS",
        "diagram_type": "dependency",
        "spec": {"kind": "node_type_and_edge_type", "node_type": "dns_server", "min_nodes": 2,
                 "relationship_types": ["replication", "trust"], "min_edges": 1,
                 "generic_fallback": True},
    },
    "3.6": {
        "domain_name": "Network / Segmentation",
        "diagram_type": "purdue",
        "spec": {"kind": "purdue_levels", "min_distinct_levels": 2,
                 "relationship_types": ["conduit"], "min_edges": 1},
    },
    "3.7": {
        "domain_name": "Storage & Data Transfer",
        "diagram_type": "dependency",
        "spec": {"kind": "generic_with_edge_type", "min_nodes": 3,
                 "relationship_types": ["data-flow"], "min_edges": 1},
    },
    "3.8": {
        "domain_name": "Management & Administrative Access",
        "diagram_type": "dependency",
        "spec": {"kind": "edge_type_only", "relationship_types": ["remote-access"], "min_edges": 1},
    },
    "3.9": {
        "domain_name": "Monitoring & Logging",
        "diagram_type": "dependency",
        "spec": {"kind": "fanin", "target_node_type": "collector", "min_sources": 3},
    },
    "3.10": {"domain_name": "Patch & Lifecycle Management", "diagram_type": None, "spec": None},
    "3.11": {
        "domain_name": "Backup & Recovery",
        "diagram_type": "dependency",
        "spec": {"kind": "node_type_and_edge_type", "node_type": "backup_target", "min_nodes": 2,
                 "relationship_types": None, "min_edges": 1, "generic_fallback": True},
    },
    "3.12": {
        "domain_name": "Isolation & Resilience Validation (Drawbridge)",
        "diagram_type": "purdue",
        "spec": {"kind": "generic", "min_nodes": 1, "min_edges": 1, "generic_fallback": True},
    },
    "3.13": {
        "domain_name": "Perimeter / Firewall & Network Boundary Validation",
        "diagram_type": "purdue",
        "spec": {"kind": "node_type_with_any_edge", "node_type": "firewall", "min_nodes": 1},
    },
    "3.14": {"domain_name": "Vulnerability Management", "diagram_type": None, "spec": None},
    "3.15": {
        "domain_name": "Infrastructure Dependencies (Virtualisation / Hardware)",
        "diagram_type": "dependency",
        "spec": {"kind": "generic_with_edge_type", "min_nodes": 3,
                 "relationship_types": ["hosting"], "min_edges": 1},
    },
    "3.16": {
        "domain_name": "Supply Chain & Third-Party / Vendor Access",
        "diagram_type": "dependency",
        "spec": {"kind": "node_type_and_edge_type", "node_type": "vendor_path", "min_nodes": 0,
                 "relationship_types": ["remote-access"], "min_edges": 1, "generic_fallback": True},
    },
    "3.17": {
        "domain_name": "Internet Access & Communications (Proxy / SMTP)",
        "diagram_type": "purdue",
        "spec": {"kind": "purdue_levels", "required_levels": {"4", "5"},
                 "relationship_types": None, "min_edges": 1},
    },
}


def fail(code, message, **extra):
    print(json.dumps({"status": "ERROR", "code": code, "message": message, **extra}, indent=2))
    sys.exit(2)


def emit(payload):
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Project registry resolution -- copied from graph_store.py's own copy of
# evidence_matrix.py's mechanism, on purpose, so all three scripts agree on
# what "a registered project" means.
# ---------------------------------------------------------------------------

def _load_project_registry():
    """Parse csa-context/PROJECTS.yaml (fixed-shape, no PyYAML dependency for
    THIS parsing step -- PyYAML is still used elsewhere for the model file).
    This is a deliberate byte-for-byte copy of graph_store.py's own parser
    (which itself mirrors evidence_matrix.py's), so all three scripts agree
    on what "a registered project" means and none of them can drift apart
    on the registry's actual shape: a top-level `projects:` key holding a
    YAML list of `- key: ...` blocks, not one top-level key per project.

    This script's own location is .agents/skills/csa-diagram-generator/scripts/
    -- three parents up is .agents/.
    """
    registry_path = Path(__file__).resolve().parents[3] / "csa-context" / "PROJECTS.yaml"
    if not registry_path.is_file():
        return []
    projects = []
    current = {}
    for raw_line in registry_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line[:1] not in (" ", "\t"):
            continue
        if stripped.startswith("- key:"):
            if current:
                projects.append(current)
            current = {}
            stripped = stripped[2:]
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        projects.append(current)
    return projects


def resolve_paths(project_arg):
    if not project_arg:
        fail("PROJECT_REQUIRED", "--project is required (e.g. iamps, utcdtc)")

    registry = _load_project_registry()
    if not registry:
        fail("REGISTRY_NOT_FOUND", "csa-context/PROJECTS.yaml not found or empty")

    block = next((p for p in registry if p.get("key") == project_arg), None)
    if not block:
        fail("UNKNOWN_PROJECT", f"'{project_arg}' is not a key in PROJECTS.yaml",
             known_projects=sorted(p.get("key", "") for p in registry))

    root = Path(block["project_root"]).expanduser()
    work_dir = Path(block["work_dir"]).expanduser() if block.get("work_dir") else root / "csa-work"
    return {
        "project_key": block["key"],
        "project_root": root,
        "work_dir": work_dir,
        "nodes_path": work_dir / "graph" / "nodes.csv",
        "edges_path": work_dir / "graph" / "edges.csv",
        "diagrams_dir": work_dir / "diagrams",
    }


def load_rows(path, columns):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            fail("BAD_HEADER", f"{path} header does not match expected columns",
                 expected=columns, found=reader.fieldnames)
        return list(reader)


def slugify(domain):
    slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")
    return slug


def match_domain_to_section(domain_arg):
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\b", domain_arg)
    if m and m.group(1) in ROUTING:
        return m.group(1), ROUTING[m.group(1)]
    lowered = domain_arg.strip().lower()
    for section, entry in ROUTING.items():
        if entry["domain_name"].lower() == lowered:
            return section, entry
    return None, None


# ---------------------------------------------------------------------------
# Threshold evaluation. Every "kind" here reads only nodes/edges already
# filtered to (project, domain) by the caller. Returns (met: bool, counts: dict).
# ---------------------------------------------------------------------------

def _edge_touches_node_type(edge, nodes_by_id, node_type):
    for nid in (edge["source_node_id"], edge["target_node_id"]):
        n = nodes_by_id.get(nid)
        if n and n["node_type"] == node_type:
            return True
    return False


def evaluate_threshold(spec, nodes, edges):
    nodes_by_id = {n["node_id"]: n for n in nodes}
    kind = spec["kind"]

    if kind == "generic":
        met = len(nodes) >= spec["min_nodes"] and len(edges) >= spec["min_edges"]
        return met, {"nodes": len(nodes), "edges": len(edges),
                     "required_nodes": spec["min_nodes"], "required_edges": spec["min_edges"]}

    if kind == "generic_with_edge_type":
        rel = spec["relationship_types"]
        matching_edges = [e for e in edges if e["relationship_type"] in rel]
        met = len(nodes) >= spec["min_nodes"] and len(matching_edges) >= spec["min_edges"]
        return met, {"nodes": len(nodes), "matching_edges": len(matching_edges),
                     "required_nodes": spec["min_nodes"], "required_edges": spec["min_edges"],
                     "relationship_types": rel}

    if kind == "edge_type_only":
        rel = spec["relationship_types"]
        matching_edges = [e for e in edges if e["relationship_type"] in rel]
        met = len(matching_edges) >= spec["min_edges"]
        return met, {"matching_edges": len(matching_edges),
                     "required_edges": spec["min_edges"], "relationship_types": rel}

    if kind == "node_type_and_edge_type":
        nt = spec["node_type"]
        matching_nodes = [n for n in nodes if n["node_type"] == nt]
        rel = spec["relationship_types"]
        if rel:
            matching_edges = [e for e in edges if e["relationship_type"] in rel]
        else:
            matching_edges = edges
        met = len(matching_nodes) >= spec["min_nodes"] and len(matching_edges) >= spec["min_edges"]
        return met, {"matching_nodes": len(matching_nodes), "node_type": nt,
                      "matching_edges": len(matching_edges),
                      "required_nodes": spec["min_nodes"], "required_edges": spec["min_edges"]}

    if kind == "node_type_with_any_edge":
        nt = spec["node_type"]
        matching_nodes = [n for n in nodes if n["node_type"] == nt]
        edges_touching = [e for e in edges if _edge_touches_node_type(e, nodes_by_id, nt)]
        met = len(matching_nodes) >= spec["min_nodes"] and len(edges_touching) >= 1
        return met, {"matching_nodes": len(matching_nodes), "node_type": nt,
                      "edges_touching": len(edges_touching), "required_nodes": spec["min_nodes"]}

    if kind == "fanout":
        nt = spec["source_node_type"]
        source_nodes = {n["node_id"] for n in nodes if n["node_type"] == nt}
        matching_edges = [e for e in edges if e["source_node_id"] in source_nodes]
        met = len(source_nodes) >= spec["min_sources"] and len(matching_edges) >= spec["min_edges"]
        return met, {"source_nodes": len(source_nodes), "node_type": nt,
                      "matching_edges": len(matching_edges),
                      "required_sources": spec["min_sources"], "required_edges": spec["min_edges"]}

    if kind == "fanin":
        nt = spec["target_node_type"]
        target_ids = {n["node_id"] for n in nodes if n["node_type"] == nt}
        source_ids = {e["source_node_id"] for e in edges if e["target_node_id"] in target_ids}
        met = len(source_ids) >= spec["min_sources"]
        return met, {"distinct_sources_into_collector": len(source_ids), "node_type": nt,
                      "required_sources": spec["min_sources"]}

    if kind == "purdue_levels":
        levels = {n["purdue_level"] for n in nodes if n.get("purdue_level") and n["purdue_level"] != "n/a"}
        rel = spec.get("relationship_types")
        matching_edges = [e for e in edges if not rel or e["relationship_type"] in rel]
        required_levels = spec.get("required_levels")
        if required_levels:
            met = required_levels.issubset(levels) and len(matching_edges) >= spec.get("min_edges", 1)
        else:
            met = len(levels) >= spec["min_distinct_levels"] and len(matching_edges) >= spec.get("min_edges", 1)
        return met, {"distinct_purdue_levels": sorted(levels), "matching_edges": len(matching_edges)}

    fail("UNKNOWN_THRESHOLD_KIND", f"no evaluator for threshold kind '{kind}'")


def build_model_nodes_edges(nodes, edges):
    model_nodes = [{
        "node_id": n["node_id"], "label": n["label"], "node_type": n["node_type"],
        "purdue_level": n.get("purdue_level", ""), "zone": n.get("zone", ""),
        "evidence_ids": n.get("evidence_ids", ""),
    } for n in nodes]
    model_edges = [{
        "edge_id": e["edge_id"], "source_node_id": e["source_node_id"],
        "target_node_id": e["target_node_id"], "relationship_type": e["relationship_type"],
        "evidence_ids": e.get("evidence_ids", ""),
    } for e in edges]
    return model_nodes, model_edges


def write_model(paths, model, dry_run):
    if yaml is None:
        fail("PYYAML_MISSING", "PyYAML is required to write the model file")
    diagrams_dir = paths["diagrams_dir"]
    slug = slugify(model["domain"])
    out_path = diagrams_dir / f"{slug}.yaml"
    if dry_run:
        return out_path, False
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(model, f, sort_keys=False, allow_unicode=True)
    return out_path, True


def cmd_build(args):
    paths = resolve_paths(args.project)
    section, entry = match_domain_to_section(args.domain)
    if not entry:
        fail("UNKNOWN_DOMAIN", f"'{args.domain}' does not match a Part 1b routing-table domain",
             known_sections=sorted(ROUTING.keys()))

    if entry["diagram_type"] is None:
        emit({"status": "SKIPPED", "reason": "no diagram for this domain (routing table: None)",
              "project": paths["project_key"], "domain": args.domain, "section": section})
        return

    all_nodes = load_rows(paths["nodes_path"], NODE_COLUMNS)
    all_edges = load_rows(paths["edges_path"], EDGE_COLUMNS)
    # Honour graph/graph-reviews.jsonl (graph_store.py review): rejected nodes and edges,
    # and edges touching a rejected node, are never drawn.
    import json as _json
    _log = paths["nodes_path"].parent / "graph-reviews.jsonl"
    _state = {}
    if _log.is_file():
        for _l in _log.read_text(encoding="utf-8").splitlines():
            try:
                _r = _json.loads(_l); _state[_r["id"]] = _r["state"]
            except (ValueError, KeyError):
                pass
    _gone = {n["node_id"] for n in all_nodes if _state.get(n["node_id"]) == "rejected"}
    all_nodes = [n for n in all_nodes if n["node_id"] not in _gone]
    all_edges = [e for e in all_edges if _state.get(e["edge_id"]) != "rejected"
                 and e["source_node_id"] not in _gone and e["target_node_id"] not in _gone]

    if entry["spec"]["kind"] == "executive_summary":
        diagrams_dir = paths["diagrams_dir"]
        existing = sorted(p for p in diagrams_dir.glob("*.yaml")) if diagrams_dir.exists() else []
        if not existing:
            emit({"status": "SKIPPED",
                  "reason": "executive overview waits until at least one domain diagram exists; none found yet",
                  "project": paths["project_key"], "domain": args.domain,
                  "diagrams_dir": str(diagrams_dir)})
            return
        agg_nodes, agg_edges = {}, {}
        source_files = []
        for p in existing:
            with open(p, "r", encoding="utf-8") as f:
                m = yaml.safe_load(f)
            if not m or m.get("diagram_type") == "executive_overview":
                continue
            source_files.append(p.name)
            for n in m.get("nodes", []):
                agg_nodes[n["node_id"]] = n
            for e in m.get("edges", []):
                agg_edges[e["edge_id"]] = e
        if not agg_nodes:
            emit({"status": "SKIPPED",
                  "reason": "no non-executive domain diagrams found to aggregate",
                  "project": paths["project_key"], "domain": args.domain})
            return
        model = {
            "project": paths["project_key"], "domain": args.domain,
            "diagram_type": "executive_overview",
            "title": f"{paths['project_key'].upper()} Executive Overview",
            "nodes": list(agg_nodes.values()), "edges": list(agg_edges.values()),
        }
        out_path, written = write_model(paths, model, args.dry_run)
        emit({"status": "DRY_RUN" if args.dry_run else "BUILT",
              "project": paths["project_key"], "domain": args.domain,
              "diagram_type": "executive_overview", "aggregated_from": source_files,
              "node_count": len(model["nodes"]), "edge_count": len(model["edges"]),
              "model_path": str(out_path),
              "note": "aggregation of already-drawn domain diagrams is a judgment call -- review before treating as authoritative"})
        return

    domain_nodes = [n for n in all_nodes if n["project"] == paths["project_key"] and n["domain"] == args.domain]
    domain_edges = [e for e in all_edges if e["project"] == paths["project_key"] and e["domain"] == args.domain]

    met, counts = evaluate_threshold(entry["spec"], domain_nodes, domain_edges)
    generic_flag = bool(entry["spec"].get("generic_fallback"))

    if not met:
        emit({"status": "SKIPPED", "reason": "threshold not met", "project": paths["project_key"],
              "domain": args.domain, "section": section, "diagram_type": entry["diagram_type"],
              "counts": counts, "generic_fallback_threshold": generic_flag})
        return

    model_nodes, model_edges = build_model_nodes_edges(domain_nodes, domain_edges)
    model = {
        "project": paths["project_key"], "domain": args.domain,
        "diagram_type": entry["diagram_type"],
        "title": f"{paths['project_key'].upper()} -- {args.domain}",
        "nodes": model_nodes, "edges": model_edges,
    }
    out_path, written = write_model(paths, model, args.dry_run)
    result = {"status": "DRY_RUN" if args.dry_run else "BUILT", "project": paths["project_key"],
              "domain": args.domain, "section": section, "diagram_type": entry["diagram_type"],
              "node_count": len(model_nodes), "edge_count": len(model_edges),
              "model_path": str(out_path), "counts": counts}
    if generic_flag:
        result["note"] = ("this domain's threshold is a generic node/edge-count approximation, "
                           "not a semantic check against the prose in Part 1b -- review before trusting it")
    emit(result)


def cmd_list_domains(args):
    paths = resolve_paths(args.project)
    rows = []
    for section, entry in sorted(ROUTING.items(), key=lambda kv: [int(p) for p in kv[0].split(".")]):
        rows.append({"section": section, "domain_name": entry["domain_name"],
                      "diagram_type": entry["diagram_type"]})
    emit({"project": paths["project_key"], "routing_table": rows})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--project", required=True)
    p_build.add_argument("--domain", required=True,
                          help='exact domain string as used in graph_store.py rows, e.g. "3.6 Network / Segmentation"')
    p_build.add_argument("--dry-run", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_list = sub.add_parser("list-domains")
    p_list.add_argument("--project", required=True)
    p_list.set_defaults(func=cmd_list_domains)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
