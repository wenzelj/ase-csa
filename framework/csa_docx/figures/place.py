"""Put a saved figure into the working document as a tracked change. Your one approval stays in Word.

    place(docx, section, figure_png, caption, source, key, author) -> {"status", "mode", "backup", ...}

Where it goes, decided from the document itself:
  slot     the section has the template's empty figure slot (Figure / Caption / FigureSource paragraphs with
           placeholder text, as in 2.1): the placeholder text is deleted and the figure, caption and source
           are inserted in those same paragraphs, all tracked.
  insert   a requirement domain (3.x) has no slot: a Figure block (the document's own Figure, Caption and
           FigureSource styles) is inserted, tracked, right after the section's Discovery Information table.
  replace  the section already holds a figure this step placed (bookmark _CSAFig_<KEY>): the old block is
           deleted and the new one inserted, as one set of tracked changes.
A section whose figure slot holds an image this step did not place is left alone (BLOCKED).

The caption number is a SEQ Figure field, so Word numbers it. The document is backed up first and closed in
Word if it is open. Only document.xml, its relationships, the content types and one new image change.
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from csa_docx.docx_package import create_backup

TAG = re.compile(rb"<(/?)(w:[A-Za-z]+)\b[^>]*?(/?)>")
CONTAINERS = {b"w:p", b"w:tbl", b"w:sdt"}
NS = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


class Blocked(Exception):
    pass


# ------------------------------------------------------------------ reading the body
def _body_children(xml: bytes) -> list[tuple[int, int, bytes]]:
    """Top-level children of <w:body>: (start, end, tag)."""
    b = xml.index(b"<w:body>") + len(b"<w:body>")
    end_body = xml.rindex(b"</w:body>")
    out, depth, start, tag = [], 0, None, None
    for m in TAG.finditer(xml, b, end_body):
        closing, name, selfclose = m.group(1), m.group(2), m.group(3)
        if name not in CONTAINERS:
            if depth == 0 and not closing:
                out.append((m.start(), m.end(), name)) if selfclose else None
            continue
        if not closing and not selfclose:
            if depth == 0:
                start, tag = m.start(), name
            depth += 1
        elif closing:
            depth -= 1
            if depth == 0:
                out.append((start, m.end(), tag))
    return out


def _text(chunk: bytes) -> str:
    import html as _html
    return _html.unescape("".join(t.decode("utf-8") for t in re.findall(rb"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", chunk))).strip()


def _style(chunk: bytes) -> str:
    m = re.search(rb'<w:pStyle w:val="([^"]+)"', chunk[:600])
    return m.group(1).decode() if m else ""


def _heading_level(style: str) -> int | None:
    m = re.fullmatch(r"Heading(\d)", style)
    return int(m.group(1)) if m else None


def locate(xml: bytes, title: str, level: int, key: str, after_key: str | None = None) -> dict:
    kids = _body_children(xml)
    heads = [i for i, (s, e, t) in enumerate(kids) if t == b"w:p" and _heading_level(_style(xml[s:e])) and _text(xml[s:e]) == title]
    if len(heads) != 1:
        raise Blocked(f"found {len(heads)} headings titled '{title}' in the document; expected one")
    h = heads[0]
    hl = _heading_level(_style(xml[kids[h][0]:kids[h][1]]))
    end = next((i for i in range(h + 1, len(kids)) if kids[i][2] == b"w:p"
                and (_heading_level(_style(xml[kids[i][0]:kids[i][1]])) or 99) <= hl), len(kids))
    span = range(h + 1, end)
    # our own block from an earlier placement
    ours = [i for i in span if f'w:name="_CSAFig_{key}"'.encode() in xml[kids[i][0]:kids[i][1]]]
    figs = [i for i in span if kids[i][2] == b"w:p" and _style(xml[kids[i][0]:kids[i][1]]) == "Figure"]
    if ours:
        i = ours[0]
        block = [i] + [j for j in (i + 1, i + 2) if j < end and _style(xml[kids[j][0]:kids[j][1]]) in ("Caption", "FigureSource")]
        return {"mode": "replace", "kids": kids, "block": block}
    if after_key:                                    # a second figure: straight after the section's first one
        first = [i for i in span if f'w:name="_CSAFig_{after_key}"'.encode() in xml[kids[i][0]:kids[i][1]]]
        if not first:
            raise Blocked(f"place the section's first figure ({after_key}) before this one")
        i = first[-1]                            # the live one: a replaced figure stays before it as a tracked deletion
        block = [i] + [j for j in (i + 1, i + 2) if j < end and _style(xml[kids[j][0]:kids[j][1]]) in ("Caption", "FigureSource")]
        return {"mode": "insert", "kids": kids, "after": block[-1], "after_figure": True}
    for i in figs:
        chunk = xml[kids[i][0]:kids[i][1]]
        if b"<w:drawing" in chunk:
            raise Blocked("the section's figure slot already holds an image that this step did not place")
        block = [i] + [j for j in (i + 1, i + 2) if j < end and _style(xml[kids[j][0]:kids[j][1]]) in ("Caption", "FigureSource")]
        return {"mode": "slot", "kids": kids, "block": block}
    di = next((i for i in span if kids[i][2] == b"w:p" and _text(xml[kids[i][0]:kids[i][1]]).lower() == "discovery information"), None)
    tbl = next((i for i in range(di + 1, end) if kids[i][2] == b"w:tbl"), None) if di is not None else None
    if di is not None:                           # after the framework's topic tables and their notes, never among them
        last, j = None, di + 1
        while j < end:
            c = xml[kids[j][0]:kids[j][1]]
            if kids[j][2] == b"w:tbl" and b'w:tblCaption w:val="csa-topic-table"' in c:
                last = j
            elif kids[j][2] == b"w:p" and _style(c) in ("TableNote", "Figure", "Caption", "FigureSource"):
                last = j
            else:
                break
            j += 1
        if last is not None:
            tbl = last
    if tbl is None:
        raise Blocked("the section has no figure slot and no Discovery Information table to put the figure after")
    return {"mode": "insert", "kids": kids, "after": tbl}


# ------------------------------------------------------------------ building the block
class _Ids:
    def __init__(self, xml: bytes):
        nums = [int(x) for x in re.findall(rb'\bw:id="(\d+)"', xml)] or [0]
        self.rev = max(nums) + 1
        self.doc_pr = max([int(x) for x in re.findall(rb'<wp:docPr id="(\d+)"', xml)] or [0]) + 1

    def next(self) -> int:
        self.rev += 1
        return self.rev


def _png_size(png: bytes) -> tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise Blocked("the figure image is not a PNG")
    return struct.unpack(">II", png[16:24])


def _text_width_emu(xml: bytes) -> int:
    sect = re.findall(rb"<w:sectPr[\s>].*?</w:sectPr>", xml, re.S)
    s = sect[-1] if sect else b""
    w = re.search(rb'<w:pgSz [^>]*w:w="(\d+)"', s)
    l = re.search(rb'<w:pgMar [^>]*w:left="(\d+)"', s)
    r = re.search(rb'<w:pgMar [^>]*w:right="(\d+)"', s)
    twips = (int(w.group(1)) - int(l.group(1)) - int(r.group(1))) if (w and l and r) else 9638
    return twips * 635


def _drawing(rid: str, cx: int, cy: int, doc_pr: int, key: str) -> str:
    return (f'<w:drawing><wp:inline {NS} distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{doc_pr}" name="CSA figure {escape(key)}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            f'<pic:nvPicPr><pic:cNvPr id="0" name="figure-{escape(key.lower())}.png"/><pic:cNvPicPr><a:picLocks noChangeAspect="1"/></pic:cNvPicPr></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')


def _rev(kind: str, ids: _Ids, author: str, date: str) -> str:
    return f'w:id="{ids.next()}" w:author="{escape(author)}" w:date="{date}"'


def _t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


def _seq_runs(n: int) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> SEQ Figure \\* ARABIC </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:noProof/></w:rPr><w:t>{n}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _new_block(drawing: str, caption: str, source: str, n: int, ids: _Ids, author: str, date: str, key: str) -> str:
    bm = ids.next()
    mark = lambda: f'<w:rPr><w:ins {_rev("ins", ids, author, date)}/></w:rPr>'
    return (f'<w:p><w:pPr><w:pStyle w:val="Figure"/>{mark()}</w:pPr><w:bookmarkStart w:id="{bm}" w:name="_CSAFig_{escape(key)}"/>'
            f'<w:ins {_rev("ins", ids, author, date)}><w:r>{drawing}</w:r></w:ins><w:bookmarkEnd w:id="{bm}"/></w:p>'
            f'<w:p><w:pPr><w:pStyle w:val="Caption"/>{mark()}</w:pPr><w:ins {_rev("ins", ids, author, date)}>'
            f'<w:r>{_t("Figure ")}</w:r>{_seq_runs(n)}<w:r>{_t(": " + caption)}</w:r></w:ins></w:p>'
            + (f'<w:p><w:pPr><w:pStyle w:val="FigureSource"/>{mark()}</w:pPr><w:ins {_rev("ins", ids, author, date)}>'
               f'<w:r>{_t(source)}</w:r></w:ins></w:p>' if source else ""))


def _iter_runs(chunk: str):
    """Yield (start, end) for every top-level <w:r>...</w:r> in *chunk*, honouring nesting.

    A run may itself contain a Word shape/text box whose <w:txbxContent> holds its own
    nested <w:p>/<w:r> pairs; a non-greedy regex stops at the first inner </w:r> and
    orphans the outer run's real closer, producing a mismatched-tag error when the
    fragment is wrapped in <w:del>.  A depth-counting scan bounds each run correctly:
    depth starts at 1 on the opening tag and returns to 0 at the matching close.

    A '<w:r' match must be a real run tag, not <w:rPr> or another longer name."""
    def _find_run(s: str, i: int) -> int:
        while True:
            j = s.find("<w:r", i)
            if j < 0:
                return -1
            nxt = j + 4
            if nxt >= len(s) or not s[nxt].isalnum():
                return j
            i = j + 1

    i, n = 0, len(chunk)
    while True:
        j = _find_run(chunk, i)
        if j < 0:
            return
        end = chunk.find(">", j)
        if end < 0:
            return
        if chunk[end - 1] == "/":
            i = end + 1
            continue
        i = end + 1
        depth = 1
        while depth:
            o = _find_run(chunk, i)
            c = chunk.find("</w:r>", i)
            if o >= 0 and (c < 0 or o < c):
                # next real open before any close: nested run
                close = chunk.find(">", o)
                if close < 0:
                    return
                if chunk[close - 1] != "/":
                    depth += 1
                i = close + 1
            elif c >= 0:
                # close tag: decrement depth
                depth -= 1
                i = c + 6
            else:
                return
        yield (j, i)

def _delete_runs(chunk: str, ids: _Ids, author: str, date: str, only_placeholder: bool) -> tuple[str, int]:
    """Wrap runs in <w:del> (their w:t becoming w:delText). only_placeholder: just runs whose text has '['.
    Returns the new paragraph and the position just after the last deleted run (or -1)."""
    out, last, pos = [], -1, 0
    fields = [(f.start(), f.end()) for f in re.finditer(r"<w:fldSimple\b.*?</w:fldSimple>", chunk, re.S)]
    for m_start, m_end in _iter_runs(chunk):
        run = chunk[m_start:m_end]
        if only_placeholder and any(a <= m_start < b for a, b in fields):
            continue                                          # a run inside the template's own SEQ field: keep it
        text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", run))
        if only_placeholder and "[" not in text:
            continue
        gone = run.replace("<w:t>", '<w:delText xml:space="preserve">').replace('<w:t xml:space="preserve">', '<w:delText xml:space="preserve">') \
                  .replace("</w:t>", "</w:delText>").replace("<w:instrText", "<w:delInstrText").replace("</w:instrText>", "</w:delInstrText>")
        out.append(chunk[pos:m_start] + f'<w:del {_rev("del", ids, author, date)}>{gone}</w:del>')
        pos = m_end
        last = len("".join(out))
    out.append(chunk[pos:])
    return "".join(out), last


def _delete_paragraph(chunk: str, ids: _Ids, author: str, date: str) -> str:
    """The whole paragraph deleted, tracked: every run and the paragraph mark."""
    new, _ = _delete_runs(chunk, ids, author, date, only_placeholder=False)
    mark = f'<w:del {_rev("del", ids, author, date)}/>'
    m = re.search(r"<w:pPr>(.*?)</w:pPr>", new, re.S)
    if m:
        inner = m.group(1)
        inner = inner.replace("<w:rPr>", f"<w:rPr>{mark}", 1) if "<w:rPr>" in inner else inner + f"<w:rPr>{mark}</w:rPr>"
        return new[:m.start(1)] + inner + new[m.end(1):]
    return re.sub(r"(<w:p(?:\s[^>]*)?>)", lambda mm: mm.group(1) + f"<w:pPr><w:rPr>{mark}</w:rPr></w:pPr>", new, count=1)


# ------------------------------------------------------------------ the step
def _author_from_cli(agents: Path) -> str:
    try:
        m = re.search(r"^comment_author:\s*(.+)$", (agents / "cli.yaml").read_text(encoding="utf-8"), re.M)
        return m.group(1).strip() if m else "CSA framework"
    except OSError:
        return "CSA framework"


def place(docx: Path, title: str, level: int, key: str, png: Path, caption: str, source: str, author: str,
          close_word: bool = True, backup: bool = True, word: dict | None = None, after_key: str | None = None) -> dict:
    """word: {"model": ..., "aggregate": bool} draws the figure as editable Word shapes (the picture is kept as the
    fallback for readers without Word 2010 drawing support); None inserts the picture."""
    docx, png = Path(docx), Path(png)
    if close_word:
        from csa_docx import word_close
        closed = word_close.ensure_closed(docx)
        if closed["status"] == "LOCKED":
            return {"status": "BLOCKED", "message": closed["message"]}
    image = png.read_bytes()
    pw, ph = _png_size(image)
    with zipfile.ZipFile(docx) as z:
        parts = {n: z.read(n) for n in z.namelist()}
        infos = {i.filename: i for i in z.infolist()}
    xml = parts["word/document.xml"]
    try:
        where = locate(xml, title, level, key, after_key)
    except Blocked as e:
        return {"status": "BLOCKED", "message": str(e)}
    date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = _Ids(xml)
    # image part and relationship
    rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
    used_ids = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels)] or [0]
    rid = f"rId{max(used_ids) + 1}"
    stem = f"media/csa-figure-{key.lower()}-{_dt.datetime.now():%Y%m%d%H%M%S}"
    media, k = f"{stem}.png", 1
    while "word/" + media in parts:                          # never overwrite the image an earlier placement used
        k += 1
        media = f"{stem}-{k}.png"
    rels = rels.replace("</Relationships>", f'<Relationship Id="{rid}" Type="{REL_IMAGE}" Target="{media}"/></Relationships>')
    ct = parts["[Content_Types].xml"].decode("utf-8")
    if 'Extension="png"' not in ct:
        ct = ct.replace("<Types ", "<Types ", 1).replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
    width = _text_width_emu(xml)
    if word:
        from csa_docx.techdiagram.word_drawing import drawing_xml
        drawing, _info = drawing_xml(word["model"], aggregate=word.get("aggregate", False), width_mm=width / 36000,
                                     png_rid=rid, doc_pr=ids.doc_pr, name=f"CSA figure {key}")
        ids.doc_pr += 2
    else:
        drawing = _drawing(rid, width, int(width * ph / pw), ids.doc_pr, key)
    kids = where["kids"]
    text = xml.decode("utf-8")
    bpos = lambda i: len(xml[:kids[i][0]].decode("utf-8"))
    epos = lambda i: len(xml[:kids[i][1]].decode("utf-8"))
    if where["mode"] in ("insert", "replace"):
        at = epos(where["after"]) if where["mode"] == "insert" else bpos(where["block"][0])
        n = len(re.findall(r"SEQ Figure", text[:at])) + 1
        block = _new_block(drawing, caption, source, n, ids, author, date, key)
        if where["mode"] == "insert":
            text = text[:at] + block + text[at:]
        else:
            first, last = where["block"][0], where["block"][-1]
            old = "".join(_delete_paragraph(text[bpos(i):epos(i)], ids, author, date) for i in where["block"])
            text = text[:bpos(first)] + old + block + text[epos(last):]
    else:                                                    # slot: fill the template's placeholder paragraphs
        fig, *rest = where["block"]
        new_parts = []
        for i in where["block"]:
            chunk = text[bpos(i):epos(i)]
            style = _style(chunk.encode())
            chunk, last = _delete_runs(chunk, ids, author, date, only_placeholder=True)
            if style == "Figure":
                ins = f'<w:bookmarkStart w:id="{ids.next()}" w:name="_CSAFig_{escape(key)}"/>'
                bm = ids.rev
                ins += f'<w:ins {_rev("ins", ids, author, date)}><w:r>{drawing}</w:r></w:ins><w:bookmarkEnd w:id="{bm}"/>'
            elif style == "Caption":
                ins = f'<w:ins {_rev("ins", ids, author, date)}><w:r>{_t(": " + caption)}</w:r></w:ins>'
            else:
                ins = f'<w:ins {_rev("ins", ids, author, date)}><w:r>{_t(source)}</w:r></w:ins>'
            cut = last if last >= 0 else chunk.rindex("</w:p>")
            new_parts.append(chunk[:cut] + ins + chunk[cut:])
        text = text[:bpos(fig)] + "".join(new_parts) + text[epos(where["block"][-1]):]
    bak = create_backup(docx, f"figure_{key}") if backup else None
    parts["word/document.xml"] = text.encode("utf-8")
    parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    parts["[Content_Types].xml"] = ct.encode("utf-8")
    parts["word/" + media] = image
    tmp = Path(tempfile.mkstemp(suffix=".docx", dir=str(docx.parent))[1])
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                info = infos.get(name)
                z.writestr(info if info else zipfile.ZipInfo(name, date_time=_dt.datetime.now().timetuple()[:6]), data,
                           compress_type=zipfile.ZIP_DEFLATED)
        try:
            _validate(tmp)
        except Blocked as e:
            return {"status": "BLOCKED", "message": str(e), "backup": str(bak) if bak else None}
        shutil.move(str(tmp), str(docx))
    finally:
        tmp.unlink(missing_ok=True)
    return {"status": "OK", "mode": where["mode"], "backup": str(bak) if bak else None, "media": media,
            "message": ("added a figure block after the section's first figure" if where.get("after_figure") else
                        {"slot": "filled the section's figure slot", "insert": "added a figure block after Discovery Information",
                         "replace": "replaced the figure placed earlier"}[where["mode"]]) + " (tracked)"
                       + (", drawn as Word shapes" if word else ", as a picture")}


def _validate(docx: Path) -> None:
    """The changed parts must parse, and the vendored DocxEngine validator (when present) must find no error."""
    import sys
    import xml.dom.minidom
    with zipfile.ZipFile(docx) as z:
        for n in ("word/document.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"):
            xml.dom.minidom.parseString(z.read(n))
    vendor = Path(__file__).resolve().parents[2] / "vendor"
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from docxengine._opc import Package
        from docxengine._validate import validate_package
    except Exception:
        return
    errors = [i.message for i in validate_package(Package.open(str(docx))) if i.severity == "error"]
    if errors:
        raise Blocked("the changed document did not validate: " + "; ".join(errors[:3]))
