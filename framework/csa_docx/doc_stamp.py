"""Identity stamps: a hidden bookmark `_csa_<KEY>` in a heading names the section for good.

A heading's number changes when a section is inserted above it, and its text changes when someone renames
it. A bookmark travels with the heading through both, is hidden in Word when its name starts with `_`, and
is not duplicated when a block is copied inside the same document (Word keeps the name on the original).
So the stamp, not the number or the text, is the section's identity.

Stamping only adds `w:bookmarkStart` / `w:bookmarkEnd` to heading paragraphs; every other part of the
package is copied byte for byte.

    python3 -m csa_docx.doc_stamp <in.docx|.dotx> <out> [--template T] [--confirm]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from csa_docx import doc_spec

_P = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)
_HSTYLE = re.compile(r'<w:pStyle w:val="Heading\s?([1-9])"\s*/>')
_BM_ID = re.compile(r'<w:bookmarkStart\b[^>]*\bw:id="(\d+)"')
MAX_NAME = 40


def stamp_name(key: str) -> str:
    name = doc_spec.STAMP_PREFIX + re.sub(r"[^A-Za-z0-9_]", "_", key)
    if len(name) > MAX_NAME:
        raise ValueError(f"stamp {name} is longer than Word's {MAX_NAME}-character bookmark limit")
    return name


def plan(doc: dict, template: dict | None, confirm: bool = False) -> dict:
    """Which unstamped headings get which stamp.

    A key is accepted without confirmation only when it is exact: the requirement family of the section's
    own requirement IDs, or a heading key the template also has. Anything else (a section a user added by
    hand, a renamed heading) is listed and stamped only with confirm=True. Never guessed."""
    tkeys = {n["key"] for n in (template or {}).get("nodes", [])}
    stamp, ask, keep = {}, [], []
    used = {n["key"] for n in doc["nodes"] if n["stamp"]}
    for n in doc["nodes"]:
        if n["stamp"]:
            keep.append({"number": n["number"], "title": n["title"], "stamp": n["stamp"]})
            continue
        key = n["key"].split("_")[0] if n["key_from"].startswith("requirement family") else n["key"]
        exact = n["key_from"].startswith("requirement family") or (template is not None and key in tkeys)
        if "deduplicated" in n["key_from"] or key in used:
            ask.append({"number": n["number"], "title": n["title"], "key": n["key"], "reason": "key already used"})
            continue
        if exact or confirm:
            stamp[n["path"]] = key
            used.add(key)
        else:
            ask.append({"number": n["number"], "title": n["title"], "key": key,
                        "reason": "no requirement family and the template has no section with this heading"})
    return {"stamp": stamp, "ask": ask, "keep": keep}


def stamp_xml(xml: str, targets: dict[str, str]) -> tuple[str, list[dict]]:
    """Insert a bookmark into each heading whose stable path (heading ordinal path, as in @H3.4) is in targets."""
    next_id = max([int(i) for i in _BM_ID.findall(xml)] or [0]) + 1
    ordinals: dict[int, int] = {}
    done: list[dict] = []
    out, pos = [], 0
    for m in _P.finditer(xml):
        p = m.group(0)
        hs = _HSTYLE.search(p.split("</w:pPr>")[0]) if "<w:pPr>" in p else None
        if not hs:
            continue
        level = int(hs.group(1))
        ordinals[level] = ordinals.get(level, 0) + 1
        for d in [k for k in ordinals if k > level]:
            del ordinals[d]
        number = ".".join(str(ordinals.get(lv, 0)) for lv in range(1, level + 1))
        key = targets.get(number)
        if not key or f'w:name="{doc_spec.STAMP_PREFIX}' in p:
            continue
        name = stamp_name(key)
        mark = f'<w:bookmarkStart w:id="{next_id}" w:name="{name}"/><w:bookmarkEnd w:id="{next_id}"/>'
        cut = p.index("</w:pPr>") + len("</w:pPr>")
        out.append(xml[pos:m.start()] + p[:cut] + mark + p[cut:])
        pos = m.end()
        done.append({"number": number, "stamp": name, "id": next_id})
        next_id += 1
    out.append(xml[pos:])
    return "".join(out), done


def stamp_file(src: Path, dst: Path, targets: dict[str, str]) -> list[dict]:
    """targets: stable path (3.4) -> key."""
    """Copy src to dst with the stamps added. src and dst may be the same file (written through a temp file)."""
    src, dst = Path(src), Path(dst)
    with tempfile.NamedTemporaryFile(delete=False, suffix=dst.suffix, dir=str(dst.parent)) as tmp:
        tmp_path = Path(tmp.name)
    done: list[dict] = []
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml, done = stamp_xml(data.decode("utf-8"), targets)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp_path), str(dst))
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--template", type=Path)
    ap.add_argument("--confirm", action="store_true", help="also stamp headings that need confirmation")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    doc = doc_spec.read(a.src)
    tmpl = doc_spec.read(a.template) if a.template else None
    pl = plan(doc, tmpl, a.confirm)
    if not a.dry_run and pl["stamp"]:
        pl["done"] = stamp_file(a.src, a.dst, pl["stamp"])
    print(json.dumps(pl, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
