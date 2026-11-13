"""Which answer sheets cite evidence rows the answer accessor no longer offers, why, and which row replaces each.

A sheet written before a re-capture can rest on rows that were rejected as superseded (a newer capture of the same host),
retired in a cleanup, or removed from the matrix. Such a sheet fails UNKNOWN_EVIDENCE the next time it is checked and has to be
answered again. This report says which sheets, which rows, and the verified row that now says the same thing.

    python3 -m csa_docx.evidence_stale --work-dir <csa-work> [--out evidence-stale.md]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

from csa_docx import evidence_live

_EID = re.compile(r"(?<![\w:])E-\d+\b")
_SKIP = {"BAK", "EXECUTIVE_SUMMARY"}


def _host(row: dict) -> str:
    m = re.search(r"discovery_([A-Z0-9]+)_", row.get("source_title") or "")
    return m[1] if m else ""


def _key(row: dict) -> tuple:
    return (_host(row), row.get("csa_area", ""), (row.get("question") or "")[:80])


def _last_reviews(work: Path) -> dict[str, dict]:
    last: dict[str, dict] = {}
    p = work / "evidence-reviews.jsonl"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                last[d["evidence_id"]] = d
            except (ValueError, KeyError):
                continue
    return last


def stale_rows(work: Path) -> dict[str, list[dict]]:
    """{sheet key: [{id, why, replacements}]} for every sheet that cites a row the accessor does not offer."""
    work = Path(work)
    if work.name == "csa-work-v2":
        from csa_docx import v2_access
        return _stale_rows_v2(work, v2_access.active_db(work.parent))
    rows = {r["evidence_id"]: r for r in evidence_live.read(work / "evidence-matrix.csv")}
    usable = {i for i, r in rows.items() if evidence_live.is_verified(r)}
    reviews = _last_reviews(work)
    by_key: dict[tuple, list[str]] = collections.defaultdict(list)
    for i in usable:
        by_key[_key(rows[i])].append(i)
    out: dict[str, list[dict]] = {}
    for f in sorted(glob.glob(str(work / "cards" / "*.answer.md"))):
        key = os.path.basename(f).split(".")[0]
        if key in _SKIP:
            continue
        found = []
        for i in sorted(set(_EID.findall(Path(f).read_text(encoding="utf-8"))), key=lambda s: int(s[2:])):
            if i in usable:
                continue
            if i not in rows:
                found.append({"id": i, "why": "no longer in the matrix", "replacements": []})
                continue
            note = reviews.get(i, {}).get("note", "") or rows[i].get("status", "")
            m = re.search(r"re-quoted as (E-\d+)", note)
            repl = [m[1]] if m and m[1] in usable else by_key.get(_key(rows[i]), [])[:3]
            found.append({"id": i, "why": note[:110], "replacements": repl})
        if found:
            out[key] = found
    return out


def _stale_rows_v2(work: Path, db: Path) -> dict[str, list[dict]]:
    from csa_docx import v2_access
    rows = {r["evidence_id"]: r for r in v2_access.evidence_rows(db)}
    usable = {i for i, r in rows.items() if r.get("status") == "VERIFIED" and r.get("review_state") != "rejected"}
    reviews = {r["subject_id"]: r for r in v2_access.review_events(db)}
    by_key: dict[tuple, list[str]] = collections.defaultdict(list)
    for i in usable:
        by_key[_key(rows[i])].append(i)
    out: dict[str, list[dict]] = {}
    for f in sorted(glob.glob(str(work / "cards" / "*.answer.md"))):
        key = os.path.basename(f).split(".")[0]
        if key in _SKIP:
            continue
        found = []
        for i in sorted(set(_EID.findall(Path(f).read_text(encoding="utf-8"))), key=lambda s: int(s[2:])):
            if i in usable:
                continue
            if i not in rows:
                found.append({"id": i, "why": "not available in csa.sqlite", "replacements": []})
                continue
            note = reviews.get(i, {}).get("note", "") or rows[i].get("review_state", "")
            found.append({"id": i, "why": note[:110], "replacements": by_key.get(_key(rows[i]), [])[:3]})
        if found:
            out[key] = found
    return out


def report(work: Path) -> str:
    stale = stale_rows(work)
    lines = ["# Answers that cite evidence the framework no longer offers", ""]
    if not stale:
        return "\n".join(lines + ["None."]) + "\n"
    lines += ["| Sheet | Unusable rows | With a replacement |", "|---|---|---|"]
    for k, v in stale.items():
        lines.append(f"| {k} | {len(v)} | {sum(1 for x in v if x['replacements'])} |")
    for k, v in stale.items():
        lines += ["", f"## {k}", ""]
        for x in v:
            lines.append(f"- {x['id']}: {x['why']}" + (f" -> use {', '.join(x['replacements'])}" if x["replacements"] else ""))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    text = report(Path(a.work_dir))
    if a.out:
        Path(a.work_dir, a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
