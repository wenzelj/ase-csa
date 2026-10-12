"""Band layout: the CSA figure as IT, the IT/OT boundary and OT, top to bottom, one icon per machine role.

Design (see README "Figure design"):

  * three full-width bands in Purdue order: IT and Internet at the top, the IT / OT boundary in the middle, OT
    at the bottom; every line out of OT visibly crosses the boundary band;
  * the boundary band holds the systems whose recorded role is a boundary function (jump host, firewall,
    remote access); when lines cross with no boundary control evidenced, it holds a "None evidenced" marker;
  * OT sites (data centres, other sites, site not recorded, OT-resident services) are panels inside the OT band;
  * one tile per machine role in a site: a large icon, the role in bold, the host names small underneath, and a
    count when several hosts share the role; connections inside one tile are not drawn;
  * a line between two tiles means one or more of their hosts connect; it is labelled with the service
    (SMB, RPC, Time, DNS), never a port list; lines to one system share a trunk;
  * every line runs in a clear corridor: vertical lines in the gutters between tile columns, horizontal lines in
    the channel above a tile row, and enter or leave a tile at the top of its icon;
  * the drawing is 1000 units wide, placed at the CSA's 17 cm text width; no text is under 17 units (8.2 pt).

    render_band_svg(model, band_of=None) -> (svg, info)
"""
from __future__ import annotations

import html
import math
import re
from collections import defaultdict

from .icons import GREY, ICONS, KINDS, NAVY, RED, TEAL

W = 1000.0
TEXT_W_MM = 170.0
MM = TEXT_W_MM / W
PAGE_H_MAX = 1350
F_BAND, F_ZONE, F_NAME, F_TEXT = 19, 17, 17, 17
NCOL = 4
CW = 172.0                                     # tile column width
G = (W - NCOL * CW) / (NCOL + 1)               # gutter width (left margin, between columns, right margin)
ICON = 42.0                                    # icon size in units
LANE = 11.0
LINE_H = 20.0
MUTED = "#55677a"
BORDER = "#b9c8d3"
BAND_FILL = {"it": "#f2f7fc", "boundary": "#fff8f0", "ot": "#f1f9f7"}
BAND_TITLE = {"it": "IT AND INTERNET", "boundary": "IT / OT BOUNDARY", "ot": "OPERATIONAL TECHNOLOGY (OT)"}
SUB_FILL = {"ot": "#ffffff", "it": "#ffffff", "boundary": "#ffffff"}
STATUS_STYLE = {
    "observed": (TEAL, "", 2.6, "Observed in connection captures"),
    "configured": (TEAL, "8 5", 2.4, "Configured setting"),
    "inactive": (GREY, "2.5 4", 2.4, "Configured, not in use"),
    "inferred": (NAVY, "8 5", 2.2, "Inferred, to validate"),
    "documented": (NAVY, "2.5 4", 2.4, "Documented only"),
    "unknown": (RED, "8 5", 2.4, "Path not captured"),
    "unenforced": (RED, "", 2.8, "Crosses a zone, no control evidenced"),
    "direct": (RED, "", 2.8, "From outside OT, no jump host"),
    "via-jump": ("#1a7f37", "", 2.6, "Through a jump host"),
}
STATUS_DASH = {                                # evidence status -> (dash, width); the colour is the function
    "observed": ("", 2.8), "unenforced": ("", 2.8), "direct": ("", 2.8), "via-jump": ("", 2.8),
    "configured": ("9 5", 2.6), "inferred": ("9 5", 2.4), "unknown": ("14 6", 2.6),
    "inactive": ("2.5 4.5", 2.6), "documented": ("2.5 4.5", 2.6),
}
STATUS_LABEL = {"observed": "Solid: observed in connection captures", "unenforced": "Solid: crosses a zone, no control evidenced",
                "direct": "Solid: from outside OT, no jump host", "via-jump": "Solid: through a jump host",
                "configured": "Dashed: configured setting", "inferred": "Dashed: inferred, to validate",
                "unknown": "Long dash: path not captured", "inactive": "Dotted: configured, not in use",
                "documented": "Dotted: documented only"}
STATUS_PHRASE = {"observed": "observed", "configured": "configured setting", "inactive": "configured, not in use",
                 "unenforced": "crosses a zone, no control evidenced", "direct": "from outside OT, no jump host",
                 "via-jump": "through a jump host", "unknown": "path not captured", "inferred": "inferred, to validate",
                 "documented": "documented only"}
BUS_GAP = 12.0
GAP_COL = "#b4602a"                             # a missing control or service: muted orange, not alarm red
# Line colour is the function of the traffic; the line style is its evidence status. Muted colours that stay
# apart in print and for the common colour-vision deficiencies; no alarm red.
FUNCTIONS = {
    "directory": ("#7b5ea7", "Directory, name and time services"),
    "management": ("#b7791f", "Management and monitoring"),
    "web": ("#2f6fb0", "Web and Internet"),
    "application": ("#167d8d", "Application and database"),
    "other": ("#6b7785", "Other ports (no service name captured)"),
}
DIRECTORY_SVCS = {"DNS", "Time", "NTP", "Kerberos", "LDAP", "LDAPS"}
MANAGEMENT_SVCS = {"RPC", "SMB", "RDP", "SSH", "WinRM", "VNC", "Telnet", "SNMP", "Syslog", "HealthService", "agentService",
                   "WmiPrvSE", "mstsc"}
WEB_SVCS = {"HTTP", "HTTPS", "HTTP-alt"}


def classify(svc: str, kinds: set[str]) -> str:
    """The function of one named service, from its name and the roles at its ends (stated in the legend)."""
    if svc in DIRECTORY_SVCS or (svc in ("RPC", "SMB") and "directory" in kinds):
        return "directory"
    if svc in MANAGEMENT_SVCS:
        return "management"
    if svc in WEB_SVCS:
        return "web"
    if re.match(r"(TCP|UDP)\s+\d+$", svc) or svc.isdigit():
        return "other"
    return "application"


BOUNDARY_ROLE = re.compile(r"\bjump\b|firewall|bastion|remote access|data diode|\bproxy\b|\bdmz\b", re.I)
WELL_KNOWN = {"445": "SMB", "139": "SMB", "135": "RPC", "3389": "RDP", "22": "SSH", "23": "Telnet", "443": "HTTPS",
              "80": "HTTP", "8080": "HTTP", "53": "DNS", "123": "NTP", "25": "SMTP", "587": "SMTP", "1433": "SQL",
              "5985": "WinRM", "5986": "WinRM", "5900": "VNC", "389": "LDAP", "636": "LDAPS", "88": "Kerberos",
              "161": "SNMP", "514": "Syslog", "502": "Modbus", "20000": "DNP3", "2404": "IEC 104", "102": "S7"}
esc = lambda s: html.escape(str(s), quote=True)


# ------------------------------------------------------------------ text helpers
_NARROW = set("iljI.,:;'|!()[]")
_SEMI = set("frt -/1")
_WIDE = set("mwMW")


def _cw(ch: str, bold: bool) -> float:
    """Approximate Helvetica / Arial advance width, in em."""
    if ch in _NARROW:
        return 0.28 if bold else 0.24
    if ch in _SEMI:
        return 0.36 if bold else 0.32
    if ch in _WIDE:
        return 0.92 if bold else 0.84
    if ch.isupper():
        return 0.72 if bold else 0.67
    return 0.6 if bold else 0.55


def _tw(text: str, size: float, bold: bool = False) -> float:
    return sum(_cw(c, bold) for c in text) * size


def _wrap(text: str, units: float, size: float, bold: bool = False, lines: int = 2) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        cand = f"{cur} {w}" if cur else w
        if cur and _tw(cand, size, bold) > units:
            out.append(cur); cur = w
        else:
            cur = cand
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[: lines - 1] + [" ".join(out[lines - 1:])]
    res = []
    for l in out:
        while _tw(l, size, bold) > units and len(l) > 4:
            l = l[:-2].rstrip() + "…"
        res.append(l)
    return res


def short_role(n: dict) -> str:
    """The machine role as the tile names it: the recorded role without site, domain or instance detail."""
    kind = n.get("kind", "unknown")
    if kind in ("internal", "internet") and not n.get("host"):
        return KINDS[kind][1] if n["id"].startswith("G-") else (n.get("role") or KINDS[kind][1])
    role = (n.get("role") or "").strip()
    if not role:
        return KINDS.get(kind, KINDS["unknown"])[1]
    role = re.sub(r"\s*·\s*(enterprise \(IT\)|OT)\s*$", "", role)
    role = re.sub(r",\s*site\s+\S+", "", role)
    role = re.sub(r"\s*\((instance|site)\b[^)]*\)", "", role)
    role = re.sub(r"\bcluster nodes?\b", "cluster", role, flags=re.I)
    role = re.sub(r"\s*\(\d+\)\s*$", "", role)
    return role.strip() or KINDS.get(kind, KINDS["unknown"])[1]


def members_label(ids: list[str]) -> str:
    """ROTPRDCLU101..104 -> ROTPRDCLU101–104; mixed names -> first two and a count."""
    m = [re.fullmatch(r"(.*?)(\d+)", i) for i in ids]
    if len(ids) > 1 and all(m) and len({x.group(1) for x in m}) == 1:
        stem, nums = m[0].group(1), sorted(int(x.group(2)) for x in m)
        wd = len(m[0].group(2))
        if nums == list(range(nums[0], nums[-1] + 1)):
            return f"{stem}{nums[0]:0{wd}d}–{nums[-1]:0{wd}d}"
        return f"{stem}{nums[0]:0{wd}d}, " + ", ".join(f"{k:0{wd}d}" for k in nums[1:])
    if len(ids) <= 2:
        return ", ".join(ids)
    return f"{ids[0]}, {ids[1]} +{len(ids) - 2}"


def service_names(e: dict) -> tuple[list[str], int]:
    """Services on a line, named by the evidence: a well-known name, else the process, else the port."""
    if e.get("status") in ("configured", "inactive"):
        base = (e.get("label") or "").split("\n")[0]
        base = re.sub(r":.*$", "", base)
        base = re.sub(r"\s+(1st|2nd|3rd|\d+th)$", "", base).strip()
        return ([x.strip() for x in base.split("·") if x.strip()] or [e.get("short") or ""]), 0
    out, more = [], 0
    for ln in (e.get("label") or "").split("\n"):
        ln = ln.strip()
        mm = re.match(r"\+(\d+) more", ln)
        if mm:
            more += int(mm.group(1)); continue
        if not ln:
            continue
        proc = ln.split("·")[1].strip() if "·" in ln else ""
        head = ln.split("·")[0].strip()
        port = re.search(r"(\d+)", head)
        named = re.sub(r"^(TCP|UDP)\s+\d+\s*", "", head).strip()
        if head.lower().startswith("dynamic rpc"):
            out.append("RPC")
        elif port and port.group(1) in WELL_KNOWN:
            out.append(WELL_KNOWN[port.group(1)])
        elif named and not named.isdigit():
            out.append(named)
        elif proc:
            out.append(proc)
        else:
            out.append(head)
    return list(dict.fromkeys(out)), more


def _join_label(svcs: list[str], more: int, width: float) -> list[str]:
    svcs = [s for s in dict.fromkeys(svcs) if s]
    shown, extra = svcs[:3], len(svcs) - 3 + more
    text = ", ".join(shown) + (f" +{extra}" if extra > 0 else "")
    return _wrap(text, width, F_TEXT, lines=2) if text else []


# ------------------------------------------------------------------ bands and tiles
def _band(n: dict, model: dict, band_of: dict) -> str:
    if n["id"] in band_of:
        return band_of[n["id"]]
    if n.get("band") in ("it", "boundary", "ot"):              # stamped from the project's residency rule
        return n["band"]
    z = n["zone"]
    dcs = set((model.get("layout") or {}).get("dcs") or [])
    if n.get("kind") in ("firewall", "jump_host") or BOUNDARY_ROLE.search(n.get("role") or ""):
        return "boundary"
    if z in dcs or z.startswith("site:") or z == "nosite":
        return "ot"
    if z == "shared":
        role = n.get("role") or ""
        if "enterprise (IT)" in role:
            return "it"
        zl = next((x["label"] for x in model["zones"] if x["id"] == "shared"), "")
        return "ot" if ("OT" in zl or n.get("kind") == "gap") else "it"
    return "it"


def _sub(n: dict, band: str, model: dict) -> str:
    z = n["zone"]
    if band == "boundary":
        return "boundary"
    if band == "it":
        return "outside" if z == "outside" else "it"
    return z


def build(model: dict, band_of: dict | None = None, conduits: bool = False) -> dict:
    band_of = band_of or {}
    zlabel = {z["id"]: z["label"] for z in model["zones"]}
    dcs = list((model.get("layout") or {}).get("dcs") or [])
    tiles: dict[str, dict] = {}
    tile_of: dict[str, str] = {}
    for n in model["nodes"]:
        b = _band(n, model, band_of)
        s = _sub(n, b, model)
        role = short_role(n)
        gap = n["kind"] == "gap"
        key = f"{b}|{s}|{n['kind']}|{role}" if not gap else f"{b}|{s}|gap|{n['id']}"
        t = tiles.setdefault(key, {"id": key, "band": b, "sub": s, "kind": n["kind"], "role": role, "hosts": [],
                                    "labels": [], "gap": gap, "sites": []})
        t["hosts"].append(n["id"])
        t["labels"].append(n["label"])
        if b == "boundary" and n["zone"] in zlabel:
            site = re.sub(r"\s*data centre$", "", zlabel[n["zone"]], flags=re.I)
            if site not in t["sites"]:
                t["sites"].append(site)
        tile_of[n["id"]] = key
    for g in model.get("groups", []):
        mem = [m for m in g["members"] if m in tile_of]
        if mem:
            tile_of[g["id"]] = tile_of[mem[0]]
    # sub-zones per band, in page order
    subs: dict[str, list[str]] = {"it": [], "boundary": [], "ot": []}
    order = {"it": 0, "outside": 1, "boundary": 0, "shared": 99, "nosite": 98}
    for t in tiles.values():
        if t["sub"] not in subs[t["band"]]:
            subs[t["band"]].append(t["sub"])
    for b in subs:
        subs[b].sort(key=lambda s: (dcs.index(s) if s in dcs else order.get(s, 50 if s.startswith("site:") else 60), s))
    def sub_label(s):
        if s == "outside":
            return "Location not captured"
        if s == "shared":
            lab = zlabel.get(s, "")
            return lab if "OT" in lab else "Shared services"
        return zlabel.get(s, s.replace("site:", ""))
    # lines between tiles (zone ends kept as zones)
    def end(x):
        if x.startswith("Z:"):
            z = x[2:]
            hit = [t for t in tiles.values() if t["sub"] == z or (z == "it" and t["sub"] == "it")]
            if hit:
                return "Z:" + hit[0]["band"] + "|" + hit[0]["sub"]
            return None
        return tile_of.get(x)
    agg: dict[tuple, dict] = {}
    inside = 0
    for e in model["edges"]:
        a, b = end(e["s"]), end(e["t"])
        if not a or not b:
            continue
        if conduits:                                  # zones-and-conduits figures: OT ends are the sites
            a, b = (("Z:" + "|".join(tiles[x]["id"].split("|")[:2]) if not x.startswith("Z:") and tiles[x]["band"] == "ot" else x)
                    for x in (a, b))
        if a == b:
            inside += 1; continue
        svcs, more = service_names(e)
        kinds = {tiles[x]["kind"] for x in (a, b) if not x.startswith("Z:")}
        if e["status"] in ("configured", "inactive"):
            parts = {"directory": svcs}
        else:
            parts = {}
            for sv in svcs:
                parts.setdefault(classify(sv, kinds), []).append(sv)
        if more:                                      # ports the capture counted but did not list: function unknown
            parts.setdefault("other", [])
        for fn, sv in (parts or {"other": []}).items():
            k = (a, b, e["status"], fn)
            d = agg.setdefault(k, {"s": a, "t": b, "status": e["status"], "fn": fn, "svcs": [], "more": 0, "both": False,
                                   "evidence": set(), "ids": []})
            d["svcs"] += sv
            if fn == "other":
                d["more"] += more
            d["both"] = d["both"] or e.get("dir") == "both"
            d["evidence"].update(e.get("evidence", [])); d["ids"].append(e["id"])
    for (a, b, st, fn), d in list(agg.items()):       # a line in each direction is one two-way line
        if (b, a, st, fn) in agg and a < b:
            o = agg.pop((b, a, st, fn)); d["both"] = True; d["svcs"] += o["svcs"]; d["more"] += o["more"]
            d["evidence"] |= o["evidence"]; d["ids"] += o["ids"]
    return {"tiles": tiles, "subs": subs, "sub_label": sub_label, "lines": list(agg.values()), "inside": inside,
            "dcs": dcs}


# ------------------------------------------------------------------ render
def render_band_svg(model: dict, band_of: dict | None = None, conduits: bool = False,
                    per_target: bool | None = None) -> tuple[str, dict]:
    if per_target is None:
        per_target = bool((model.get("print") or {}).get("per_target"))
    B = build(model, band_of, conduits)
    tiles, subs, lines = B["tiles"], B["subs"], B["lines"]
    stem = model["id"] + "-band"
    colx = lambda c: G + c * (CW + G)

    # a boundary marker when lines cross into or out of OT with no boundary control evidenced
    band_t = lambda e: e.split("|")[0].replace("Z:", "")
    crossing_risk = any({band_t(l["s"]), band_t(l["t"])} == {"it", "ot"} and l["status"] in ("unenforced", "direct")
                        for l in lines)
    if crossing_risk and not any(t["kind"] == "firewall" for t in tiles.values()):
        key = "boundary|boundary|gap|control"
        tiles[key] = {"id": key, "band": "boundary", "sub": "boundary", "kind": "gap", "role": "Boundary control",
                      "hosts": [], "labels": ["None evidenced"], "gap": True, "sites": []}
        if "boundary" not in subs["boundary"]:
            subs["boundary"].append("boundary")

    # tile text
    for t in tiles.values():
        t["role_lines"] = _wrap(t["role"], CW - 8, F_NAME, True, 2)
        if t["gap"]:
            host = "None evidenced"
        elif t["kind"] in ("internal", "internet") and t["hosts"] and t["hosts"][0].startswith("G-"):
            host = t["labels"][0]
        else:
            host = members_label(t["labels"])
            if len(t["labels"]) > 1 and _tw(host, F_TEXT) > CW - 4:    # several hosts: one line, the first and a count
                host = f"{sorted(t['labels'])[0]} +{len(t['labels']) - 1}"
        t["host_lines"] = _wrap(host, CW - 4, F_TEXT, False, 2)
        t["h"] = ICON + 6 + LINE_H * (len(t["role_lines"]) + len(t["host_lines"])) + 2

    # pack sub-zones into shelves of columns, tiles row-major inside their sub-zone
    import itertools

    def pack(band, spans):
        """Shelves for one band: sites in order, left to right, a new shelf when the columns run out."""
        out, cur, used = [], None, NCOL
        for s_, sp in zip(subs[band], spans):
            if cur is None or used + sp > NCOL:
                cur = {"band": band, "subs": [], "rows": 0}; out.append(cur); used = 0
            n = sum(1 for t in tiles.values() if t["band"] == band and t["sub"] == s_)
            cur["subs"].append((s_, used, sp)); cur["rows"] = max(cur["rows"], math.ceil(n / sp))
            used += sp
        return out

    shelves = []                                  # [{band, subs: [(sub, c0, span)], rows}]
    for band in ("it", "boundary", "ot"):
        if not subs[band]:
            shelves.append({"band": band, "subs": [], "rows": 0}); continue
        opts = []
        for s_ in subs[band]:
            n = sum(1 for t in tiles.values() if t["band"] == band and t["sub"] == s_)
            if band != "ot" and s_ in ("it", "boundary"):
                opts.append([min(NCOL, max(1, n))])
            else:
                opts.append(list(range(1, min(NCOL, max(1, n)) + 1)))
        # the packing with the least height; narrow sites preferred (their lines go straight up)
        best = min(itertools.product(*opts),
                   key=lambda sp: (sum(sh["rows"] * 115 + 70 for sh in pack(band, sp)) + 4 * sum(x - 1 for x in sp)))
        for sh in pack(band, best):
            shelves.append(sh)
            for s_, c0, sp in sh["subs"]:
                ts = [t for t in tiles.values() if t["band"] == band and t["sub"] == s_]
                for i, t in enumerate(sorted(ts, key=lambda t: (t["gap"], t["kind"] == "unknown", t["role"]))):
                    t["col"], t["row"] = c0 + i % sp, i // sp
    # re-number shelves on tiles after any insert
    for i, sh in enumerate(shelves):
        for s, c0, sp in sh["subs"]:
            for t in tiles.values():
                if t["band"] == sh["band"] and t["sub"] == s:
                    t["shelf"] = i
    has_panel = lambda band, s: band == "ot" or s == "outside"

    # channels: one above every sub-zone header (zone ends) and one above every tile row
    chan_ids = []                                 # (shelf, "head" | row)
    for i, sh in enumerate(shelves):
        if any(has_panel(sh["band"], s) for s, _, _ in sh["subs"]):
            chan_ids.append((i, "head"))
        for r in range(sh["rows"]):
            chan_ids.append((i, r))
    chan_index = {c: k for k, c in enumerate(chan_ids)}
    tile_by = {t["id"]: t for t in tiles.values()}

    # ends: tile -> top of its icon in the channel above its row; zone -> top of its panel
    def end_info(e):
        if e.startswith("Z:"):
            band, s = e[2:].split("|", 1)
            for i, sh in enumerate(shelves):
                for s2, c0, sp in sh["subs"]:
                    if sh["band"] == band and s2 == s:
                        ch = (i, "head") if (i, "head") in chan_index else (i, 0)
                        return {"chan": chan_index[ch], "c0": c0, "sp": sp, "zone": (i, s), "kind": "zone"}
            return None
        t = tile_by[e]
        return {"chan": chan_index[(t["shelf"], t["row"])], "col": t["col"], "kind": "tile", "tile": t}

    # buses: one line per function (and evidence status); every system in that traffic joins it with a tap
    buses: dict[tuple, dict] = {}
    for l in lines:
        si, ti = end_info(l["s"]), end_info(l["t"])
        if not si or not ti:
            continue
        # service figures keep one line per provider, so who takes the service from whom stays visible
        key = (l["fn"], l["status"], l["t"] if per_target else "")
        b = buses.setdefault(key, {"fn": l["fn"], "status": l["status"], "ends": {}, "svcs": [], "more": 0})
        for e, info, into in ((l["s"], si, l["both"]), (l["t"], ti, True)):
            d = b["ends"].setdefault(e, {"info": info, "in": False})
            d["in"] = d["in"] or into
        b["svcs"] += l["svcs"]; b["more"] += l["more"]
    order_fn = list(FUNCTIONS)
    bl = sorted(buses.values(), key=lambda b: (order_fn.index(b["fn"]), b["status"]))

    def end_cx(info):
        if info["kind"] == "tile":
            return colx(info["col"]) + CW / 2
        return colx(info["c0"]) + 40
    gutter_x = [G / 2 + k * (CW + G) for k in range(NCOL + 1)]
    shelf_chans = defaultdict(list)
    for (i, _), k in chan_index.items():
        shelf_chans[i].append(k)
    panels = [(i, s_, c0, sp) for i, sh in enumerate(shelves) for s_, c0, sp in sh["subs"] if has_panel(sh["band"], s_)]

    def owner(info):
        if info["kind"] == "zone":
            return info["zone"]
        t = info["tile"]
        return (t["shelf"], t["sub"])

    def pick_gutter(b):
        infos = [d["info"] for d in b["ends"].values()]
        xs = [end_cx(x) for x in infos]
        chans = [x["chan"] for x in infos]
        lo, hi = min(chans), max(chans)
        mine = {owner(x) for x in infos if x["kind"] == "tile"}
        def cost(g):
            c = sum(abs(gutter_x[g] - x) for x in xs)
            for i, s_, c0, sp in panels:           # never run a line down the inside of a site it does not touch
                if c0 < g < c0 + sp and (i, s_) not in mine and any(lo <= k <= hi for k in shelf_chans[i]):
                    c += 5000
                if c0 < g < c0 + sp and (i, s_) in mine:
                    c += 5000 if hi > max(shelf_chans[i]) else 150
            return c
        return min(range(NCOL + 1), key=lambda g: (cost(g), -g))
    for b in bl:
        b["g"] = pick_gutter(b)
        b["chans"] = sorted({d["info"]["chan"] for d in b["ends"].values()})
        b["trunk"] = len(b["chans"]) > 1

    # taps: each system has one tap per bus, spread across its icon (or along the top of its site)
    ports = defaultdict(list)
    for bi, b in enumerate(bl):
        for e in b["ends"]:
            ports[e].append(bi)
    port_x = {}
    for e, lst in ports.items():
        info = end_info(e)
        cx = end_cx(info)
        lst.sort(key=lambda bi: (gutter_x[bl[bi]["g"]], bi))
        n = len(lst)
        step = 9.0 if info["kind"] == "tile" else 16.0
        for k, bi in enumerate(lst):
            port_x[(e, bi)] = cx + (k - (n - 1) / 2) * step if info["kind"] == "tile" else cx + k * step

    # lanes: one horizontal run per bus in each channel it uses; one vertical trunk per bus in its gutter
    chan_segs = defaultdict(list)
    gut_segs = defaultdict(list)
    for bi, b in enumerate(bl):
        gx = gutter_x[b["g"]]
        for c in b["chans"]:
            xs = [port_x[(e, bi)] for e, d in b["ends"].items() if d["info"]["chan"] == c]
            if b["trunk"]:
                xs.append(gx)
            chan_segs[c].append((min(xs), max(xs), ("b", bi)))
        if b["trunk"]:
            gut_segs[b["g"]].append((b["chans"][0], b["chans"][-1], ("g", bi)))
    def colour(segs):
        lanes, out = [], {}
        for a, z, key in sorted(segs, key=lambda s: (s[0], s[1])):
            for k, last in enumerate(lanes):
                if a > last + 1e-6:
                    lanes[k] = z; out[key] = k; break
            else:
                lanes.append(z); out[key] = len(lanes) - 1
        return out, len(lanes)
    chan_lane, chan_n, lane_room = {}, {}, defaultdict(float)
    for c, segs in chan_segs.items():
        m, n = colour([(a - 8, z + 8, k) for a, z, k in segs])
        chan_lane.update({(c,) + (k,): v for k, v in m.items()}); chan_n[c] = n
    gut_lane, gut_n = {}, {}
    for g, segs in gut_segs.items():
        m, n = colour(segs)
        gut_lane.update(m); gut_n[g] = n

    # vertical positions
    y = 0.0
    chan_y, chan_h = {}, {}
    shelf_rows_y = {}
    band_box = {}
    sub_box = {}
    head_h = 30.0
    def sub_title(i, s_, c0, sp):
        x1, x2 = colx(c0) - 12, colx(c0 + sp - 1) + CW + 12
        return _wrap(B["sub_label"](s_), x2 - x1 - 22, F_ZONE, True, 2)
    for i, sh in enumerate(shelves):
        band = sh["band"]
        first = i == 0 or shelves[i - 1]["band"] != band
        if first:
            if i:
                y += 12
            band_box.setdefault(band, [y, y])
            y += 36                                     # band title
        def chan(ckey):
            nonlocal y
            c = chan_index[ckey]
            h = 12 + sum(BUS_GAP + lane_room[(c, k)] for k in range(chan_n.get(c, 0))) + 8
            chan_y[c], chan_h[c] = y, h
            y += h
        if (i, "head") in chan_index:
            chan((i, "head"))
            top = y
            nl = max(len(sub_title(i, s_, c0, sp)) for s_, c0, sp in sh["subs"])
            y += head_h + LINE_H * (nl - 1)
            for s, c0, sp in sh["subs"]:
                sub_box[(i, s)] = [top, None, c0, sp]
        for r in range(sh["rows"]):
            chan((i, r))
            rh = max([t["h"] for t in tiles.values() if t.get("shelf") == i and t["row"] == r] + [60])
            shelf_rows_y[(i, r)] = (y, rh)
            y += rh
        if not sh["rows"]:
            y += 8
        for s, c0, sp in sh["subs"]:
            if (i, s) in sub_box:
                nr = max([t["row"] for t in tiles.values() if t.get("shelf") == i and t["sub"] == s] + [0])
                yy, rh = shelf_rows_y.get((i, nr), (y, 0))
                sub_box[(i, s)][1] = yy + rh + 8
        y += 10
        band_box[band][1] = y
    body_h = y

    # coordinates
    def lane_y(c, key):
        k = chan_lane.get((c, key), 0)
        return chan_y[c] + 12 + sum(BUS_GAP + lane_room[(c, j)] for j in range(k)) + lane_room[(c, k)]
    def gut_x(g, bi):
        n = gut_n.get(g, 1)
        k = gut_lane.get(("g", bi), 0)
        room = G - 24
        step = min(BUS_GAP, room / max(1, n - 1)) if n > 1 else 0
        return gutter_x[g] + (k - (n - 1) / 2) * step
    def port_y(info):
        if info["kind"] == "tile":
            t = info["tile"]
            return shelf_rows_y[(t["shelf"], t["row"])][0]
        return sub_box[info["zone"]][0]

    # ------------------------------------------------------------------ SVG
    used_fn = [f for f in FUNCTIONS if any(b["fn"] == f for b in bl)]
    used_status = sorted({b["status"] for b in bl}, key=lambda s_: list(STATUS_DASH).index(s_) if s_ in STATUS_DASH else 99)
    styles = sorted({STATUS_DASH.get(st, ("", ""))[0] for st in used_status})
    risk = [st for st in used_status if st in ("unenforced", "direct", "unknown")]
    note = ("Every line crosses a zone boundary with no boundary control evidenced. " if risk == used_status and "unenforced" in risk else "")
    note += "Arrow: the system that receives. ×n: hosts in the role."
    note_lines = _wrap(note, W - 140, F_TEXT, False, 2)
    legend_keys = []
    for b in bl:
        if (b["fn"], b["status"]) not in legend_keys:
            legend_keys.append((b["fn"], b["status"]))
    legend_rows = len(legend_keys) + len(note_lines)
    H = body_h + 14 + legend_rows * 26 + 8
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W * MM:.1f}mm" height="{H * MM:.1f}mm" '
         f'font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif" class="tdiag print band" data-diagram="{esc(stem)}">', "<defs>"]
    for k, (col, _) in FUNCTIONS.items():
        o.append(f'<marker id="b-{esc(stem)}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" '
                 f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    o += ["</defs>", '<rect width="100%" height="100%" fill="#ffffff"/>']
    titles = []
    for band, (y1, y2) in band_box.items():
        o.append(f'<g class="zone" data-id="band-{band}"><rect x="0" y="{y1:.1f}" width="{W:.0f}" height="{y2 - y1:.1f}" rx="12" '
                 f'fill="{BAND_FILL[band]}" stroke="{BORDER}" stroke-width="1.6"/></g>')
        title = BAND_TITLE[band]
        titles.append((band, y1, title))
    for (i, s), (y1, y2, c0, sp) in sub_box.items():
        band = shelves[i]["band"]
        x1, x2 = colx(c0) - 12, colx(c0 + sp - 1) + CW + 12
        dashed = ' stroke-dasharray="6 4"' if s in ("outside", "nosite") else ""
        labs = sub_title(i, s, c0, sp)
        o.append(f'<g class="zone" data-id="{esc(s)}"><rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="9" '
                 f'fill="{SUB_FILL[band]}" fill-opacity="0.7" stroke="{BORDER}" stroke-width="1.3"{dashed}/>'
                 + "".join(f'<text x="{x1 + 12:.1f}" y="{y1 + 21 + LINE_H * j:.1f}" font-size="{F_ZONE}" font-weight="700" fill="{NAVY}">{esc(l_)}</text>'
                         for j, l_ in enumerate(labs)) + '</g>')

    # lines
    o.append('<g class="edges">')
    def path(pts):
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - clean[-1][0]) > 0.05 or abs(p[1] - clean[-1][1]) > 0.05:
                clean.append(p)
        return "M" + " L".join(f"{x:.1f},{yy:.1f}" for x, yy in clean)
    def line(pts, fn, st, a1, eid):
        col = FUNCTIONS[fn][0]
        dash, w = STATUS_DASH.get(st, ("", 2.6))
        mk = f' marker-end="url(#b-{esc(stem)}-{fn})"' if a1 else ""
        da = f' stroke-dasharray="{dash}"' if dash else ""
        return (f'<path class="edge" data-id="{esc(eid)}" d="{path(pts)}" fill="none" stroke="{col}" stroke-width="{w}" '
                f'stroke-linecap="round"{da}{mk}/>')
    label_svg = []
    dots = []
    for bi, b in enumerate(bl):
        fn, st = b["fn"], b["status"]
        col = FUNCTIONS[fn][0]
        gx = gut_x(b["g"], bi)
        ys = []
        for c in b["chans"]:
            ly = lane_y(c, ("b", bi))
            ys.append(ly)
            taps = [(port_x[(e, bi)], e, d) for e, d in b["ends"].items() if d["info"]["chan"] == c]
            xs = [x for x, _, _ in taps] + ([gx] if b["trunk"] else [])
            if max(xs) - min(xs) > 0.1:
                o.append(line([(min(xs), ly), (max(xs), ly)], fn, st, False, f"bus-{fn}-{st}"))
            for x, e, d in taps:
                o.append(line([(x, ly), (x, port_y(d["info"]) - (1 if d["in"] else 0))], fn, st, d["in"], f"tap-{e}"))
                dots.append(f'<circle cx="{x:.1f}" cy="{ly:.1f}" r="3.6" fill="{col}"/>')
            if b["trunk"]:
                dots.append(f'<circle cx="{gx:.1f}" cy="{ly:.1f}" r="3.6" fill="{col}"/>')
        if b["trunk"]:
            o.append(line([(gx, min(ys)), (gx, max(ys))], fn, st, False, f"trunk-{fn}-{st}"))
    o += dots
    o.append("</g>")
    o += label_svg

    # band titles over the lines, on the band colour
    for band, y1, title in titles:
        tw = _tw(title, F_BAND, True) + 16
        o.append(f'<rect x="10" y="{y1 + 8:.1f}" width="{tw:.1f}" height="28" fill="{BAND_FILL[band]}"/>'
                 f'<text x="16" y="{y1 + 29:.1f}" font-size="{F_BAND}" font-weight="700" fill="{NAVY}" letter-spacing="0.5">{esc(title)}</text>')

    # tiles: icon, role, hosts
    for t in tiles.values():
        x = colx(t["col"]); y0 = shelf_rows_y[(t["shelf"], t["row"])][0]
        cx = x + CW / 2
        icon, _, col = KINDS.get(t["kind"], KINDS["unknown"])
        sc = ICON / 24
        bg = (f'<rect x="{cx - ICON / 2 - 4:.1f}" y="{y0 - 2:.1f}" width="{ICON + 8:.1f}" height="{ICON + 4:.1f}" rx="8" '
              f'fill="#ffffff" fill-opacity="0.85"/>')
        badge = ""
        if len(t["hosts"]) > 1:
            n = f"×{len(t['hosts'])}"
            bw = _tw(n, F_TEXT, True) + 12
            badge = (f'<rect x="{cx + ICON / 2 - 4:.1f}" y="{y0 - 4:.1f}" width="{bw:.1f}" height="22" rx="11" fill="{TEAL}"/>'
                     f'<text x="{cx + ICON / 2 - 4 + bw / 2:.1f}" y="{y0 + 12:.1f}" font-size="{F_TEXT}" font-weight="700" '
                     f'fill="#ffffff" text-anchor="middle">{esc(n)}</text>')
        name_col = GAP_COL if t["gap"] else NAVY
        if t["gap"]:
            col = GAP_COL
        txt = []
        yy = y0 + ICON + 6
        for j, ln in enumerate(t["role_lines"]):
            yy += LINE_H
            txt.append(f'<text x="{cx:.1f}" y="{yy - 4:.1f}" font-size="{F_NAME}" font-weight="700" fill="{name_col}" '
                       f'text-anchor="middle">{esc(ln)}</text>')
        for ln in t["host_lines"]:
            yy += LINE_H
            txt.append(f'<text x="{cx:.1f}" y="{yy - 4:.1f}" font-size="{F_TEXT}" fill="{GAP_COL if t["gap"] else MUTED}" '
                       f'text-anchor="middle">{esc(ln)}</text>')
        o.append(f'<g class="node" data-id="{esc(t["id"])}">{bg}'
                 f'<g transform="translate({cx - ICON / 2:.1f},{y0:.1f}) scale({sc:.4f})" fill="none" stroke="{col}" '
                 f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" color="{col}">{ICONS[icon]}</g>'
                 f'{badge}{"".join(txt)}</g>')

    # legend: line colour = function (with the services on it), line style = evidence, then how to read it
    y = body_h + 14
    # one row per line: its colour and style, the function, the services on it and, when it matters, its status
    say_status = not (len(used_status) == 1 and used_status[0] in ("observed", "unenforced"))
    cells = []
    for j, (fn_, st_) in enumerate(legend_keys):
        same = [b for b in bl if (b["fn"], b["status"]) == (fn_, st_)]
        b = {"fn": fn_, "status": st_, "svcs": [x for bb in same for x in bb["svcs"]], "more": sum(bb["more"] for bb in same)}
        svcs = list(dict.fromkeys(x for x in b["svcs"] if x))
        extra = max(0, len(svcs) - 6) + b["more"]
        shown = ", ".join(svcs[:6])
        if extra:
            shown = (shown + " and " if shown else "") + f"{extra} more ports not listed in the capture"
        lab = FUNCTIONS[b["fn"]][1] + (f": {shown}" if shown else "")
        if say_status:
            lab += f" ({STATUS_PHRASE.get(b['status'], b['status'])})"
        cells.append((0, j, (FUNCTIONS[b["fn"]][0], STATUS_DASH.get(b["status"], ("", 2.6))[0], lab, True)))
    for colno, j, (col, dash, lab, bold) in cells:
        xx = 8
        yy = y + j * 26 + 18
        da = f' stroke-dasharray="{dash}"' if dash else ""
        lab = _wrap(lab, W - 160, F_TEXT, False, 1)[0]
        o.append(f'<line x1="{xx:.1f}" y1="{yy - 6:.1f}" x2="{xx + 44:.1f}" y2="{yy - 6:.1f}" stroke="{col}" stroke-width="3.2" stroke-linecap="round"{da}/>'
                 f'<text x="{xx + 54:.1f}" y="{yy:.1f}" font-size="{F_TEXT}" fill="{MUTED}">{esc(lab)}</text>')
    yy = y + (max([j for _, j, _ in cells] + [-1]) + 1) * 26 + 18
    for j, ln in enumerate(note_lines):
        o.append(f'<text x="8" y="{yy + j * 22:.1f}" font-size="{F_TEXT}" fill="{MUTED}">{esc(ln)}</text>')
    o.append("</svg>")
    info = {"width_mm": TEXT_W_MM, "height_mm": round(H * MM, 1), "fits_page": H <= PAGE_H_MAX, "min_text_pt": round(F_TEXT * MM / 0.3528, 1),
            "tiles": len(tiles), "lines": len(bl), "inside_not_drawn": B["inside"], "functions": used_fn}
    return "\n".join(o), info
