"""Host network for the Evidence Workspace: every connection the captures recorded, as nodes and edges.

Built live from the project's evidence matrix (connection rows written by host_profile.py) and its host
register (hosts/hosts.csv, roles from the card's host register). Nothing is inferred: an address with no
captured name stays an address, and its kind (private/public) comes from the address itself.
"""
from __future__ import annotations

import csv
import ipaddress
import sqlite3
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


def device_identities(work_dir: Path, agents: Path) -> dict[str, dict[str, str]]:
    """{address: identity} for the observed addresses an active, confirmed connected device owns.

    Read live from the register, so a device retired or disputed after the last rebuild is not shown
    as confirmed. Only confirmed identities appear; proposed, disputed and ambiguous claims leave the
    address unidentified."""
    _framework(agents)
    from csa_docx import connected_devices
    out: dict[str, dict[str, str]] = {}
    for address, d in connected_devices.resolution_map(work_dir)["confirmed"].items():
        out[address] = {"device_id": d["device_id"], "name": d["name"], "type": d["device_type"],
                        "classification": d["classification"], "site": d["site_zone"],
                        "revision": d["revision"], "provenance": d["provenance"], "state": d["identification_state"]}
    return out


def build(work_dir: Path, agents: Path, view: str = "global", application_key: str | None = None) -> dict[str, Any]:
    if work_dir.name == "csa-work-v2":
        return _build_v2(work_dir, agents, view=view, application_key=application_key)
    _framework(agents)
    from csa_docx import evidence_digest, section_card
    identities = device_identities(work_dir, agents)

    matrix = work_dir / "evidence-matrix.csv"
    from csa_docx import evidence_live          # the latest review applied: rejected rows draw no link
    rows = evidence_live.read(matrix)
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
        device = identities.get(name)
        if device:                                  # the raw address stays the node id; the identity is added beside it
            nodes[name].update({"role": device["name"] + (f" ({device['type']})" if device["type"] else ""),
                                "site": device["site"], "device": device})

    edges: dict[tuple, dict] = {}
    for l in evidence_digest.links(rows, reg):
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


def _build_v2(work_dir: Path, agents: Path, view: str = "global", application_key: str | None = None) -> dict[str, Any]:
    """Read the active V2 host and flow records, never leftover V1 exports."""
    db = work_dir / "csa.sqlite"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        hosts = [dict(row) for row in con.execute(
            "SELECT name,role,site FROM host WHERE status='active' ORDER BY name")]
        addresses = [dict(row) for row in con.execute(
            "SELECT ip,owner_host FROM address ORDER BY ip")]
        flows = [dict(row) for row in con.execute(
            "SELECT src_host,dst_host,port,protocol,purpose FROM flow ORDER BY id")]
        graph_edges = [dict(row) for row in con.execute(
            "SELECT src,dst,evidence_ids FROM graph_edge WHERE kind='flow' ORDER BY edge_id")]
        evidence = [dict(row) for row in con.execute(
            "SELECT id AS evidence_id,area AS csa_area,status,claim,review_state FROM evidence ORDER BY id")]
    ips: dict[str, list[str]] = {}
    for row in addresses:
        if row["owner_host"]:
            ips.setdefault(row["owner_host"], []).append(row["ip"])
    nodes = {row["name"]: {"id": row["name"], "kind": "captured", "role": row["role"] or "",
                           "site": row["site"] or "", "ips": ";".join(ips.get(row["name"], [])), "listed": True}
             for row in hosts}
    # V2 host rows intentionally keep only canonical inventory fields. Restore a
    # displayed role when accepted evidence explicitly identifies a domain controller.
    for claim in evidence:
        text = claim.get("claim") or ""
        if "domain controller" not in text.lower() and "ad domain controller" not in text.lower():
            continue
        for name, node in nodes.items():
            if name in text:
                node["role"] = node["role"] or "Domain controller"
    edges = []
    _framework(agents)
    from csa_docx import evidence_digest
    register = {row["name"]: {"ips": ";".join(ips.get(row["name"], [])), "in_scope": "yes"}
                for row in hosts}
    for link in evidence_digest.links(evidence, register):
        for endpoint in (link["host"], link["peer"]):
            if endpoint not in nodes:
                try:
                    kind = "public" if not ipaddress.ip_address(endpoint.split("%")[0]).is_private else "unnamed"
                except ValueError:
                    kind = "named"
                nodes[endpoint] = {"id": endpoint, "kind": kind, "role": "", "site": "",
                                   "ips": endpoint if kind in ("public", "unnamed") else "", "listed": False}
        source, target = ((link["peer"], link["host"]) if link["dir"] == "inbound"
                          else (link["host"], link["peer"]))
        edge = next((item for item in edges if (item["s"], item["t"], item["port"]) ==
                     (source, target, str(link["port"]))), None)
        if edge is None:
            edge = {"s": source, "t": target, "port": str(link["port"]), "procs": [], "ids": [], "est": False}
            edges.append(edge)
        if link["proc"] and link["proc"] not in edge["procs"]:
            edge["procs"].append(link["proc"])
        edge["ids"].append(link["id"])
        edge["est"] = edge["est"] or link["state"].startswith("established")
    for row in flows:
        for endpoint in (row["src_host"], row["dst_host"]):
            if endpoint not in nodes:
                nodes[endpoint] = {"id": endpoint, "kind": "named", "role": "", "site": "",
                                   "ips": endpoint, "listed": False}
        if not any(edge["s"] == row["src_host"] and edge["t"] == row["dst_host"]
                   and edge["port"] == str(row["port"] or "") for edge in edges):
            edges.append({"s": row["src_host"], "t": row["dst_host"], "port": str(row["port"] or ""),
                          "procs": [], "ids": [], "est": False})
    for row in graph_edges:
        source = row["src"].removeprefix("host/")
        target = row["dst"].removeprefix("host/")
        if source not in nodes or target not in nodes:
            continue
        ids = [value for value in (row["evidence_ids"] or "").split(";") if value]
        matched = [edge for edge in edges if edge["s"] == source and edge["t"] == target]
        if matched:
            for edge in matched:
                edge["ids"] = sorted(set(edge["ids"] + ids))
        elif ids:
            edges.append({"s": source, "t": target, "port": "", "procs": [], "ids": ids, "est": False})
    if view not in {"global", "application"}:
        raise ValueError("view must be 'application' or 'global'")
    if view == "application":
        if not application_key:
            raise ValueError("application_key is required for application view")
        _framework(agents)
        from csa_docx.v2repo import Repo
        from csa_docx.v2repo import graph as _v2_graph  # noqa: F401 — patches Repo.graph
        from csa_docx.v2repo.scope import projected_graph
        scoped_repo = Repo(db)
        try:
            projection = projected_graph(scoped_repo, application_key, view="application")
        finally:
            scoped_repo.close()
        allowed = {node["node_id"].removeprefix("host/")
                   for node in projection["nodes"] if node["node_id"].startswith("host/")}
        nodes = {name: node for name, node in nodes.items() if name in allowed}
        edges = [edge for edge in edges if edge["s"] in allowed and edge["t"] in allowed]
    return {"nodes": list(nodes.values()), "edges": edges,
            "source": "csa.sqlite host, address, flow, evidence and graph_edge",
            "matrix_rows": len(evidence), "view": view, "application_key": application_key}
