"""Archetype G: where the system holds its data, and which hosts use each store (print layout, A4 text width).

Bands top to bottom: IT, then OT, then anything whose zone is not recorded. Inside OT, one column per data
centre in page order (Rockhampton left, Mackay right), then a full-width row for roles that hold stores in both
data centres. A card is the role that holds stores: its hosts, its stores (a whole-drive or user-folder share is
marked), replication between its hosts, and one row per role that uses its stores.

Each use row starts with a short line sample instead of a long line across the page:
  * colour   the mechanism (database, backup agent, file share), as in the legend
  * style    solid seen in the captures, dashed declared in the flow map and not seen, dotted attempted
  * dot      the side that opens the connection (the user, on the left)
  * arrow    where the data goes (both ends for a database, which reads and writes)
No words sit on lines, no counts are given, and every text is at least 8.2 pt at the 17 cm text width.
"""
from __future__ import annotations

import html

from .icons import ICONS, NAVY, TEAL

W = 1000.0
TEXT_W_MM = 170.0
MM = TEXT_W_MM / W
PAGE_H_MAX = 1350                       # about 229 mm: one A4 page under the caption
F_MIN = 17.0                            # 17 units = 8.2 pt at 170 mm
F_BAND, F_ROLE, F_STORE, F_TEXT = 17.0, 18.0, 17.0, 17.0
LH = 20.0                               # line height for 17-unit text
PAD = 10.0
GAP = 10.0
ICON = 22.0
SAMPLE_W = 62.0

GAP_COL = "#b4602a"
BORDER = "#b9c8d3"
MUTED = "#4f6175"
PANEL_FILL = "#f5f9fc"
CARD_FILL = "#ffffff"

MECH = {"database": ("#167d8d", "Database"), "database replication": ("#167d8d", "Replication"),
        "file share": ("#2f6fb0", "File share"), "file transfer": ("#2f6fb0", "File transfer"),
        "backup agent": ("#b7791f", "Backup agent")}
MECH_DASH = {"database replication": "2 0"}
STATUS_DASH = {"seen": "", "declared": "7 5", "attempted": "2 4"}
STATUS_TEXT = {"seen": "Seen in the captures", "declared": "Declared, not seen",
               "attempted": "Attempted, no reply seen"}
CHAR = 0.54                             # average glyph width / font size (Segoe UI, Helvetica)

esc = lambda s: html.escape(str(s), quote=True)
SITE_ORDER: list[str] = []              # set per render from the model: data-centre labels in page order


# ------------------------------------------------------------------ text
def text_w(text: str, size: float, bold: bool = False) -> float:
    """Estimated width of a text run: capitals and digits are wide, punctuation narrow (host names are capitals)."""
    w = 0.0
    for ch in str(text):
        w += 0.66 if ch.isupper() or ch.isdigit() else (0.29 if ch in " .,:;()'|!iljtf/\\-" else 0.53)
    return w * size * (1.07 if bold else 1.0)


def wrap(text: str, width: float, size: float, bold: bool = False) -> list[str]:
    """Greedy wrap by estimated width, breaking a word only at a space or a hyphen.

    A single word wider than the box is not split: it is drawn on one line at a
    smaller font size (down to 70%)."""
    lines, cur = [], ""
    for word in str(text).split():
        # A single word wider than the box is drawn whole (at a smaller size, down to 70%),
        # never split.
        tok = word
        if not cur:
            cur = tok
        elif text_w(cur + " " + tok, size, bold) <= width:
            cur += " " + tok
        else:
            lines.append(cur); cur = tok
    if cur:
        lines.append(cur)
    return lines or [""]


def _text(x, y, lines, size, fill=NAVY, bold=False, anchor="start") -> str:
    fw = ' font-weight="700"' if bold else ""
    return "".join(f'<text x="{x:.1f}" y="{y + i * (size + 3):.1f}" font-size="{size:.0f}"{fw} fill="{fill}" '
                   f'text-anchor="{anchor}">{esc(t)}</text>' for i, t in enumerate(lines))


# ------------------------------------------------------------------ the line sample
def _sample(x, y, mech, status, data, opens_left=True, mid="m", dash: str | None = None) -> str:
    """A short line from the user (left) to the store (right): colour = mechanism, style = status,
    dot = the side that opens the connection, arrowheads = where the data goes."""
    col = MECH.get(mech, ("#6b7785", mech))[0]
    if dash is None:
        dash = MECH_DASH.get(mech, "") or STATUS_DASH.get(status, "")
    da = f' stroke-dasharray="{dash}"' if dash else ""
    x1, x2 = x + 6, x + SAMPLE_W - 4
    o = [f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="2.6" '
         f'stroke-linecap="round"{da}/>']
    right = data in ("both", "to_t")       # data reaches the store
    left = data in ("both", "to_s")        # data reaches the user (a backup server pulls)
    if right:
        o.append(f'<path d="M{x2 + 3:.1f},{y:.1f} l-9,-5 l0,10 z" fill="{col}"/>')
    if left:
        o.append(f'<path d="M{x1 - 3:.1f},{y:.1f} l9,-5 l0,10 z" fill="{col}"/>')
    if opens_left:
        cx = x1 + (11 if left else 0)
        o.append(f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="4.6" fill="#ffffff" stroke="{col}" stroke-width="2"/>'
                 f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="2.2" fill="{col}"/>')
    return "".join(o)


# ------------------------------------------------------------------ one card
def _hosts_text(c: dict) -> str:
    if c.get("site") == "both":
        by: dict[str, list[str]] = {}
        for h in c["hosts"]:
            by.setdefault(h["site"] or "site not recorded", []).append(h["host"])
        return " · ".join(f"{', '.join(v)} ({k})" for k, v in by.items())
    return ", ".join(h["host"] for h in c["hosts"])


def _use_text(u: dict, c: dict, card_kind: str) -> tuple[str, str, bool]:
    """(who, detail, warn): the user role, then its hosts and what it reaches; warn = zone not recorded."""
    who = u["role"].split(",")[0].strip() if len(u["role"]) > 40 else u["role"]
    hz = u.get("host_zones") or {h: [u["zone_kind"], u["zone"]] for h in u["hosts"]}
    tag = lambda k, z: "" if k == "unknown" else (z if k != card_kind else "")
    groups: dict[str, list[str]] = {}
    for h in u["hosts"]:
        groups.setdefault(tag(*hz.get(h, [u["zone_kind"], u["zone"]])), []).append(h)
    if len(groups) == 1:
        (t, hs), = groups.items()
        bits = ([", ".join(hs)] if hs != [u["role"]] else []) + ([t] if t else [])
    else:                                  # hosts of one role in different zones: each keeps its own zone
        bits = [f"{', '.join(hs)} ({t})" if t else ", ".join(hs) for t, hs in groups.items()]
    dbs = [s for s in c["stores"] if s["kind"] == "database"]
    if u["store"].startswith("backup"):
        bits.append("backs up the host")
    elif u["store"].startswith("a share") or len(dbs) > 1:
        bits.append(f"to {u['store']}")
    if u.get("declared"):
        bits.append("(" + ", ".join(u["declared"]) + ")")
    return who, " · ".join(b for b in bits if b), u["zone_kind"] == "unknown"


def card(c: dict, x: float, y: float, w: float) -> tuple[float, list[str]]:
    o: list[str] = []
    inner = w - 2 * PAD
    cy = y + PAD + F_ROLE
    role = wrap(c["role"], inner, F_ROLE, True)
    o.append(_text(x + PAD, cy, role, F_ROLE, NAVY, True))
    cy += (len(role) - 1) * (F_ROLE + 3) + LH
    hl = wrap(_hosts_text(c), inner, F_TEXT)
    o.append(_text(x + PAD, cy, hl, F_TEXT, MUTED))
    cy += (len(hl) - 1) * (F_TEXT + 3) + 10

    # stores (a wide card puts two side by side)
    ncs = 2 if w > 700 and len(c["stores"]) > 1 else 1
    sw = (inner - GAP * (ncs - 1)) / ncs
    row_top, row_bottom = cy, cy
    for k, s in enumerate(c["stores"]):
        col = k % ncs
        if col == 0:
            cy = row_top = row_bottom
        else:
            cy = row_top
        sx = x + col * (sw + GAP)
        cy += 6
        icon = "database" if s["kind"] == "database" else "storage"
        flag = bool(s.get("flag"))
        icol = GAP_COL if flag else NAVY
        o.append(f'<g transform="translate({sx + PAD:.1f},{cy:.1f}) scale({ICON / 24:.4f})" fill="none" stroke="{icol}" '
                 f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" color="{icol}">{ICONS[icon]}</g>')
        tx = sx + PAD + ICON + 8
        lab = wrap(s["label"], sw - ICON - 8, F_STORE, True)
        o.append(_text(tx, cy + F_STORE - 2, lab, F_STORE, GAP_COL if flag else NAVY, True))
        sy = cy + F_STORE - 2 + (len(lab) - 1) * (F_STORE + 3)
        subs = []
        if s.get("ag"):
            subs.append(f"Availability group {s['ag']}")
        held = sorted({i["host"] for i in s["instances"]})
        if len(c["hosts"]) > 1 and held != sorted(h["host"] for h in c["hosts"]):
            subs.append("On " + ", ".join(held))
        for t in subs:
            ln = wrap(t, sw - ICON - 8, F_TEXT)
            o.append(_text(tx, sy + LH, ln, F_TEXT, MUTED))
            sy += LH + (len(ln) - 1) * (F_TEXT + 3)
        if flag:
            from csa_docx.figures.storeview import FLAG_TEXT
            ft = FLAG_TEXT.get(s["flag"], "Wide share")
            bw = len(ft) * F_TEXT * 0.56 + 18
            o.append(f'<rect x="{tx:.1f}" y="{sy + 7:.1f}" width="{bw:.1f}" height="{F_TEXT + 6:.1f}" rx="{(F_TEXT + 6) / 2:.1f}" '
                     f'fill="{GAP_COL}"/>' + _text(tx + 9, sy + 7 + F_TEXT + 0.5, [ft], F_TEXT, "#ffffff", True))
            sy += F_TEXT + 12
        cy = max(cy + ICON, sy + 6)
        row_bottom = max(row_bottom, cy)

    cy = row_bottom

    # replication between the nodes that hold the store
    for r in c.get("replication", []):
        cy += 8
        o.append(_sample(x + PAD, cy + 6, "database replication", r["status"], "both", opens_left=False, dash="2 0"))
        sites = sorted(r["sites"], key=lambda x_: next((i for i, lab in enumerate(SITE_ORDER) if lab.lower().startswith(x_.lower())), 99))
        where = (" and ".join(sites) if len(sites) > 1 else (sites[0] if sites else ""))
        txt = "Replicated between the cluster nodes" + (f", {where}" if where else "")
        ln = wrap(txt, inner - SAMPLE_W - 6, F_TEXT)
        o.append(_text(x + PAD + SAMPLE_W + 6, cy + 12, ln, F_TEXT, MUTED))
        cy += 6 + len(ln) * (F_TEXT + 3)

    # who uses the stores
    cy += 8
    if not c["uses"]:
        ln = wrap("No other host seen or declared using these stores", inner, F_TEXT)
        o.append(_text(x + PAD, cy + F_TEXT, ln, F_TEXT, MUTED))
        cy += F_TEXT + (len(ln) - 1) * (F_TEXT + 3)
    else:
        o.append(f'<line x1="{x + PAD:.1f}" y1="{cy:.1f}" x2="{x + w - PAD:.1f}" y2="{cy:.1f}" stroke="{BORDER}" stroke-width="1"/>')
        cy += F_TEXT + 6
        o.append(_text(x + PAD, cy, ["USED BY"], F_TEXT, MUTED, True))
    for u in c["uses"]:
        cy += 6
        who, detail, warn = _use_text(u, c, c["band"])
        tx = x + PAD + SAMPLE_W + 6
        tw = inner - SAMPLE_W - 6
        o.append(_sample(x + PAD, cy + 8, u["mechanism"], u["status"], u["data"]))
        one = text_w(who, F_TEXT, True) + text_w("  " + detail, F_TEXT)
        if one <= tw:                       # role and detail on one line
            col = GAP_COL if warn else MUTED
            o.append(f'<text x="{tx:.1f}" y="{cy + 14:.1f}" font-size="{F_TEXT:.0f}"><tspan font-weight="700" fill="{NAVY}">'
                     f'{esc(who)}</tspan><tspan fill="{col}">{esc("  " + detail)}</tspan></text>')
            cy += 14 + 6
            continue
        wl = wrap(who, tw, F_TEXT, True)
        o.append(_text(tx, cy + 14, wl, F_TEXT, NAVY, True))
        dy = cy + 14 + len(wl) * (F_TEXT + 3)
        dl = wrap(detail, tw, F_TEXT)
        o.append(_text(tx, dy, dl, F_TEXT, GAP_COL if warn else MUTED))
        cy = dy + (len(dl) - 1) * (F_TEXT + 3) + 6
    h = cy + PAD - y
    o.insert(0, f'<g class="node card" data-id="{esc(c["id"])}"><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="7" fill="{CARD_FILL}" stroke="{BORDER}" stroke-width="1.3"/>')
    o.append("</g>")
    return h, o


# ------------------------------------------------------------------ the page
def _panel(title: str, x: float, y: float, w: float, h: float, dashed: bool = False) -> str:
    da = ' stroke-dasharray="6 4"' if dashed else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="9" fill="{PANEL_FILL}" stroke="{BORDER}" '
            f'stroke-width="1.3"{da}/>' + _text(x + 12, y + F_BAND + 8, [title.upper()], F_BAND, NAVY, True))


def _grid(cards: list[dict], x: float, y: float, w: float, cols: int) -> tuple[float, list[str]]:
    """Cards in a grid of `cols` columns, filled column by column to balance the heights. Two cards side by side
    get the split of the width that makes the row lowest (the card with more rows gets more width)."""
    if not cards:
        return 0.0, []
    if cols == 2 and len(cards) == 2:
        best = None
        for f in (0.5, 0.55, 0.6, 0.65):
            for a, b in ((cards[0], cards[1]), (cards[1], cards[0])):
                wa = (w - GAP) * f
                hh = max(card(a, 0, 0, wa)[0], card(b, 0, 0, w - GAP - wa)[0])
                if best is None or hh < best[0] - 0.5:
                    best = (hh, a, b, wa)
        hh, a, b, wa = best
        ha, pa = card(a, x, y, wa)
        hb, pb = card(b, x + wa + GAP, y, w - GAP - wa)
        return max(ha, hb), pa + pb
    cw = (w - GAP * (cols - 1)) / cols
    heights = [card(c, 0, 0, cw)[0] for c in cards]
    colh = [0.0] * cols
    o: list[str] = []
    for c, hgt in sorted(zip(cards, heights), key=lambda t: -t[1]):
        k = colh.index(min(colh))
        _h, parts = card(c, x + k * (cw + GAP), y + colh[k], cw)
        o += parts
        colh[k] += hgt + GAP
    return max(colh) - GAP, o


def _site_match(site: str, label: str) -> bool:
    return bool(site) and label.lower().startswith(site.lower())


def render_store_svg(model: dict) -> tuple[str, dict]:
    cards = model.get("cards", [])
    order = model.get("site_order", [])
    SITE_ORDER[:] = order
    o: list[str] = []
    y = 6.0
    x0, wfull = 4.0, W - 8.0
    inner_x, inner_w = x0 + 10, wfull - 20
    HEAD = F_BAND + 18

    # IT, then OT, then anything else
    for band, title in (("it", "IT"), ("ot", "OT"), ("unknown", "Other")):
        bc = [c for c in cards if c["band"] == band]
        if not bc:
            continue
        parts: list[str] = []
        yy = y + HEAD
        if band == "ot":
            cols = []
            for lab in order:
                cs = [c for c in bc if c["site"] != "both" and _site_match(c["site"], lab)]
                if cs:
                    cols.append((lab, cs))
            placed = {c["id"] for _, cs in cols for c in cs}
            both = [c for c in bc if c["site"] == "both"]
            other = [c for c in bc if c["id"] not in placed and c["site"] != "both"]
            if cols:
                cw = (inner_w - GAP * (len(cols) - 1)) / len(cols)
                hs = []
                for i, (lab, cs) in enumerate(cols):
                    cx = inner_x + i * (cw + GAP)
                    h, ps = _grid(cs, cx + 8, yy + F_TEXT + 18, cw - 16, 1)
                    hs.append((cx, lab, h, ps))
                colh = max(h for *_, h, _ in hs) + F_TEXT + 28
                for cx, lab, h, ps in hs:
                    parts.append(f'<rect x="{cx:.1f}" y="{yy:.1f}" width="{cw:.1f}" height="{colh:.1f}" rx="7" fill="none" '
                                 f'stroke="{BORDER}" stroke-width="1.1" stroke-dasharray="5 3"/>')
                    parts.append(_text(cx + 10, yy + F_TEXT + 6, [lab], F_TEXT, NAVY, True))
                    parts += ps
                yy += colh + GAP
            for lab, cs in (("Both data centres", both), ("Site not recorded", other)):
                if not cs:
                    continue
                h, ps = _grid(cs, inner_x + 8, yy + F_TEXT + 18, inner_w - 16, 2 if len(cs) > 1 else 1)
                parts.append(f'<rect x="{inner_x:.1f}" y="{yy:.1f}" width="{inner_w:.1f}" height="{h + F_TEXT + 28:.1f}" rx="7" '
                             f'fill="none" stroke="{BORDER}" stroke-width="1.1" stroke-dasharray="5 3"/>')
                parts.append(_text(inner_x + 10, yy + F_TEXT + 6, [lab], F_TEXT, NAVY, True))
                parts += ps
                yy += h + F_TEXT + 28 + GAP
        else:
            h, ps = _grid(bc, inner_x, yy, inner_w, 2 if len(bc) > 1 else 1)
            parts += ps
            yy += h + GAP
        o.append(_panel(title, x0, y, wfull, yy - y, dashed=band == "unknown"))
        o += parts
        y = yy + 8

    # legend
    uses = [u for c in cards for u in c["uses"]]
    reps = [r for c in cards for r in c.get("replication", [])]
    mechs = list(dict.fromkeys([u["mechanism"] for u in uses] + (["database replication"] if reps else [])))
    if len(mechs) > 1:
        seen = {}
        for m in mechs:
            dash = MECH_DASH.get(m, "") or STATUS_DASH.get("seen", "")
            k = (MECH.get(m, ("", m))[0], dash)
            if k in seen:
                raise ValueError(f"legend entries {seen[k]} and {m} look the same")
            seen[k] = m
    stats = list(dict.fromkeys([u["status"] for u in uses] + [r["status"] for r in reps]))
    flags = sorted({s["flag"] for c in cards for s in c["stores"] if s.get("flag")})
    rows: list[str] = []
    for m in mechs:
        rows.append(("mech", m))
    for s in ("seen", "declared", "attempted"):
        if s in stats:
            rows.append(("status", s))
    rows += [("dot", ""), ("arrow", "")]
    rows += [("flag", f) for f in flags]
    if any(u.get("declared") for u in uses):
        rows.append(("ids", ""))
    y += 6
    ncol = 3
    half = (len(rows) + ncol - 1) // ncol
    colw = wfull / ncol
    for i, (kind, val) in enumerate(rows):
        lx = x0 + 4 + (i // half) * colw
        ly = y + (i % half) * (LH + 4) + 10
        tx = lx + SAMPLE_W + 10
        if kind == "mech":
            o.append(_sample(lx, ly, val, "seen", "none", opens_left=False, dash=MECH_DASH.get(val, "")))
            o.append(_text(tx, ly + 6, [MECH.get(val, ("", val))[1]], F_TEXT, MUTED))
        elif kind == "status":
            o.append(f'<line x1="{lx + 6:.1f}" y1="{ly:.1f}" x2="{lx + SAMPLE_W - 4:.1f}" y2="{ly:.1f}" stroke="{NAVY}" '
                     f'stroke-width="2.6" stroke-linecap="round"' + (f' stroke-dasharray="{STATUS_DASH[val]}"' if STATUS_DASH[val] else "") + "/>")
            o.append(_text(tx, ly + 6, [STATUS_TEXT[val]], F_TEXT, MUTED))
        elif kind == "dot":
            o.append(f'<circle cx="{lx + 12:.1f}" cy="{ly:.1f}" r="4.6" fill="#ffffff" stroke="{NAVY}" stroke-width="2"/>'
                     f'<circle cx="{lx + 12:.1f}" cy="{ly:.1f}" r="2.2" fill="{NAVY}"/>')
            o.append(_text(tx, ly + 6, ["Dot: side that opens it"], F_TEXT, MUTED))
        elif kind == "arrow":
            o.append(f'<line x1="{lx + 6:.1f}" y1="{ly:.1f}" x2="{lx + SAMPLE_W - 4:.1f}" y2="{ly:.1f}" stroke="{NAVY}" stroke-width="2.6"/>'
                     f'<path d="M{lx + SAMPLE_W - 1:.1f},{ly:.1f} l-9,-5 l0,10 z" fill="{NAVY}"/>')
            o.append(_text(tx, ly + 6, ["Arrow: where data goes"], F_TEXT, MUTED))
        elif kind == "ids":
            o.append(_text(lx + 6, ly + 6, ["(R1)"], F_TEXT, MUTED, True))
            o.append(_text(tx, ly + 6, ["Flow map ID of the use"], F_TEXT, MUTED))
        elif kind == "flag":
            from csa_docx.figures.storeview import FLAG_TEXT
            o.append(f'<rect x="{lx + 6:.1f}" y="{ly - 9:.1f}" width="{SAMPLE_W - 10:.1f}" height="18" rx="9" fill="{GAP_COL}"/>')
            o.append(_text(tx, ly + 6, [FLAG_TEXT.get(val, val)], F_TEXT, MUTED))
    y += half * (LH + 4) + 8
    H = y + 4
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W * MM:.1f}mm" height="{H * MM:.1f}mm" '
            f'font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif" class="tdiag print stores" '
            f'data-diagram="{esc(model["id"])}"><rect width="100%" height="100%" fill="#ffffff"/>')
    info = {"width_mm": TEXT_W_MM, "height_mm": round(H * MM, 1), "fits_page": H <= PAGE_H_MAX,
            "min_text_pt": round(F_MIN * MM / 0.3528, 1), "stores": sum(len(c["stores"]) for c in cards),
            "lines": len(uses) + len(reps), "functions": mechs}
    return head + "".join(o) + "</svg>", info


def info(model: dict) -> dict:
    _, i = render_store_svg(model)
    return i
