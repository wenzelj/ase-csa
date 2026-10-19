"""Store-centric figures (archetype G): the unit is the data store, not the host.

Built from the same Discovery Information tables as archetype F (hosts/flows.csv,
hosts/host_settings.csv, the host register and zones), so both figures always agree
on the evidence. Stores are grouped by role: a share with the same path on several
hosts is one store with several instances, and the instances keep their evidence.
Consumers are the hosts (or unrecorded ends) that read from or write to a store.

    view(work_dir, over, prof, p, *, key, title, subtitle) -> model dict for store_layout.render_store_svg
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from csa_docx import flows as F
from csa_docx.figures import flowview as FV
from csa_docx import zones as Z

_DB = re.compile(r"^(SQL Server|PostgreSQL|MySQL|MariaDB|Oracle|MongoDB|Redis|Elasticsearch|InfluxDB)[^,;]*", re.I)
_WHOLE_DRIVE = re.compile(r"^[A-Z]:\\?$", re.I)
_USERS = re.compile(r"\\Users(?:\\|$)", re.I)


def _norm_db(v: str) -> str:
    """Canonical store identity for a database: product + instance name (case-insensitive)."""
    m = _DB.match(v.strip())
    if not m:
        return v.strip().lower()
    s = m.group(0).strip()
    mm = re.search(r"\(([^()]+)\)\s*$", s)
    name = mm.group(1).strip().lower() if mm else ""
    return s.split("(")[0].strip().lower() + ((":" + name) if name else "")


def _norm_share(what: str) -> str:
    m = FV._SHARE.search(what)
    if not m:
        return what.lower()
    name, path = m.group(1).strip().lower(), m.group(2).strip()
    # a whole-drive or user-folder share is identity-less by path: the share name is what matters
    if _WHOLE_DRIVE.match(path) or _USERS.search(path):
        return name
    return f"{name}:{path.lower()}"


def store_rows(settings: list[dict]) -> list[dict]:
    """One row per (host, store) with kind, what, flag and source, from the host settings inventory."""
    out = []
    for r in settings:
        if r["attribute"] == "storage.database" and r["value"] != "None found":
            out.append({"host": r["host"], "kind": "database", "what": r["value"],
                        "flag": False, "source": r.get("source", ""), "norm": _norm_db(r["value"])})
        elif r["attribute"] == "storage.shares" and r["value"] != "Default and administrative shares only":
            for m in FV._SHARE.finditer(r["value"]):
                name, p = m.group(1).strip(), m.group(2).strip()
                out.append({"host": r["host"], "kind": "share", "what": f"Share {name} ({p})",
                            "flag": bool(_WHOLE_DRIVE.match(p) or _USERS.search(p)),
                            "source": r.get("source", ""), "norm": _norm_share(f"Share {name} ({p})")})
    return out


def view(work_dir, over: dict, prof: dict, p: dict, *, key: str, title: str, subtitle: str) -> dict:
    from csa_docx.techdiagram import model as M
    rows = F.load(work_dir)
    flt = p.get("flows") or FV.topic_flows(p.get("from_topic")) or {"data": True}
    es = FV.edges(rows, flt, FV._register(work_dir), FV._frame(work_dir, key))
    zs = Z.for_project(work_dir)
    settings = FV._settings(work_dir)
    reg = FV._register(work_dir)

    # ── consumer nodes: every end of a drawn flow, in its zone
    nodes: dict[str, dict] = {}
    known = {n["id"]: n for n in over["nodes"]}

    hints = F.peer_hints(rows)

    def consumer(x: str) -> str:
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
                            "band": FV.BAND_OF_KIND.get(zk, "it")}
        return x

    # ── store nodes: group the per-host store rows by canonical identity
    stores: dict[str, dict] = {}
    for r in store_rows(settings):
        s = stores.setdefault(r["norm"], {"kind": r["kind"], "label": "", "flag": False,
                                          "instances": [], "hosts": set()})
        s["flag"] = s["flag"] or r["flag"]
        s["hosts"].add(r["host"])
        s["instances"].append({"host": r["host"], "what": r["what"], "source": r["source"]})
        if not s["label"]:
            s["label"] = r["what"]

    zone_label = {z["id"]: z["label"] for z in over.get("zones", [])}
    regf = Path(work_dir) / "hosts" / "hosts.csv"
    reg_rows = {r["host"].upper(): r for r in csv.DictReader(regf.open(encoding="utf-8"))} if regf.is_file() else {}

    def site_of(host: str) -> str:
        row = reg_rows.get(host.upper())
        if row and (row.get("site") or "").strip():
            return (row.get("site") or "").strip()
        z = zs.of(host)
        if z.get("zone") and z.get("kind") in ("ot", "it"):
            return z["zone"]
        return ""

    def store_id(norm: str) -> str:
        return f"ST-{re.sub(r'[^a-z0-9]+', '-', norm).strip('-')}"

    def label_of(s: dict) -> str:
        label = s["label"]
        if s["kind"] == "share":
            m = FV._SHARE.search(label)
            label = m.group(1).strip() if m else label
        return label

    def zone_of(hosts: list[str]) -> tuple[str, str]:
        sites = [site_of(h) for h in hosts]
        real = [x for x in sites if x]
        if len(real) > 1:
            return "shared", " · ".join(dict.fromkeys(real)) or "Shared across data centres"
        site = real[0] if real else ""
        if not site:
            return "shared" if len(hosts) > 1 else "outside", "Shared across data centres" if len(hosts) > 1 else "Zone not recorded"
        if site in zone_label:
            return site, zone_label[site]
        low = {z["id"].lower(): z["id"] for z in over.get("zones", [])}
        if site.lower() in low:
            zid = low[site.lower()]
            return zid, zone_label.get(zid, zid)
        return site, site

    def dedupe(rows: list[dict]) -> list[dict]:
        seen, out = set(), []
        for r in rows:
            k = (r["host"].upper(), r["what"].lower())
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    store_nodes = []
    for norm, s in sorted(stores.items()):
        hosts = sorted(s["hosts"])
        zone, zlabel = zone_of(hosts)
        label = label_of(s)
        store_nodes.append({"id": store_id(norm), "label": label, "kind": s["kind"], "role": label,
                            "zone": zone, "zone_label": zlabel,
                            "replication": f"{len(hosts)} host(s)" if len(hosts) > 1 else "",
                            "instances": dedupe(s["instances"]), "flag": s["flag"], "marks": {}})

    # ── edges: consumer -> store. A flow connects a store when one of its ends is a host that holds the store;
    # the consumer is the other end (a registered host, or the end as recorded in the flow map).
    sid_by_host: dict[str, list[str]] = defaultdict(list)
    for norm, s in stores.items():
        for h in s["hosts"]:
            sid_by_host[h.upper()].append(store_id(norm))

    reg = {h.upper() for h in reg}

    # ── edges: a store is a consumer's when a *registered host* has a named flow to a
    # store-holder. The consumer is the other registered host; the store is attached to
    # the holder end. Raw-IP / unrecorded ends are NOT consumers — they are context, kept
    # as a note. A store-holder is not treated as consuming its own store (that would
    # invent an edge the flow map does not record).
    acc: dict[tuple, dict] = {}
    context: dict[str, list[dict]] = {}       # unrecorded end -> [(mechanism, other_registered_end, holder)]
    for e in es:
        for end, other in ((e["s"], e["t"]), (e["t"], e["s"])):
            cands = sid_by_host.get(end.upper(), [])          # `end` is a store-holder host
            if not cands:
                continue
            if end.upper() not in reg or other.upper() not in reg:
                # one end is a raw IP / unrecorded address: context, not a consumer
                ctx = context.setdefault(other, [])
                if (e["mechanism"], e.get("data") or "") not in [(m, d) for m, d, _h in ctx]:
                    ctx.append((e["mechanism"], e.get("data") or "", other))
                continue
            for sid in cands:
                k = (other, sid, e["mechanism"], e["status"])
                a = acc.setdefault(k, {"s": other, "t": sid, "mechanism": e["mechanism"], "status": e["status"],
                                       "opens": "s" if other == e["s"] else "t", "data": e["data"],
                                       "detail": {"flows": []}, "evidence": []})
                a["detail"]["flows"].extend(e["flows"])
                if e.get("port") and e["port"] not in a["detail"].get("ports", []):
                    a["detail"].setdefault("ports", []).append(e["port"])
                a["evidence"].extend(x for x in e["evidence"] if x not in a["evidence"])
    out = list(acc.values())
    for n, e in enumerate(out, 1):
        e["id"] = f"E{n:02d}"
        e["label"] = e["mechanism"]

    # consumers: the registered hosts that hold a store, or that have a named flow to one
    for e in out:
        consumer(e["s"])
    for s in stores.values():
        for h in s["hosts"]:
            if h.upper() in reg and h not in nodes:
                consumer(h)

    # ── context note: unrecorded ends that touch a store-holder
    notes: list[str] = []
    unrecorded = sorted(context)
    if unrecorded:
        role_txt = ", ".join(dict.fromkeys(e[0] for v in context.values() for e in v if e[0]))
        notes.append(
            "Context — these ends are recorded as addresses with no host role in the register "
            f"({'; '.join(unrecorded)}); they reach or are reached by a store-holder through {role_txt} "
            "but are not shown as consumers because their role is not recorded.")

    nodes_list = list(nodes.values()) + store_nodes
    zones = list(over.get("zones", []))
    have = {z["id"] for z in zones}
    for n in store_nodes:
        if n["zone"] not in have and n["zone"] != "nosite":
            zones.append({"id": n["zone"], "label": n["zone"]}); have.add(n["zone"])
    if not any(z["id"] == "shared" for z in zones):
        zones.insert(0, {"id": "shared", "label": "Shared across data centres"})
    if any(n["zone"] == "outside" for n in nodes_list) and not any(z["id"] == "outside" for z in zones):
        zones.append({"id": "outside", "label": "Zone not recorded"})

    model = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "zones": zones, "groups": [],
             "nodes": nodes_list, "edges": out, "notes": notes, "flow": True, "archetype": "G"}
    model = M._layout(model, prof)
    return model
