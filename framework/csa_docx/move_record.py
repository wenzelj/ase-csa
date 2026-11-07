"""Records for `csa move`: what was moved, what is still open, and Section 8 built from the open items.

Mechanical and agent-free: no discovery index, no evidence matrix.

    record(workspace, section)   csa-work/move/moved.csv, csa-work/move/open-items.csv, csa-work/convert/parked.md
    section8(workspace)          csa-work/sections/8-discovery-required.md from open-items.csv

    python3 -m csa_docx.move_record --workspace <project root> (--record 3.4 | --section8)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from csa_docx import check_section, convert_ledger, scope_map, section_file
from csa_docx.check_section import normalise_heading

MOVED_COLUMNS = ["id", "target", "section_file"]
OPEN_COLUMNS = ["section", "ref", "text"]
HEADER = ["ID", "Requirement(s)", "Discovery needed", "Why it's needed", "Rating impact",
          "Owner / source", "How to obtain", "Status"]
_REQ_RE = re.compile(r"SEP-([A-Z]+)-\d+")
_SECTION8_FILE = "8-discovery-required.md"
# The placement engine drops empty cells from a pipe row, so the owner and how-to-obtain cells carry
# a short placeholder (the same owner text csa convert uses) until someone fills them in.
OWNER = "To be assigned"
HOW = "To be confirmed"


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def _find_section_file(work: Path, section: str) -> Path | None:
    want = normalise_heading(convert_ledger._target_heading(section))
    for path in sorted((work / "sections").glob("*.md")):
        try:
            parsed = section_file.parse_section_file(path)
        except (ValueError, OSError):
            continue
        if normalise_heading(parsed["heading"]) == want:
            return path
    return None


def section_path(workspace, section: str) -> str | None:
    """The section file written for ``section`` (``None`` when there is none yet)."""
    path = _find_section_file(Path(workspace) / "csa-work", str(section))
    return str(path) if path else None


def record(workspace, section: str) -> dict:
    """Write or update the move records for one subsection; earlier rows for it are replaced."""
    work = Path(workspace) / "csa-work"
    section = str(section)
    path = _find_section_file(work, section)
    if path is None:
        return {"status": "ERROR", "message": f"no section file for {section} in {work / 'sections'}"}

    blocks = [r for r in _read_csv(work / "legacy" / "map.csv")
              if r.get("job") in ("convert", "context")
              and (r.get("target") == section or (r.get("target") or "").startswith(section + "."))]
    moved = [r for r in _read_csv(work / "move" / "moved.csv") if r["target"] != section]
    moved += [{"id": r["id"], "target": section, "section_file": path.name} for r in blocks]
    _write_csv(work / "move" / "moved.csv", MOVED_COLUMNS, moved)

    items = section_file.parse_section_file(path)["open_items"]
    kept = [r for r in _read_csv(work / "move" / "open-items.csv") if r["section"] != section]
    kept += [{"section": section, "ref": i["ref"], "text": i["text"]} for i in items]
    _write_csv(work / "move" / "open-items.csv", OPEN_COLUMNS, kept)

    convert_ledger.write_parked(work)
    return {"status": "OK", "blocks": len(blocks), "open_items": len(items)}


def _cell(text: str) -> str:
    return " ".join((text or "").replace("|", "/").split())


def _area(ref: str, section: str, domains: dict) -> str:
    m = _REQ_RE.search(ref)
    if m:
        return m[1]
    for rid in (domains.get(section) or {}).get("req_ids", []):
        return _REQ_RE.match(rid)[1]
    return "GEN"


def section8(workspace) -> dict:
    """Build the Discovery Required section file from open-items.csv, one row per distinct open item."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    try:
        domains = scope_map.load()
    except (ValueError, OSError):
        domains = {}
    items: dict[tuple[str, str], dict] = {}
    for r in _read_csv(work / "move" / "open-items.csv"):
        key = (" ".join(r["ref"].split()).lower(), " ".join(r["text"].split()).lower())
        items.setdefault(key, r)
    if not items:
        return {"status": "EMPTY"}

    counts: dict[str, int] = {}
    rows = []
    for r in items.values():
        area = _area(r["ref"], r["section"], domains)
        counts[area] = counts.get(area, 0) + 1
        is_req = bool(_REQ_RE.fullmatch(r["ref"].strip()))
        what = r["text"] if is_req or not r["ref"].strip() else f"{r['ref'].strip()}: {r['text']}"
        cells = [f"DR-{area}-{counts[area]:02d}", r["ref"].strip() if is_req else "", what,
                 "previous assessment does not state it", "not assessed", OWNER, HOW, "Open"]
        rows.append([_cell(c) for c in cells])

    lines = ["---", "mode: move", "block: discovery-required", "heading: Discovery Required", "status: draft", "---", "",
             "## Items", "", "| " + " | ".join(HEADER) + " |", "| " + " | ".join(["---"] * len(HEADER)) + " |"]
    lines += ["| " + " | ".join(cells) + " |" for cells in rows]
    out = work / "sections" / _SECTION8_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = check_section.check(out, lint=False)
    if res.get("errors"):
        return {"status": "ERROR", "file": str(out), "rows": len(rows), "findings": res["findings"]}
    return {"status": "OK", "rows": len(rows), "file": str(out)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move records and Section 8 for csa move.")
    ap.add_argument("--workspace", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", metavar="SECTION")
    g.add_argument("--section8", action="store_true")
    a = ap.parse_args(argv)
    res = record(a.workspace, a.record) if a.record else section8(a.workspace)
    print(json.dumps(res, ensure_ascii=False))
    return 2 if res.get("status") == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
