"""Diagram models from a project's evidence: one system overview plus one numbered data-flow
diagram per journey.

Inputs are the same live structures the Evidence Workspace uses:
  net      evidence-browser network.build(): nodes {id, kind, role, site, ips} and captured
           connections {s, t, port, procs, ids, est}
  spec     csa-work/explorer/journeys.json: components, dependencies, journeys (may be empty)
  profile  the project's layout (csa-context/system-diagrams.json): which sites are the data
           centres, left to right, and the band labels. Without one, the two sites with the most
           hosts become the data centres.

Nothing is inferred. A node's type comes from the role recorded against it (never from its
name); a host with no recorded role is drawn as "Role not recorded".
"""
from __future__ import annotations

import collections
import re

WELL_KNOWN = {"443": "HTTPS", "80": "HTTP", "445": "SMB", "135": "RPC", "3306": "MySQL", "1433": "SQL",
              "53": "DNS", "88": "Kerberos", "389": "LDAP", "636": "LDAPS", "123": "NTP", "25": "SMTP",
              "3389": "RDP", "22": "SSH", "8080": "HTTP-alt", "514": "syslog"}
# Tier rows inside a data centre, top to bottom; a row is drawn only when something sits in it.
TIER = {"firewall": "net", "switch": "net", "router": "net",
        "jump_host": "access", "terminal": "access", "hmi": "access",
        "app_server": "app", "radio": "app", "logging": "app", "server": "app", "unknown": "app",
        "hypervisor": "app", "dns": "app", "time": "app", "backup": "app",
        "workstation": "access", "scada": "app", "vm": "app", "dhcp": "app", "api": "app", "rack": "app",
        "wireless": "net", "cloud": "app",
        "database": "db", "historian": "db", "storage": "db",
        "plc": "ot", "rtu": "ot"}
TIERS = [["net", "Network"], ["access", "Access"], ["app", "Application\nand logging"], ["db", "Database\nand storage"],
         ["ot", "Control and\nfield devices"]]
DEFAULT_LABELS = {"top": "IT, Internet and other networks", "shared": "Shared services: directory, DNS and time",
                  "nosite": "Site not recorded", "outside": "Location not captured"}
STATUS_OF = {"verified": "observed", "inferred": "inferred", "documented": "documented", "unknown": "unknown"}
DEP_WHAT = {"RESOLVES_VIA": "DNS", "AUTHENTICATES_WITH": "Kerberos", "DEPENDS_ON": "Time"}
NOISE_PROCS = {"closed", "System", "svchost", ""}


# ------------------------------------------------------------------ classification
RULES = [  # (pattern on the recorded role, kind) -- first match wins; order matters
    (r"domain controller", "directory"),
    (r"historian|\bpi server\b|osisoft|aveva pi", "historian"),
    (r"sql server|database|\bdb\b|oracle|postgres|mysql", "database"),
    (r"jump host|jump server|bastion", "jump_host"),
    (r"\bhmi\b|scada client|operator station|human.machine", "hmi"),
    (r"\bscada\b", "scada"),
    (r"engineering (?:workstation|station)|\bews\b", "workstation"),
    (r"radio manager", "radio"),
    (r"workstation|operator|reviewer|revviewer|radio management|console", "terminal"),
    (r"log server|logging|syslog|\bsiem\b", "logging"),
    (r"firewall", "firewall"),
    (r"\bswitch\b", "switch"),
    (r"\brouter\b|gateway router", "router"),
    (r"hypervisor|esxi|vmware host|hyper-v|virtuali[sz]ation host", "hypervisor"),
    (r"\bsan\b|\bnas\b|storage", "storage"),
    (r"backup server|backup target|backup appliance", "backup"),
    (r"\bdns\b", "dns"),
    (r"\bdhcp\b", "dhcp"),
    (r"wireless|access point|\bwap\b|wi-?fi", "wireless"),
    (r"virtual machine|\bvm\b", "vm"),
    (r"\bntp\b|time server|time source", "time"),
    (r"\bplc|programmable logic|modicon|controllogix|compactlogix|simatic|\bs7-?\d", "plc"),
    (r"\brtu|remote terminal unit", "rtu"),
    (r"application|app server|virtual server|broadcast|gateway", "app_server"),
]


def classify(role: str, kind: str) -> tuple[str, str]:
    r = (role or "").lower()
    if kind == "dc":
        return "directory", "Recorded as a domain controller"
    for pat, k in RULES:
        if re.search(pat, r):
            return k, "Role recorded: " + role
    if r.strip():                                  # a role is recorded, just not one of the known types
        return "server", "Role recorded: " + role + " (no specific system type matched; drawn as a server)"
    return "unknown", "No role recorded in the evidence"


def port_label(port: str, procs) -> str:
    p = [x for x in procs if x not in NOISE_PROCS]
    s = f"TCP {port}" if str(port).isdigit() else ("dynamic RPC" if port == "dynamic" else str(port))
    if WELL_KNOWN.get(str(port)):
        s += f" {WELL_KNOWN[str(port)]}"
    if p:
        s += f" · {p[0]}"
    return s


# ------------------------------------------------------------------ profile
def resolve_profile(net: dict, profile: dict | None) -> dict:
    profile = dict(profile or {})
    if not profile.get("data_centres"):
        counts = collections.Counter(n.get("site") for n in net["nodes"] if n.get("site") and n.get("kind") not in ("unnamed", "public"))
        profile["data_centres"] = [{"key": f"dc{i}", "label": s, "sites": [s]} for i, (s, _) in enumerate(counts.most_common(2))]
    for i, dc in enumerate(profile["data_centres"]):
        dc.setdefault("key", f"dc{i}")
        dc["sites_lc"] = {s.lower() for s in dc.get("sites", [])}
    profile.setdefault("top_label", DEFAULT_LABELS["top"])
    profile.setdefault("shared_label", DEFAULT_LABELS["shared"])
    return profile


def _dc_for_site(site: str, profile: dict) -> str | None:
    s = (site or "").strip().lower()
    for dc in profile["data_centres"]:
        if s and s in dc["sites_lc"]:
            return dc["key"]
    return None


def _zones(profile: dict, other_sites: list[str]) -> list[dict]:
    z = [{"id": "it", "label": profile["top_label"]}]
    z += [{"id": "nosite", "label": DEFAULT_LABELS["nosite"]}]
    z += [{"id": "site:" + s, "label": s} for s in other_sites]
    z += [{"id": "outside", "label": DEFAULT_LABELS["outside"]}]
    z += [{"id": dc["key"], "label": dc["label"]} for dc in profile["data_centres"]]
    z += [{"id": "shared", "label": profile["shared_label"]}]
    return z


def _layout(model: dict, profile: dict) -> dict:
    present = {n["zone"] for n in model["nodes"]}
    top = [z["id"] for z in model["zones"] if z["id"] in present and (z["id"] in ("it", "nosite", "outside") or z["id"].startswith("site:"))]
    model["layout"] = {"type": "tracks", "top": top,
                       "dcs": [dc["key"] for dc in profile["data_centres"] if dc["key"] in present],
                       "bottom": ["shared"] if "shared" in present else [], "tiers": TIERS}
    dcs = set(model["layout"]["dcs"])
    for n in model["nodes"]:
        n["tier"] = TIER.get(n["kind"], "app") if n["zone"] in dcs else None
    return model


# ------------------------------------------------------------------ overview
def overview(net: dict, spec: dict, profile: dict, application: str) -> dict:
    profile = resolve_profile(net, profile)
    linked = {e["s"] for e in net["edges"]} | {e["t"] for e in net["edges"]}
    nodes, loose, other_sites = [], [], []
    for n in net["nodes"]:
        if n.get("kind") in ("unnamed", "public"):
            continue
        if not n.get("role") and not n.get("site") and n["id"] not in linked:
            loose.append(n["id"]); continue
        kind, basis = classify(n.get("role", ""), n.get("kind", ""))
        dc = _dc_for_site(n.get("site", ""), profile)
        if kind == "directory":
            zone, under = "shared", dc
        elif dc:
            zone, under = dc, None
        elif n.get("site"):
            zone, under = "site:" + n["site"], None
            if n["site"] not in other_sites: other_sites.append(n["site"])
        else:
            zone, under = "nosite", None
        role = n.get("role") or "Role not recorded"
        if kind == "directory":
            role = "Domain controller" + (f", site {n['site']}" if n.get("site") else "")
        ips = [i.strip() for i in re.split(r"[;,]", n.get("ips") or "") if i.strip() and not i.strip().endswith(".0") and not i.strip().startswith("169.254")]
        nodes.append({"id": n["id"], "label": n["id"], "role": role, "kind": kind, "zone": zone, "under": under,
                      "kind_basis": basis, "ips": ips, "host": True})
    cnt = collections.Counter(n.get("kind") for n in net["nodes"])
    groups_ = {"unnamed": "G-INTERNAL", "public": "G-INTERNET"}
    if cnt["unnamed"]:
        nodes.append({"id": "G-INTERNAL", "label": f"{cnt['unnamed']} internal addresses", "role": "Name and network not captured",
                      "kind": "internal", "zone": "it", "kind_basis": "Private addresses seen in connection captures; host name not captured",
                      "ips": [n["id"] for n in net["nodes"] if n.get("kind") == "unnamed"]})
    if cnt["public"]:
        nodes.append({"id": "G-INTERNET", "label": f"{cnt['public']} public addresses", "role": "Internet; owner not identified",
                      "kind": "internet", "zone": "it", "kind_basis": "Public addresses seen in connection captures",
                      "ips": [n["id"] for n in net["nodes"] if n.get("kind") == "public"]})
    kinds = {n["id"]: n.get("kind") for n in net["nodes"]}
    shown = {n["id"] for n in nodes}
    zone_of = {n["id"]: n["zone"] for n in nodes}
    grp = lambda i: groups_.get(kinds.get(i), i)

    # captured connections, merged per pair; addresses without names roll up per zone
    agg = collections.OrderedDict()
    for e in net["edges"]:
        s, t = grp(e["s"]), grp(e["t"])
        if s == t or s not in shown or t not in shown:
            continue
        if s.startswith("G-") or t.startswith("G-"):
            a = s if s.startswith("G-") else "Z:" + zone_of[s]
            b = t if t.startswith("G-") else "Z:" + zone_of[t]
        else:
            a, b = s, t
        key = tuple(sorted((a, b)))
        d = agg.setdefault(key, {"dirs": set(), "ports": collections.Counter(), "procs": collections.defaultdict(set),
                                 "ids": set(), "n": 0, "hosts": set()})
        d["dirs"].add((a, b)); d["ports"][str(e["port"])] += 1; d["procs"][str(e["port"])].update(e.get("procs") or [])
        d["ids"].update(e.get("ids") or []); d["n"] += 1
        d["hosts"].update(x for x in (e["s"], e["t"]) if not grp(x).startswith("G-"))
    edges = []
    for i, (key, d) in enumerate(agg.items(), 1):
        a, b = sorted(d["dirs"])[0] if len(d["dirs"]) == 1 else key
        top = [port_label(p, sorted(d["procs"][p])) for p, _ in d["ports"].most_common(2)]
        more = len(d["ports"]) - len(top)
        label = "\n".join(top) + (f"\n+{more} more ports" if more > 0 else "")
        edges.append({"id": f"L-{i:03d}", "s": a, "t": b, "dir": "both" if len(d["dirs"]) > 1 else "forward",
                      "label": label, "status": "observed", "evidence": sorted(d["ids"]),
                      "detail": {"connections": d["n"], "ports": dict(d["ports"]), "hosts": sorted(d["hosts"])}})

    # database cluster groups: database servers of one data centre that share a recorded role
    groups = []
    by = collections.defaultdict(list)
    for n in nodes:
        if n["kind"] == "database" and n["zone"] in {dc["key"] for dc in profile["data_centres"]}:
            by[(n["zone"], n["role"])].append(n["id"])
    for (z, role), mem in by.items():
        if len(mem) >= 2:
            gid = f"SG:{z}-{len(groups)}"
            lab = re.sub(r"\s+node\b", " nodes", role, flags=re.I)
            groups.append({"id": gid, "zone": z, "label": f"{lab} ({len(mem)})", "members": mem})
            for n in nodes:
                if n["id"] in mem: n["group"] = gid
    edges = _rollup_groups(edges, groups)
    edges = _rollup_fans(edges, nodes, groups)

    # configured dependencies (DNS, Kerberos, time) from journeys.json
    for i, (s, t, what, ids, notes) in enumerate(_deps(spec), 1):
        if s in shown and t in shown:
            edges.append({"id": f"C-{i:03d}", "s": s, "t": t, "dir": "forward", "label": " · ".join(what),
                          "status": "configured", "evidence": ids, "detail": {"settings": notes}})

    notes = []
    if not any(n["kind"] == "firewall" for n in nodes):
        notes.append("No firewall, router or switch appears in the captured evidence, so none is drawn. "
                     "Boundary controls between sites and the Internet are not evidenced.")
    if loose:
        notes.append(f"Also in the inventory with no role, site or captured connection: {', '.join(sorted(loose))}.")
    model = {"id": "system-overview", "title": f"{application}: hosts, sites and observed connections",
             "subtitle": "Named hosts from the connection captures, grouped by data centre and tier. Unnamed and public addresses are rolled up.",
             "zones": _zones(profile, other_sites), "groups": groups, "nodes": nodes, "edges": edges, "notes": notes}
    return _layout(model, profile)


def _deps(spec: dict):
    agg = collections.OrderedDict()
    for dep in spec.get("dependencies", []) or []:
        for t in dep.get("to") or []:
            d = agg.setdefault((dep["from"], t), {"what": [], "ids": set(), "notes": []})
            w = DEP_WHAT.get(dep.get("kind", ""), dep.get("kind", "").replace("_", " ").title())
            if w not in d["what"]: d["what"].append(w)
            d["ids"].update(dep.get("evidence") or []); d["notes"].append(dep.get("label", ""))
    return [(s, t, d["what"], sorted(d["ids"]), d["notes"]) for (s, t), d in agg.items()]


def _rollup_groups(edges, groups):
    member_of = {m: g["id"] for g in groups for m in g["members"]}
    bucket = collections.defaultdict(list)
    for e in edges:
        for end, other in (("t", "s"), ("s", "t")):
            g = member_of.get(e[end])
            if g and member_of.get(e[other]) != g and not e[other].startswith("Z:"):
                bucket[(g, end, e[other], e["label"], e["dir"])].append(e); break
    drop, new = set(), []
    for (g, end, other, label, dr), es in bucket.items():
        if len(es) < 2: continue
        n = {"id": "G" + es[0]["id"], end: g, ("s" if end == "t" else "t"): other, "dir": dr,
             "label": label, "status": es[0]["status"], "short": es[0].get("short"),
             "evidence": sorted({i for e in es for i in e["evidence"]}),
             "detail": {"connections": sum(e["detail"].get("connections", 1) for e in es), "hosts": sorted({h for e in es for h in e["detail"].get("hosts", [])})}}
        drop.update(e["id"] for e in es); new.append(n)
    return [e for e in edges if e["id"] not in drop] + new


def _rollup_fans(edges, nodes, groups):
    """Many hosts of one zone calling the same domain controller become one line from that zone."""
    kind_of = {n["id"]: n["kind"] for n in nodes}
    zone_of = {n["id"]: n["zone"] for n in nodes}
    zone_of.update({g["id"]: g["zone"] for g in groups})
    fan = collections.defaultdict(list)
    for e in edges:
        if e["s"].startswith(("Z:", "G-")) or e["t"].startswith(("Z:", "G-")) or e["dir"] == "both":
            continue
        if kind_of.get(e["t"]) == "directory" and zone_of.get(e["s"]) != zone_of.get(e["t"]):
            fan[(zone_of.get(e["s"]), e["t"])].append(e)
    drop, new = set(), []
    for (z, dc), es in fan.items():
        if len(es) < 3: continue
        ports = sorted({l.split(" · ")[0] for e in es for l in e["label"].split("\n") if not l.startswith(("+", "("))})
        new.append({"id": "F" + es[0]["id"], "s": "Z:" + z, "t": dc, "dir": "forward",
                    "label": "\n".join(ports[:2]), "status": "observed",
                    "evidence": sorted({i for e in es for i in e["evidence"]}),
                    "detail": {"hosts": sorted({h for e in es for h in e["detail"].get("hosts", [])}),
                               "connections": sum(e["detail"].get("connections", 1) for e in es)}})
        drop.update(e["id"] for e in es)
    return [e for e in edges if e["id"] not in drop] + new


# ------------------------------------------------------------------ journeys
def journeys(spec: dict, over: dict, profile: dict) -> list[dict]:
    comp = {c["id"]: c for c in spec.get("components", []) or []}
    host_node = {n["id"]: n for n in over["nodes"]}
    out = []
    for jj in spec.get("journeys", []) or []:
        fn, fe = [], []
        def add(nid, role=None):
            if any(x["id"] == nid for x in fn) or nid not in host_node: return
            h = {k: v for k, v in host_node[nid].items() if k not in ("group", "tier")}
            if role: h["role"] = role
            fn.append(h)
        for t in jj.get("transitions", []):
            for cid in (t["from"], t["to"]):
                c = comp.get(cid)
                if c and c.get("host"): add(c["host"], c.get("name"))
                elif c and not any(x["id"] == cid for x in fn):
                    name = c.get("name", cid); low = (name + " " + c.get("role", "")).lower()
                    kind = "mail" if re.search(r"mail|smtp", low) else ("backup" if "backup" in low else "unknown")
                    fn.append({"id": cid, "label": name, "role": c.get("role", "")[:60],
                               "kind": kind, "zone": "it" if kind == "mail" else "outside",
                               "kind_basis": "External system named in the journey", "ips": []})
        for s in jj.get("steps", []):
            c = comp.get(s.get("component") or "")
            if c and c.get("host"): add(c["host"], c.get("name"))
        deps = [d for d in _deps(spec) if any(x["id"] == d[0] for x in fn)]
        for s, t, *_ in deps: add(t)
        for n, t in enumerate(jj.get("transitions", []), 1):
            s_ = (comp.get(t["from"]) or {}).get("host") or t["from"]
            d_ = (comp.get(t["to"]) or {}).get("host") or t["to"]
            lab = t.get("payload", "")
            if t.get("port"): lab += "\n" + f"{t.get('protocol', '')} {t['port']}".strip()
            fe.append({"id": t["id"], "s": s_, "t": d_, "dir": "forward", "step": n, "label": lab,
                       "status": STATUS_OF.get(t.get("status"), "unknown"), "evidence": t.get("evidence", []),
                       "detail": {k: t[k] for k in ("inference", "unknown") if k in t}})
        for i, (s, t, what, ids, notes) in enumerate(deps, 1):
            if any(x["id"] == t for x in fn):
                fe.append({"id": f"C-{i:03d}", "s": s, "t": t, "dir": "forward", "label": " · ".join(what),
                           "status": "configured", "evidence": ids, "detail": {"settings": notes}})
        steps = []
        for n, t in enumerate(jj.get("transitions", []), 1):
            st = next((s for s in jj.get("steps", []) if t["id"] in str(s.get("transition", ""))), None)
            steps.append({"n": n, "text": (st or {}).get("action", t.get("payload", "")), "status": STATUS_OF.get(t.get("status"), "unknown")})
        model = {"id": "flow-" + jj["id"], "title": "Data flow: " + jj.get("title", jj["id"]),
                 "subtitle": (jj.get("trigger") or {}).get("text", ""), "zones": over["zones"], "groups": [],
                 "nodes": fn, "edges": fe, "steps": steps, "notes": ["Step numbers give the documented order; they are not timings."]}
        out.append(_layout(model, profile))
    return out


def build_models(net: dict, spec: dict | None, profile: dict | None, application: str) -> list[dict]:
    spec = spec or {}
    prof = resolve_profile(net, profile)
    over = overview(net, spec, prof, application)
    return [over] + journeys(spec, over, prof)
