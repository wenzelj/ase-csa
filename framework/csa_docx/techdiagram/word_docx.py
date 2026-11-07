"""A standalone Word document for one figure: A4 landscape, the figure as an editable Word drawing (with the
picture as fallback), a caption Word numbers itself, the source line and the technical notes.

    write_docx(out, model, title, caption, source, notes, aggregate=False, png=None, landscape=True) -> info

No third-party library: the package is written part by part, and checked by parsing every part (and by the
vendored DocxEngine validator when it is present).
"""
from __future__ import annotations

import html
import struct
import zipfile
from pathlib import Path

from .word_drawing import drawing_xml

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
esc = lambda s: html.escape(str(s), quote=False)

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                 '</Types>')
ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
             '</Relationships>')
STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{W_NS}">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/>'
          '<w:lang w:val="en-AU"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="80"/></w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr>'
          '<w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="1F2328"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Figure"><w:name w:val="Figure"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/>'
          '<w:spacing w:before="60" w:after="60"/></w:pPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/>'
          '<w:rPr><w:b/><w:color w:val="1F4F99"/><w:sz w:val="18"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="FigureSource"><w:name w:val="Figure Source"/><w:basedOn w:val="Normal"/>'
          '<w:rPr><w:i/><w:color w:val="57606A"/><w:sz w:val="16"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
          '<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>'
          '</w:styles>')


def _png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


def _p(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'


def write_docx(out: Path, model: dict, title: str, caption: str, source: str, notes: list[str] | None = None,
               aggregate: bool = False, png: Path | None = None, landscape: bool | None = None, svg: str | None = None) -> dict:
    """landscape None: chosen from the drawing's shape (A4 landscape for a wide figure, portrait for a tall one)."""
    out = Path(out)
    if landscape is None:
        from .print_layout import render_print_svg
        svg = svg or render_print_svg(model, aggregate=aggregate)[0]
        import re as _re
        vb = [float(v) for v in _re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
        landscape = vb[3] / vb[2] < 0.72
    page_w, page_h, margin = (16838, 11906, 1134) if landscape else (11906, 16838, 1134)
    text_w_mm = (page_w - 2 * margin) / 56.6929                 # twips -> mm
    png_bytes = Path(png).read_bytes() if png and Path(png).is_file() else None
    run, info = drawing_xml(model, aggregate=aggregate, width_mm=text_w_mm, png_rid="rIdImg1" if png_bytes else None,
                            doc_pr=1, name=title, svg=svg)
    max_h_mm = (page_h - 2 * margin) / 56.6929 - 30               # leave room for the caption and source
    if info["height_mm"] > max_h_mm:                              # taller than the page: scale the width down
        run, info = drawing_xml(model, aggregate=aggregate, width_mm=text_w_mm * max_h_mm / info["height_mm"],
                                png_rid="rIdImg1" if png_bytes else None, doc_pr=1, name=title, svg=svg)
    seq = ('<w:r><w:t xml:space="preserve">Figure </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText xml:space="preserve"> SEQ Figure \\* ARABIC </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:rPr><w:noProof/></w:rPr><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
           f'<w:r><w:t xml:space="preserve">: {esc(caption)}</w:t></w:r>')
    body = [_p(title, "Title"),
            f'<w:p><w:pPr><w:pStyle w:val="Figure"/></w:pPr><w:r>{run}</w:r></w:p>',
            f'<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>{seq}</w:p>',
            _p(source, "FigureSource")]
    if notes:
        body.append(_p("Technical notes", "Heading2"))
        body += [_p(n) for n in notes]
    body.append(_p("The drawing is made of Word shapes: select it and use Ungroup, or click into it, to move, recolour or "
                   "retype any part. Lines are not attached to the boxes, so move a line with the box it connects.", "FigureSource"))
    orient = ' w:orient="landscape"' if landscape else ""
    sect = (f'<w:sectPr><w:pgSz w:w="{page_w}" w:h="{page_h}"{orient}/><w:pgMar w:top="{margin}" w:right="{margin}" '
            f'w:bottom="{margin}" w:left="{margin}" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
           'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
           'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
           'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14">'
           f'<w:body>{"".join(body)}{sect}</w:body></w:document>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            + ('<Relationship Id="rIdImg1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/figure.png"/>'
               if png_bytes else "") + "</Relationships>")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + esc(title) + '</dc:title></cp:coreProperties>')
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("docProps/core.xml", core)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/_rels/document.xml.rels", rels)
        if png_bytes:
            z.writestr("word/media/figure.png", png_bytes)
    _check(out)
    return {**info, "path": str(out), "landscape": landscape}


def _check(path: Path) -> None:
    import xml.dom.minidom
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                xml.dom.minidom.parseString(z.read(n))
    try:
        import sys
        vendor = Path(__file__).resolve().parents[2] / "vendor"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from docxengine._opc import Package
        from docxengine._validate import validate_package
    except Exception:
        return
    errors = [i.message for i in validate_package(Package.open(str(path))) if i.severity == "error"]
    if errors:
        raise ValueError("the figure document did not validate: " + "; ".join(errors[:3]))
