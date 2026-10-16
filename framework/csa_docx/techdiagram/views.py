"""Section figures: a view of the system scoped to the one question a CSA section asks.

service_view (archetype B, service dependency): the vital OT hosts that take a service, the providers they
take it from, and on which side of the IT/OT line each provider sits. Providers the project's residency rule
places in IT are drawn across the top; OT-resident providers in the band below the data centres; providers
the evidence does not place go in "Location not captured". When no OT-resident provider is evidenced, that
band holds a dashed "none evidenced" box: the gap is the finding. Systems outside the question are left out.

Same page structure and track layout as the overview, so a host sits in the same place in every figure.
"""
from __future__ import annotations

import collections
import re

from . import model as M

ORDER_WORD = {1: "1st", 2: "2nd", 3: "3rd"}
SERVICE_LABEL = {"time": "Time", "dns": "DNS"}
SERVICE_WORD = {"time": "time", "dns": "name resolution"}
PROVIDER_ROLE = {"time": "time source", "dns": "DNS server"}


def _edge_label(r: dict) -> str:
    base = SERVICE_LABEL.get(r["service"], r["service"].title())
    if r["state"] != "active":
        return f"{base}: configured, not in use"
    return f"{base} {ORDER_WORD.get(r['order'], str(r['order']) + 'th')}" if r["service"] == "dns" else base


def service_view(net: dict, spec: dict, layout: dict, rows: list[dict], *, key: str, title: str, subtitle: str,
                 service: str, ot_gap: str | None, application: str) -> dict:
    prof = M.resolve_profile(net, layout)
    over = M.overview(net, spec or {}, prof, application)
    known = {n["id"]: n for n in over["nodes"]}
    consumers = sorted({r["consumer"] for r in rows})
    nodes, other_sites = [], []
    for c in consumers:
        n = known.get(c)
        if n is None:
            continue
        n = {k: v for k, v in n.items() if k not in ("group", "tier")}
        if n["zone"].startswith("site:") and n["zone"][5:] not in other_sites:
            other_sites.append(n["zone"][5:])
        nodes.append(n)

    zone_for = {"it": "it", "internet": "it", "ot": "shared", "unknown": "outside"}
    providers = collections.OrderedDict()
    for r in rows:
        providers.setdefault(r["provider"], (r["side"], r["side_reason"]))
    dc_order = {dc["key"]: i for i, dc in enumerate(prof["data_centres"])}
    site_of = {n["id"]: n["zone"] for n in nodes}
    def _rank(p):
        # a provider with its own site sits above its data centre; otherwise above the hosts it serves
        own = re.search(r"site (\S+)", (known.get(p) or {}).get("role") or "")
        dc = M._dc_for_site(own.group(1), prof) if own else None
        if dc in dc_order:
            return dc_order[dc]
        served = [dc_order.get(site_of.get(r["consumer"]), 9) for r in rows if r["provider"] == p and r["state"] == "active"]
        return (sum(served) / len(served)) if served else 9
    providers = collections.OrderedDict(sorted(providers.items(), key=lambda kv: (_rank(kv[0]), kv[0])))
    for p, (side, why) in providers.items():
        base = known.get(p)
        if (base and base["kind"] == "directory") or why.startswith("Domain controller"):
            base = base or {"role": "Domain controller", "kind": "directory"}
            role = base["role"] + (" · enterprise (IT)" if side == "it" else " · OT" if side == "ot" else "")
            kind = "directory"
        elif side == "internet":
            role, kind = f"Internet {PROVIDER_ROLE.get(service, 'service')}", "internet"
        elif re.fullmatch(r"\d+(\.\d+){3}", p):
            role, kind = "Not named in the evidence", "unknown"
        else:
            role, kind = (base or {}).get("role") or PROVIDER_ROLE.get(service, "provider").capitalize(), (base or {}).get("kind", "server")
        zone = zone_for.get(side, "outside")
        nodes.append({"id": p, "label": p, "role": role, "kind": kind, "zone": zone,
                      "under": (base or {}).get("under") if zone == "shared" else None, "kind_basis": why,
                      "ips": (base or {}).get("ips", []), "host": bool(base)})
    has_ot = any(side == "ot" for side, _ in providers.values())
    notes = []
    if ot_gap and not has_ot:
        nodes.append({"id": "GAP-OT", "label": "None evidenced", "role": ot_gap, "kind": "gap", "zone": "shared",
                      "kind_basis": f"No {ot_gap} appears in the evidence", "ips": []})
        notes.append(f"No {ot_gap} appears in the evidence. Every vital host takes {SERVICE_WORD.get(service, service)} "
                     f"from a provider outside OT.")
    rule = (layout or {}).get("residency") or {}
    if rule.get("basis"):
        notes.append("Where providers sit: " + rule["basis"])

    edges = []
    for i, r in enumerate(sorted(rows, key=lambda r: (r["consumer"], r["order"])), 1):
        if r["consumer"] not in {n["id"] for n in nodes}:
            continue
        edges.append({"id": f"S-{i:03d}", "s": r["consumer"], "t": r["provider"], "dir": "forward",
                      "label": _edge_label(r), "short": ("not in use" if r["state"] != "active" else
                                                         ORDER_WORD.get(r["order"], str(r["order"])) if r["service"] == "dns" else ""),
                      "status": "configured" if r["state"] == "active" else "inactive",
                      "evidence": r["evidence"], "detail": {"setting": r["text"], "provider side": r["side_reason"]}})

    # cluster nodes that take the service the same way are drawn as one line from their group
    groups, by = [], collections.defaultdict(list)
    for n in nodes:
        if n["kind"] == "database" and n["zone"] in {dc["key"] for dc in prof["data_centres"]}:
            by[(n["zone"], n["role"])].append(n["id"])
    for (z, role), mem in by.items():
        if len(mem) >= 2:
            gid = f"SG:{z}-{len(groups)}"
            groups.append({"id": gid, "zone": z, "label": re.sub(r"\s+node\b", " nodes", role, flags=re.I) + f" ({len(mem)})", "members": mem})
            for n in nodes:
                if n["id"] in mem: n["group"] = gid
    edges = M._rollup_groups(edges, groups)

    zones = M._zones(prof, other_sites)
    for z in zones:
        if z["id"] == "shared":
            z["label"] = "OT-resident services"
        if z["id"] == "it":
            z["label"] = "IT (enterprise) and Internet"
    view = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "zones": zones, "groups": groups,
            "nodes": nodes, "edges": edges, "notes": notes}
    return M._layout(view, prof)


# ------------------------------------------------------------------ C: zones and conduits
TRANSFER_PORTS = {"20", "21", "22", "445", "989", "990", "2049", "139",
               "7000"}   # 7000: the recorded agentService backup data path (PPDM) the STOR section asks about
MAIL_WEB_PORTS = {"25", "465", "587", "80", "443", "8080", "3128"}
ADMIN_PORTS = {"3389": "RDP", "22": "SSH", "5985": "WinRM", "5986": "WinRM", "135": "RPC", "445": "SMB", "23": "Telnet",
               "5900": "VNC", "443": "HTTPS"}


def _zone_of(model: dict) -> dict:
    z = {n["id"]: n["zone"] for n in model["nodes"]}
    z.update({g["id"]: g["zone"] for g in model.get("groups", [])})
    return z


def _endpoint_zone(x: str, zone: dict) -> str | None:
    if x.startswith("Z:"):
        return x[2:]
    return zone.get(x)


def _zone_hosts(edges: list[dict], over: dict) -> set[str]:
    """A line drawn to a whole zone (Z:<zone>) needs that zone on the page: keep the zone's hosts on those lines."""
    zone = _zone_of(over)
    ids = {n["id"] for n in over["nodes"]}
    out = set()
    for e in edges:
        for end in (e["s"], e["t"]):
            if end.startswith("Z:"):
                out |= {h for h in (e.get("detail") or {}).get("hosts", []) if h in ids and zone.get(h) == end[2:]}
                if not any(zone.get(h) == end[2:] for h in out):
                    out |= {n["id"] for n in over["nodes"] if n["zone"] == end[2:]}
    return out


def _ports(e: dict) -> set[str]:
    return {str(p) for p in (e.get("detail") or {}).get("ports", {})}


def conduit_view(over: dict, prof: dict, *, key: str, title: str, subtitle: str, scope: str = "all") -> dict:
    """Archetype C. Zones are the data centres, the shared-services band, IT and the Internet. A conduit is a captured
    flow between two zones. Flows inside one zone are left out. Every conduit with no boundary device on it in the
    evidence has status unenforced: crossing the boundary with no control evidenced. scope: all | internet | transfer."""
    zone = _zone_of(over)
    kinds = {n["id"]: n["kind"] for n in over["nodes"]}
    keep = []
    for e in over["edges"]:
        if e["status"] == "configured":
            continue
        a, b = _endpoint_zone(e["s"], zone), _endpoint_zone(e["t"], zone)
        if a is None or b is None or a == b:
            continue
        ports = _ports(e)
        if scope == "internet" and not ("G-INTERNET" in (e["s"], e["t"]) or ports & MAIL_WEB_PORTS):
            continue
        if scope == "transfer" and not ports & TRANSFER_PORTS:
            continue
        guarded = any(kinds.get(x) == "firewall" for x in (e["s"], e["t"]))
        keep.append({**e, "status": "observed" if guarded else "unenforced",
                     "detail": {**(e.get("detail") or {}), "zones": f"{a} ↔ {b}",
                                "boundary control": "a boundary device is on this path" if guarded else "none in the evidence"}})
    used = {x for e in keep for x in (e["s"], e["t"])} | _zone_hosts(keep, over)
    groups = [g for g in over.get("groups", []) if g["id"] in used or set(g["members"]) & used]
    gmem = {m for g in groups for m in g["members"]}
    nodes = [dict(n) for n in over["nodes"] if n["id"] in used or n["id"] in gmem]
    # A boundary firewall recorded in the register but not on any captured edge: keep it in the node list
    # so the brief can reflect it honestly, and mark it "register-only" so the caption does not claim
    # "no boundary control is evidenced" while the register and the evidence rows say otherwise.
    fw_in_over = [n for n in over["nodes"] if n.get("kind") == "firewall"]
    register_only_fw = [n for n in fw_in_over if n["id"] not in used and n["id"] not in gmem]
    for n in register_only_fw:
        nodes.append({**n, "register_only": True})
    notes = []
    if any(e["status"] == "unenforced" for e in keep):
        if register_only_fw:
            notes.append("A boundary firewall is recorded in the register (" + register_only_fw[0]["role"] + ") "
                         "but its address was not captured, so no individually drawn path is shown crossing it.")
        else:
            notes.append("No firewall, proxy or other boundary device appears in the evidence on these paths. "
                         "Each red line crosses a zone boundary with no boundary control evidenced.")
    if not keep:
        notes.append("No captured flow crosses a zone boundary for this question.")
    view = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "zones": over["zones"], "groups": groups,
            "nodes": nodes, "edges": keep, "notes": notes}
    return M._layout(view, prof)


# ------------------------------------------------------------------ D: access path
def access_view(over: dict, prof: dict, *, key: str, title: str, subtitle: str) -> dict:
    """Archetype D. Admin protocols (RDP, SSH, WinRM, RPC, SMB, VNC) into the assessed hosts. A path that ends on a jump
    host or starts from one is the intended route (status via-jump); an admin path from anywhere else straight to an
    OT host bypasses the jump hosts (status direct)."""
    zone = _zone_of(over)
    kinds = {n["id"]: n["kind"] for n in over["nodes"]}
    gk = {g["id"]: "group" for g in over.get("groups", [])}
    jump = {n["id"] for n in over["nodes"] if n["kind"] == "jump_host"}
    dcs = {dc["key"] for dc in prof["data_centres"]}
    keep = []
    for e in over["edges"]:
        if e["status"] == "configured":
            continue
        ports = _ports(e) & set(ADMIN_PORTS) - {"443"}
        if not ports:
            continue
        a, b = _endpoint_zone(e["s"], zone), _endpoint_zone(e["t"], zone)
        touches_jump = e["s"] in jump or e["t"] in jump
        ends = [(x, z) for x, z in ((e["s"], a), (e["t"], b))]
        inside = [x for x, z in ends if z in dcs and kinds.get(x) != "directory"]
        outside = [x for x, z in ends if z not in dcs and z != "shared"]
        from_outside = bool(inside) and bool(outside) and (e.get("dir") == "both" or e["s"] in outside)
        if not (touches_jump or from_outside):
            continue                                       # server-to-server traffic inside OT is not an access path
        protos = ", ".join(sorted({ADMIN_PORTS[p] for p in ports}))
        status = "via-jump" if touches_jump else "direct"
        keep.append({**e, "status": status, "label": protos, "detail": {**(e.get("detail") or {}), "admin protocols": protos,
                     "route": "through a jump host" if touches_jump else "from outside OT, not through a jump host"}})
    used = {x for e in keep for x in (e["s"], e["t"])} | jump | _zone_hosts(keep, over)
    groups = [g for g in over.get("groups", []) if g["id"] in used]
    gmem = {m for g in groups for m in g["members"]}
    nodes = [dict(n) for n in over["nodes"] if n["id"] in used or n["id"] in gmem]
    notes = []
    if not any(e["t"] in jump for e in keep):
        notes.append("Who connects to the jump hosts is not in the captured connections: the inbound side of the access "
                     "path is not captured.")
    if any(e["status"] == "direct" for e in keep):
        notes.append("Red lines are admin protocols reaching an OT host without passing a jump host.")
    view = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "zones": over["zones"], "groups": groups,
            "nodes": nodes, "edges": keep, "notes": notes}
    return M._layout(view, prof)
