"""Fixture documents for the document-spec tests, made by editing the template's XML.

Each helper takes a template (.dotx) path and writes a new file with one change: a stamped copy, a new
requirement block inserted between two others, a renamed heading, a removed block, a copied block that
carries a duplicate stamp, or a heading with no fillable content.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_P = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)


def _rewrite(src: Path, dst: Path, fn) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = fn(data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    return dst


def _heading_span(xml: str, title_xml: str, level: int = 2) -> tuple[int, int]:
    """Start of the Heading `level` paragraph with this text, and start of the next heading of that level or above."""
    start = None
    for m in _P.finditer(xml):
        p = m.group(0)
        hs = re.search(r'<w:pStyle w:val="Heading([1-9])"', p)
        if not hs:
            continue
        lv = int(hs.group(1))
        if start is None and lv == level and f">{title_xml}<" in p:
            start = m.start()
            continue
        if start is not None and lv <= level:
            return start, m.start()
    if start is None:
        raise ValueError(f"no Heading {level} '{title_xml}'")
    return start, xml.index("<w:sectPr", start) if "<w:sectPr" in xml[start:] else len(xml)


def insert_block(src: Path, dst: Path, *, copy_of: str, before: str, title: str, req_id: str, req_text: str,
                 old_req: str) -> Path:
    def fn(xml):
        a, b = _heading_span(xml, copy_of)
        block = xml[a:b]
        block = re.sub(r'<w:bookmarkStart w:id="\d+" w:name="_[^"]*"/>', "", block)
        block = re.sub(r'<w:bookmarkEnd w:id="\d+"/>', "", block)
        block = re.sub(r"<w:comment(?:RangeStart|RangeEnd|Reference)\b[^>]*/>", "", block)
        block = block.replace(f">{copy_of}<", f">{title}<", 1).replace(f">{old_req}<", f">{req_id}<")
        block = re.sub(r"(<w:t[^>]*>)Vital OT systems shall[^<]*(</w:t>)", rf"\g<1>{req_text}\g<2>", block, count=1)
        c, _ = _heading_span(xml, before)
        return xml[:c] + block + xml[c:]
    return _rewrite(src, dst, fn)


def rename_heading(src: Path, dst: Path, old: str, new: str) -> Path:
    def fn(xml):
        a, b = _heading_span(xml, old)
        head_end = xml.index("</w:p>", a)
        return xml[:a] + xml[a:head_end].replace(f">{old}<", f">{new}<", 1) + xml[head_end:]
    return _rewrite(src, dst, fn)


def remove_block(src: Path, dst: Path, title: str) -> Path:
    def fn(xml):
        a, b = _heading_span(xml, title)
        return xml[:a] + xml[b:]
    return _rewrite(src, dst, fn)


def copy_block_with_stamp(src: Path, dst: Path, title: str, before: str) -> Path:
    """A block pasted with its bookmark (Word would drop it; a script might not)."""
    def fn(xml):
        a, b = _heading_span(xml, title)
        block = xml[a:b].replace(f">{title}<", f">{title} (copy)<", 1)
        c, _ = _heading_span(xml, before)
        return xml[:c] + block + xml[c:]
    return _rewrite(src, dst, fn)


def add_empty_heading(src: Path, dst: Path, title: str, before: str) -> Path:
    def fn(xml):
        c, _ = _heading_span(xml, before)
        para = (f'<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>{title}</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Some notes about this.</w:t></w:r></w:p>')
        return xml[:c] + para + xml[c:]
    return _rewrite(src, dst, fn)


def unstamp(src: Path, dst: Path) -> Path:
    """The same document with every `_csa_` stamp removed (a document made before stamps existed)."""
    def fn(xml):
        ids = re.findall(r'<w:bookmarkStart w:id="(\d+)" w:name="_csa_[^"]*"/>', xml)
        xml = re.sub(r'<w:bookmarkStart w:id="\d+" w:name="_csa_[^"]*"/>', "", xml)
        for i in ids:
            xml = xml.replace(f'<w:bookmarkEnd w:id="{i}"/>', "")
        return xml
    return _rewrite(src, dst, fn)
