"""Read an old-format CSA into an ordered list of numbered blocks.

Each block is a heading, paragraph, bullet, table row or figure, with the heading path it sits under,
so later conversion steps can trace every fact back to where it came from. The old document is only
ever read.

    python3 -m csa_docx.legacy_extract <docx> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


_HEADING_STYLE = re.compile(r"^heading\s?([1-9])$", re.IGNORECASE)
_BULLET_STYLES = ("listbullet", "listnumber", "listparagraph")


def _style(p: ET.Element) -> str:
    el = p.find(f"{_q('pPr')}/{_q('pStyle')}")
    return el.get(_q("val"), "") if el is not None else ""


def _text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(_q("t"))).strip()


def _heading_level(p: ET.Element, style: str) -> int:
    m = _HEADING_STYLE.match(style)
    if m:
        return int(m.group(1))
    lvl = p.find(f"{_q('pPr')}/{_q('outlineLvl')}")
    if lvl is not None:
        try:
            return int(lvl.get(_q("val"), "")) + 1
        except ValueError:
            return 0
    return 0


def _is_figure(p: ET.Element) -> bool:
    return p.find(f".//{_q('drawing')}") is not None or p.find(f".//{_q('pict')}") is not None


def _is_bullet(p: ET.Element, style: str) -> bool:
    if p.find(f"{_q('pPr')}/{_q('numPr')}") is not None:
        return True
    return style.lower().startswith(_BULLET_STYLES)


def _body_children(body: ET.Element) -> list[ET.Element]:
    """Body-level paragraphs and tables in order, looking through content controls."""
    out: list[ET.Element] = []
    for child in body:
        if child.tag in (_q("p"), _q("tbl")):
            out.append(child)
        elif child.tag == _q("sdt"):
            content = child.find(_q("sdtContent"))
            if content is not None:
                out.extend(_body_children(content))
    return out


def _cell_text(tc: ET.Element) -> str:
    parts = (_text(p) for p in tc.findall(_q("p")))
    return " ".join(t for t in parts if t)


def _row_cells(tr: ET.Element) -> list[str]:
    return [_cell_text(tc) for tc in tr.findall(_q("tc"))]


def extract(docx: Path) -> list[dict]:
    """Return the old document's blocks in order. Never writes to the document."""
    with zipfile.ZipFile(docx) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(_q("body"))
    if body is None:
        return []

    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []  # (heading level, heading text)

    def add(kind: str, text: str, level: int = 0, **extra) -> None:
        n = len(blocks) + 1
        block = {
            "id": f"L-{n:04d}",
            "order": n,
            "kind": kind,
            "level": level,
            "path": [t for _, t in stack],
            "text": text,
        }
        block.update(extra)
        blocks.append(block)

    children = _body_children(body)
    i = 0
    while i < len(children):
        el = children[i]
        i += 1

        if el.tag == _q("tbl"):
            rows = el.findall(_q("tr"))
            if not rows:
                continue
            if len(rows) == 1:
                header: list[str] = []
                data = rows
            else:
                header = _row_cells(rows[0])
                data = rows[1:]
            for tr in data:
                cells = _row_cells(tr)
                if not any(cells):
                    continue
                add("table_row", " | ".join(cells), cells=cells, header=header)
            continue

        style = _style(el)
        if style.lower().startswith("toc"):
            continue

        if _is_figure(el):
            caption = ""
            if i < len(children) and children[i].tag == _q("p") \
                    and _style(children[i]).lower().startswith("caption"):
                caption = _text(children[i])
                i += 1
            add("figure", caption)
            continue

        text = _text(el)
        if not text:
            continue

        level = _heading_level(el, style)
        if level:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            add("heading", text, level=level)
        elif _is_bullet(el, style):
            add("bullet", text)
        else:
            add("para", text)
    return blocks


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50].strip("-")
    return slug or "section"


def _render(block: dict) -> str:
    if block["kind"] == "heading":
        return f"{'#' * min(block['level'], 3)} {block['text']}  `{block['id']}`"
    return f"`{block['id']}` {block['text']}".rstrip()


def write(blocks: list[dict], out_dir: Path) -> dict:
    """Write blocks.jsonl and one readable Markdown file per Heading 1."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "blocks.jsonl").write_text(
        "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks), encoding="utf-8")

    files: list[tuple[str, list[str]]] = []  # (file name, lines)
    current: list[str] | None = None
    h1_count = 0
    for b in blocks:
        if b["kind"] == "heading" and b["level"] == 1:
            h1_count += 1
            current = []
            files.append((f"{h1_count:02d}-{_slug(b['text'])}.md", current))
        elif current is None:
            current = []
            files.append(("00-front-matter.md", current))
        current.append(_render(b))

    for name, lines in files:
        (out_dir / name).write_text("\n\n".join(lines) + "\n", encoding="utf-8")

    headings = sum(1 for b in blocks if b["kind"] == "heading")
    return {"status": "OK", "blocks": len(blocks), "headings": headings, "out": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read an old-format CSA into numbered blocks.")
    ap.add_argument("docx", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    def error(message: str) -> int:
        print(json.dumps({"status": "ERROR", "message": message}))
        return 2

    if not args.docx.is_file():
        return error(f"file not found: {args.docx}")
    if args.docx.suffix.lower() != ".docx":
        return error(f"not a .docx file: {args.docx}")
    try:
        blocks = extract(args.docx)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        return error(f"cannot read {args.docx}: {e}")
    print(json.dumps(write(blocks, args.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
