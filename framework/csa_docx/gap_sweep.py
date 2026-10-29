"""Check every open question against the evidence matrix and the discovery index (no model).

Reads csa-work/draft/open-questions.md (the `Unknown:` lines of every answered card, written by the draft lane) and
runs gap_lookup.lookup_gap on each question. What the index finds goes into the append-only lead store
(duplicates are reused and terminal leads are never offered again). The result is written to
csa-work/intake/gap-check-<UTC>.json and gap-check-latest.json for the Evidence Workspace.

    python3 -m csa_docx.gap_sweep --workspace <project_root> [--section KEY] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from csa_docx import gap_lookup

_SECTION = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s+(.*?)\s+\(([A-Z0-9_]+)\)\s*$")
_FIGURE = re.compile(r"^##\s+Figure for\s+(\d+(?:\.\d+)*)\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*-\s+\[([A-Za-z0-9_.-]+)\]\s+(.+?)\s*$")
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


def _safe_for_retirement(text: str, questions: list[dict]) -> bool:
    """Retirement is allowed only when the question file was present, non-empty and parsed completely."""
    if not text.strip() or not questions:
        return False
    bracket_bullets = sum(1 for line in text.splitlines() if line.lstrip().startswith("- ["))
    return bracket_bullets == len(questions)


def _retire_absent(workspace: Path, questions: list[dict], section_key: str | None) -> list[str]:
    from csa_docx import leads
    active = {q["dr_id"] for q in questions}
    rows = leads.open_leads(workspace)
    if section_key:
        rows = [r for r in rows if str(r.get("dr_id", "")).startswith(f"DR-{section_key}-")]
    ids = [r["lead_id"] for r in rows if r.get("dr_id") not in active]
    if ids:
        scope = f"section {section_key}" if section_key else "complete open-question set"
        leads.review(workspace, ids, "retired", "gap sweep", f"question absent from successful {scope}")
    return ids


def sweep(workspace: Path, section_key: str | None = None) -> dict:
    """Look up every open question (or one section's); write intake/gap-check-<ts>.json and gap-check-latest.json."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    source = work / "draft" / "open-questions.md"
    source_text = source.read_text(encoding="utf-8") if source.is_file() else ""
    all_questions = parse_open_questions(source_text)
    safe_retirement = _safe_for_retirement(source_text, all_questions)
    qs = list(all_questions)
    if section_key:
        qs = [q for q in qs if q["key"] == section_key]
    results = []
    for q in qs:
        res = gap_lookup.lookup_gap(workspace, q["dr_id"], q["text"])
        answers = list(dict.fromkeys(res.get("answer_evidence_ids", res.get("evidence_ids", []))))[:gap_lookup._MAX_CANDIDATES]
        related = list(dict.fromkeys(res.get("related_evidence_ids", res.get("related", []))))[:gap_lookup._MAX_CANDIDATES]
        lead_ids = list(dict.fromkeys(res.get("lead_ids", res.get("index", []))))[:gap_lookup._MAX_CANDIDATES]
        results.append({**q, "verdict": res["verdict"], "answer_evidence_ids": answers,
                        "related_evidence_ids": related, "lead_ids": lead_ids, "evidence_ids": answers,
                        "kind": res.get("kind", ""), "owners": res.get("owners", []), "related": related,
                        "queries": res.get("queries", []), "searched": res.get("searched", ""),
                        "searches": len(res.get("queries", []))})
    retired = _retire_absent(workspace, qs, section_key) if safe_retirement else []
    affected: dict[str, dict] = {}
    for r in results:
        if r["verdict"] not in ("ANSWERED", "CANDIDATES"):
            continue
        a = affected.setdefault(r["key"], {"number": r["number"], "key": r["key"], "title": r["title"],
                                           "answered": 0, "candidates": 0})
        a["answered" if r["verdict"] == "ANSWERED" else "candidates"] += 1
    stamp = time.gmtime()
    record = {"schema_version": 2, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", stamp), "section": section_key or "",
              "questions": results, "affected": list(affected.values()), "retired_lead_ids": retired,
              "summary": summarise(results)}
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
            "candidates_to_read": sum(len(r.get("lead_ids", [])) for r in results if r["verdict"] == "CANDIDATES"),
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
        ids = ", ".join(q.get("lead_ids", []) if q["verdict"] == "CANDIDATES" else q.get("answer_evidence_ids", []))
        print(f"  {q['number']:<6} {q['dr_id']:<34} {_LABEL.get(q['verdict'], q['verdict'].lower())}" + (f" ({ids})" if ids else ""))
    print("")
    for line in report_lines(res["summary"]):
        print(line)
    n = sum(a["answered"] + a["candidates"] for a in res["affected"])
    print(f"{n} of {len(res['questions'])} open question(s) have evidence to read, in {len(res['affected'])} subsection(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
