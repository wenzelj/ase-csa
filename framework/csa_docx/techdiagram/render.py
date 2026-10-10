"""Draw a diagram model as one SVG: the CSA figure and the Evidence Workspace view use the same file.

Boxes are placed and lines routed by layout_tracks (no Graphviz). Every element carries data-id
attributes so a viewer can select a system or a line and highlight what it connects to.
"""
from __future__ import annotations

import html
import math

from .icons import ICONS, KINDS
from .layout_tracks import NODE_H, NODE_W, layout

STATUS = {  # line style per evidence status
    "observed":   {"stroke": "#3d444d", "dash": "",        "w": 1.4, "label": "Observed in connection captures"},
    "configured": {"stroke": "#9a6700", "dash": "",        "w": 1.4, "label": "Configured setting (DNS, Kerberos, time)"},
    "inferred":   {"stroke": "#3d444d", "dash": "6 4",     "w": 1.4, "label": "Inferred — validate"},
    "documented": {"stroke": "#3d444d", "dash": "1.5 3.5", "w": 1.6, "label": "Documented only, not observed"},
    "unknown":    {"stroke": "#cf222e", "dash": "6 4",     "w": 1.4, "label": "Path not captured"},
}
TOP, LEFT = 92, 170          # title strip; left margin holds the tier labels
ROLE_CH = 34                 # role text that fits on a card at 12.5px
NAME_CH = 23                 # name that fits at 16px bold; the full name is in the tooltip and panel
esc = lambda s: html.escape(str(s), quote=True)


def _rounded(P, r=7):
    d = f"M{P[0][0]:.1f},{P[0][1]:.1f}"
    for i in range(1, len(P) - 1):
        (x0, y0), (x1, y1), (x2, y2) = P[i - 1], P[i], P[i + 1]
        l1 = math.hypot(x1 - x0, y1 - y0) or 1; l2 = math.hypot(x2 - x1, y2 - y1) or 1
        rr = min(r, l1 / 2, l2 / 2)
        a = (x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr); b = (x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr)
        d += f" L{a[0]:.1f},{a[1]:.1f} Q{x1:.1f},{y1:.1f} {b[0]:.1f},{b[1]:.1f}"
    return d + f" L{P[-1][0]:.1f},{P[-1][1]:.1f}"


def _along(pts, f):
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    L = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs) or 1
    t = L * f
    for a, b in segs:
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        if t <= l and l > 0: return a[0] + (b[0] - a[0]) * t / l, a[1] + (b[1] - a[1]) * t / l
        t -= l
    return pts[-1]


def _wrap(text, width):
    words, line, lines = text.split(), "", []
    for w in words:
        if line and len(line) + len(w) > width: lines.append(line.strip()); line = ""
        line += w + " "
    return lines + [line.strip()] if line.strip() else lines


def render_svg(model: dict) -> str:
    stem = model["id"]
    T = layout(model)
    zones = {z["id"]: z for z in model["zones"]}
    groups = {g["id"]: g for g in model.get("groups", [])}
    fx = lambda x: x + LEFT
    fy = lambda y: y + TOP
    pos = {k: (fx(x), fy(y)) for k, (x, y) in T["pos"].items()}
    paths = {k: [(fx(x), fy(y)) for x, y in v] for k, v in T["paths"].items()}
    W = T["W"] + LEFT + 24
    note_lines = sum(len(_wrap(n, 60)) + 2 for n in model.get("notes", []))
    legend_h = max(190, 50 + 18 * note_lines) + 28 * len(model.get("steps", []))
    H = T["H"] + TOP + legend_h
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
         f'font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif" class="tdiag" data-diagram="{esc(stem)}">', "<defs>"]
    for k, st in STATUS.items():
        o.append(f'<marker id="ah-{stem}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                 f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{st["stroke"]}"/></marker>')
    o += ["</defs>", '<rect width="100%" height="100%" fill="#ffffff"/>',
          f'<text x="24" y="38" font-size="26" font-weight="700" fill="#1f2328">{esc(model["title"])}</text>',
          f'<text x="24" y="66" font-size="15" fill="#57606a">{esc(model.get("subtitle", ""))}</text>']

    # zones, then groups on top
    for zid, (x1, y1, x2, y2) in T["zones"].items():
        z = zones[zid]; dashed = zid == "outside"
        dash_attr = ' stroke-dasharray="6 4"' if dashed else ""
        o.append(f'<g class="zone" data-id="{esc(zid)}"><rect x="{fx(x1):.1f}" y="{fy(y1):.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" '
                 f'rx="14" fill="{"#fbfbfc" if dashed else "#f5f7fa"}" stroke="#c9d1d9"{dash_attr}/>'
                 f'<text x="{fx(x1) + 18:.1f}" y="{fy(y1) + 30:.1f}" font-size="18" font-weight="700" fill="#24292f" letter-spacing="0.2">'
                 f'{esc(z["label"] if dashed else z["label"].upper())}</text></g>')
    for lab_, y1_, y2_ in T["tiers"]:
        Y1, Y2 = fy(y1_) - 4, fy(y2_) + 2
        for bx in T["dcs"]:
            o.append(f'<rect x="{fx(bx[0]) + 6:.1f}" y="{Y1:.1f}" width="{bx[2] - bx[0] - 12:.1f}" height="{Y2 - Y1:.1f}" rx="8" fill="#e9edf2" fill-opacity="0.55"/>')
        tl = lab_.upper().split("\n")
        for j, t_ in enumerate(tl):
            o.append(f'<text x="{LEFT - 14}" y="{(Y1 + Y2) / 2 + 4 + (j - (len(tl) - 1) / 2) * 17:.1f}" font-size="14" font-weight="700" '
                     f'fill="#57606a" text-anchor="end" letter-spacing="0.5">{esc(t_)}</text>')
    for gid, (x1, y1, x2, y2) in T["groups"].items():
        o.append(f'<g class="group" data-id="{esc(gid)}"><rect x="{fx(x1):.1f}" y="{fy(y1):.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="10" '
                 f'fill="#eef4ff" stroke="#9cb9e8" stroke-dasharray="4 3"/><text x="{fx(x1) + 12:.1f}" y="{fy(y1) + 21:.1f}" font-size="14" '
                 f'font-weight="600" fill="#1f4f99">{esc(groups[gid]["label"])}</text></g>')

    # lines
    o.append('<g class="edges">')
    for e in model["edges"]:
        st = STATUS[e["status"]]; d = _rounded(paths[e["id"]])
        mk = f'marker-end="url(#ah-{stem}-{e["status"]})"' + (f' marker-start="url(#ah-{stem}-{e["status"]})"' if e.get("dir") == "both" else "")
        o.append(f'<g class="edge" data-id="{esc(e["id"])}" data-s="{esc(e["s"])}" data-t="{esc(e["t"])}">'
                 f'<path d="{d}" fill="none" stroke="transparent" stroke-width="12"/>'
                 f'<path d="{d}" fill="none" stroke="{st["stroke"]}" stroke-width="{st["w"]}" stroke-dasharray="{st["dash"]}" {mk}/></g>')
    o.append("</g>")

    # boxes
    for n in model["nodes"]:
        cx, cy = pos[n["id"]]
        icon, kind_label, col = KINDS.get(n["kind"], KINDS["unknown"])
        x, y = cx - NODE_W / 2, cy - NODE_H / 2
        unk = n["kind"] == "unknown"
        role = n.get("role", "")
        unk_attr = ' stroke-dasharray="4 3"' if unk else ""
        name = n["label"] if len(n["label"]) <= NAME_CH else n["label"][:NAME_CH - 1] + "…"
        o.append(f'<g class="node" data-id="{esc(n["id"])}" tabindex="0" role="button" aria-label="{esc(n["label"])}"><title>{esc(n["label"])}{" — " + esc(role) if role else ""}</title>'
                 f'<rect x="{x:.1f}" y="{y:.1f}" width="{NODE_W}" height="{NODE_H}" rx="8" fill="#ffffff" stroke="{"#8c959f" if unk else "#d0d7de"}"'
                 f'{unk_attr} stroke-width="1.1"/>'
                 f'<rect x="{x:.1f}" y="{y:.1f}" width="5" height="{NODE_H}" rx="2" fill="{col}"/>'
                 f'<rect x="{x + 14:.1f}" y="{y + 14:.1f}" width="46" height="46" rx="9" fill="{col}" fill-opacity="0.12"/>'
                 f'<g transform="translate({x + 20:.1f},{y + 20:.1f}) scale(1.4)" fill="none" stroke="{col}" stroke-width="1.6" stroke-linecap="round" '
                 f'stroke-linejoin="round">{ICONS[icon]}</g>'
                 f'<text x="{x + 72:.1f}" y="{y + 23:.1f}" font-size="11" font-weight="700" fill="{col}" letter-spacing="0.6">{esc(kind_label.upper())}</text>'
                 f'<text x="{x + 72:.1f}" y="{y + 43:.1f}" font-size="16" font-weight="700" fill="#1f2328">{esc(name)}</text>'
                 f'<text x="{x + 72:.1f}" y="{y + 61:.1f}" font-size="12.5" fill="#57606a">{esc(role[:ROLE_CH] + ("…" if len(role) > ROLE_CH else ""))}</text></g>')

    # labels last, along each line where they cover no box, zone title or other label
    cards = [(x - NODE_W / 2 - 4, y - NODE_H / 2 - 4, x + NODE_W / 2 + 4, y + NODE_H / 2 + 4) for x, y in pos.values()]
    placed = [(fx(r[0]), fy(r[1]), fx(r[0]) + 18 + 12 * len(zones[z]["label"]), fy(r[1]) + 42) for z, r in T["zones"].items()]
    hit = lambda r, R: not (r[2] < R[0] or r[0] > R[2] or r[3] < R[1] or r[1] > R[3])
    o.append('<g class="labels">')
    for e in model["edges"]:
        st = STATUS[e["status"]]; pts = paths[e["id"]]
        lines = e["label"].split("\n"); lh = 14
        wmax = max(len(l) for l in lines) * 6.4 + 14; hh = lh * len(lines) + 7
        extra = 30 if e.get("step") else 0
        cands = []
        segs = sorted([(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if abs(pts[i][1] - pts[i + 1][1]) < 0.5],
                      key=lambda ab: -abs(ab[1][0] - ab[0][0]))
        for a, b in segs:
            for f in (0.5, 0.35, 0.65, 0.2, 0.8):
                cands.append((a[0] + (b[0] - a[0]) * f, a[1]))
        for dy in (0, -14, 14):
            for f in (0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.18, 0.82):
                x_, y_ = _along(pts, f); cands.append((x_, y_ + dy))
        best = None
        for lx, ly in cands:
            r = (lx - wmax / 2 - extra, ly - hh / 2, lx + wmax / 2, ly + hh / 2)
            if not any(hit(r, c) for c in cards) and not any(hit(r, c) for c in placed):
                best = (lx, ly, r); break
        if not best:
            lx, ly = _along(pts, 0.5); best = (lx, ly, (lx - wmax / 2 - extra, ly - hh / 2, lx + wmax / 2, ly + hh / 2))
        lx, ly, r = best; placed.append(r)
        o.append(f'<g class="edge elabel" data-id="{esc(e["id"])}">')
        if e.get("step"):
            o.append(f'<circle cx="{lx - wmax / 2 - 14:.1f}" cy="{ly:.1f}" r="12" fill="{st["stroke"]}"/>'
                     f'<text x="{lx - wmax / 2 - 14:.1f}" y="{ly + 5:.1f}" font-size="13" font-weight="700" text-anchor="middle" fill="#fff">{e["step"]}</text>')
        o.append(f'<rect x="{lx - wmax / 2:.1f}" y="{ly - hh / 2:.1f}" width="{wmax:.1f}" height="{hh:.1f}" rx="4" fill="#ffffff" '
                 f'stroke="{st["stroke"] if e["status"] in ("configured", "unknown") else "#d0d7de"}" stroke-width="0.8"/>')
        tc = "#9a6700" if e["status"] == "configured" else ("#cf222e" if e["status"] == "unknown" else "#24292f")
        for i, l in enumerate(lines):
            o.append(f'<text x="{lx:.1f}" y="{ly - hh / 2 + 3 + lh * (i + 1) - 3:.1f}" font-size="11.5" text-anchor="middle" fill="{tc}">{esc(l)}</text>')
        if e["status"] == "unknown":
            o.append(f'<circle cx="{lx + wmax / 2 + 12:.1f}" cy="{ly:.1f}" r="10" fill="#cf222e"/><text x="{lx + wmax / 2 + 12:.1f}" '
                     f'y="{ly + 5:.1f}" font-size="13" font-weight="700" text-anchor="middle" fill="#fff">?</text>')
        o.append("</g>")
    o.append("</g>")

    # legend
    ly = T["H"] + TOP + 26
    o.append(f'<g class="legend"><line x1="24" y1="{ly - 8}" x2="{W - 24}" y2="{ly - 8}" stroke="#d0d7de"/>'
             f'<text x="24" y="{ly + 12}" font-size="14" font-weight="700" fill="#24292f">LINES</text>')
    used_st = [k for k in STATUS if any(e["status"] == k for e in model["edges"])]
    for i, k in enumerate(used_st):
        st = STATUS[k]; yy = ly + 34 + i * 22
        o.append(f'<line x1="24" y1="{yy}" x2="64" y2="{yy}" stroke="{st["stroke"]}" stroke-width="{st["w"] + 0.4}" stroke-dasharray="{st["dash"]}" '
                 f'marker-end="url(#ah-{stem}-{k})"/><text x="76" y="{yy + 5}" font-size="13" fill="#24292f">{esc(st["label"])}</text>')
    kx = 420
    o.append(f'<text x="{kx}" y="{ly + 12}" font-size="14" font-weight="700" fill="#24292f">SYSTEM TYPES</text>')
    used = [k for k in KINDS if any(n["kind"] == k for n in model["nodes"])]
    for i, k in enumerate(used):
        icon, lab, col = KINDS[k]; c, r = divmod(i, 5)
        xx, yy = kx + c * 250, ly + 26 + r * 24
        o.append(f'<g transform="translate({xx},{yy}) scale(0.75)" fill="none" stroke="{col}" stroke-width="2" stroke-linecap="round" '
                 f'stroke-linejoin="round">{ICONS[icon]}</g><text x="{xx + 26}" y="{yy + 13}" font-size="13" fill="#24292f">{esc(lab)}</text>')
    nx, yy = kx + 250 * ((len(used) + 4) // 5) + 20, ly + 12
    for note in model.get("notes", []):
        lines = _wrap(note, 60)
        o.append(f'<text x="{nx}" y="{yy}" font-size="14" font-weight="700" fill="#24292f">NOTE</text>')
        for j, l in enumerate(lines):
            o.append(f'<text x="{nx}" y="{yy + 22 + j * 18}" font-size="13" fill="#57606a">{esc(l)}</text>')
        yy += 32 + 18 * len(lines)
    if model.get("steps"):
        sy = ly + 34 + 24 * max(5, len(used_st)) + 14
        o.append(f'<text x="24" y="{sy}" font-size="14" font-weight="700" fill="#24292f">STEPS</text>')
        for i, s in enumerate(model["steps"]):
            o.append(f'<text x="24" y="{sy + 22 + i * 24}" font-size="13" fill="#24292f"><tspan font-weight="700">{s["n"]}.</tspan> '
                     f'{esc(s["text"])} <tspan fill="#57606a">({esc(STATUS[s["status"]]["label"].lower())})</tspan></text>')
    o.append("</g></svg>")
    return "\n".join(o)
