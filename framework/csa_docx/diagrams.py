#!/usr/bin/env python3
"""CSA diagram renderer: turns a node/edge model into a PNG+SVG figure.

Pure rendering layer -- no evidence reading, no docx access, no project
resolution. Its only job is: given a model dict/YAML file shaped like the
one below, produce a Graphviz drawing. csa-diagram-generator (a separate
skill) is what builds this model from a project's graph store
(<work_dir>/graph/nodes.csv + edges.csv) and decides whether a domain
clears the threshold to get one at all -- see the diagram-agent plan.

Requires the `graphviz` Python package (thin wrapper around the `dot`
binary) and, for the CLI's --model *.yaml path, PyYAML. Both are already
installed in this environment; a model dict can also be passed to the
render_* functions directly from Python without either dependency issue
arising (only the CLI's YAML loading needs PyYAML).

Model schema (matches the columns graph_store.py already validates, minus
the bookkeeping fields diagrams.py has no use for):

{
  "project": "iamps",
  "domain": "3.6 Network / Segmentation",
  "diagram_type": "purdue" | "dependency" | "executive_overview",
  "title": "Network / Segmentation -- current-state topology",
  "nodes": [
    {"node_id": "N-001", "label": "...", "node_type": "zone",
     "purdue_level": "2", "zone": "OT_...", "evidence_ids": "E-025;E-040"},
    ...
  ],
  "edges": [
    {"edge_id": "R-001", "source_node_id": "N-001", "target_node_id": "N-002",
     "relationship_type": "conduit", "evidence_ids": "E-025"},
    ...
  ]
}

CLI:
  python3 diagrams.py <model.yaml|model.json> [--out-dir DIR] [--stem NAME]
Prints one JSON result. Exit code 2 = the model failed validation; nothing
was rendered.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import graphviz
except ImportError:
    graphviz = None

# Purdue band order, bottom to top (rankdir=BT below puts index 0 at the
# bottom of the picture, matching the model: physical process at the
# bottom, enterprise/external at the top).
PURDUE_ORDER = ["0", "1", "2", "3", "3.5", "4", "5"]
PURDUE_LABEL = {
    "0": "Level 0 -- Physical Process", "1": "Level 1 -- Basic Control",
    "2": "Level 2 -- Supervisory Control", "3": "Level 3 -- Site Operations",
    "3.5": "Level 3.5 -- Industrial DMZ", "4": "Level 4 -- Enterprise IT",
    "5": "Level 5 -- External / Internet",
}

NODE_SHAPE = {
    "zone": "component", "firewall": "diamond", "backup_target": "cylinder",
    "idp": "cylinder", "directory": "cylinder", "hypervisor": "doubleoctagon",
    "host": "box", "service": "ellipse", "vendor_path": "cds",
    "collector": "box", "dns_server": "box", "ntp_source": "box",
}
DEFAULT_NODE_SHAPE = "box"

EDGE_STYLE = {
    "conduit": {"color": "#1a1a1a", "style": "solid"},
    "dependency": {"color": "#2b6cb0", "style": "solid"},
    "trust": {"color": "#6b46c1", "style": "dashed"},
    "data-flow": {"color": "#276749", "style": "solid"},
    "remote-access": {"color": "#c53030", "style": "dashed"},
    "hosting": {"color": "#4a5568", "style": "dotted"},
    "replication": {"color": "#4a5568", "style": "dashed"},
}
DEFAULT_EDGE_STYLE = {"color": "#4a5568", "style": "solid"}

FONT = "Helvetica"


# --------------------------------------------------------------------------- validation
def validate_model(model):
    issues = []
    for req in ("diagram_type", "nodes", "edges"):
        if req not in model:
            issues.append(f"model is missing required key {req!r}")
    if issues:
        return issues
    if model["diagram_type"] not in ("purdue", "dependency", "executive_overview"):
        issues.append(f"unknown diagram_type {model['diagram_type']!r}")
    node_ids = set()
    for i, n in enumerate(model["nodes"]):
        for req in ("node_id", "label"):
            if not n.get(req):
                issues.append(f"nodes[{i}] is missing required field {req!r}")
        if n.get("node_id") in node_ids:
            issues.append(f"duplicate node_id {n.get('node_id')!r}")
        node_ids.add(n.get("node_id"))
    for i, e in enumerate(model["edges"]):
        for req in ("source_node_id", "target_node_id"):
            if not e.get(req):
                issues.append(f"edges[{i}] is missing required field {req!r}")
                continue
            if e[req] not in node_ids:
                issues.append(f"edges[{i}].{req} {e[req]!r} does not match any node_id in this model")
        if e.get("source_node_id") == e.get("target_node_id") and e.get("source_node_id"):
            issues.append(f"edges[{i}] is a self-loop ({e['source_node_id']!r} -> itself)")
    if model["diagram_type"] == "purdue" and not model["nodes"]:
        issues.append("diagram_type is 'purdue' but there are no nodes to place on the Purdue bands")
    return issues


# --------------------------------------------------------------------------- shared helpers
def _node_label(n):
    parts = [n["label"]]
    if n.get("zone"):
        parts.append(f"<{n['zone']}>")
    return "\n".join(parts)


def _add_node(g, n):
    g.node(
        n["node_id"],
        label=_node_label(n),
        shape=NODE_SHAPE.get(n.get("node_type", ""), DEFAULT_NODE_SHAPE),
        fontname=FONT, fontsize="11", style="filled", fillcolor="#f7fafc",
        color="#2d3748",
    )


def _add_edge(g, e):
    style = EDGE_STYLE.get(e.get("relationship_type", ""), DEFAULT_EDGE_STYLE)
    g.edge(
        e["source_node_id"], e["target_node_id"],
        label=e.get("relationship_type", ""), fontname=FONT, fontsize="9",
        color=style["color"], style=style["style"],
    )


# --------------------------------------------------------------------------- purdue
def render_purdue_diagram(model):
    g = graphviz.Digraph(name=model.get("domain", "purdue"), format="png")
    g.attr(rankdir="BT", fontname=FONT, label=model.get("title", ""), labelloc="t",
           fontsize="14", splines="true", nodesep="0.4", ranksep="0.6")
    g.attr("node", fontname=FONT)

    by_level = {lvl: [] for lvl in PURDUE_ORDER}
    unclassified = []
    for n in model["nodes"]:
        lvl = str(n.get("purdue_level") or "").strip()
        if lvl in by_level:
            by_level[lvl].append(n)
        else:
            unclassified.append(n)

    # Invisible anchor chain, one per Purdue band, forces the vertical
    # order even for a band with zero real nodes in it -- without this a
    # band that happens to be empty could let Graphviz's layout collapse
    # the vertical spacing and blur the level boundaries.
    prev_anchor = None
    for lvl in PURDUE_ORDER:
        anchor = f"__anchor_{lvl.replace('.', '_')}"
        with g.subgraph() as s:
            s.attr(rank="same")
            s.node(anchor, label=PURDUE_LABEL.get(lvl, f"Level {lvl}"), shape="plaintext",
                   fontname=FONT, fontsize="10", fontcolor="#718096")
            for n in by_level[lvl]:
                _add_node(s, n)
        if prev_anchor:
            g.edge(prev_anchor, anchor, style="invis")
        prev_anchor = anchor

    if unclassified:
        with g.subgraph(name="cluster_unclassified") as s:
            s.attr(label="Unclassified / not placed on the Purdue model", fontname=FONT,
                   fontsize="10", fontcolor="#718096", style="dashed", color="#cbd5e0")
            for n in unclassified:
                _add_node(s, n)

    for e in model["edges"]:
        _add_edge(g, e)
    return g


# --------------------------------------------------------------------------- dependency
def render_dependency_diagram(model):
    g = graphviz.Digraph(name=model.get("domain", "dependency"), format="png")
    g.attr(rankdir="LR", fontname=FONT, label=model.get("title", ""), labelloc="t",
           fontsize="14", splines="true", nodesep="0.35", ranksep="0.7")
    g.attr("node", fontname=FONT)

    by_zone = {}
    unzoned = []
    for n in model["nodes"]:
        zone = n.get("zone") or ""
        if zone:
            by_zone.setdefault(zone, []).append(n)
        else:
            unzoned.append(n)

    for zone, nodes in by_zone.items():
        with g.subgraph(name=f"cluster_{zone}") as s:
            s.attr(label=zone, fontname=FONT, fontsize="10", fontcolor="#718096",
                   style="dashed", color="#cbd5e0")
            for n in nodes:
                _add_node(s, n)
    for n in unzoned:
        _add_node(g, n)

    for e in model["edges"]:
        _add_edge(g, e)
    return g


# --------------------------------------------------------------------------- executive overview
def render_executive_overview(model):
    """A simplified rollup. Rendering-wise this is the dependency layout
    with a more prominent title and a flatter look; csa-diagram-generator
    is responsible for actually simplifying the node/edge set (dropping
    low-level detail) before it gets here -- diagrams.py only renders
    what it's given, it does not decide what to leave out."""
    g = render_dependency_diagram(model)
    g.attr(fontsize="18", nodesep="0.5", ranksep="0.9")
    return g


BUILDERS = {
    "purdue": render_purdue_diagram,
    "dependency": render_dependency_diagram,
    "executive_overview": render_executive_overview,
}


# --------------------------------------------------------------------------- render to disk
def render(model, out_dir, stem=None):
    if graphviz is None:
        raise RuntimeError("the 'graphviz' Python package is not installed (pip install graphviz); "
                            "the 'dot' binary must also be on PATH")
    issues = validate_model(model)
    if issues:
        return {"status": "ISSUES", "issues": issues}

    builder = BUILDERS[model["diagram_type"]]
    g = builder(model)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or model.get("domain", "diagram").lower().replace(" ", "-").replace("/", "-")
    written = {}
    for fmt in ("png", "svg"):
        g.format = fmt
        path = g.render(filename=stem, directory=str(out_dir), cleanup=True)
        written[fmt] = path
    dot_path = out_dir / f"{stem}.gv"
    dot_path.write_text(g.source, encoding="utf-8")
    written["dot"] = str(dot_path)

    return {
        "status": "OK", "diagram_type": model["diagram_type"],
        "domain": model.get("domain"), "project": model.get("project"),
        "node_count": len(model["nodes"]), "edge_count": len(model["edges"]),
        **{f"{k}_path": v for k, v in written.items()},
    }


# --------------------------------------------------------------------------- CLI
def _load_model(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="path to a *.yaml or *.json model file")
    ap.add_argument("--out-dir", required=True, help="directory to write <stem>.png/.svg/.gv into")
    ap.add_argument("--stem", help="output file base name (default: the model's domain, slugified)")
    args = ap.parse_args()

    try:
        model = _load_model(args.model)
    except Exception as e:
        print(json.dumps({"status": "ERROR", "message": f"could not load model: {e}"}, indent=2))
        sys.exit(2)

    result = render(model, args.out_dir, args.stem)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "OK":
        sys.exit(2)


if __name__ == "__main__":
    main()
