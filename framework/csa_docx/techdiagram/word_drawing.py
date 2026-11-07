"""The figure as a native Word drawing: every zone, card, icon, line and label is its own shape, editable in Word.

    drawing_xml(model, aggregate=False, width_mm=170.0, png_rid=None, doc_pr=1) -> (run_xml, info)

The drawing is built from the print layout (print_layout.render_print_svg), so it looks the same as the picture
version and passes the same 8 pt check. It becomes one Word group (wpg) so the figure moves as one object:

  zones and groups      rounded rectangles with their title as a text box
  each card             a nested group: card outline, colour bar, icon, name and role text boxes
  icons                 vector freeforms (custGeom) drawn from the icon library's paths, not pictures
  lines                 freeform polylines with Word arrowheads and dash styles
  labels, legend        text boxes and short sample lines

Word does not keep a freeform line attached to a shape, so moving a card leaves its lines where they are; move
the lines too, or the whole group. When png_rid is given, the picture is kept as the fallback (mc:Fallback) for
readers that cannot draw Word 2010 groups, as Word itself does.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from . import svgpath
from .print_layout import render_print_svg

EMU_PER_MM = 36000
SVG = "{http://www.w3.org/2000/svg}"
NS = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')
FONT = "Arial"
esc = lambda s: html.escape(str(s), quote=True)


class _Ids:
    def __init__(self, start: int):
        self.n = start

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _num(v, d=0.0) -> float:
    try:
        return float(str(v).replace("mm", "").replace("px", ""))
    except (TypeError, ValueError):
        return d


def _color(c: str | None) -> str | None:
    if not c or c in ("none", "transparent"):
        return None
    c = c.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", c):
        return c[1:].upper()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", c):
        return "".join(ch * 2 for ch in c[1:]).upper()
    return {"white": "FFFFFF", "black": "000000"}.get(c, "3D444D")


def _transform(t: str | None) -> tuple[float, float, float]:
    tx = ty = 0.0
    s = 1.0
    if t:
        m = re.search(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)", t)
        if m:
            tx, ty = float(m.group(1)), float(m.group(2))
        m = re.search(r"scale\(\s*([-\d.]+)", t)
        if m:
            s = float(m.group(1))
    return tx, ty, s


class Builder:
    def __init__(self, k: float, ids: _Ids):
        self.k = k                    # EMU per drawing unit
        self.ids = ids

    def e(self, v: float) -> int:
        return int(round(v * self.k))

    # ------------------------------------------------------------------ pieces
    def _fill(self, color, opacity=None) -> str:
        c = _color(color)
        if not c:
            return "<a:noFill/>"
        alpha = f'<a:alpha val="{int(max(0, min(1, opacity)) * 100000)}"/>' if opacity is not None and opacity < 1 else ""
        return f'<a:solidFill><a:srgbClr val="{c}">{alpha}</a:srgbClr></a:solidFill>'

    def _ln(self, color, width, dash=None, head=False, tail=False, cap="flat") -> str:
        c = _color(color)
        if not c:
            return "<a:ln><a:noFill/></a:ln>"
        w = max(3175, self.e(width))
        dash_xml = ""
        if dash:
            parts = [_num(x) for x in re.split(r"[ ,]+", dash.strip()) if x]
            if len(parts) % 2:
                parts = parts * 2
            ds = "".join(f'<a:ds d="{int(parts[i] / max(width, 0.1) * 100000)}" sp="{int(parts[i + 1] / max(width, 0.1) * 100000)}"/>'
                         for i in range(0, len(parts), 2))
            dash_xml = f"<a:custDash>{ds}</a:custDash>"
        he = '<a:headEnd type="triangle" w="med" len="med"/>' if head else ""
        te = '<a:tailEnd type="triangle" w="med" len="med"/>' if tail else ""
        return (f'<a:ln w="{w}" cap="{cap}"><a:solidFill><a:srgbClr val="{c}"/></a:solidFill>{dash_xml}'
                f'<a:round/>{he}{te}</a:ln>')

    def _xfrm(self, x, y, w, h) -> str:
        return f'<a:xfrm><a:off x="{self.e(x)}" y="{self.e(y)}"/><a:ext cx="{max(1, self.e(w))}" cy="{max(1, self.e(h))}"/></a:xfrm>'

    def _wsp(self, name, sppr, body='<wps:bodyPr/>', txbx="", txbox=False) -> str:
        i = self.ids()
        nv = '<wps:cNvSpPr txBox="1"/>' if txbox else "<wps:cNvSpPr/>"
        return (f'<wps:wsp><wps:cNvPr id="{i}" name="{esc(name)} {i}"/>{nv}<wps:spPr>{sppr}</wps:spPr>'
                f"{txbx}{body}</wps:wsp>")

    def rect(self, x, y, w, h, rx=0, fill=None, stroke=None, sw=1.0, dash=None, opacity=None, name="Box") -> str:
        if rx > 0:
            adj = int(min(50000, rx / max(1e-6, min(w, h)) * 100000))
            geom = f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
        else:
            geom = '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        return self._wsp(name, self._xfrm(x, y, w, h) + geom + self._fill(fill, opacity) + self._ln(stroke, sw, dash))

    def ellipse(self, cx, cy, r, fill=None, stroke=None, sw=1.0, name="Dot") -> str:
        return self._wsp(name, self._xfrm(cx - r, cy - r, 2 * r, 2 * r) + '<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom>'
                         + self._fill(fill) + self._ln(stroke, sw))

    def freeform(self, shapes, tx, ty, s, stroke, sw, fill=None, head=False, tail=False, cap="rnd", name="Line",
                 dash=None) -> str:
        """shapes: svgpath shapes in local units; drawn at (tx, ty) scaled by s. One shape, several paths."""
        pts = [(tx + p[j] * s, ty + p[j + 1] * s) for sh in shapes for sub in sh["subpaths"] for p in sub
               for j in range(1, len(p) - 1, 2)]
        if not pts:
            return ""
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
        W, H = max(1, self.e(x1 - x0)), max(1, self.e(y1 - y0))
        loc = lambda x, y: (self.e(tx + x * s - x0), self.e(ty + y * s - y0))
        paths = []
        for sh in shapes:
            for sub in sh["subpaths"]:
                cmds = []
                for seg in sub:
                    if seg[0] == "M":
                        a, b = loc(seg[1], seg[2]); cmds.append(f'<a:moveTo><a:pt x="{a}" y="{b}"/></a:moveTo>')
                    elif seg[0] == "L":
                        a, b = loc(seg[1], seg[2]); cmds.append(f'<a:lnTo><a:pt x="{a}" y="{b}"/></a:lnTo>')
                    elif seg[0] == "C":
                        p1, p2, p3 = loc(seg[1], seg[2]), loc(seg[3], seg[4]), loc(seg[5], seg[6])
                        cmds.append(f'<a:cubicBezTo><a:pt x="{p1[0]}" y="{p1[1]}"/><a:pt x="{p2[0]}" y="{p2[1]}"/>'
                                    f'<a:pt x="{p3[0]}" y="{p3[1]}"/></a:cubicBezTo>')
                    elif seg[0] == "Z":
                        cmds.append("<a:close/>")
                fill_attr = "" if fill else ' fill="none"'
                paths.append(f'<a:path w="{W}" h="{H}"{fill_attr}>{"".join(cmds)}</a:path>')
        geom = ('<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
                f'<a:pathLst>{"".join(paths)}</a:pathLst></a:custGeom>')
        sppr = (f'<a:xfrm><a:off x="{self.e(x0)}" y="{self.e(y0)}"/><a:ext cx="{W}" cy="{H}"/></a:xfrm>' + geom +
                self._fill(fill) + self._ln(stroke, sw * s, dash, head, tail, cap))
        return self._wsp(name, sppr)

    def text(self, x, y, txt, size, color="#24292F", bold=False, anchor="start", name="Text") -> str:
        """A text box whose baseline sits at y (SVG text coordinates)."""
        w = max(8.0, len(txt) * size * (0.84 if bold else 0.74) + 12)    # generous: Word fonts run wider than the SVG estimate
        h = size * 1.3
        lim = getattr(self, "max_w", None)               # keep every box inside the drawing: Word and LibreOffice
        if lim:                                          # shrink a group whose shapes overrun its frame
            if anchor == "middle":
                w = min(w, 2 * min(x, lim - x))
            elif anchor == "start":
                w = min(w, lim - x)
            else:
                w = min(w, x)
            w = max(w, 8.0)
        left = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
        top = y - size * 1.0
        pt = size * self.k / 12700                       # EMU -> points
        hp = max(2, int(round(pt * 2)))                   # half-points
        jc = {"start": "left", "middle": "center", "end": "right"}[anchor]
        line = int(round(pt * 1.2 * 20))
        rpr = (f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>' + ("<w:b/>" if bold else "") +
               f'<w:color w:val="{_color(color) or "24292F"}"/><w:sz w:val="{hp}"/><w:szCs w:val="{hp}"/>')
        txbx = (f'<wps:txbx><w:txbxContent><w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="exact"/>'
                f'<w:jc w:val="{jc}"/><w:rPr>{rpr}</w:rPr></w:pPr><w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{esc(txt)}</w:t></w:r>'
                f'</w:p></w:txbxContent></wps:txbx>')
        body = ('<wps:bodyPr rot="0" vert="horz" wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0" '
                'upright="1"><a:noAutofit/></wps:bodyPr>')
        sppr = self._xfrm(left, top, w, h) + '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln>'
        return self._wsp(name, sppr, body=body, txbx=txbx, txbox=True)

    def group(self, children: list[str], bbox, name="Group") -> str:
        x0, y0, x1, y1 = bbox
        i = self.ids()
        xf = (f'<a:xfrm><a:off x="{self.e(x0)}" y="{self.e(y0)}"/><a:ext cx="{max(1, self.e(x1 - x0))}" cy="{max(1, self.e(y1 - y0))}"/>'
              f'<a:chOff x="{self.e(x0)}" y="{self.e(y0)}"/><a:chExt cx="{max(1, self.e(x1 - x0))}" cy="{max(1, self.e(y1 - y0))}"/></a:xfrm>')
        return (f'<wpg:grpSp><wpg:cNvPr id="{i}" name="{esc(name)} {i}"/><wpg:cNvGrpSpPr/><wpg:grpSpPr>{xf}</wpg:grpSpPr>'
                + "".join(c for c in children if c) + "</wpg:grpSp>")


# ------------------------------------------------------------------ SVG -> shapes
def _bbox(el, tx=0.0, ty=0.0) -> tuple[float, float, float, float] | None:
    xs, ys = [], []
    for c in el.iter():
        tag = c.tag.replace(SVG, "")
        if tag == "rect":
            x, y, w, h = _num(c.get("x")), _num(c.get("y")), _num(c.get("width")), _num(c.get("height"))
            xs += [x, x + w]; ys += [y, y + h]
        elif tag == "text":
            x, y, s = _num(c.get("x")), _num(c.get("y")), _num(c.get("font-size"), 12)
            xs += [x, x + len(c.text or "") * s * 0.6]; ys += [y - s, y + s * 0.3]
    if not xs:
        return None
    return min(xs) + tx, min(ys) + ty, max(xs) + tx, max(ys) + ty


def _shape(b: Builder, el, ox=0.0, oy=0.0) -> str:
    tag = el.tag.replace(SVG, "")
    g = el.get
    if tag == "rect":
        if g("width") == "100%":
            return ""
        return b.rect(_num(g("x")) + ox, _num(g("y")) + oy, _num(g("width")), _num(g("height")), _num(g("rx")),
                      g("fill"), g("stroke"), _num(g("stroke-width"), 1.0), g("stroke-dasharray"),
                      _num(g("fill-opacity"), 1.0) if g("fill-opacity") else None, name="Box")
    if tag == "text":
        weight = (g("font-weight") or "")
        return b.text(_num(g("x")) + ox, _num(g("y")) + oy, el.text or "", _num(g("font-size"), 12), g("fill") or "#24292F",
                      weight in ("600", "700", "bold"), g("text-anchor") or "start", name="Label")
    if tag == "circle":
        return b.ellipse(_num(g("cx")) + ox, _num(g("cy")) + oy, _num(g("r")), g("fill"), g("stroke"), _num(g("stroke-width"), 1))
    if tag == "line":
        sh = [{"subpaths": [[("M", _num(g("x1")), _num(g("y1"))), ("L", _num(g("x2")), _num(g("y2")))]]}]
        return b.freeform(sh, ox, oy, 1.0, g("stroke"), _num(g("stroke-width"), 1), dash=g("stroke-dasharray"), cap="flat",
                          name="Legend line")
    if tag == "path":
        sh = [{"subpaths": svgpath.path_d(g("d") or "")}]
        return b.freeform(sh, ox, oy, 1.0, g("stroke"), _num(g("stroke-width"), 1), dash=g("stroke-dasharray"),
                          head=bool(g("marker-start")), tail=bool(g("marker-end")), cap="flat",
                          name="Line " + (g("data-id") or ""))
    if tag == "g" and g("transform") and "scale" in g("transform"):     # an icon
        tx, ty, s = _transform(g("transform"))
        frag = "".join("<" + c.tag.replace(SVG, "") + "".join(f' {k}="{esc(v)}"' for k, v in c.attrib.items()) + "/>"
                       for c in el)
        shapes = svgpath.parse(frag)
        base_stroke, base_fill = g("stroke"), g("fill")
        base_sw = _num(g("stroke-width"), 1.6)
        def style(s_):
            pick = lambda v, d: d if v in (None, "currentColor") else v
            fill = pick(s_.get("fill"), base_fill)
            fill = base_stroke if s_.get("fill") == "currentColor" else fill
            return (fill if fill not in ("none",) else None, pick(s_.get("stroke"), base_stroke),
                    _num(s_.get("sw"), base_sw) if s_.get("sw") else base_sw, s_.get("dash"))
        runs: list[tuple[tuple, list]] = []            # consecutive shapes with one style: drawing order is kept
        for s_ in shapes:
            st = style(s_)
            if runs and runs[-1][0] == st:
                runs[-1][1].append(s_)
            else:
                runs.append((st, [s_]))
        out = ""
        for (fill, stroke, sw, dash), group in runs:
            out += b.freeform(group, tx + ox, ty + oy, s, stroke, sw, fill=fill, name="Icon", dash=dash)
        return out
    if tag == "g":
        return "".join(_shape(b, c, ox, oy) for c in el)
    return ""


def build_group(svg: str, width_mm: float, ids: _Ids) -> tuple[str, int, int]:
    root = ET.fromstring(svg)
    vb = [float(v) for v in root.get("viewBox").split()]
    W, H = vb[2], vb[3]
    k = width_mm * EMU_PER_MM / W
    b = Builder(k, ids)
    b.max_w = W
    parts = []
    for el in root:
        tag = el.tag.replace(SVG, "")
        cls = el.get("class") or ""
        if tag in ("defs",):
            continue
        if tag == "g" and cls in ("node", "zone", "group"):
            kids = [_shape(b, c) for c in el]
            bb = _bbox(el)
            name = {"node": "Card", "zone": "Zone", "group": "Group"}[cls] + " " + (el.get("data-id") or "")
            parts.append(b.group(kids, bb, name) if bb and cls == "node" else "".join(kids))
        else:
            parts.append(_shape(b, el))
    cx, cy = int(round(W * k)), int(round(H * k))
    i = ids()
    wgp = (f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
           f'<a:chOff x="0" y="0"/><a:chExt cx="{cx}" cy="{cy}"/></a:xfrm></wpg:grpSpPr>{"".join(p for p in parts if p)}</wpg:wgp>')
    return wgp, cx, cy


def drawing_xml(model: dict, aggregate: bool = False, width_mm: float = 170.0, png_rid: str | None = None,
                doc_pr: int = 1, name: str = "CSA figure", svg: str | None = None) -> tuple[str, dict]:
    """The run content (no <w:r>) that draws the figure as an editable Word group."""
    if svg is None:
        svg, info = render_print_svg(model, aggregate=aggregate)
    else:
        info = {}
    ids = _Ids(doc_pr * 1000)
    wgp, cx, cy = build_group(svg, width_mm, ids)
    inline = (f'<wp:inline {NS} distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
              f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{doc_pr}" name="{esc(name)}"/><wp:cNvGraphicFramePr/>'
              f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">{wgp}'
              f'</a:graphicData></a:graphic></wp:inline>')
    choice = f"<w:drawing>{inline}</w:drawing>"
    info = {**info, "width_mm": width_mm, "height_mm": round(cy / EMU_PER_MM, 1), "shapes": choice.count("<wps:wsp>"),
            "cards": choice.count("<wpg:grpSp>")}
    if not png_rid:
        return choice, info
    fallback = (f'<w:drawing><wp:inline {NS} distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{doc_pr + 1}" name="{esc(name)} (picture)"/>'
                '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr>'
                f'<pic:cNvPr id="0" name="figure.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
                f'<a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{png_rid}"/>'
                f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
                '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
                "</wp:inline></w:drawing>")
    alt = ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
           'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
           f'<mc:Choice Requires="wpg">{choice}</mc:Choice><mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent>')
    return alt, info
