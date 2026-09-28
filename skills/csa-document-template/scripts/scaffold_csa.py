#!/usr/bin/env python3
"""Set the number of placeholder table rows or bullets in a template-based CSA .docx.

Why: change records (and the framework) only fill or replace what already exists; they refuse to
reshape a table, and text inserted by the framework loses bullet formatting. The template ships a
few placeholder rows and bullets per block. Run this once, BEFORE drafting change records, so each
block has exactly as many placeholders as the evidence needs; the change records then replace each
placeholder by its @H... ID.

Standard library only (Python 3.8+). Byte-level edit of word/document.xml (namespaces untouched),
timestamped backup first, atomic write. Idempotent: it sets a COUNT, it does not add N more.
It only ever removes placeholder-only rows/bullets from the end, and refuses if that would delete
content. New rows/bullets are clones of the last one with grey/bracketed placeholder text, so
`check_csa.py` flags any left unfilled.

After a run call prepareDocument(force_regenerate=True): the stable-ID manifest only rebuilds by
itself when the heading skeleton changes, and row/paragraph IDs have moved.

Locate the block by the heading above it (exact text, no number):
  rows    --heading "Discovery Coverage" --set-count 26                               (template v1.2; v1.1: "Workstation and Server Discovery Coverage")
  rows    --heading "Discovery Information" --heading-occurrence 2 --set-count 6     (3.2 accounts table)
  rows    --heading "Discovery Information" --heading-occurrence 5 --set-count 4     (3.5 DNS Discovery table, v1.2)
  bullets --heading "Governance Note and Next Steps" --set-count 5                 (3 standard actions + 2)

Output: one JSON object. Exit 0 = done (or already at that count), 2 = refused (nothing changed).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PARA = re.compile(r"<w:p(?: [^>]*)?>.*?</w:p>", re.S)
TBL = re.compile(r"<w:tbl>.*?</w:tbl>", re.S)
ROW = re.compile(r"<w:tr(?: [^>]*)?>.*?</w:tr>", re.S)
CELL = re.compile(r"<w:tc>.*?</w:tc>", re.S)
HEADING = re.compile(r'<w:pStyle w:val="Heading([1-3])"\s*/>')
BULLET = re.compile(r'<w:pStyle w:val="ListBullet"\s*/>')
PLACEHOLDER_ONLY = re.compile(r"\[[^\[\]]+\]")


def fail(msg, **kw):
    print(json.dumps({"status": "ERROR", "message": msg, **kw}, indent=2))
    sys.exit(2)


def text_of(xml: str) -> str:
    return re.sub(r"\s+", " ", "".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", xml, re.S))).strip()


def is_placeholder_only(xml: str) -> bool:
    """True when every non-empty cell/paragraph text is a single [bracketed] token."""
    parts = [text_of(c) for c in CELL.findall(xml)] or [text_of(xml)]
    parts = [p for p in parts if p]
    return bool(parts) and all(PLACEHOLDER_ONLY.fullmatch(p) for p in parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["rows", "bullets"])
    ap.add_argument("--docx", required=True)
    ap.add_argument("--heading", required=True)
    ap.add_argument("--heading-occurrence", type=int, default=1)
    ap.add_argument("--table", type=int, default=1, help="rows: Nth table under the heading (default 1)")
    ap.add_argument("--set-count", type=int, required=True, help="rows: data rows (header excluded); bullets: bullet paragraphs")
    args = ap.parse_args()
    if not 0 <= args.set_count <= 300:
        fail("--set-count must be 0-300")
    path = Path(args.docx).expanduser()
    if not path.is_file():
        fail(f"not found: {path}")

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
    xml = parts["word/document.xml"].decode("utf-8")

    heads = []
    for m in PARA.finditer(xml):
        h = HEADING.search(m.group(0))
        if h:
            heads.append((m.start(), m.end(), text_of(m.group(0))))
    hits = [h for h in heads if h[2] == args.heading]
    if len(hits) < args.heading_occurrence:
        fail(f"heading {args.heading!r} occurrence {args.heading_occurrence} not found", found=len(hits))
    idx = heads.index(hits[args.heading_occurrence - 1])
    lo = heads[idx][1]
    hi = heads[idx + 1][0] if idx + 1 < len(heads) else len(xml)

    if args.kind == "rows":
        tables = list(TBL.finditer(xml, lo, hi))
        if len(tables) < args.table:
            fail(f"table {args.table} not found under {args.heading!r}", tables_found=len(tables))
        tm = tables[args.table - 1]
        tx = tm.group(0)
        style = re.search(r'<w:tblStyle w:val="([^"]+)"', tx)
        if not style or style.group(1) != "CSATable":
            fail("target table is not a CSA Table; refusing")
        rows = list(ROW.finditer(tx))
        headers = [text_of(c) for c in CELL.findall(rows[0].group(0))]
        data = rows[1:]
        cur = len(data)
        if not data and args.set_count:
            fail("table has no data row to clone")
        if args.set_count > cur:
            last = data[-1].group(0)
            trpr = re.search(r"<w:trPr>.*?</w:trPr>", last, re.S)
            new = []
            for _ in range(args.set_count - cur):
                cells = []
                for tc, hdr in zip(CELL.findall(last), headers):
                    tcpr = re.search(r"<w:tcPr>.*?</w:tcPr>", tc, re.S)
                    ppr = re.search(r"<w:pPr>.*?</w:pPr>", tc, re.S)
                    cells.append("<w:tc>" + (tcpr.group(0) if tcpr else "") + "<w:p>" + (ppr.group(0) if ppr else "")
                                 + f'<w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t>[{escape(hdr)}]</w:t></w:r></w:p></w:tc>')
                new.append("<w:tr>" + (trpr.group(0) if trpr else "") + "".join(cells) + "</w:tr>")
            pos = tm.start() + tx.rindex("</w:tbl>")
            new_xml = xml[:pos] + "".join(new) + xml[pos:]
        elif args.set_count < cur:
            drop = data[args.set_count:]
            filled = [i + args.set_count + 1 for i, r in enumerate(drop) if not is_placeholder_only(r.group(0))]
            if filled:
                fail("would delete rows that contain content; only placeholder rows can be removed", data_rows_with_content=filled)
            first = tm.start() + drop[0].start()
            last_end = tm.start() + drop[-1].end()
            new_xml = xml[:first] + xml[last_end:]
        else:
            new_xml = xml
        summary = {"table": args.table, "columns": headers, "rows_before": cur, "rows_after": args.set_count}
    else:
        paras = [m for m in PARA.finditer(xml, lo, hi) if BULLET.search(m.group(0))]
        cur = len(paras)
        if not cur and args.set_count:
            fail("no bullet paragraph under that heading to clone")
        if args.set_count > cur:
            last = paras[-1].group(0)
            clone = re.sub(r"<w:t(?: [^>]*)?>.*?</w:t>", "<w:t>[Finding]</w:t>", last, count=1, flags=re.S)
            clone = re.sub(r"<w:(?:commentRange(?:Start|End)|commentReference|bookmark(?:Start|End))[^>]*/>", "", clone)
            clone = re.sub(r"<w:r><w:rPr><w:rStyle w:val=\"CommentReference\"\s*/></w:rPr></w:r>", "", clone)
            clone = re.sub(r"<w:(?:ins|del) [^>]*>|</w:(?:ins|del)>", "", clone)
            if not text_of(clone) == "[Finding]":
                fail("last bullet has a shape this script does not clone (tracked changes or several runs); accept/finish those edits first")
            pos = paras[-1].end()
            new_xml = xml[:pos] + clone * (args.set_count - cur) + xml[pos:]
        elif args.set_count < cur:
            drop = paras[args.set_count:]
            filled = [i + args.set_count + 1 for i, m in enumerate(drop) if not is_placeholder_only(m.group(0))]
            if filled:
                fail("would delete bullets that contain content; only placeholder bullets can be removed", bullets_with_content=filled)
            new_xml = xml[: drop[0].start()] + xml[drop[-1].end():]
        else:
            new_xml = xml
        summary = {"bullets_before": cur, "bullets_after": args.set_count}

    if new_xml == xml:
        print(json.dumps({"status": "UNCHANGED", "docx": str(path), "heading": args.heading, **summary}, indent=2))
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.before_scaffold_{stamp}.bak")
    shutil.copy2(path, backup)
    if backup.stat().st_size == 0:
        fail("backup is empty; aborting", backup=str(backup))
    parts["word/document.xml"] = new_xml.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, parts[n])
    tmp.replace(path)
    print(json.dumps({"status": "UPDATED", "docx": str(path), "backup": str(backup), "heading": args.heading,
                      "heading_occurrence": args.heading_occurrence, **summary,
                      "next": "Call prepareDocument(force_regenerate=True); IDs have moved. Then draft change records for the placeholders."},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
