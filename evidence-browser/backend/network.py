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


VIEWS = ("application", "owned", "global")


def _check_view(view: str, application_key: str | None) -> None:
    """A scoped view needs a registered application key; an unknown view is rejected outright."""
    if view not in VIEWS:
        raise ValueError("view must be 'application', 'owned' or 'global'")
    if view != "global":
        if not application_key or not str(application_key).strip():
            raise ValueError(f"application_key is required for the {view} view")


def _scoped_application_keys() -> set[str]:
    """Every registered application key across the project stores, without a framework import."""
    import os
    try:
        path = Path(os.environ.get("CSA_PROJECTS_FILE", "")).expanduser() if os.environ.get("CSA_PROJECTS_FILE") else Path(os.environ.get("CSA_AGENTS_DIR", "")) / "csa-context" / "PROJECTS.yaml"
        path = path if path.is_file() else Path(__file__).resolve().parents[3] / "csa-context" / "PROJECTS.yaml"
    except Exception:
        path = Path(__file__).resolve().parents[3] / "csa-context" / "PROJECTS.yaml"
    keys: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- key:"):
                keys.add(line.split(":", 1)[1].strip().strip("\"'"))
    return keys


def resolve_application_key(registered: list[str], application_key: str | None) -> str:
    """The canonical V2 application key for the key a caller passed.

    Browser routes pass the project key (for TETRA: ``tetra``) while V2 scope is keyed by the
    registered application key (``tetra-reveloc``). The short form is accepted only as a
    deterministic alias: it must be the prefix, up to a hyphen, of exactly one registered key.
    An unknown key and a key that matches several registered keys both fail clearly."""
    key = (application_key or "").strip()
    if not key:
        raise ValueError("application_key is required for a scoped view")
    if key in registered:
        return key
    aliases = [candidate for candidate in registered if candidate.startswith(f"{key}-")]
    if len(aliases) == 1:
        return aliases[0]
    if aliases:
        raise ValueError(f"ambiguous application_key: {key} matches {', '.join(aliases)}")
    raise ValueError(f"unknown application_key: {key}")


def _contract_hosts(db: Path, agents: Path, application_key: str) -> tuple[set[str], set[str], set[str]]:
    """(owned hosts, visible scoped peer hosts, every registered host) from the repository's
    projection contract (csa_docx.v2repo.scope). The browser never decides scope itself."""
    _framework(agents)
    from csa_docx.v2repo import Repo
    from csa_docx.v2repo import graph as _v2_graph  # noqa: F401 — patches Repo.graph
    from csa_docx.v2repo import scope as _v2_scope
    repo = Repo(db)
    try:
        owned, peers = _v2_scope._scoped_host_ids(repo, application_key)
        registered = _v2_scope._registered_hosts(repo)
    finally:
        repo.close()
    if not owned and not peers:
        raise ValueError(f"unknown application_key: {application_key}")
    return ({name.removeprefix("host/") for name in owned}, {name.removeprefix("host/") for name in peers},
            registered)


def _apply_contract(nodes: dict[str, dict], edges: list[dict], view: str, owned: set[str], peers: set[str],
                    registered: set[str]) -> tuple[dict[str, dict], list[dict]]:
    """The repository contract applied to the browser's port-level network.

    ``owned`` keeps the owned hosts and the links between them. ``application`` adds the scoped
    peer hosts the contract makes visible and every external endpoint (an address or name that is
    not a registered host) on a captured link to an owned host. A registered host that the contract
    does not make visible (an unlinked peer, another application's host) is never shown, and a
    link is kept only when one end is an owned host and both ends are visible."""
    if view == "owned":
        kept = [edge for edge in edges if edge["s"] in owned and edge["t"] in owned]
        return {name: node for name, node in nodes.items() if name in owned}, kept
    visible = set(owned) | set(peers)
    for edge in edges:
        for near, far in ((edge["s"], edge["t"]), (edge["t"], edge["s"])):
            if near in owned and far not in registered:
                visible.add(far)                     # an external endpoint needs no scope row
    kept = [edge for edge in edges
            if (edge["s"] in owned or edge["t"] in owned) and edge["s"] in visible and edge["t"] in visible]
    return {name: node for name, node in nodes.items() if name in visible}, kept


def scoped_network(project: dict[str, str], agents: Path, view: str = "application",
                   application_key: str | None = None) -> dict[str, Any]:
    """The one adapter Host network, System Explorer, technical diagrams and CSA figures use.

    Every caller gets the same network for the same store and view, with the selected ``view`` and
    the canonical ``application_key`` in the response; none of them filters hosts or links itself."""
    work = Path(project["work_dir"]).expanduser()
    key = application_key or project.get("key")
    try:
        net = build(work, agents, view=view, application_key=key)
    except TypeError as exc:                         # older test doubles and V1 extensions take no view
        if "unexpected keyword argument" not in str(exc):
            raise
        net = build(work, agents)
    net.setdefault("view", view)
    net.setdefault("application_key", key)
    return net


def identity(net: dict[str, Any], node_key: str = "nodes") -> dict[str, set]:
    """The identity sets parity is judged on: endpoint IDs and (source, target, port) links."""
    return {"nodes": {node["id"] for node in net.get(node_key, [])},
            "edges": {(edge["s"], edge["t"], str(edge.get("port", ""))) for edge in net.get("edges", [])}}


def parity(surfaces: dict[str, dict[str, set]]) -> dict[str, Any]:
    """Compare the identity sets of several surfaces for one store and view.

    Returns counts per surface and, for every surface that differs from the first one, the
    identities it is missing and the ones it adds, so a mismatch is reported rather than accepted."""
    names = list(surfaces)
    base = surfaces[names[0]]
    differences = []
    for name in names[1:]:
        for part in ("nodes", "edges"):
            missing, extra = base[part] - surfaces[name][part], surfaces[name][part] - base[part]
            if missing or extra:
                differences.append({"surface": name, "against": names[0], "part": part,
                                    "missing": sorted(map(str, missing)), "extra": sorted(map(str, extra))})
    return {"status": "OK" if not differences else "MISMATCH",
            "counts": {name: {part: len(values) for part, values in sets.items()} for name, sets in surfaces.items()},
            "differences": differences}


def build(work_dir: Path, agents: Path, view: str = "global", application_key: str | None = None) -> dict[str, Any]:
    """One graph, every browser page: Host network, System Explorer, technical diagrams and CSA
    figures all reach this through ``scoped_network``, so the same view can never disagree across
    the workspace."""
    if work_dir.name == "csa-work-v2":
        _check_view(view, application_key)
        return _build_v2(work_dir, agents, view=view, application_key=application_key)
    if view != "global":
        # V1 stores have no application scope: the selected application's own view is the only
        # scoped one, and it is the same as the global graph for that one store.
        view = "global"
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
        try:
            registered = [row[0] for row in con.execute(
                "SELECT DISTINCT application_key FROM application_scope ORDER BY application_key")]
        except sqlite3.OperationalError:             # a store with no scope metadata yet: global only
            registered = []
    if view != "global":
        application_key = resolve_application_key(registered, application_key)
    else:
        # The global view is never filtered; a key that resolves only labels the response.
        try:
            application_key = resolve_application_key(registered, application_key)
        except ValueError:
            application_key = None
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
    scope = {"owned": [], "peers": [], "external": []}
    if application_key and view == "global":
        try:                                         # labels only: the global view never fails on scope
            _contract_hosts(db, agents, application_key)
        except ValueError:
            application_key = None
    if application_key:
        owned, peers, registered_hosts = _contract_hosts(db, agents, application_key)
        if view != "global":
            nodes, edges = _apply_contract(nodes, edges, view, owned, peers, registered_hosts)
        scope = {"owned": sorted(owned & set(nodes)), "peers": sorted(peers & set(nodes)),
                 "external": sorted(name for name in nodes if name not in registered_hosts)
                 if view == "application" else []}
    return {"nodes": list(nodes.values()), "edges": edges,
            "source": "csa.sqlite host, address, flow, evidence and graph_edge",
            "matrix_rows": len(evidence), "view": view,
            "application_key": application_key, "scope": scope}
