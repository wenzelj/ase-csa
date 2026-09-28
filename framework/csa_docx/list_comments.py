"""List the Word comments in a working DOCX, grouped by the heading they sit under.

Usage (from .agents/framework): python3 -m csa_docx.list_comments <docx> [--heading "3.7.1"] [--json]

--heading matches the start of a heading's text (for example "3.7.1" or "3.7.1 OTIS"); comments under
that heading and its child headings are listed. Read-only.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from pathlib import Path

HEAD_RE = re.compile(r'<w:pStyle w:val="(?:Heading|heading)\s?(\d)"')


def _text(xml: str) -> str:
    xml = re.sub(r"<w:delText[^>]*>.*?</w:delText>", "", xml, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", xml)).strip())


def list_comments(docx: Path) -> list[dict]:
    z = zipfile.ZipFile(docx)
    doc = z.read("word/document.xml").decode("utf-8")
    try:
        cx = z.read("word/comments.xml").decode("utf-8")
    except KeyError:
        return []
    comments = {}
    for m in re.finditer(r'<w:comment\b([^>]*)>(.*?)</w:comment>', cx, re.S):
        cid = re.search(r'w:id="(\d+)"', m.group(1)).group(1)
        author = (re.search(r'w:author="([^"]*)"', m.group(1)) or [None, ""])[1]
        comments[cid] = {"id": cid, "author": author, "text": _text(m.group(2))}
    out, path = [], []
    for p in re.finditer(r"<w:p[ >].*?</w:p>", doc, re.S):
        px = p.group(0)
        h = HEAD_RE.search(px)
        if h:
            lvl = int(h.group(1))
            path = [x for x in path if x[0] < lvl] + [(lvl, _text(px))]
        for cid in re.findall(r'<w:commentRangeStart w:id="(\d+)"', px) or re.findall(r'<w:commentReference w:id="(\d+)"', px):
            if cid in comments and not any(o["id"] == cid for o in out):
                c = dict(comments[cid])
                c["heading_path"] = [t for _, t in path]
                c["anchored_text"] = _text(px)[:160]
                out.append(c)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx"); ap.add_argument("--heading"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    items = list_comments(Path(a.docx))
    if a.heading:
        key = a.heading.strip().lower()
        items = [c for c in items if any(h.lower().startswith(key) for h in c["heading_path"])]
    if a.json:
        print(json.dumps(items, indent=2))
    else:
        if not items:
            print("no comments" + (f" under '{a.heading}'" if a.heading else ""))
        for c in items:
            print(f"[{c['id']}] {c['author']}: {c['text']}\n    under: {' > '.join(c['heading_path'][-2:])}\n    on: {c['anchored_text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
