"""Archetype G: a store-centric data flow figure.

Layout: two-column.
  Left  — store cards, one per row, full panel width.
  Right — consumer tiles grouped by site.
Lines run left-to-right through the gutter from store right-edge to consumer left-edge.

Design notes:
  * The unit is the data store, not the host.
  * Each store card is a horizontal row: icon, label, instance count, flag badge.
  * Consumers are compact host tiles grouped by site.
  * Edge labels sit in the gutter between panels, de-collided.
"""
from __future__ import annotations

import html
from collections import defaultdict

from .icons import ICONS, KINDS, GREY, NAVY, TEAL

W = 1000.0
TEXT_W_MM = 170.0
MM = TEXT_W_MM / W
PAGE_H_MAX = 1350
F_NAME, F_TEXT, F_ZONE = 19, 17, 17
PAD = 14.0
ICON = 28.0
GAP_COL = "#b4602a"
BORDER = "#b9c8d3"
MUTED = "#55677a"
SUB_FILL = "#ffffff"
PANEL_FILL = "#f5f9fc"

# ── proportions ──
LEFT_FRAC = 0.52
GUTTER = 80.0
LEFT_W = W * LEFT_FRAC
RIGHT_X = LEFT_W + GUTTER
RIGHT_W = W - RIGHT_X - PAD

STATUS_STYLE = {
    "observed": (TEAL, ""), "seen": (TEAL, ""),
    "configured": (TEAL, "8 5"), "declared": (TEAL, "8 5"),
    "inactive": (GREY, "2.5 4"), "attempted": (GREY, "2.5 4"),
    "unknown": (NAVY, "8 5"),
}
STATUS_PHRASE = {
    "observed": "observed in the captures", "seen": "seen in the captures",
    "configured": "configured setting", "declared": "declared in the flow map, not seen",
    "inactive": "configured, not in use", "attempted": "attempted, no reply seen",
    "unknown": "path not captured",
}
MECH_FAMILY = {
    "database": "application", "database replication": "application",
    "file share": "application", "file transfer": "application",
    "backup agent": "management", "log forwarding": "management", "monitoring": "management",
    "message/API": "web", "web/API": "web",
}
FUNCTIONS = {
    "application": ("#167d8d", "Application and database"),
    "management": ("#b7791f", "Management and monitoring"),
    "web": ("#2f6fb0", "Web and Internet"),
    "other": ("#6b7785", "Other"),
}

esc = lambda s: html.escape(str(s), quote=True)


def build(model: dict) -> dict:
    stores = [n for n in model["nodes"] if n["id"].startswith("ST-")]
    consumers = [n for n in model["nodes"] if not n["id"].startswith("ST-")]
    zlabel = {z["id"]: z["label"] for z in model["zones"]}

    by_site: dict[str, list[dict]] = defaultdict(list)
    for c in consumers:
        by_site[c["zone"]].append(c)

    stores.sort(key=lambda n: (not n.get("flag"), 0 if n["kind"] == "database" else 1, n["label"]))

    czone = {c["id"]: c["zone"] for c in consumers}
    store_ids = {s["id"] for s in stores}
    consumer_ids = {c["id"] for c in consumers}
    agg: dict[tuple, dict] = {}
    for e in model.get("edges", []):
        if e["s"] not in consumer_ids or e["t"] not in store_ids:
            continue
        mech = e.get("mechanism", "") or e.get("label", "") or "other"
        fn = MECH_FAMILY.get(mech, "other")
        k = (e["s"], e["t"], e["status"], fn, mech)
        d = agg.setdefault(k, {"s": e["s"], "t": e["t"], "status": e["status"], "fn": fn,
                               "mech": mech, "zone": czone.get(e["s"], "")})
    store_order = {s["id"]: i for i, s in enumerate(stores)}
    lines = sorted(agg.values(), key=lambda l: (store_order.get(l["t"], 99), l["zone"], l["s"]))
    for i, l in enumerate(lines):
        l["lineid"] = f"L{i:02d}"

    return {"stores": stores, "by_site": dict(by_site), "zlabel": zlabel,
            "consumers": consumers, "lines": lines}


def render_store_svg(model: dict) -> tuple[str, dict]:
    B = build(model)
    stores, by_site, zlabel, consumers, lines = (
        B["stores"], B["by_site"], B["zlabel"], B["consumers"], B["lines"])

    # ── arrange stores: single column, horizontal cards ──
    ROW_H = 40.0
    FLAG_EXTRA = 20.0
    ROW_GAP = 6.0
    TOP = 30.0

    store_pos: dict[str, dict] = {}
    y = TOP
    for s in stores:
        h = ROW_H + (FLAG_EXTRA if s.get("flag") else 0)
        store_pos[s["id"]] = {"x": PAD + 6, "y": y, "w": LEFT_W - 12, "h": h,
                              "cx": PAD + 6 + (LEFT_W - 12) / 2, "cy": y + h / 2}
        y += h + ROW_GAP
    left_bottom = y - ROW_GAP

    # ── arrange consumers by site ──
    edge_counts = defaultdict(int)
    for l in lines:
        edge_counts[l["zone"]] += 1
    site_order = sorted(by_site.keys(), key=lambda z: -edge_counts.get(z, 0))

    HOST_ROW = 28.0
    SITE_HEADER = 26.0
    SITE_PAD = 10.0

    consumer_pos: dict[str, dict] = {}
    total_consumer_h = sum(
        SITE_HEADER + SITE_PAD * 2 + HOST_ROW * len(by_site[z])
        for z in site_order
    ) + 10 * (len(site_order) - 1)

    avail_h = left_bottom - TOP
    extra_per_gap = max(0, (avail_h - total_consumer_h) / max(1, len(site_order) - 1)) if len(site_order) > 1 else 0

    ry = TOP
    for z in site_order:
        cs = by_site[z]
        site_h = SITE_HEADER + SITE_PAD * 2 + HOST_ROW * len(cs)
        hy = ry + SITE_HEADER + SITE_PAD / 2
        for c in cs:
            consumer_pos[c["id"]] = {"x": RIGHT_X + PAD, "y": hy, "w": RIGHT_W - 2 * PAD,
                                     "h": HOST_ROW, "cx": RIGHT_X + PAD + (RIGHT_W - 2 * PAD) / 2,
                                     "cy": hy + HOST_ROW / 2, "zone": z}
            hy += HOST_ROW
        ry += site_h + 10 + extra_per_gap
    right_bottom = ry - 10 - extra_per_gap

    # ── total height ──
    content_bottom = max(left_bottom, right_bottom)
    LEGEND_ROWS = 26 + 18 * len({(l["fn"], l["status"]) for l in lines}) + 30
    H = content_bottom + 10 + LEGEND_ROWS

    # ── render ──
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W * MM:.1f}mm" height="{H * MM:.1f}mm" '
         f'font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif" class="tdiag print stores" data-diagram="{esc(model["id"])}">',
         "<defs>"]
    for k, (col, _) in FUNCTIONS.items():
        o.append(f'<marker id="g-{esc(model["id"])}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" '
                 f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    o += ["</defs>", '<rect width="100%" height="100%" fill="#ffffff"/>']

    # Left panel
    panel_h = left_bottom - 20 + 10
    o.append(f'<rect x="{PAD}" y="20" width="{LEFT_W:.1f}" height="{panel_h:.1f}" rx="10" '
             f'fill="{PANEL_FILL}" stroke="{BORDER}" stroke-width="1.4"/>')
    o.append(f'<text x="{PAD + 14}" y="44" font-size="{F_ZONE}" font-weight="700" fill="{NAVY}" '
             f'letter-spacing="0.5">DATA STORES</text>')

    # Right panel
    panel_h_r = right_bottom - 20 + 10
    o.append(f'<rect x="{RIGHT_X}" y="20" width="{RIGHT_W:.1f}" height="{panel_h_r:.1f}" rx="10" '
             f'fill="{PANEL_FILL}" stroke="{BORDER}" stroke-width="1.4"/>')
    o.append(f'<text x="{RIGHT_X + 14}" y="44" font-size="{F_ZONE}" font-weight="700" fill="{NAVY}" '
             f'letter-spacing="0.5">CONSUMERS BY SITE</text>')

    # ── store rows ──
    for s in stores:
        p = store_pos[s["id"]]
        icon, _, col = KINDS.get(s["kind"], KINDS["unknown"])
        icol = GAP_COL if s.get("flag") else col
        is_flag = bool(s.get("flag"))
        stroke_w = 1.8 if is_flag else 1.2

        o.append(f'<g class="node store" data-id="{esc(s["id"])}" data-flag="{1 if is_flag else 0}">')
        o.append(f'<rect x="{p["x"]:.1f}" y="{p["y"]:.1f}" width="{p["w"]:.1f}" height="{p["h"]:.1f}" rx="6" '
                 f'fill="#ffffff" stroke="{icol if is_flag else BORDER}" stroke-width="{stroke_w}"/>')

        # icon
        ix = p["x"] + 10
        iy = p["y"] + (p["h"] - ICON) / 2
        o.append(f'<g transform="translate({ix:.1f},{iy:.1f}) scale({(ICON / 24):.4f})" '
                 f'fill="none" stroke="{icol}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
                 f'color="{icol}">{ICONS[icon]}</g>')

        # label
        lx = ix + ICON + 10
        ly = p["cy"] + (4 if not is_flag else -2)
        o.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="{F_NAME}" font-weight="700" '
                 f'fill="{GAP_COL if is_flag else NAVY}">{esc(s["label"])}</text>')

        # instance count (right-aligned, well clear of the gutter)
        inst = s.get("instances") or []
        if inst:
            count_txt = f"{len(inst)}" if len(inst) > 1 else f"{inst[0]['host']}"
            o.append(f'<text x="{p["x"] + p["w"] - 12:.1f}" y="{p["cy"] + (2 if not is_flag else -2):.1f}" '
                     f'font-size="12" fill="{MUTED}" text-anchor="end">{esc(count_txt)}</text>')

        # flag badge
        if is_flag:
            fy = p["y"] + p["h"] - 17
            o.append(f'<rect x="{lx:.1f}" y="{fy:.1f}" width="170" height="15" rx="7" fill="{GAP_COL}"/>'
                     f'<text x="{lx + 85:.1f}" y="{fy + 11:.1f}" font-size="10" font-weight="700" fill="#ffffff" '
                     f'text-anchor="middle">FLAGGED — whole drive / users</text>')

        o.append("</g>")

    # ── consumer tiles ──
    for z in site_order:
        cs = by_site[z]
        if not cs:
            continue
        rows = [consumer_pos[c["id"]]["y"] for c in cs]
        top = min(rows) - SITE_PAD
        bottom = max(rows) + SITE_PAD
        site_h = bottom - top + SITE_HEADER
        o.append(f'<rect x="{RIGHT_X + 6:.1f}" y="{top - 4:.1f}" width="{RIGHT_W - 12:.1f}" height="{site_h:.1f}" rx="7" '
                 f'fill="{SUB_FILL}" stroke="{BORDER}" stroke-width="1.2" stroke-dasharray="5 3"/>')
        o.append(f'<text x="{RIGHT_X + 18:.1f}" y="{top + SITE_HEADER - 8:.1f}" '
                 f'font-size="{F_TEXT}" font-weight="700" fill="{NAVY}">{esc(zlabel.get(z, z))}</text>')
        for c in cs:
            cy = consumer_pos[c["id"]]["cy"]
            o.append(f'<text x="{RIGHT_X + 26:.1f}" y="{cy + 4:.1f}" font-size="{F_TEXT}" fill="{MUTED}">'
                     f'{esc(c["label"])}</text>')

    # ── edges ──
    o.append('<g class="edges">')
    gutter_x = LEFT_W + GUTTER / 2
    labpos = {}
    for l in lines:
        sp = store_pos.get(l["t"])
        cp = consumer_pos.get(l["s"])
        if not sp or not cp:
            continue
        x1 = sp["x"] + sp["w"]
        x2 = cp["x"]
        y1 = sp["cy"]
        y2 = cp["cy"]
        labpos[l["lineid"]] = {"x": gutter_x, "y": (y1 + y2) / 2 - 3,
                               "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    # De-collide labels in the gutter
    lds = sorted(labpos.keys(), key=lambda k: labpos[k]["y"])
    last = None
    for k in lds:
        if last is not None and labpos[k]["y"] - last < 15:
            labpos[k]["y"] = last + 15
        last = labpos[k]["y"]

    for l in lines:
        sp = store_pos.get(l["t"])
        cp = consumer_pos.get(l["s"])
        if not sp or not cp or l["lineid"] not in labpos:
            continue
        lp = labpos[l["lineid"]]
        col = FUNCTIONS[l["fn"]][0]
        dash, _ = STATUS_STYLE.get(l["status"], ("", 2.6))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        x1, y1, x2, y2 = lp["x1"], lp["y1"], lp["x2"], lp["y2"]
        pts = [(x1, y1), (gutter_x, y1), (gutter_x, y2), (x2, y2)]
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - clean[-1][0]) > 0.5 or abs(p[1] - clean[-1][1]) > 0.5:
                clean.append(p)
        d = "M" + " L".join(f"{x:.1f},{yy:.1f}" for x, yy in clean)
        o.append(f'<path class="edge" data-id="{esc(l["lineid"])}" data-s="{esc(l["s"])}" data-t="{esc(l["t"])}" data-status="{esc(l["status"])}" '
                 f'd="{d}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linecap="round"{da} '
                 f'marker-end="url(#g-{esc(model["id"])}-{l["fn"]})"/>')
        o.append(f'<text x="{lp["x"]:.1f}" y="{lp["y"]:.1f}" font-size="10" fill="{col}" text-anchor="middle" '
                 f'font-weight="600">{esc(l["mech"][:16])}</text>')
    o.append("</g>")

    # ── legend ──
    y = content_bottom + 26
    used_fn = {l["fn"] for l in lines}
    yy = y
    for fn in sorted(used_fn):
        sts = sorted({l["status"] for l in lines if l["fn"] == fn})
        for st_ in sts:
            col = FUNCTIONS[fn][0]
            dash, _ = STATUS_STYLE.get(st_, ("", 2.6))
            da = f' stroke-dasharray="{dash}"' if dash else ""
            o.append(f'<line x1="12" y1="{yy}" x2="56" y2="{yy}" stroke="{col}" stroke-width="3.2" stroke-linecap="round"{da}/>'
                     f'<text x="66" y="{yy + 4}" font-size="13" fill="{MUTED}">'
                     f'{esc(FUNCTIONS[fn][1])} — {esc(STATUS_PHRASE.get(st_, st_))}</text>')
            yy += 18
    o.append(f'<rect x="12" y="{yy + 2}" width="44" height="14" rx="7" fill="{GAP_COL}"/>'
             f'<text x="66" y="{yy + 13}" font-size="13" fill="{MUTED}">'
             f'Flagged: share of a whole drive or user folders — wider exposure than a purpose-built share</text>')

    info = {"width_mm": TEXT_W_MM, "height_mm": round(H * MM, 1), "fits_page": H <= PAGE_H_MAX,
            "min_text_pt": round(F_TEXT * MM / 0.3528, 1), "stores": len(stores), "lines": len(lines),
            "functions": sorted(used_fn)}
    o.append("</svg>")
    return "\n".join(o), info


def info(model: dict) -> dict:
    _, i = render_store_svg(model)
    return i
