"""Track layout: fixed page structure + orthogonal line routing in dedicated tracks.

Page structure (y grows downwards):
  row 0         top band (IT, Internet, other sites, site not recorded)
  rows 1..k     tier rows (access, application, database) running across BOTH data centres
  row k+1       shared services band
Tracks:
  gutter i      horizontal track between row i and row i+1 (no boxes in it)
  channel       vertical track: each data centre's outer edge (IT / shared traffic),
                the middle trunk between the two data centres (cross-site traffic),
                and each data centre's inner edge for long hops inside one site.
A line leaves a box from the side facing its target, drops into the adjacent gutter,
runs along it (to a channel if it must change more than one row), and enters the
target from the adjacent gutter. Every line gets its own lane in each track, so
parallel lines never overlap and nothing crosses a box.
"""
from collections import defaultdict

NODE_W, NODE_H = 290, 74
CARD_GAP = 64          # between cards in a tier
LANE = 11               # spacing between parallel lines in a track
BAND_HEAD = 48         # zone title height
GROUP_HEAD = 32
MIN_GUTTER, MIN_CHANNEL = 54, 46


def layout(model):
    L = model["layout"]
    nodes = {n["id"]: n for n in model["nodes"]}
    groups = {g["id"]: g for g in model.get("groups", [])}
    dcs = L["dcs"]
    tiers = [t for t, _ in L["tiers"] if any(n.get("tier") == t for n in model["nodes"])]
    tier_label = dict(L["tiers"])
    top_row, bot_row = 0, len(tiers) + 1

    # ---------------------------------------------------------------- objects
    # obj: id -> dict(row_top,row_bot, zone)
    def row_of(n):
        if n["zone"] in L["top"]: return 0
        if n["zone"] in L["bottom"]: return bot_row
        return 1 + tiers.index(n["tier"])
    obj = {}
    for n in model["nodes"]:
        r = row_of(n); obj[n["id"]] = {"r0": r, "r1": r, "zone": n["zone"], "kind": "card"}
    for g in groups.values():
        z = nodes[g["members"][0]]["zone"]; r = row_of(nodes[g["members"][0]])
        obj[g["id"]] = {"r0": r, "r1": r, "zone": z, "kind": "group"}
    for z in set(L["top"] + L["dcs"] + L["bottom"]):
        rs = [obj[n["id"]]["r0"] for n in model["nodes"] if n["zone"] == z]
        if rs: obj["Z:" + z] = {"r0": min(rs), "r1": max(rs), "zone": z, "kind": "zone"}

    # order cards inside each tier: cross-site talkers face the middle trunk
    cross = defaultdict(int)
    def zone_of(x): return obj[x]["zone"]
    for e in model["edges"]:
        a, b = zone_of(e["s"]), zone_of(e["t"])
        if a in dcs and b in dcs and a != b:
            for x in (e["s"], e["t"]):
                for m in (groups[x]["members"] if x in groups else [x]): cross[m] += 1
    rowcards = defaultdict(list)            # (zone,row) -> [ids] left to right
    # inside a data centre cards are ordered by name (then by cross-site weight below); in the bands the
    # model's own order is kept, so a figure can put each provider above the data centre it serves
    order = {id(n): i for i, n in enumerate(model["nodes"])}
    for n in sorted(model["nodes"], key=lambda n: (n["label"], 0) if n["zone"] in dcs else ("", order[id(n)])):
        rowcards[(n["zone"], obj[n["id"]]["r0"])].append(n["id"])
    for (z, r), ids in rowcards.items():
        if z in dcs:
            # keep each group's members together; sort blocks by cross-site weight
            blocks, seen = [], set()
            for i in ids:
                if i in seen: continue
                g = nodes[i].get("group")
                blk = sorted(groups[g]["members"], key=lambda m: (cross[m], m), reverse=dcs.index(z) == 1) if g in groups else [i]
                seen.update(blk); blocks.append(blk)
            w = lambda blk: sum(cross[m] for m in blk)
            rev = dcs.index(z) == 1          # right-hand data centre: talkers on the left
            blocks.sort(key=lambda blk: (w(blk), -len(blk)), reverse=rev)
            if not rev: blocks.sort(key=lambda blk: w(blk))
            rowcards[(z, r)] = [m for blk in blocks for m in blk]

    # ---------------------------------------------------------------- logical routes
    def side_toward(a, b):
        A, B = obj[a], obj[b]
        if B["r0"] > A["r1"]: return "bottom"
        if B["r1"] < A["r0"]: return "top"
        return "same"
    def gutter_on(a, side):
        return obj[a]["r1"] if side == "bottom" else obj[a]["r0"] - 1
    def channel_for(a, b):
        za, zb = zone_of(a), zone_of(b)
        if za in dcs and zb in dcs and za != zb: return ("mid",)
        if za in dcs and zb in dcs:
            # same data centre: use the edge nearer to both cards
            def frac(x):
                ids = rowcards[(za, obj[x]["r0"])]
                m = groups[x]["members"][0] if x in groups else x
                return (ids.index(m) + 0.5) / len(ids) if m in ids else 0.5
            return ("edge", za, "L" if (frac(a) + frac(b)) / 2 < 0.5 else "R")
        dz = za if za in dcs else zb
        if dz in dcs: return ("edge", dz, "L" if dcs.index(dz) == 0 else "R")
        return ("page", "L")

    routes = {}
    for e in model["edges"]:
        s, t = e["s"], e["t"]
        S, T = obj[s], obj[t]
        same_row = S["r0"] == T["r0"] and S["r1"] == T["r1"] and S["kind"] != "zone" and T["kind"] != "zone"
        if not same_row and side_toward(s, t) == "same":
            g = S["r1"] if S["r1"] < bot_row else S["r0"] - 1
            routes[e["id"]] = {"type": "u", "g": g, "ss": "bottom" if g == S["r1"] else "top"}
            continue
        if same_row:
            ids = rowcards.get((S["zone"], S["r0"]), [])
            sm = groups[s]["members"] if s in groups else [s]
            tm = groups[t]["members"] if t in groups else [t]
            # neighbours in one tier, or the two facing cards across the trunk
            adj = False
            if S["zone"] == T["zone"] and ids:
                ia = [ids.index(x) for x in sm]; ib = [ids.index(x) for x in tm]
                adj = max(ia) + 1 == min(ib) or max(ib) + 1 == min(ia)
            elif S["zone"] in dcs and T["zone"] in dcs:
                L0 = rowcards[(dcs[0], S["r0"])]; R0 = rowcards[(dcs[1], S["r0"])]
                adj = (L0 and R0 and ((L0[-1] in sm and R0[0] in tm) or (L0[-1] in tm and R0[0] in sm)))
            if adj:
                routes[e["id"]] = {"type": "side"}; continue
            g = S["r1"] if S["r1"] < bot_row else S["r0"] - 1
            routes[e["id"]] = {"type": "u", "g": g, "ss": "bottom" if g == S["r1"] else "top"}
            continue
        ss, ts = side_toward(s, t), side_toward(t, s)
        gs, gt = gutter_on(s, ss), gutter_on(t, ts)
        if gs == gt:
            routes[e["id"]] = {"type": "z", "g": gs, "ss": ss, "ts": ts}
        else:
            routes[e["id"]] = {"type": "c", "gs": gs, "gt": gt, "ss": ss, "ts": ts, "ch": channel_for(s, t)}

    # lane bookkeeping
    glanes, clanes = defaultdict(list), defaultdict(list)
    for eid, r in routes.items():
        if r["type"] in ("u", "z"): glanes[r["g"]].append(eid)
        if r["type"] == "c":
            glanes[r["gs"]].append(eid); glanes[r["gt"]].append(eid); clanes[r["ch"]].append(eid)
    gh = {g: max(MIN_GUTTER, 28 + LANE * len(set(v))) for g, v in glanes.items()}
    cw = {c: max(MIN_CHANNEL, 24 + LANE * len(set(v))) for c, v in clanes.items()}

    # ---------------------------------------------------------------- geometry (x)
    def row_width(z, r):
        ids = rowcards.get((z, r), [])
        extra = 0
        gs_ = {nodes[i].get("group") for i in ids if nodes[i].get("group") in groups}
        extra = 24 * len(gs_)
        return len(ids) * NODE_W + max(0, len(ids) - 1) * CARD_GAP + extra
    zone_rect = {}
    x = 0.0
    dc_inner = {}
    for z in dcs:
        inner = max(row_width(z, r) for r in range(1, bot_row))
        padL = 24 + cw.get(("edge", z, "L"), 0); padR = 24 + cw.get(("edge", z, "R"), 0)
        zone_rect[z] = [x, None, x + padL + inner + padR, None]
        dc_inner[z] = (x + padL, x + padL + inner)
        x = zone_rect[z][2]
        if z != dcs[-1]: x += max(110, cw.get(("mid",), 0) + 40)
    pageL = cw.get(("page", "L"), 0)
    if pageL:
        for z in zone_rect: zone_rect[z][0] += pageL; zone_rect[z][2] += pageL
        dc_inner = {z: (a + pageL, b + pageL) for z, (a, b) in dc_inner.items()}
    PAGE_W = max(zone_rect[z][2] for z in dcs)
    mid_x = (zone_rect[dcs[0]][2] + zone_rect[dcs[-1]][0]) / 2 if len(dcs) > 1 else PAGE_W / 2

    # top / bottom bands: first zone takes the free width
    def band(zs):
        widths = {z: max(NODE_W + 48, len([n for n in model["nodes"] if n["zone"] == z]) * (NODE_W + CARD_GAP) + 48) for z in zs}
        others = sum(widths[z] for z in zs[1:]) + 30 * (len(zs) - 1)
        xx = pageL
        for i, z in enumerate(zs):
            w = (PAGE_W - pageL - others) if i == 0 else widths[z]
            zone_rect[z] = [xx, None, xx + w, None]; xx += w + 30
    band(L["top"]); band(L["bottom"])

    # ---------------------------------------------------------------- geometry (y)
    row_h = {}
    for r in range(0, bot_row + 1):
        if r == 0: row_h[r] = BAND_HEAD + NODE_H + 22 if L["top"] else 0
        elif r == bot_row: row_h[r] = BAND_HEAD + NODE_H + 22 if L["bottom"] else 0
        else:
            has_grp = any(nodes[i].get("group") in groups for z in dcs for i in rowcards.get((z, r), []))
            row_h[r] = NODE_H + (GROUP_HEAD + 12 if has_grp else 0) + 14
    y, row_y, gut_y = 0.0, {}, {}
    DC_HEAD = 48
    for r in range(0, bot_row + 1):
        row_y[r] = y; y += row_h[r]
        if r < bot_row:
            h = gh.get(r, MIN_GUTTER)
            if r == 0: h += DC_HEAD            # data-centre titles sit at the bottom of gutter 0
            gut_y[r] = (y, y + h); y += h
    PAGE_H = y
    for z in L["top"]: zone_rect[z][1], zone_rect[z][3] = row_y[0], row_y[0] + row_h[0]
    for z in L["bottom"]: zone_rect[z][1], zone_rect[z][3] = row_y[bot_row], row_y[bot_row] + row_h[bot_row]
    for z in dcs:
        zone_rect[z][1] = gut_y[0][1] - DC_HEAD - 6
        zone_rect[z][3] = row_y[bot_row - 1] + row_h[bot_row - 1] + 6
    # gutter centre lines (gutter 0 excludes the DC title strip)
    gc = {g: ((a + b - (DC_HEAD if g == 0 else 0)) / 2) for g, (a, b) in gut_y.items()}

    # ---------------------------------------------------------------- card positions
    pos, gbox = {}, {}
    for (z, r), ids in rowcards.items():
        if z in dcs:
            a, b = dc_inner[z]; w = row_width(z, r); xx = a + (b - a - w) / 2
            cy = row_y[r] + row_h[r] - 14 - NODE_H / 2
            prev_g = None
            for i in ids:
                g = nodes[i].get("group")
                if g in groups and g != prev_g: xx += 12
                if prev_g in groups and g != prev_g: xx += 12
                pos[i] = (xx + NODE_W / 2, cy); xx += NODE_W + CARD_GAP; prev_g = g
        else:
            x1, _, x2, _ = zone_rect[z]
            cy = row_y[r] + BAND_HEAD + NODE_H / 2
            # a node may ask to sit under one data centre (e.g. that site's domain controller)
            placed_x = []
            for k, i in enumerate(ids):
                cx = x1 + (k + 0.5) * (x2 - x1) / len(ids)
                u = nodes[i].get("under")
                if u in zone_rect and u in dcs:
                    zr = zone_rect[u]; cx = (zr[0] + zr[2]) / 2
                    while any(abs(cx - px) < NODE_W + CARD_GAP for px in placed_x): cx += NODE_W + CARD_GAP
                placed_x.append(cx)
                pos[i] = (cx, cy)
    for g in groups.values():
        xs = [pos[m][0] for m in g["members"]]; ys = [pos[m][1] for m in g["members"]]
        gbox[g["id"]] = [min(xs) - NODE_W / 2 - 12, min(ys) - NODE_H / 2 - GROUP_HEAD, max(xs) + NODE_W / 2 + 12, max(ys) + NODE_H / 2 + 10]

    def rect(x):
        if x in pos: cx, cy = pos[x]; return [cx - NODE_W / 2, cy - NODE_H / 2, cx + NODE_W / 2, cy + NODE_H / 2]
        if x in gbox: return gbox[x]
        return zone_rect[x[2:]]
    def centre(x):
        r = rect(x); return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)

    # ---------------------------------------------------------------- lanes
    def lane_pos(centre_, n, i): return centre_ + (i - (n - 1) / 2) * LANE
    gl = {}
    for g, eids in glanes.items():
        eids = list(dict.fromkeys(eids))
        # outer lanes for long spans to reduce crossings
        span = {}
        for eid in eids:
            e = next(x for x in model["edges"] if x["id"] == eid)
            span[eid] = abs(centre(e["s"])[0] - centre(e["t"])[0])
        eids.sort(key=lambda k: span[k])
        order = []
        for k, eid in enumerate(eids):           # shortest in the middle, longer alternate outwards
            order.insert(0 if k % 2 else len(order), eid)
        for i, eid in enumerate(order): gl[(g, eid)] = lane_pos(gc[g], len(order), i)
    cl = {}
    def ch_x(ch):
        if ch[0] == "mid": return mid_x
        if ch[0] == "page": return pageL / 2
        z, sd = ch[1], ch[2]; zr = zone_rect[z]
        return zr[0] + 12 + cw[ch] / 2 if sd == "L" else zr[2] - 12 - cw[ch] / 2
    for ch, eids in clanes.items():
        eids = list(dict.fromkeys(eids))
        for i, eid in enumerate(eids): cl[(ch, eid)] = lane_pos(ch_x(ch), len(eids), i)

    # ports: spread several lines on one side of a box
    port_req = defaultdict(list)
    for e in model["edges"]:
        r = routes[e["id"]]
        if r["type"] == "side": continue
        if r["type"] == "u": port_req[(e["s"], r["ss"])].append((e, "s")); port_req[(e["t"], r["ss"])].append((e, "t"))
        else: port_req[(e["s"], r["ss"])].append((e, "s")); port_req[(e["t"], r["ts"])].append((e, "t"))
    port = {}
    for (o_, side), lst in port_req.items():
        R = rect(o_)
        def other_x(item):
            e, end = item; oth = e["t"] if end == "s" else e["s"]
            r = routes[e["id"]]
            if r["type"] == "c": return cl[(r["ch"], e["id"])]
            return centre(oth)[0]
        lst.sort(key=other_x)
        n = len(lst); step = min(18, (R[2] - R[0] - 30) / max(1, n))
        base = (R[0] + R[2]) / 2
        if o_.startswith("Z:"):
            # zone ports sit over the free part of the edge nearest the traffic
            base = min(max(other_x(lst[0]), R[0] + 40), R[2] - 40)
        for i, item in enumerate(lst):
            px = base + (i - (n - 1) / 2) * step
            py = R[3] if side == "bottom" else R[1]
            port[(item[0]["id"], item[1])] = (px, py)

    paths = {}
    for e in model["edges"]:
        r = routes[e["id"]]
        if r["type"] == "side":
            A, B = rect(e["s"]), rect(e["t"]); cy = (max(A[1], B[1]) + min(A[3], B[3])) / 2
            paths[e["id"]] = [(A[2], cy), (B[0], cy)] if A[0] < B[0] else [(A[0], cy), (B[2], cy)]
            continue
        p0, p1 = port[(e["id"], "s")], port[(e["id"], "t")]
        if r["type"] in ("u", "z"):
            ly = gl[(r["g"], e["id"])]
            paths[e["id"]] = [p0, (p0[0], ly), (p1[0], ly), p1]
        else:
            y1, y2 = gl[(r["gs"], e["id"])], gl[(r["gt"], e["id"])]; cx = cl[(r["ch"], e["id"])]
            paths[e["id"]] = [p0, (p0[0], y1), (cx, y1), (cx, y2), (p1[0], y2), p1]

    tier_bands = [(tier_label[t], row_y[1 + i], row_y[1 + i] + row_h[1 + i]) for i, t in enumerate(tiers)]
    return {"pos": pos, "zones": zone_rect, "groups": gbox, "paths": paths, "W": PAGE_W, "H": PAGE_H,
            "tiers": tier_bands, "dcs": [zone_rect[z] for z in dcs]}
