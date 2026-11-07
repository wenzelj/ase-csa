"""SVG shapes to plain path segments, for drawing the icons as native Word (DrawingML) freeforms.

    parse(svg_fragment) -> [Shape]   Shape = {"subpaths": [[("M", x, y), ("L", x, y), ("C", x1, y1, x2, y2, x, y), ("Z",)]],
                                              "dash": "3 2.5" | None}

Handles what the icon set uses: <path d> with M L H V C S Q T A Z in absolute and relative form, <rect> (with rx),
<circle>, <ellipse>, <line>, <polyline>, <polygon>. Arcs and quadratic curves become cubic Béziers, so the
output only has M, L, C and Z, which DrawingML draws directly (moveTo, lnTo, cubicBezTo, close).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

K = 0.5522847498                      # circle-to-Bézier constant
_TOK = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _f(el, k, d=0.0):
    try:
        return float(el.get(k, d))
    except (TypeError, ValueError):
        return d


def _ellipse(cx, cy, rx, ry):
    return [("M", cx + rx, cy),
            ("C", cx + rx, cy + K * ry, cx + K * rx, cy + ry, cx, cy + ry),
            ("C", cx - K * rx, cy + ry, cx - rx, cy + K * ry, cx - rx, cy),
            ("C", cx - rx, cy - K * ry, cx - K * rx, cy - ry, cx, cy - ry),
            ("C", cx + K * rx, cy - ry, cx + rx, cy - K * ry, cx + rx, cy), ("Z",)]


def _rect(x, y, w, h, rx, ry):
    rx, ry = min(rx, w / 2), min(ry, h / 2)
    if rx <= 0 or ry <= 0:
        return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
    k = 1 - K
    return [("M", x + rx, y), ("L", x + w - rx, y), ("C", x + w - k * rx, y, x + w, y + k * ry, x + w, y + ry),
            ("L", x + w, y + h - ry), ("C", x + w, y + h - k * ry, x + w - k * rx, y + h, x + w - rx, y + h),
            ("L", x + rx, y + h), ("C", x + k * rx, y + h, x, y + h - k * ry, x, y + h - ry),
            ("L", x, y + ry), ("C", x, y + k * ry, x + k * rx, y, x + rx, y), ("Z",)]


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """SVG endpoint arc -> cubic Bézier segments (W3C SVG implementation notes, F.6.5)."""
    if (x1, y1) == (x2, y2):
        return []
    if rx == 0 or ry == 0:
        return [("L", x2, y2)]
    rx, ry = abs(rx), abs(ry)
    p = math.radians(phi)
    cp, sp = math.cos(p), math.sin(p)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(1, int(math.ceil(abs(dt) / (math.pi / 2))))
    d = dt / n
    out = []
    e = 4 / 3 * math.tan(d / 4)
    pt = lambda t: (cx + rx * math.cos(t) * cp - ry * math.sin(t) * sp, cy + rx * math.cos(t) * sp + ry * math.sin(t) * cp)
    dv = lambda t: (-rx * math.sin(t) * cp - ry * math.cos(t) * sp, -rx * math.sin(t) * sp + ry * math.cos(t) * cp)
    t = t1
    for _ in range(n):
        a, b = pt(t), pt(t + d)
        da, db = dv(t), dv(t + d)
        out.append(("C", a[0] + e * da[0], a[1] + e * da[1], b[0] - e * db[0], b[1] - e * db[1], b[0], b[1]))
        t += d
    return out


def path_d(d: str) -> list[list[tuple]]:
    toks = _TOK.findall(d or "")
    subs, cur = [], []
    x = y = sx = sy = 0.0
    lastc = None                       # last cubic control point (for S)
    lastq = None                       # last quadratic control point (for T)
    cmd = None
    i = 0
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                cur.append(("Z",)); x, y = sx, sy
                subs.append(cur); cur = []
                lastc = lastq = None
                continue
        if cmd is None:
            break
        rel = cmd.islower(); c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            nx, ny = num() + ox, num() + oy
            if cur:
                subs.append(cur)
            cur = [("M", nx, ny)]; x, y = sx, sy = nx, ny
            cmd = "l" if rel else "L"
            lastc = lastq = None
        elif c == "L":
            x, y = num() + ox, num() + oy; cur.append(("L", x, y)); lastc = lastq = None
        elif c == "H":
            x = num() + (x if rel else 0); cur.append(("L", x, y)); lastc = lastq = None
        elif c == "V":
            y = num() + (y if rel else 0); cur.append(("L", x, y)); lastc = lastq = None
        elif c == "C":
            x1, y1, x2, y2, nx, ny = num() + ox, num() + oy, num() + ox, num() + oy, num() + ox, num() + oy
            cur.append(("C", x1, y1, x2, y2, nx, ny)); lastc = (x2, y2); lastq = None; x, y = nx, ny
        elif c == "S":
            x1, y1 = (2 * x - lastc[0], 2 * y - lastc[1]) if lastc else (x, y)
            x2, y2, nx, ny = num() + ox, num() + oy, num() + ox, num() + oy
            cur.append(("C", x1, y1, x2, y2, nx, ny)); lastc = (x2, y2); lastq = None; x, y = nx, ny
        elif c in "QT":
            if c == "Q":
                qx, qy = num() + ox, num() + oy
            else:
                qx, qy = (2 * x - lastq[0], 2 * y - lastq[1]) if lastq else (x, y)
            nx, ny = num() + ox, num() + oy
            cur.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny), nx, ny))
            lastq = (qx, qy); lastc = None; x, y = nx, ny
        elif c == "A":
            rx, ry, phi = num(), num(), num()
            large, sweep = int(num()), int(num())
            nx, ny = num() + ox, num() + oy
            cur += _arc(x, y, rx, ry, phi, large, sweep, nx, ny); x, y = nx, ny; lastc = lastq = None
        else:
            i += 1
    if cur:
        subs.append(cur)
    return [s for s in subs if len(s) > 1 or (s and s[0][0] != "M")]


def parse(fragment: str) -> list[dict]:
    """Every shape in an SVG fragment (the icon markup), in drawing order."""
    root = ET.fromstring(f'<g xmlns="http://www.w3.org/2000/svg">{fragment}</g>')
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        dash = el.get("stroke-dasharray")
        if tag == "path":
            subs = path_d(el.get("d", ""))
        elif tag == "rect":
            rx = _f(el, "rx", _f(el, "ry")); ry = _f(el, "ry", rx)
            subs = [_rect(_f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height"), rx, ry)]
        elif tag == "circle":
            r = _f(el, "r"); subs = [_ellipse(_f(el, "cx"), _f(el, "cy"), r, r)]
        elif tag == "ellipse":
            subs = [_ellipse(_f(el, "cx"), _f(el, "cy"), _f(el, "rx"), _f(el, "ry"))]
        elif tag == "line":
            subs = [[("M", _f(el, "x1"), _f(el, "y1")), ("L", _f(el, "x2"), _f(el, "y2"))]]
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)", el.get("points", ""))]
            pts = list(zip(nums[::2], nums[1::2]))
            if not pts:
                continue
            sub = [("M", *pts[0])] + [("L", *p) for p in pts[1:]]
            subs = [sub + ([("Z",)] if tag == "polygon" else [])]
        else:
            continue
        if subs:
            out.append({"subpaths": subs, "dash": dash, "fill": el.get("fill"), "stroke": el.get("stroke"),
                        "sw": el.get("stroke-width")})
    return out
