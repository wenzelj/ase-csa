"""Data flow figures (archetype F): the system's data stores and the flows between them, drawn from the
Discovery Information inventories (hosts/flows.csv, hosts/host_settings.csv, zones.csv and the analysis frame),
never from evidence-matrix connection rows. Every flow row is written from the side that opens the connection,
so an edge keeps who opens it (opens = "s") separately from which way the data goes (data)."""

from __future__ import annotations

import re

from csa_docx import flows as F

STATUS = {"observed": "seen", "both": "seen", "declared": "declared", "attempted": "attempted"}
# which way the data goes, by mechanism: to the opener (a backup server pulls), from the opener (a push), or both
DATA_DIRECTION = {"backup agent": "to_opener", "mail": "from_opener", "message/API": "from_opener",
                  "security agent telemetry": "from_opener", "log forwarding": "from_opener",
                  "monitoring": "from_opener", "file share": "both", "file transfer": "both",
                  "database": "both", "database replication": "both", "web/API": "both"}
_VIA = re.compile(r"\s+via\s+(.+)$", re.I)


def _ends(text: str) -> list[tuple[str, str]]:
    """[(end, via)] for one src or dst cell: declared rows list several ends and may say 'X via F5/Proxy'."""
    out = []
    for part in (p.strip() for p in (text or "").split(",")):
        if not part:
            continue
        m = _VIA.search(part)
        out.append((_VIA.sub("", part).strip(), m.group(1).strip() if m else ""))
    return out


def _data(mech: str) -> str:
    d = DATA_DIRECTION.get(mech)
    return {"to_opener": "to_s", "from_opener": "to_t", "both": "both"}.get(d, "unknown")


def edges(rows: list[dict], flt: dict | None = None, register: set[str] | None = None,
          frame: dict | None = None) -> list[dict]:
    """Directed data-flow edges, one per (opener, receiver, mechanism, status). flt: a flows.select filter.
    frame: the saved analysis frame (csa-work/topic-frames/<KEY>.json); its finding IDs become each edge's evidence."""
    if flt:
        rows = F.select(rows, flt, register)
    acc: dict[tuple, dict] = {}
    for r in rows:
        st = STATUS.get(r.get("status", ""), "seen")
        for s, via_s in _ends(r.get("src", "")):
            for t, via_t in _ends(r.get("dst", "")):
                k = (s, t, r["mechanism"], st)
                e = acc.setdefault(k, {"s": s, "t": t, "mechanism": r["mechanism"], "status": st, "opens": "s",
                                       "data": _data(r["mechanism"]), "flows": [], "ports": [], "via": "",
                                       "declared_id": "", "cross": r.get("cross_zone", ""),
                                       "zones": f"{r.get('src_zone') or 'zone not recorded'} to {r.get('dst_zone') or 'zone not recorded'}",
                                       "evidence": []})
                e["flows"].append(r["flow_id"])
                if r.get("port") and r["port"] not in e["ports"]:
                    e["ports"].append(r["port"])
                e["via"] = e["via"] or via_s or via_t
                e["declared_id"] = e["declared_id"] or r.get("declared_id", "")
                for cit in [c for c in [r.get("sources"), r.get("declared_id")] if c]:
                    for part in [p.strip() for p in re.split(r"[;]", str(cit)) if p.strip()]:
                        if part not in e["evidence"]:
                            e["evidence"].append(part)
    out = list(acc.values())
    for n, e in enumerate(out, 1):
        e["id"] = f"D{n}"
    if frame:
        for e in out:
            for s in frame.get("slots", []):
                for f in s.get("findings", []):
                    if f.get("mechanism") == e["mechanism"] and e["s"] in f.get("hosts", []) and e["t"] in f.get("hosts", []):
                        e["evidence"] += [i for i in f.get("ids", []) if i not in e["evidence"]]
    return out


# ------------------------------------------------------------------ stores, markers, controls
_SHARE = re.compile(r"\s*([^,()]+?)\s+\(([^)]*)\)")
_WHOLE_DRIVE = re.compile(r"^[A-Z]:\\?$", re.I)
_USERS = re.compile(r"\\Users(?:\\|$)", re.I)
_ITEMS = re.compile(r",(?![^()]*\))")              # split on commas that are not inside brackets
MARK_LABEL = {"edr": "EDR", "av": "Antivirus", "tools": "Transfer tools", "usb": "USB storage not restricted"}


def stores(settings: list[dict]) -> dict[str, list[dict]]:
    """{host: [{"kind": "database" | "share", "what", "flag", "source"}]} from storage.database and storage.shares.
    flag: a share of a whole drive or of user folders (drawn with a muted orange edge)."""
    out: dict[str, list[dict]] = {}
    for r in settings:
        if r["attribute"] == "storage.database" and r["value"] != "None found":
            out.setdefault(r["host"], []).append({"kind": "database", "what": r["value"], "flag": False, "source": r["source"]})
        elif r["attribute"] == "storage.shares" and r["value"] != "Default and administrative shares only":
            for m in _SHARE.finditer(r["value"]):
                name, p = m.group(1).strip(), m.group(2).strip()
                out.setdefault(r["host"], []).append({"kind": "share", "what": f"Share {name} ({p})",
                                                      "flag": bool(_WHOLE_DRIVE.match(p) or _USERS.search(p)),
                                                      "source": r["source"]})
    return out


def markers(settings: list[dict]) -> dict[str, dict]:
    """{host: {"edr", "av", "tools", "usb"}}: products running (stopped ones left out), transfer tools, and
    "not restricted" when removable storage is not set in applied Group Policy. A key is absent when none is found."""
    out: dict[str, dict] = {}
    for r in settings:
        a, v = r["attribute"], r["value"]
        m = out.setdefault(r["host"], {})
        if a == "agent.edr" and v != "None found":
            run = [x.strip() for x in _ITEMS.split(v) if x.strip() and "stopped" not in x]
            if run:
                m["edr"] = ", ".join(run)
        elif a == "agent.antivirus" and v != "None found":
            m["av"] = v
        elif a == "transfer.tools" and v != "None found":
            m["tools"] = v
        elif a == "transfer.removable":
            m["usb"] = "not restricted" if v == "Not set in applied Group Policy" else "policy set"
    return {h: m for h, m in out.items() if m}


def common(marks: dict[str, dict], hosts: set[str] | None = None) -> dict[str, str]:
    """The markers EVERY represented registered host shares, with the same value - the ones that may be stated
    once on the legend rather than on each tile. A marker is "common" only if it appears on every host in `hosts`
    (not just the hosts that happen to carry some marker): five of our hosts have no EDR row, so "all hosts: EDR"
    would be an overstatement. If fewer than all hosts carry it, it is returned qualified instead (see view())."""
    hosts = {h.upper() for h in (hosts or marks)}
    if not hosts:
        return {}
    out = {}
    for k in {key for m in marks.values() for key in m}:
        holders = {h for h in hosts if marks.get(h, {}).get(k)}
        if len(holders) == len(hosts):
            vals = {marks[h][k] for h in holders}
            if len(vals) == 1:
                out[k] = vals.pop()
    return out


def controls(edges: list[dict], kinds: dict[str, str] | None = None) -> list[dict]:
    """What is evidenced or declared on each edge that crosses (or may cross) a zone: a proxy or broker the flow map
    names ("via ..."), a boundary firewall at one end in the host register, or "not captured"."""
    kinds = kinds or {}
    out = []
    for e in edges:
        if e.get("cross") not in ("yes", "unknown"):
            continue
        if e.get("via"):
            kind = "proxy" if re.search(r"proxy", e["via"], re.I) else "broker"
            out.append({"edge": e["id"], "kind": kind, "label": e["via"], "basis": "declared in the flow map"})
        elif any(kinds.get(x) == "firewall" for x in (e["s"], e["t"])):
            out.append({"edge": e["id"], "kind": "firewall", "label": "Boundary firewall", "basis": "in the host register"})
        else:
            out.append({"edge": e["id"], "kind": "not captured", "label": "Boundary device not captured",
                        "basis": "the captures do not cover the boundary"})
    return out


# ------------------------------------------------------------------ the figure model (archetype F)
import csv as _csv
import json as _json
from pathlib import Path as _Path

TOPIC_TABLES = _Path(__file__).resolve().parents[3] / "references" / "topic-tables"
BAND_OF_KIND = {"ot": "ot", "it": "it", "internet": "it", "cloud": "it", "vendor": "it", "unknown": "it"}


def _settings(work_dir) -> list[dict]:
    f = _Path(work_dir) / "hosts" / "host_settings.csv"
    return list(_csv.DictReader(f.open(encoding="utf-8"))) if f.is_file() else []


def _register(work_dir) -> set[str]:
    f = _Path(work_dir) / "hosts" / "hosts.csv"
    return {r["host"].upper() for r in _csv.DictReader(f.open(encoding="utf-8"))} if f.is_file() else set()


def _frame(work_dir, key: str) -> dict | None:
    try:
        return _json.loads((_Path(work_dir) / "topic-frames" / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def topic_flows(name: str | None) -> dict | None:
    """The flows filter of a topic table profile (references/topic-tables/<name>.json), so table and figure agree."""
    try:
        return _json.loads((TOPIC_TABLES / f"{name}.json").read_text(encoding="utf-8")).get("flows") if name else None
    except (OSError, ValueError):
        return None


def view(work_dir, over: dict, prof: dict, p: dict, *, key: str, title: str, subtitle: str) -> dict:
    """Archetype F: data stores and data flows. p: the figure profile (its "flows" filter, else its topic table's)."""
    from csa_docx import zones as Z
    from csa_docx.techdiagram import model as M
    rows = F.load(work_dir)
    flt = p.get("flows") or topic_flows(p.get("from_topic")) or {"data": True}
    es = edges(rows, flt, _register(work_dir), _frame(work_dir, key))
    zs = Z.for_project(work_dir)
    hints = F.peer_hints(rows)
    known = {n["id"]: n for n in over["nodes"]}
    nodes: dict[str, dict] = {}

    def node(x: str) -> str:
        if x not in nodes:
            if x in known:
                nodes[x] = dict(known[x])
            else:
                zk = zs.of(x).get("kind", "unknown")
                named = not re.fullmatch(r"[\d.:a-fA-F%]+", x)     # a declared end named in the flow map, not an address
                if x in hints:
                    role, kind = f"{hints[x]['role']} (likely, confirm)", "unknown"
                elif zk == "internet":
                    role, kind = "Internet", "internet"
                elif zk == "cloud":
                    role, kind = "Cloud service", "cloud"
                elif named:
                    role, kind = x, "unknown"
                else:
                    role, kind = "Role not recorded", "unknown"
                nodes[x] = {"id": x, "label": x, "kind": kind,
                            "role": role, "zone": "outside" if zk == "unknown" else ("nosite" if zk == "ot" else "it"),
                            "band": BAND_OF_KIND.get(zk, "it")}
        return x

    medges = []
    for e in es:
        s, t = node(e["s"]), node(e["t"])
        base = {"status": e["status"], "mechanism": e["mechanism"], "data": e["data"], "evidence": e["evidence"],
                "label": e["mechanism"], "detail": {"flows": e["flows"], "ports": e["ports"], "zones": e["zones"],
                                                     "declared_id": e["declared_id"]}}
        if e.get("via"):                              # the flow map says the path goes through a proxy or broker
            v = f"VIA:{e['via']}"
            nodes.setdefault(v, {"id": v, "label": e["via"], "kind": "server", "role": f"{e['via']} (declared)",
                                 "zone": "boundary", "band": "boundary"})
            medges += [{**base, "id": e["id"] + "a", "s": s, "t": v}, {**base, "id": e["id"] + "b", "s": v, "t": t}]
        else:
            medges.append({**base, "id": e["id"], "s": s, "t": t})
    ctl = controls(es, {n["id"]: n.get("kind", "") for n in nodes.values()})
    if any(c["kind"] == "not captured" for c in ctl):
        nodes["GAP:boundary"] = {"id": "GAP:boundary", "label": "Boundary device", "kind": "gap", "role": "Boundary device",
                                 "gap_text": "Not captured", "zone": "boundary", "band": "boundary"}
    settings = _settings(work_dir)
    reg = _register(work_dir)
    st, mk = stores(settings), markers(settings)
    # stores belong to the evidenced host that holds them; a shared tile (same role, several sites) shows its hosts'
    # stores together, and the legend note says which hosts, so no site is silently merged into a shared store.
    host_stores: dict[str, list] = {n["id"]: st.get(n["id"], []) for n in nodes.values()}
    for n in nodes.values():
        n["stores"] = host_stores[n["id"]]
        n["marks"] = mk.get(n["id"], {})
    zones = list(over["zones"])
    if any(n["zone"] == "outside" for n in nodes.values()) and not any(z["id"] == "outside" for z in zones):
        zones.append({"id": "outside", "label": "Zone not recorded"})
    boundary = any(n["zone"] == "boundary" for n in nodes.values())
    if boundary and not any(z["id"] == "boundary" for z in zones):
        zones.append({"id": "boundary", "label": "IT / OT boundary"})
    rep = {n["id"].upper() for n in nodes.values()} & {h.upper() for h in reg}
    common_mk = common({h: m for h, m in mk.items() if h.upper() in rep}, hosts=rep)
    # any marker held by only some represented hosts is stated on exactly those hosts, never as "all hosts"
    partial: dict[str, tuple[str, list[str]]] = {}
    for k in {key for m in mk.values() for key in m}:
        holders = sorted(h for h in rep if mk.get(h, {}).get(k))
        if holders and len(holders) != len(rep):
            partial[k] = (" · ".join(holders), holders)
    model = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "zones": zones, "groups": [],
             "nodes": list(nodes.values()), "edges": medges, "notes": [], "flow": True, "controls": ctl,
             "common_marks": common_mk, "partial_marks": partial, "outside_label": "Zone not recorded"}
    model = M._layout(model, prof)
    if boundary and "boundary" not in model["layout"]["top"]:   # the screen view puts boundary nodes in its top band
        model["layout"]["top"].append("boundary")
    return model
