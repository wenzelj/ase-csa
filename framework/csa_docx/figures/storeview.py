"""Store-centric figures (archetype G): where the system holds its data, and which hosts use each store.

Built from the same Discovery Information tables as archetype F (hosts/flows.csv, hosts/host_settings.csv,
hosts/hosts.csv and zones.csv), so both figures always agree on the evidence.

  * A card is the role that holds stores (RevServer cluster, OT Reveloc Server, ...). A store is identified by
    that role plus its engine and instance (a database) or its name and path (a share), so two clusters that both
    run an instance called S01 stay two stores, and a share called Temp in IT is never merged with one in OT.
  * A host uses a store only when a flow says so, never because it talks to the host that holds it:
      - database: the flow reaches a holder host and its port or listening process names the store's engine
        (sqlservr / 1433 for SQL Server, mysqld / 3306 for MySQL, ...);
      - backup agent: the flow reaches the agent on a holder host (the host is backed up, the store with it);
      - file share / file transfer: the flow reaches a holder host on SMB and the card holds shares.
    Any other flow to a holder host (web/API, management, ...) is not a use of its stores and is not drawn.
  * Replication between the holder hosts of one store is shown on the store, not as a consumer.
  * An end with no role in the host register is kept as "Role not recorded" (with its zone), never dropped
    and never given a guessed role.

    view(work_dir, over, prof, p, *, key, title, subtitle) -> model dict for store_layout.render_store_svg
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from csa_docx import flows as F
from csa_docx import zones as Z
from csa_docx.figures import flowview as FV

_DB = re.compile(r"^(SQL Server|PostgreSQL|MySQL|MariaDB|Oracle|MongoDB|Redis|Elasticsearch|InfluxDB)\b", re.I)
_INSTANCE = re.compile(r"^[^(;]*\(([^()]+)\)")
_AG = re.compile(r"availability group\s+([^\s,;]+)", re.I)
_WHOLE_DRIVE = re.compile(r"^[A-Z]:\\?$", re.I)
_USERS = re.compile(r"\\Users(?:\\|$)", re.I)
_IP = re.compile(r"^[\d.:a-fA-F%]+$")

# the engine a database flow reaches, from its listening process or port (declared rows give "1433 expected")
ENGINES = [("SQL Server", re.compile(r"sqlservr|\b1433\b|\bms-?sql\b", re.I)),
           ("MySQL", re.compile(r"mysqld|\b3306\b|\bmysql\b", re.I)),
           ("MariaDB", re.compile(r"mariadb", re.I)),
           ("PostgreSQL", re.compile(r"postgres|\b5432\b", re.I)),
           ("Oracle", re.compile(r"oracle|tnslsnr|\b1521\b", re.I)),
           ("MongoDB", re.compile(r"mongod|\b27017\b", re.I)),
           ("Redis", re.compile(r"redis|\b6379\b", re.I))]
SHARE_MECH = {"file share", "file transfer"}
USE_MECH = {"database", "backup agent"} | SHARE_MECH
DEFAULT_FLOWS = {"data": True, "status": ["observed", "both", "declared", "attempted"]}
# a whole-drive or user-folder share exposes more than a purpose-built share does
FLAG_TEXT = {"drive": "Whole drive shared", "users": "User folder shared"}


# ------------------------------------------------------------------ stores
def _engine_of(text: str) -> str:
    for name, rx in ENGINES:
        if rx.search(text or ""):
            return name
    return ""


def store_rows(settings: list[dict], exclude: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """(stores, left_out): one row per (host, store) from the host settings inventory. exclude: regexes on the
    share name for shares the profile leaves out (cluster validation test shares and the like)."""
    rx = [re.compile(x, re.I) for x in (exclude or [])]
    out, left = [], []
    for r in settings:
        v = (r.get("value") or "").strip()
        if r["attribute"] == "storage.database" and v and v != "None found":
            m = _DB.match(v)
            engine = m.group(1) if m else v.split("(")[0].strip()
            inst = _INSTANCE.match(v)
            ag = _AG.search(v)
            out.append({"host": r["host"], "kind": "database", "what": v, "engine": engine,
                        "instance": inst.group(1).strip() if inst else "", "ag": ag.group(1) if ag else "",
                        "flag": "", "source": r.get("source", ""),
                        "norm": f"db:{engine.lower()}:{(inst.group(1).strip().lower() if inst else '')}"})
        elif r["attribute"] == "storage.shares" and v and v != "Default and administrative shares only":
            for m in FV._SHARE.finditer(v):
                name, path = m.group(1).strip(), m.group(2).strip()
                row = {"host": r["host"], "kind": "share", "what": f"{name} ({path})", "engine": "", "instance": name,
                       "path": path, "ag": "", "source": r.get("source", ""),
                       "flag": "drive" if _WHOLE_DRIVE.match(path) else ("users" if _USERS.search(path) else ""),
                       "norm": f"share:{name.lower()}:{path.lower()}"}
                (left if any(x.search(name) for x in rx) else out).append(row)
    return out, left


def _short_role(role: str) -> str:
    from csa_docx.techdiagram.band_layout import short_role
    return short_role({"role": role, "kind": "server"}) if role else ""


def _store_label(s: dict) -> str:
    if s["kind"] == "database":
        return f"{s['engine']} {s['instance']}".strip() if s["instance"] else s["engine"]
    return f"Share {s['what']}"


# ------------------------------------------------------------------ the figure model
def view(work_dir, over: dict, prof: dict, p: dict, *, key: str, title: str, subtitle: str) -> dict:
    work_dir = Path(work_dir)
    rows = F.load(work_dir)
    reg_rows: dict[str, dict] = {}
    regf = work_dir / "hosts" / "hosts.csv"
    if regf.is_file():
        reg_rows = {r["host"].upper(): r for r in csv.DictReader(regf.open(encoding="utf-8"))}
    zs = Z.for_project(work_dir)
    settings = FV._settings(work_dir)
    from csa_docx import endpoints as _endpoints
    ends = _endpoints.load(work_dir)
    stores, left_out = store_rows(settings, p.get("store_exclude"))

    # site columns in page order: the overview's data-centre zones (Rockhampton left, Mackay right)
    site_zones = [z for z in over.get("zones", []) if re.search(r"data cent(re|er)$", z.get("label", ""), re.I)]

    def site_of(host: str) -> str:
        """The site a host is in (host register, else its zone rule); '' when not recorded."""
        r = reg_rows.get(host.upper())
        site = (r.get("site") or "").strip() if r else ""
        if not site:
            z = zs.of(host)
            site = re.sub(r"^(OT|IT)\s+", "", z.get("zone", "")) if z.get("kind") in ("ot", "it") else ""
        return site

    def side_of(x: str) -> tuple[str, str]:
        """(kind, zone label) for a host or address: kind is ot, it, internet, cloud or unknown."""
        z = zs.of(x)
        kind = z.get("kind", "unknown")
        return kind, ("Zone not recorded" if kind == "unknown" else z.get("zone", ""))

    def role_of(x: str, declared: bool = False) -> tuple[str, bool]:
        """(role, registered): the short role of a registered host, the name the flow map gives a declared end, or
        'Role not recorded' (an address, or a host name the captures show but the register has no role for).
        Never a guessed role."""
        r = reg_rows.get(x.upper())
        if r is not None:
            role = _short_role((r.get("role") or "").strip())
            if role:
                return role, True
            erow = ends.get(x.upper())
            elabel = _endpoints.label(erow) if erow else ""
            return elabel or "Role not recorded", True
        elabel = _endpoints.label(ends.get(x.upper()) or {})
        if elabel:
            return elabel, False
        if declared and not _IP.match(x):
            return x, False
        return "Role not recorded", False

    # ── cards: the role that holds stores, on one side (IT / OT / unknown)
    cards: dict[str, dict] = {}
    host_card: dict[str, str] = {}
    for s in stores:
        role, _ = role_of(s["host"])
        kind, _zl = side_of(s["host"])
        band = "ot" if kind == "ot" else ("it" if kind in ("it", "internet", "cloud") else "unknown")
        ck = f"{band}|{role}"
        c = cards.setdefault(ck, {"id": f"C-{re.sub(r'[^a-z0-9]+', '-', ck.lower()).strip('-')}", "role": role, "band": band,
                                  "hosts": [], "sites": {}, "stores": {}, "uses": [], "replication": []})
        if s["host"] not in c["hosts"]:
            c["hosts"].append(s["host"])
            c["sites"][s["host"]] = site_of(s["host"])
        st = c["stores"].setdefault(s["norm"], {"id": "", "kind": s["kind"], "engine": s["engine"], "instance": s["instance"],
                                                "ag": s["ag"], "label": _store_label(s), "flag": s["flag"], "instances": []})
        st["flag"] = st["flag"] or s["flag"]
        st["ag"] = st["ag"] or s["ag"]
        st["instances"].append({"host": s["host"], "what": s["what"], "source": s["source"]})
        host_card[s["host"].upper()] = ck
    for c in cards.values():
        c["hosts"].sort()
        for norm, st in c["stores"].items():
            st["id"] = f"ST-{re.sub(r'[^a-z0-9]+', '-', (c['role'] + ' ' + norm).lower()).strip('-')}"
        sites = sorted({x for x in c["sites"].values() if x})
        c["site"] = sites[0] if len(sites) == 1 else ("both" if len(sites) > 1 else "")

    # ── uses: only flows whose mechanism and port/process say they reach a store
    flt = p.get("store_flows") or DEFAULT_FLOWS
    sel = F.select(rows, flt, {h for h in reg_rows})
    acc: dict[tuple, dict] = {}
    repl: dict[tuple, dict] = {}
    unmatched: list[str] = []
    for r in sel:
        mech = r["mechanism"]
        st_ = FV.STATUS.get(r.get("status", ""), "seen")
        srcs = [e for e, _v in FV._ends(r.get("src", ""))]
        dsts = [e for e, _v in FV._ends(r.get("dst", ""))]
        if mech == "database replication":
            for s_ in srcs:
                for d_ in dsts:
                    ck = host_card.get(s_.upper())
                    if ck and ck == host_card.get(d_.upper()):
                        k = (ck, st_)
                        x = repl.setdefault(k, {"card": ck, "status": st_, "pairs": set(), "flows": [], "ports": set()})
                        x["pairs"].add(tuple(sorted((s_, d_))))
                        x["flows"].append(r["flow_id"])
                        if r.get("port"):
                            x["ports"].add(r["port"])
            continue
        if mech not in USE_MECH:
            continue
        for d_ in dsts:
            ck = host_card.get(d_.upper())
            if not ck:
                continue
            c = cards[ck]
            if mech == "database":
                eng = _engine_of(f"{r.get('dst_process', '')} {r.get('port', '')}")
                targets = [n for n, s in c["stores"].items() if s["kind"] == "database" and eng and s["engine"].lower() == eng.lower()
                           and any(i["host"].upper() == d_.upper() for i in s["instances"])]
                if not targets:
                    unmatched.append(f"{r['flow_id']} ({mech} to {d_}{', port ' + r['port'] if r.get('port') else ''})")
                    continue
            elif mech == "backup agent":
                targets = ["@host"]
            else:
                targets = ["@shares"] if any(s["kind"] == "share" for s in c["stores"].values()) and re.search(
                    r"\b445\b|smb", f"{r.get('port', '')} {r.get('dst_process', '')}", re.I) else []
                if not targets:
                    continue
            for s_ in srcs:
                if host_card.get(s_.upper()) == ck:          # a holder using its own store: replication, not a consumer
                    continue
                role, registered = role_of(s_, r.get("status") == "declared")
                kind, zl = side_of(s_)
                site = site_of(s_) if registered else ""
                for t in targets:
                    # a registered role is one row whatever zone each host is in (each host keeps its zone);
                    # ends with no role are kept apart by zone
                    k = (ck, t, role, "" if registered else zl, mech, st_)
                    u = acc.setdefault(k, {"card": ck, "target": t, "role": role, "registered": registered, "zone": zl,
                                           "zone_kind": kind, "mechanism": mech, "status": st_, "hosts": [], "sites": set(),
                                           "flows": [], "declared": [], "ports": [], "evidence": [], "on": set(),
                                           "host_zones": {}})
                    if s_ not in u["hosts"]:
                        u["hosts"].append(s_)
                    u["host_zones"][s_] = [kind, zl]
                    if site:
                        u["sites"].add(site)
                    u["on"].add(d_)
                    u["flows"].append(r["flow_id"])
                    if r.get("declared_id") and r["declared_id"] not in u["declared"]:
                        u["declared"].append(r["declared_id"])
                    if r.get("port") and r["port"] not in u["ports"]:
                        u["ports"].append(r["port"])
                    for cit in [c_ for c_ in [r.get("sources"), r.get("declared_id")] if c_]:
                        for part in [x.strip() for x in str(cit).split(";") if x.strip()]:
                            if part not in u["evidence"]:
                                u["evidence"].append(part)

    # a declared use whose hosts a seen use of the same kind already covers is the same use: keep the flow-map ID on it
    uses = list(acc.values())
    rk = lambda u: (u["card"], u["target"], u["role"], "" if u["registered"] else u["zone"], u["mechanism"])
    seen_by = {rk(u): u for u in uses if u["status"] == "seen"}
    kept = []
    for u in uses:
        s = seen_by.get(rk(u))
        if u["status"] != "seen" and s is not None and set(u["hosts"]) <= set(s["hosts"]):
            s["declared"] += [d for d in u["declared"] if d not in s["declared"]]
            s["flows"] += u["flows"]
            s["evidence"] += [e for e in u["evidence"] if e not in s["evidence"]]
            continue
        kept.append(u)
    order = {"seen": 0, "declared": 1, "attempted": 2}
    mech_order = {"database": 0, "file share": 1, "file transfer": 1, "backup agent": 2}
    for u in sorted(kept, key=lambda u: (mech_order.get(u["mechanism"], 3), order.get(u["status"], 3),
                                         u["zone_kind"] != "ot", u["role"])):
        u["hosts"].sort()
        u["sites"] = sorted(u["sites"])
        u["on"] = sorted(u["on"])
        kinds = {v[0] for v in u["host_zones"].values()}
        u["zone_kind"] = "unknown" if "unknown" in kinds else (kinds.pop() if len(kinds) == 1 else "mixed")
        u["data"] = FV._data(u["mechanism"])               # which way the data goes, seen from the side that opens
        u["opens"] = "consumer"                            # every flow row is written from the side that opens it
        cards[u["card"]]["uses"].append(u)
    for x in repl.values():
        sites = sorted({site_of(h) for pr in x["pairs"] for h in pr} - {""})
        cards[x["card"]]["replication"].append({"status": x["status"], "flows": sorted(set(x["flows"])),
                                                "ports": sorted(x["ports"]), "sites": sites,
                                                "hosts": sorted({h for pr in x["pairs"] for h in pr})})

    # ── nodes and edges, for the brief, the fit check, the hash and the explorer
    nodes, edges = [], []
    for c in cards.values():
        for h in c["hosts"]:
            nodes.append({"id": h, "label": h, "kind": "server", "role": c["role"], "zone": c["band"], "band": c["band"],
                          "card": c["id"]})
        for st in c["stores"].values():
            nodes.append({"id": st["id"], "label": st["label"], "kind": st["kind"], "role": c["role"], "zone": c["band"],
                          "band": c["band"], "card": c["id"], "flag": st["flag"], "instances": st["instances"],
                          "stores": []})
    have = {n["id"] for n in nodes}
    n_e = 0
    for c in cards.values():
        for u in c["uses"]:
            tgt = [c["stores"][u["target"]]["id"]] if not u["target"].startswith("@") else [c["id"]]
            for h in u["hosts"]:
                if h not in have:
                    nodes.append({"id": h, "label": h, "kind": "server" if u["registered"] else "unknown",
                                  "role": u["role"], "zone": "outside" if u["zone_kind"] == "unknown" else u["zone_kind"],
                                  "band": u["zone_kind"]})
                    have.add(h)
                for t in tgt:
                    n_e += 1
                    edges.append({"id": f"E{n_e:02d}", "s": h, "t": t, "mechanism": u["mechanism"], "status": u["status"],
                                  "opens": "s", "data": u["data"], "label": u["mechanism"], "evidence": list(u["evidence"]),
                                  "detail": {"flows": sorted(set(u["flows"])), "ports": u["ports"], "on": u["on"],
                                             "declared_id": ", ".join(u["declared"])}})
    for c in cards.values():
        if any(e["t"] == c["id"] for e in edges):          # a backup or share use names the card's hosts, not one store
                nodes.append({"id": c["id"], "label": f"{c['role']} hosts", "kind": "group", "role": c["role"],
                              "zone": c["band"], "band": c["band"], "card": c["id"]})

    model = {"id": f"figure-{key.lower()}", "title": title, "subtitle": subtitle, "archetype": "G", "flow": True,
             "zones": list(over.get("zones", [])), "groups": [], "nodes": nodes, "edges": edges, "notes": [],
             "cards": [_card_out(c) for c in cards.values()],
             "site_order": [z["label"] for z in site_zones],
             "left_out": [{"host": x["host"], "what": x["what"]} for x in left_out],
             "unmatched": unmatched}
    return model


def _card_out(c: dict) -> dict:
    stores = sorted(c["stores"].values(), key=lambda s: (s["kind"] != "database", not s["flag"], s["label"].lower()))
    by_norm = {n: s for n, s in c["stores"].items()}
    uses = []
    for u in c["uses"]:
        t = u["target"]
        uses.append({**{k: v for k, v in u.items() if k not in ("card",)},
                     "store": (by_norm[t]["label"] if t in by_norm else
                               ("backup of the host" if t == "@host" else "a share on the host"))})
    return {"id": c["id"], "role": c["role"], "band": c["band"], "site": c["site"],
            "hosts": [{"host": h, "site": c["sites"].get(h, "")} for h in c["hosts"]],
            "stores": [{k: v for k, v in s.items()} for s in stores], "uses": uses, "replication": c["replication"]}
