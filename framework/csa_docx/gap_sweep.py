"""Check every open question against the evidence matrix and the discovery index (no model).

Reads csa-work/draft/open-questions.md (the `Unknown:` lines of every answered card, written by the draft lane) and
runs gap_lookup.lookup_gap on each question. What the index finds goes into the matrix as UNCONFIRMED candidate rows
(gap_lookup's rules: append-only, duplicates reused, rejected rows never offered again). The result is written to
csa-work/intake/gap-check-<UTC>.json and gap-check-latest.json for the Evidence Workspace.

    python3 -m csa_docx.gap_sweep --workspace <project_root> [--section KEY] [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from csa_docx import gap_lookup

_SECTION = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s+(.*?)\s+\(([A-Z0-9_]+)\)\s*$")
_FIGURE = re.compile(r"^##\s+Figure for\s+(\d+(?:\.\d+)*)\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*-\s+\[([A-Za-z0-9_.-]+)\]\s+(.+?)\s*$")
_CANDIDATE = re.compile(r"^Possible answer to (DR-[A-Za-z0-9_.-]+):")


def pending_candidates(workspace: Path) -> dict[str, list[str]]:
    """Pending gap-lookup rows by exact DR id.

    A later fuzzy lookup may not rank an earlier candidate highly enough to return it.  The exact
    DR id embedded when the row was created remains authoritative until the row is reviewed.
    """
    work = Path(workspace) / "csa-work"
    latest: dict[str, str] = {}
    reviews = work / "evidence-reviews.jsonl"
    if reviews.is_file():
        for line in reviews.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            latest[str(record.get("evidence_id", "")).upper()] = str(record.get("state", ""))
    out: dict[str, list[str]] = {}
    matrix = work / "evidence-matrix.csv"
    if not matrix.is_file():
        return out
    from csa_docx import modelstore
    for row in modelstore.read_csv(matrix):             # the store when it is current, else the file (S421)
        evidence_id = str(row.get("evidence_id", "")).upper()
        state = (latest.get(evidence_id) or row.get("review_state") or "pending").lower()
        match = _CANDIDATE.match(row.get("claim", ""))
        if row.get("status") == "UNCONFIRMED" and state == "pending" and match:
            out.setdefault(match.group(1), []).append(evidence_id)
    return out


def parse_open_questions(text: str) -> list[dict]:
    """[{number, title, key, qid, dr_id, text}] from open-questions.md. A figure heading takes the key of the section
    with the same number (FIGURE-<number> when there is none). Lines outside a recognised heading, and bullets without
    a [QID], are skipped."""
    keys: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            keys.setdefault(m.group(1), (m.group(3), m.group(2)))
    out: list[dict] = []
    current: tuple[str, str, str] | None = None        # (number, title, key)
    for line in text.splitlines():
        if line.startswith("## "):
            m, f = _SECTION.match(line), _FIGURE.match(line)
            if m:
                current = (m.group(1), m.group(2), m.group(3))
            elif f:
                key, title = keys.get(f.group(1), (f"FIGURE-{f.group(1)}", f.group(2)))
                current = (f.group(1), title, key)
            else:
                current = None
            continue
        b = _BULLET.match(line)
        if not b or current is None:
            continue
        bracket, body = b.group(1), b.group(2)
        number, title, key = current
        if bracket.upper().startswith("DR-"):
            dr_id, qid = bracket, bracket.rsplit("-", 1)[-1]
        else:
            dr_id, qid = f"DR-{key}-{bracket}", bracket
        out.append({"number": number, "title": title, "key": key, "qid": qid, "dr_id": dr_id, "text": body})
    return out


def sweep(workspace: Path, section_key: str | None = None) -> dict:
    """Look up every open question (or one section's); write intake/gap-check-<ts>.json and gap-check-latest.json."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    source = work / "draft" / "open-questions.md"
    qs = parse_open_questions(source.read_text(encoding="utf-8")) if source.is_file() else []
    if section_key:
        qs = [q for q in qs if q["key"] == section_key]
    carried = pending_candidates(workspace)
    best, _ = gap_lookup.judge_pending(workspace)        # an old pending candidate counts only if it still ranks in the best few
    results = []
    for q in qs:
        res = gap_lookup.lookup_gap(workspace, q["dr_id"], q["text"])
        pending = [i for i in carried.get(q["dr_id"], []) if i in best.get(q["dr_id"], [])]
        if pending:
            res["verdict"] = "CANDIDATES"
        # what is offered to read is _MAX_CANDIDATES rows at most: up to two matrix rows (they may be verified evidence), then the
        # index candidates, then the older pending ones
        ids = list(dict.fromkeys([*res.get("matrix", [])[:2], *res.get("index", []), *pending, *res.get("matrix", [])[2:]]))
        res["evidence_ids"] = ids[:gap_lookup._MAX_CANDIDATES] if res["verdict"] == "CANDIDATES" else ids[:gap_lookup._MAX_CANDIDATES]
        results.append({**q, "verdict": res["verdict"], "evidence_ids": res.get("evidence_ids", []),
                        "kind": res.get("kind", ""), "owners": res.get("owners", []), "related": res.get("related", []),
                        "searches": len(res.get("queries", []))})
    affected: dict[str, dict] = {}
    for r in results:
        if r["verdict"] not in ("ANSWERED", "CANDIDATES"):
            continue
        a = affected.setdefault(r["key"], {"number": r["number"], "key": r["key"], "title": r["title"],
                                           "answered": 0, "candidates": 0})
        a["answered" if r["verdict"] == "ANSWERED" else "candidates"] += 1
    stamp = time.gmtime()
    record = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", stamp), "section": section_key or "",
              "questions": results, "affected": list(affected.values()), "summary": summarise(results)}
    folder = work / "intake"
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=1, ensure_ascii=False)
    (folder / f"gap-check-{time.strftime('%Y%m%dT%H%M%SZ', stamp)}.json").write_text(text, encoding="utf-8")
    (folder / "gap-check-latest.json").write_text(text, encoding="utf-8")
    return record


def summarise(results: list[dict]) -> dict:
    """What a lookup run did, in numbers: gaps, by kind and verdict, searches run, candidates to read (never more than five
    per gap), gaps with related matrix rows to read, and who has to be asked for the ones nothing answers."""
    import collections
    verdicts = collections.Counter(r["verdict"] for r in results)
    ask = collections.Counter(o for r in results if r["verdict"] == "NOT_FOUND" for o in r.get("owners", []))
    return {"gaps": len(results), "by_kind": dict(collections.Counter(r.get("kind") or "system" for r in results)),
            "by_verdict": dict(verdicts), "searches": sum(r.get("searches", 0) for r in results),
            "candidates_to_read": sum(len(r["evidence_ids"]) for r in results if r["verdict"] == "CANDIDATES"),
            "gaps_with_related_rows": sum(1 for r in results if r.get("related")),
            "to_ask": dict(ask.most_common(6))}


def report_lines(summary: dict) -> list[str]:
    s = summary
    k = ", ".join(f"{n} {name}" for name, n in sorted(s["by_kind"].items()))
    v = ", ".join(f"{n} {name.lower().replace('_', ' ')}" for name, n in sorted(s["by_verdict"].items()))
    lines = [f"{s['gaps']} open question(s): {k}.", f"Result: {v}.",
             f"{s['searches']} search(es) run; {s['candidates_to_read']} candidate(s) to read (at most {gap_lookup._MAX_CANDIDATES} per question); "
             f"{s['gaps_with_related_rows']} question(s) with related matrix rows to read."]
    if s["to_ask"]:
        lines.append("Still open, to ask: " + "; ".join(f"{o} ({n})" for o, n in s["to_ask"].items()) + ".")
    return lines


_LABEL = {"ANSWERED": "answered", "CANDIDATES": "possible answer found", "NOT_FOUND": "not found"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check every open question against the evidence matrix and the index.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--section", default="", help="only this section's questions (stamp key, e.g. BAK)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = sweep(a.workspace, a.section or None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if not res["questions"]:
        print("No open questions (csa-work/draft/open-questions.md is missing or empty).")
        return 0
    for q in res["questions"]:
        ids = ", ".join(q["evidence_ids"])
        print(f"  {q['number']:<6} {q['dr_id']:<34} {_LABEL.get(q['verdict'], q['verdict'].lower())}" + (f" ({ids})" if ids else ""))
    print("")
    for line in report_lines(res["summary"]):
        print(line)
    n = sum(a["answered"] + a["candidates"] for a in res["affected"])
    print(f"{n} of {len(res['questions'])} open question(s) have evidence to read, in {len(res['affected'])} subsection(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
