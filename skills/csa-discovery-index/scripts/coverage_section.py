#!/usr/bin/env python3
"""Write the 5.1 Discovery Coverage section file (build lane, template v1.2) from a
project's discovery index.

    coverage_section.py --project iamps --out csa-work/sections/5.1-discovery-coverage.md

One `## Hosts` row per host with a current capture (the latest, not superseded or
archived), from the index's `captures` table: Host; Role (`To confirm`: the index does
not record roles); Discovery Script Run (collector and capture date); Notes (full or
lightweight capture by file count against the largest capture, the environment folder,
and any earlier capture it replaced). Read-only against the index. The file is a
`status: draft` section file for `csa check-section`, `csa qa` and `csa build`.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discovery_index as di  # noqa: E402  (project resolution and the read-only index)


def _date(utc: str) -> str:
    try:
        return datetime.strptime(utc, "%Y%m%dT%H%M%SZ").strftime("%-d %b %Y")
    except (TypeError, ValueError):
        return utc or "unknown date"


def _env(folder: str) -> str | None:
    for part in Path(folder).parts:
        if re.fullmatch(r"PROD|PRD|TEST|TST|DEV|QA|UAT|DR", part, re.I):
            return part.upper()
    return None


def _cell(s: str) -> str:
    return str(s).replace("|", "/").strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project")
    ap.add_argument("--workspace")
    ap.add_argument("--out", required=True, help="section file to write (relative paths: under the project's work_dir/sections)")
    ap.add_argument("--full-ratio", type=float, default=0.8,
                    help="a capture with at least this share of the largest capture's files counts as full (default 0.8)")
    a = ap.parse_args(argv)
    project, _root = di.resolve_project(a)
    con, _meta = di.open_ro(project)

    caps = [dict(r) for r in con.execute(
        "SELECT capture_id, folder, host, collector, capture_utc, file_count, archived, superseded_by "
        "FROM captures ORDER BY host, capture_utc")]
    current = [c for c in caps if c["superseded_by"] is None and not c["archived"]]
    if not current:
        di.fail("NO_CAPTURES", "the discovery index has no current captures")
    replaced = {}
    for c in caps:
        if c["superseded_by"] is not None:
            replaced.setdefault(c["superseded_by"], []).append(c)
    largest = max(c["file_count"] or 0 for c in current) or 1

    rows, evidence = [], []
    for n, c in enumerate(current, 1):
        files = c["file_count"] or 0
        kind = "Full capture" if files >= a.full_ratio * largest else "Lightweight capture"
        notes = [f"{kind} ({files} files)"]
        env = _env(c["folder"])
        if env:
            notes.append(f"{env} environment folder")
        older = [_date(o["capture_utc"]) for o in sorted(replaced.get(c["capture_id"], []), key=lambda o: o["capture_utc"])]
        if older:
            notes.append(f"replaces the {older[0]} capture" if len(older) == 1
                         else f"replaces the {', '.join(older[:-1])} and {older[-1]} captures")
        script = f"{c['collector']} discovery script, {_date(c['capture_utc'])}" if c["collector"] else f"Discovery script, {_date(c['capture_utc'])}"
        rows.append([_cell(c["host"]), "To confirm", _cell(script), _cell("; ".join(notes))])
        evidence.append((f"Hosts {n}", f"discovery index capture {Path(c['folder']).name}"))

    dates = sorted({c["capture_utc"] for c in current})
    collectors = sorted({c["collector"] for c in current if c["collector"]})
    when = f"on {_date(dates[0])}" if _date(dates[0]) == _date(dates[-1]) else f"between {_date(dates[0])} and {_date(dates[-1])}"
    by = (f"the {collectors[0]} discovery script" if len(collectors) == 1
          else f"the {', '.join(collectors[:-1])} and {collectors[-1]} discovery scripts" if collectors
          else "the discovery scripts")
    hosts_word = "host was" if len(current) == 1 else "hosts were"
    words = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
    count = words[len(current)] if len(current) < len(words) else str(len(current))
    summary = f"{count} {hosts_word} captured with {by} {when}; each row below is the host's latest capture."

    out = Path(a.out)
    if not out.is_absolute():
        out = di.remap(project["work_dir"], project) / "sections" / out
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", "block: coverage", "heading: Discovery Coverage", "status: draft", "---", "",
             "## Summary", "", summary, "",
             "## Hosts", "", "| Host | Role | Discovery Script Run | Notes |", "| --- | --- | --- | --- |"]
    lines += [f"| {' | '.join(r)} |" for r in rows]
    # Coverage statements come from the discovery index, not the evidence matrix, so their
    # evidence names the capture; check_section skips the matrix check for coverage blocks.
    lines += ["", "## Evidence", "", "| Statement | Evidence |", "| --- | --- |",
              f"| Summary | discovery index: {len(current)} current captures |"]
    lines += [f"| {k} | {v} |" for k, v in evidence]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    di.emit({"status": "OK", "out": str(out), "hosts": len(rows), "largest_capture_files": largest})
    return 0


if __name__ == "__main__":
    sys.exit(main())
