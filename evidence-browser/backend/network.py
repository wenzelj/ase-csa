"""Host network for the Evidence Workspace: every connection the captures recorded, as nodes and edges.

Built live from the project's evidence matrix (connection rows written by host_profile.py) and its host
register (hosts/hosts.csv, roles from the card's host register). Nothing is inferred: an address with no
captured name stays an address, and its kind (private/public) comes from the address itself.
"""
from __future__ import annotations

import csv
import ipaddress
import sys
from pathlib import Path
from typing import Any


def _framework(agents: Path) -> None:
    fw = str(agents / "framework")
    if fw not in sys.path:
        sys.path.insert(0, fw)


def _listed(r: dict) -> bool:
    """A captured host, or one the project's inventory lists (every other register entry is a peer or another application's)."""
    scope = (r.get("in_scope") or "").strip().lower()
    return scope not in ("peer", "no") and not scope.startswith("system:")


def build(work_dir: Path, agents: Path) -> dict[str, Any]:
    _framework(agents)
    from csa_docx import evidence_digest, section_card

    matrix = work_dir / "evidence-matrix.csv"
    rows = list(csv.DictReader(matrix.open(encoding="utf-8-sig", newline=""))) if matrix.is_file() else []
    hosts_csv = work_dir / "hosts" / "hosts.csv"
    reg = {r["host"]: r for r in csv.DictReader(hosts_csv.open(encoding="utf-8", newline=""))} if hosts_csv.is_file() else {}
    roles: dict[str, str] = {}
    register = section_card.host_register(work_dir.parent) if hosts_csv.is_file() else None
    if register:
        for g in register["groups"]:
            for h in g["hosts"]:
                roles[h] = g["role"]
        for u in register["uncaptured"]:
            roles.setdefault(u["host"], u["role"])

    nodes: dict[str, dict] = {}

    def node(name: str) -> None:
        if name in nodes:
            return
        r = reg.get(name)
        if r is not None:
            captured = (r.get("in_scope") or "") != "peer" and bool(r.get("capture"))
            kind = "captured" if captured else ("dc" if "domain controller" in (r.get("sources") or "").lower() else "named")
            nodes[name] = {"id": name, "kind": kind,
                           # host_register groups captured hosts and selected peers.  An in-scope inventory
                           # host can legitimately have a recorded role without a discovery capture, so keep
                           # the role already carried by hosts.csv instead of turning it into "not recorded".
                           "role": roles.get(name) or r.get("role") or ("Domain controller" if kind == "dc" else ""),
                           "site": r.get("site") or r.get("ad_site") or "", "ips": r.get("ips") or "",
                           "listed": _listed(r)}
            return
        try:
            public = not ipaddress.ip_address(name.split("%")[0]).is_private
        except ValueError:
            public = False
        nodes[name] = {"id": name, "kind": "public" if public else "unnamed", "role": "", "site": "", "ips": name}

    edges: dict[tuple, dict] = {}
    for l in evidence_digest.links(rows):
        node(l["host"])
        node(l["peer"])
        s, t = (l["peer"], l["host"]) if l["dir"] == "inbound" else (l["host"], l["peer"])
        e = edges.setdefault((s, t, l["port"]), {"s": s, "t": t, "port": l["port"], "procs": set(), "ids": [], "est": False})
        e["procs"].add(l["proc"])
        e["ids"].append(l["id"])
        e["est"] = e["est"] or l["state"].startswith("established")
    for h, r in reg.items():                       # captured and inventory-listed hosts with no recorded link still appear
        if _listed(r):
            node(h)
    out_edges = [{**e, "procs": sorted(e["procs"])} for e in edges.values()]
    return {"nodes": list(nodes.values()), "edges": out_edges,
            "source": "evidence-matrix.csv connection rows and hosts/hosts.csv",
            "matrix_rows": len(rows)}
