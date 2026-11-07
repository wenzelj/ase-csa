"""Print layout: the same diagram model drawn to fit the CSA's text width on A4, readable on paper.

The screen layout (layout_tracks) spreads both data centres side by side and is far wider than a page. Scaled
to 17 cm its text drops to about 1 mm. This layout is built for the page instead:

  * the drawing is 1000 units wide and is placed at the full text width (17 cm), so 1 unit = 0.17 mm;
  * every text is at least 17 units (2.9 mm, just over 8 pt) on paper; names are 19 units bold;
  * two columns: the OT data centres on the left, everything else (IT and Internet, other sites, shared
    services, locations not captured) on the right, each zone a box with its cards stacked;
  * a group (e.g. SQL cluster nodes) whose members connect identically becomes one card naming its members;
  * lines between the columns run in a middle channel; lines to the same right-hand system share one lane
    (a bus), so many hosts taking one service read as a tree, not a tangle; each line's label sits next to the
    left-hand card it leaves;
  * lines inside one column run in a channel on that column's outer side;
  * no title or subtitle (the Word caption carries them); the legend sits underneath (notes are not drawn).

    render_print_svg(model) -> (svg, info)   info: {"width_mm", "height_mm", "fits_page", "min_text_pt"}
"""
from __future__ import annotations

import html
import re
from collections import defaultdict

from .icons import GREY, ICONS, KINDS, NAVY, ORANGE, RED, TEAL

W = 1000.0
TEXT_W_MM = 170.0
MM = TEXT_W_MM / W                 # mm per unit
F_NAME, F_TEXT, F_ZONE = 19, 17, 18
PAGE_H_MAX = 1350                  # about 23 cm: what fits under a heading with the caption on a portrait page
HEAD, PAD, GAP = 36, 12, 10
PORT = 26                          # vertical spacing of lines on one card side
LANE = 13
TIERS = ["access", "terminal", "app", "db", "ot"]
# Design style (CSA IT/OT design example): tinted zone panels with a soft border and an uppercase navy title,
# white device tiles with a navy icon, a bold navy name and a grey role, teal lines with grey labels on white.
# Solid teal is a path seen in the captures, dashed teal a configured setting, dotted grey configured but unused;
# red keeps the risk statuses apart, as the evidence rules require.
INK, MUTED, BORDER, TILE_BORDER = NAVY, "#55677a", "#b9c8d3", "#c9d6df"
ZONE_FILL = {"it": "#f2f7fc", "shared": "#fff8f0", "nosite": "#f5f7f9", "outside": "#f5f7f9"}
OT_FILL = "#f1f9f7"
STATUS_STYLE = {
    "observed": (TEAL, "", 2.6, "Observed in connection captures"),
    "configured": (TEAL, "8 5", 2.4, "Configured setting"),
    "inactive": (GREY, "2.5 4", 2.4, "Configured, not in use"),
    "inferred": (NAVY, "8 5", 2.2, "Inferred — validate"),
    "documented": (NAVY, "2.5 4", 2.4, "Documented only"),
    "unknown": (RED, "8 5", 2.4, "Path not captured"),
    "unenforced": (RED, "", 2.8, "Crosses a zone; no control evidenced"),
    "direct": (RED, "", 2.8, "From outside OT; no jump host"),
    "via-jump": ("#1a7f37", "", 2.6, "Through a jump host"),
}
esc = lambda s: html.escape(str(s), quote=True)


def _cut(text: str, units: float, size: float, bold: bool = False) -> str:
    n = max(4, int(units / (size * (0.63 if bold else 0.55))))
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _members_label(ids: list[str]) -> str:
    """ROTPRDCLU101, ROTPRDCLU102 ... -> ROTPRDCLU101–104 (or 101, 103) when they share a stem."""
    m = [re.fullmatch(r"(.*?)(\d+)", i) for i in ids]
    if all(m) and len({x.group(1) for x in m}) == 1:
        stem, nums = m[0].group(1), sorted(int(x.group(2)) for x in m)
        width = len(m[0].group(2))
        if nums == list(range(nums[0], nums[-1] + 1)):
            return f"{stem}{nums[0]:0{width}d}–{nums[-1]:0{width}d}"
        return f"{stem}{nums[0]:0{width}d}, " + ", ".join(f"{n:0{width}d}" for n in nums[1:])
    return ", ".join(ids)


def short_label(e: dict) -> str:
    if e.get("short") is not None:
        return e["short"]
    lines = [l for l in (e.get("label") or "").split("\n") if l]
    if not lines:
        return ""
    more = sum(int(x) for x in re.findall(r"\+(\d+) more", " ".join(lines)))
    first = [l for l in lines if not l.startswith("+")]
    extra = len(first) - 1 + more
    head = re.sub(r"\s*·\s*", " ", first[0])
    return _cut(head, 175, F_TEXT) + (f" +{extra}" if extra > 0 else "")


# ------------------------------------------------------------------ model preparation
def prepare(model: dict) -> dict:
    """Collapse groups whose members connect identically; keep everything else as it is."""
    nodes = {n["id"]: dict(n) for n in model["nodes"]}
    groups = {g["id"]: g for g in model.get("groups", [])}
    edges = [dict(e) for e in model["edges"]]
    collapsed: dict[str, str] = {}
    for g in groups.values():
        sig = {}
        for m in g["members"]:
            sig[m] = sorted((e["t"] if e["s"] == m else e["s"], e["s"] == m, short_label(e), e["status"])
                            for e in edges if m in (e["s"], e["t"]))
        if len({tuple(v) for v in sig.values()}) == 1:
            first = nodes[g["members"][0]]
            role = re.sub(r"\s*\(\d+\)\s*$", "", g["label"])
            nodes[g["id"]] = {**first, "id": g["id"], "label": _members_label(g["members"]),
                              "role": f"{role} ({len(g['members'])})", "group": None}
            for m in g["members"]:
                collapsed[m] = g["id"]
                nodes.pop(m, None)
    for e in edges:
        e["s"], e["t"] = collapsed.get(e["s"], e["s"]), collapsed.get(e["t"], e["t"])
    seen, out = set(), []
    for e in edges:
        k = (e["s"], e["t"], short_label(e), e["status"])
        if e["s"] != e["t"] and k not in seen:
            seen.add(k); out.append(e)
    keep_groups = [g for g in groups.values() if g["id"] not in nodes]
    kept = {g["id"] for g in keep_groups}
    for n in nodes.values():
        if n.get("group") not in kept:
            n["group"] = None                        # a group the view left out, or one collapsed into a card
    for g in keep_groups:
        for m in g["members"]:
            if m in nodes:
                nodes[m]["group"] = g["id"]
    return {**model, "nodes": list(nodes.values()), "edges": out, "groups": keep_groups}


def _service(line: str) -> str:
    line = re.sub(r"^(TCP|UDP)\s+", "", line.strip())
    return line.split(" · ")[0].strip()


def aggregate_zones(model: dict) -> dict:
    """One line per pair of zones (and evidence status), labelled with the services on it. Lines inside one zone
    are left out. For the system overview and the zones-and-conduits figures, where host-to-host lines would
    not be readable at print size."""
    zone_of = {n["id"]: n["zone"] for n in model["nodes"]} | {g["id"]: g["zone"] for g in model.get("groups", [])}
    zone = lambda x: x[2:] if x.startswith("Z:") else zone_of.get(x)
    agg: dict[tuple, dict] = {}
    inside = 0
    for e in model["edges"]:
        a, b = zone(e["s"]), zone(e["t"])
        if a is None or b is None:
            continue
        if a == b:
            inside += 1; continue
        k = (*sorted((a, b)), e["status"])
        d = agg.setdefault(k, {"dirs": set(), "svc": [], "more": 0, "evidence": set(), "hosts": set()})
        d["dirs"].add((a, b) if e.get("dir") != "both" else "both")
        for ln in (e.get("label") or "").split("\n"):
            mm = re.match(r"\+(\d+) more", ln.strip())
            if mm:
                d["more"] += int(mm.group(1))
            elif ln.strip() and e["status"] not in ("configured", "inactive"):
                d["svc"].append(_service(ln))
            elif ln.strip():
                d["svc"] += [x.strip() for x in ln.split("·") if x.strip()]
        d["evidence"].update(e.get("evidence", [])); d["hosts"].update((e.get("detail") or {}).get("hosts", []))
    edges = []
    for i, ((a, b, st), d) in enumerate(agg.items(), 1):
        svc = list(dict.fromkeys(d["svc"]))
        lines, cur = [], ""
        for x in svc:
            if len(lines) == 2 and len(cur) + len(x) + 2 > 17:
                break
            if cur and len(cur) + len(x) + 2 > 19:
                lines.append(cur); cur = ""
            cur = f"{cur}, {x}" if cur else x
        if cur and len(lines) < 3:
            lines.append(cur)
        shown = sum(len(l.split(", ")) for l in lines)
        extra = len(svc) - shown + d["more"]
        if extra > 0:
            lines[-1] = lines[-1] + f" +{extra}"
        both = "both" in d["dirs"] or len(d["dirs"]) > 1
        s_, t_ = (a, b) if both else next(iter(d["dirs"]))
        edges.append({"id": f"ZL-{i:02d}", "s": f"Z:{s_}", "t": f"Z:{t_}", "dir": "both" if both else "forward",
                      "label": "\n".join(lines), "short": "\n".join(lines), "status": st, "evidence": sorted(d["evidence"]),
                      "detail": {"hosts": sorted(d["hosts"])}})
    notes = list(model.get("notes", []))
    if inside:
        notes.append("At print size the lines join zones, not hosts, and connections inside one zone are not drawn; "
                     "the System explorer shows every host-to-host connection.")
    return {**model, "edges": edges, "notes": notes, "groups": model.get("groups", [])}


# ------------------------------------------------------------------ layout + render
def render_print_svg(model: dict, aggregate: bool = False) -> tuple[str, dict]:
    """The figure as printed in the CSA: the band design (IT, boundary, OT; one icon per role; one line per
    function). aggregate: zones-and-conduits figures, whose OT lines join sites rather than roles."""
    from .band_layout import render_band_svg
    opts = model.get("print") or {}
    return render_band_svg(model, conduits=bool(aggregate or opts.get("conduits")))


def render_card_svg(model: dict, aggregate: bool = False) -> tuple[str, dict]:
    """The earlier two-column card layout (kept for comparison; no longer used for CSA figures)."""
    m = prepare(aggregate_zones(model) if aggregate else model)
    stem = m["id"] + "-print"
    dcs = list((m.get("layout") or {}).get("dcs") or [])
    zones = [z for z in m["zones"] if any(n["zone"] == z["id"] for n in m["nodes"])]
    zlabel = {z["id"]: z["label"] for z in m["zones"]}
    left = [z["id"] for z in zones if z["id"] in dcs] + [z["id"] for z in zones if z["id"].startswith("site:")]
    right_order = ["it", "nosite", "shared", "outside"]
    right = [z for z in right_order if any(n["zone"] == z for n in m["nodes"])]
    if not left:                                  # nothing in a data centre: split the zones over two columns
        left, right = right[: (len(right) + 1) // 2], right[(len(right) + 1) // 2:]
    side = {z: "L" for z in left} | {z: "R" for z in right}
    nodes = {n["id"]: n for n in m["nodes"]}
    groups = {g["id"]: g for g in m.get("groups", [])}
    zone_of = {n["id"]: n["zone"] for n in m["nodes"]} | {g["id"]: nodes[g["members"][0]]["zone"] for g in groups.values()}
    end_zone = lambda x: x[2:] if x.startswith("Z:") else zone_of.get(x)
    edges = [e for e in m["edges"] if end_zone(e["s"]) in side and end_zone(e["t"]) in side]

    # classify each line: between columns (bus per right-hand end), or inside one column
    buses: dict[tuple, list] = defaultdict(list)
    inner = {"L": [], "R": []}
    for e in edges:
        a, b = side[end_zone(e["s"])], side[end_zone(e["t"])]
        if a != b:
            l, r = (e["s"], e["t"]) if a == "L" else (e["t"], e["s"])
            into_r = (e["t"] == r) or e.get("dir") == "both"
            into_l = (e["t"] == l) or e.get("dir") == "both"
            buses[(r, e["status"], into_r)].append({**e, "_l": l, "_r": r, "_into_l": into_l})
        else:
            inner[a].append(e)

    # widths: lines inside the left column also run in the middle channel (their labels sit with the others)
    lw = lambda es: min(200, max([len(ln) * F_TEXT * 0.55 for e in es for ln in short_label(e).split("\n")] + [0]) + 16)
    lbl_w = lw([e for lst in buses.values() for e in lst] + inner["L"])
    lbl_r = lw(inner["R"]) if inner["R"] else 0
    lanes_mid = len(buses) + len(inner["L"])
    lch, rch = 0.0, (len(inner["R"]) * LANE + lbl_r + 14 if inner["R"] else 0.0)
    mid = lbl_w + lanes_mid * LANE + 30
    cw_r = 300.0
    cw = W - lch - rch - mid - 4 * PAD - cw_r     # left column takes the rest (it holds most of the hosts)
    if cw < cw_r:
        cw = cw_r = (W - lch - rch - mid - 4 * PAD) / 2
    scale_note = None
    if cw_r < 250:                                 # too many lines for the width: keep cards readable, widen
        cw = cw_r = 250
        scale_note = "wide"
    lx0 = lch + PAD                               # left card x
    rx0 = lch + 2 * PAD + cw + mid + PAD          # right card x  (zone boxes add PAD around cards)
    page_w = rx0 + cw_r + PAD + rch

    # ports per card side
    ports: dict[tuple, list] = defaultdict(list)    # (obj, "L"/"R") -> [key]
    for k, lst in buses.items():
        ports[(k[0], "L")].append(("bus", k))
        for e in lst:
            ports[(e["_l"], "R")].append(("e", e["id"]))
    for e in inner["L"]:
        ports[(e["s"], "R")].append(("e", e["id"])); ports[(e["t"], "R")].append(("e2", e["id"]))
    for e in inner["R"]:
        ports[(e["s"], "R")].append(("e", e["id"])); ports[(e["t"], "R")].append(("e2", e["id"]))
    elabel = {e["id"]: short_label(e) for e in edges}
    def item_h(it):
        if it[0] == "bus":
            return PORT
        return max(PORT, 20 * max(1, len(elabel.get(it[1], "").split("\n"))) + 8)
    def side_h(o, s_):
        return sum(item_h(it) for it in ports.get((o, s_), []))
    def card_h(i):
        return max(66, max(side_h(i, "L"), side_h(i, "R")) + 14)
    ztitle = {z: _title_lines(zlabel[z], (cw if side[z] == "L" else cw_r) + 2 * PAD - 28) for z in side}
    zhead = lambda z: HEAD + 21 * (len(ztitle[z]) - 1)
    def head_h(z):
        if aggregate:                                  # zone-level figure: lines meet the zone's side
            return zhead(z)
        ph = max(side_h("Z:" + z, "L"), side_h("Z:" + z, "R"))
        return zhead(z) + (ph + 4 if ph else 0)          # host-level figure: a line to a whole zone meets its title bar
    CHIP_H = 40

    # vertical stacking
    def order_cards(z):
        items = [n for n in m["nodes"] if n["zone"] == z]
        if z not in dcs:
            return items                                  # bands keep the model's order (providers by data centre)
        tier = lambda n: TIERS.index(n.get("tier")) if n.get("tier") in TIERS else len(TIERS)
        items.sort(key=lambda n: (tier(n), n.get("group") or "", n["label"]))
        return items
    rect, zrect, grect = {}, {}, {}
    col_h = {}
    for col, zs, x, w in (("L", left, lx0, cw), ("R", right, rx0, cw_r)):
        y = 0.0
        for z in zs:
            top = y
            y += head_h(z)
            cards = order_cards(z)
            if aggregate:
                # zone-level figure: cards are one-line chips (icon + name), clear of the zone edge the lines meet
                inset = 18
                cx0 = x if col == "L" else x + inset
                ww = w - inset
                need = max([len(n["label"]) for n in cards] + [8]) * F_NAME * 0.63 + 52
                per = 2 if ww >= 2 * need + GAP else 1
                cwh = (ww - GAP * (per - 1)) / per
                for i, n in enumerate(cards):
                    cx = cx0 + (i % per) * (cwh + GAP)
                    rect[n["id"]] = (cx, y, cx + cwh, y + CHIP_H)
                    if i % per == per - 1 or i == len(cards) - 1:
                        y += CHIP_H + GAP
            else:
                prev_g = None
                gstart = {}
                for n in cards:
                    g = n.get("group")
                    if g and g != prev_g:
                        y += 6; gstart[g] = y; y += 26
                    if prev_g and g != prev_g and prev_g in gstart:
                        grect[prev_g] = (x - 6, gstart[prev_g], x + w + 6, y + 2); y += 8
                    h = card_h(n["id"])
                    rect[n["id"]] = (x, y, x + w, y + h)
                    y += h + GAP
                    prev_g = g
                if prev_g and prev_g in gstart and prev_g not in grect:
                    grect[prev_g] = (x - 6, gstart[prev_g], x + w + 6, y + 2); y += 8
            y = max(y, top + zhead(z) + max(side_h("Z:" + z, "L"), side_h("Z:" + z, "R")) + 4)
            y += PAD - GAP + 2
            zrect[z] = (x - PAD, top, x + w + PAD, y)
            y += 18
        col_h[col] = y
    for g, r in grect.items():
        rect[g] = r
    body_h = max(col_h.values() or [0])

    def obj_rect(i):
        if i.startswith("Z:"):
            x1, y1, x2, y2 = zrect[i[2:]]
            return (x1, y1, x2, y2) if aggregate else (x1, y1, x2, y1 + head_h(i[2:]))
        return rect[i]

    # port positions: spread down the side, ordered by the other end's height
    port_xy = {}
    def other_y(item, o):
        kind, k = item
        if kind == "bus":
            ys = [obj_rect(e["_l"])[1] for e in buses[k]]; return sum(ys) / len(ys)
        e = next(x for x in edges if x["id"] == k)
        oth = e["t"] if kind == "e" and e["s"] == o else e["s"]
        r = obj_rect(oth); return r[1]
    for (o, s_), items in ports.items():
        r = obj_rect(o)
        items.sort(key=lambda it: other_y(it, o))
        top = r[1] + (zhead(o[2:]) if o.startswith("Z:") else 0)
        total = sum(item_h(it) for it in items)
        yy = top + max(0.0, (r[3] - top - total) / 2)
        for it in items:
            h = item_h(it)
            n_lines = 1 if it[0] == "bus" else max(1, len(elabel.get(it[1], "").split("\n")))
            y = yy + (h / 2 if it[0] == "bus" or n_lines == 1 else 20 * n_lines - 2) + (4 if n_lines == 1 and it[0] != "bus" else 0)
            x = r[2] if s_ == "R" else r[0]
            port_xy[(o, s_, it)] = (x, y)
            yy += h

    # lanes: middle (one per bus), left/right channels (one per inner line)
    bus_keys = sorted(buses, key=lambda k: obj_rect(k[0])[1])
    mid_x0 = lx0 + cw + PAD + lbl_w
    inner_x = {e["id"]: mid_x0 + 14 + i * LANE for i, e in enumerate(inner["L"])}
    lane_x = {k: mid_x0 + 14 + (len(inner["L"]) + i) * LANE for i, k in enumerate(bus_keys)}
    for i, e in enumerate(inner["R"]):
        inner_x[e["id"]] = rx0 + cw_r + PAD + lbl_r + 8 + i * LANE

    # ------------------------------------------------------------------ SVG
    used_status = sorted({e["status"] for e in edges})
    used_kinds = sorted({n["kind"] for n in m["nodes"]})
    notes: list[str] = []          # no writing under the legend: the model keeps its notes for the page and the brief
    wrap = lambda t: _wrap(t, int(page_w / (F_TEXT * 0.57)))
    note_lines = sum(len(wrap(t)) for t in notes)
    leg_rows = max(len(used_status), (len(used_kinds) + 1) // 2)
    legend_h = 30 + leg_rows * 26 + (20 + note_lines * 23 if notes else 0)
    H = body_h + 10 + legend_h
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {page_w:.0f} {H:.0f}" width="{page_w * MM:.1f}mm" height="{H * MM:.1f}mm" '
         f'font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif" class="tdiag print" data-diagram="{esc(stem)}">', "<defs>"]
    for k, (col, _, _, _) in STATUS_STYLE.items():
        o.append(f'<marker id="p-{esc(stem)}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
                 f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    o += ["</defs>", '<rect width="100%" height="100%" fill="#ffffff"/>']
    for z, (x1, y1, x2, y2) in zrect.items():
        dashed = ' stroke-dasharray="6 4"' if z == "outside" else ""
        fill = ZONE_FILL.get(z, OT_FILL)
        o.append(f'<g class="zone" data-id="{esc(z)}"><rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="12" '
                 f'fill="{fill}" stroke="{BORDER}" stroke-width="1.6"{dashed}/>'
                 + "".join(f'<text x="{x1 + 14:.1f}" y="{y1 + 26 + 21 * j:.1f}" font-size="{F_ZONE}" font-weight="700" fill="{INK}" '
                         f'letter-spacing="0.4">{esc(t_)}</text>' for j, t_ in enumerate(ztitle[z])) + '</g>')
    for g, (x1, y1, x2, y2) in grect.items():
        o.append(f'<g class="group" data-id="{esc(g)}"><rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="9" '
                 f'fill="#e4f2f1" stroke="{TEAL}" stroke-width="1.2" stroke-dasharray="5 3"/><text x="{x1 + 10:.1f}" y="{y1 + 20:.1f}" font-size="{F_TEXT}" '
                 f'font-weight="700" fill="{INK}">{esc(_cut(groups[g]["label"], x2 - x1 - 20, F_TEXT))}</text></g>')

    def path(pts):
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    def line(pts, st, start_arrow, end_arrow, eid):
        col, dash, w, _ = STATUS_STYLE.get(st, STATUS_STYLE["observed"])
        mk = (f' marker-end="url(#p-{esc(stem)}-{st})"' if end_arrow else "") + (f' marker-start="url(#p-{esc(stem)}-{st})"' if start_arrow else "")
        return (f'<path class="edge" data-id="{esc(eid)}" d="{path(pts)}" fill="none" stroke="{col}" stroke-width="{w}"'
                f'{(" stroke-dasharray=" + chr(34) + dash + chr(34)) if dash else ""}{mk}/>')
    o.append('<g class="edges">')
    label_svg = []
    def put_label(text, x, y, anchor="start"):
        ls = text.split("\n")
        for j, t_ in enumerate(ls):
            by = y - 5 - 20 * (len(ls) - 1 - j)
            tw = len(t_) * F_TEXT * 0.56 + 6
            bx = x - 3 if anchor == "start" else x - tw / 2
            label_svg.append(f'<rect x="{bx:.1f}" y="{by - F_TEXT:.1f}" width="{tw:.1f}" height="{F_TEXT + 2:.1f}" fill="#ffffff"/>'
                             f'<text x="{x:.1f}" y="{by:.1f}" font-size="{F_TEXT}" fill="{MUTED}" '
                             f'text-anchor="{anchor}">{esc(t_)}</text>')
    for k in bus_keys:
        r_obj, st, into_r = k
        lst = buses[k]
        lx = lane_x[k]
        rp = port_xy[(r_obj, "L", ("bus", k))]
        ys = []
        for e in lst:
            lp = port_xy[(e["_l"], "R", ("e", e["id"]))]
            ys.append(lp[1])
            o.append(line([lp, (lx, lp[1])], st, e["_into_l"], False, e["id"]))
            t = elabel.get(e["id"], "")
            if t:
                put_label(t, lp[0] + 6, lp[1])
            if len(lst) > 1:
                o.append(f'<circle cx="{lx:.1f}" cy="{lp[1]:.1f}" r="3.8" fill="{STATUS_STYLE.get(st, STATUS_STYLE["observed"])[0]}"/>')
        y_lo, y_hi = min(ys + [rp[1]]), max(ys + [rp[1]])
        o.append(line([(lx, y_lo), (lx, y_hi)], st, False, False, f"bus-{r_obj}"))
        o.append(line([(lx, rp[1]), rp], st, False, into_r, f"bus-{r_obj}-in"))
    for s_ in ("L", "R"):
        for e in inner[s_]:
            a = port_xy[(e["s"], "R", ("e", e["id"]))]; b = port_xy[(e["t"], "R", ("e2", e["id"]))]
            x = inner_x[e["id"]]
            o.append(line([a, (x, a[1]), (x, b[1]), b], e["status"], e.get("dir") == "both", True, e["id"]))
            t = elabel.get(e["id"], "")
            if t:
                put_label(t, a[0] + 6, a[1])
    o.append("</g>")

    for n in m["nodes"]:
        x1, y1, x2, y2 = rect[n["id"]]
        icon, kind_label, col = KINDS.get(n["kind"], KINDS["unknown"])
        unk = n["kind"] in ("unknown", "gap")
        stroke = RED if n["kind"] == "gap" else (GREY if unk else TILE_BORDER)
        dash = ' stroke-dasharray="5 3"' if unk else ""
        box = (f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="8" fill="#ffffff" stroke="{stroke}" '
               f'stroke-width="1.4"{dash}/>')
        icon_g = lambda tx, ty, sc: (f'<g transform="translate({tx:.1f},{ty:.1f}) scale({sc})" fill="none" stroke="{col}" '
                                     f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" color="{col}">{ICONS[icon]}</g>')
        if aggregate:
            o.append(f'<g class="node" data-id="{esc(n["id"])}">{box}{icon_g(x1 + 10, (y1 + y2) / 2 - 12.5, 1.04)}'
                     f'<text x="{x1 + 44:.1f}" y="{(y1 + y2) / 2 + 7:.1f}" font-size="{F_NAME}" font-weight="700" fill="{INK}">'
                     f'{esc(_cut(n["label"], x2 - x1 - 50, F_NAME, True))}</text></g>')
            continue
        o.append(f'<g class="node" data-id="{esc(n["id"])}">{box}{icon_g(x1 + 11, (y1 + y2) / 2 - 17, 1.42)}'
                 f'<text x="{x1 + 54:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" font-size="{F_NAME}" font-weight="700" fill="{INK}">'
                 f'{esc(_cut(n["label"], x2 - x1 - 60, F_NAME, True))}</text>'
                 f'<text x="{x1 + 54:.1f}" y="{(y1 + y2) / 2 + 17:.1f}" font-size="{F_TEXT}" fill="{MUTED}">'
                 f'{esc(_cut(n.get("role") or kind_label, x2 - x1 - 60, F_TEXT))}</text></g>')
    o += label_svg

    # legend and notes
    y = body_h + 10
    y += 28
    for i, st in enumerate(used_status):
        col, dash, w, lab = STATUS_STYLE.get(st, STATUS_STYLE["observed"])
        yy = y + i * 26
        o.append(f'<line x1="4" y1="{yy - 6:.1f}" x2="44" y2="{yy - 6:.1f}" stroke="{col}" stroke-width="{w + 0.6}"'
                 f'{(" stroke-dasharray=" + chr(34) + dash + chr(34)) if dash else ""}/>'
                 f'<text x="52" y="{yy:.1f}" font-size="{F_TEXT}" fill="{MUTED}">{esc(lab)}</text>')
    kx = max(380.0, page_w * 0.42)
    for i, k in enumerate(used_kinds):
        icon, lab, col = KINDS.get(k, KINDS["unknown"])
        xx = kx + (i % 2) * (page_w - kx) / 2
        yy = y + (i // 2) * 26
        o.append(f'<g transform="translate({xx:.1f},{yy - 17:.1f}) scale(0.9)" fill="none" stroke="{col}" stroke-width="2" '
                 f'stroke-linecap="round" stroke-linejoin="round" color="{col}">{ICONS[icon]}</g>'
                 f'<text x="{xx + 28:.1f}" y="{yy:.1f}" font-size="{F_TEXT}" fill="{MUTED}">{esc(lab)}</text>')
    y += leg_rows * 26 + 8
    for t in notes:
        for ln in wrap(t):
            y += 23
            o.append(f'<text x="4" y="{y:.1f}" font-size="{F_TEXT}" fill="{MUTED}">{esc(ln)}</text>')
    o.append("</svg>")
    min_pt = F_TEXT * (TEXT_W_MM / page_w) / 0.3528
    info = {"width_mm": TEXT_W_MM, "height_mm": round(H * TEXT_W_MM / page_w, 1), "fits_page": H * TEXT_W_MM / page_w <= PAGE_H_MAX * MM,
            "min_text_pt": round(min_pt, 1), "wide": scale_note == "wide"}
    return "\n".join(o), info


def _title_lines(label: str, units: float) -> list[str]:
    """A zone title in capitals, on one line or two (a long one is cut on the second)."""
    per = max(6, int(units / (F_ZONE * 0.66)))
    words, lines, cur = label.upper().split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > per:
            lines.append(cur); cur = ""
        cur = f"{cur} {w}" if cur else w
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return [l if len(l) <= per else l[: per - 1].rstrip() + "…" for l in lines]


def _wrap(text, width):
    words, line, lines = text.split(), "", []
    for w in words:
        if line and len(line) + len(w) > width:
            lines.append(line.strip()); line = ""
        line += w + " "
    return lines + [line.strip()] if line.strip() else lines
