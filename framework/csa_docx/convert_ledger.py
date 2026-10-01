"""Coverage ledger for `csa convert`: every old block mapped to a subsection gets one outcome.

USED (a VERIFIED or INFERRED row for it is in the section file's Evidence table), SUPERSEDED (a
CONFLICTING row: discovery data disagrees), or the writer's own line in `outcomes.csv` (MOVED,
DUPLICATE, NOT_USED). A block with none of these is MISSING and the ledger is INCOMPLETE. Also writes
the project-wide parked list (recommendations, scores) and figure list.

    python3 -m csa_docx.convert_ledger --work-dir <csa-work> (--target 3.4 | --parked | --figures)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from csa_docx import answer_plan, requirement_assign, scope_map, section_file
from csa_docx.check_section import normalise_heading
from csa_docx.convert_brief import _template_title

LEDGER_COLUMNS = ["id", "path", "outcome", "evidence_ids", "target", "reason", "req_id", "kind"]
_OPEN_OUTCOMES = ("MISSING", "REQ_INCOMPLETE", "FACT_UNACCOUNTED")
_CANDIDATE_TYPES = ("observed", "gap", "consequence", "design")


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _read_blocks(work_dir: Path) -> dict[str, dict]:
    blocks = {}
    path = work_dir / "legacy" / "blocks.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                b = json.loads(line)
                blocks[b["id"]] = b
    return blocks


def _target_heading(target: str) -> str:
    try:
        domains = scope_map.load()
    except (ValueError, OSError):
        domains = {}
    if target in domains:
        return domains[target]["title"]
    return _template_title(target) or target


def _find_section_file(work_dir: Path, heading: str) -> dict | None:
    want = normalise_heading(heading)
    for path in sorted((work_dir / "sections").glob("*.md")):
        try:
            parsed = section_file.parse_section_file(path)
        except (ValueError, OSError):
            continue
        if normalise_heading(parsed["heading"]) == want:
            return parsed
    return None


def _valid_outcome(line: dict) -> bool:
    outcome = (line.get("outcome") or "").strip().upper()
    if outcome == "MOVED":
        return bool((line.get("target") or "").strip())
    if outcome == "DUPLICATE":
        return True
    if outcome == "NOT_USED":
        return bool((line.get("reason") or "").strip())
    return False


def _append_moved(work_dir: Path, pairs: list[tuple[str, str]]) -> None:
    """Append `id,target` lines to legacy/moved.csv, never an id twice."""
    if not pairs:
        return
    path = work_dir / "legacy" / "moved.csv"
    have = {r.get("id") for r in _read_csv(path)}
    new = [(i, t) for i, t in pairs if i not in have]
    if not new:
        return
    fresh = not path.is_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if fresh:
            w.writerow(["id", "target"])
        w.writerows(new)


def _ids(cell: str) -> list[str]:
    return re.findall(r"L-\d+", cell or "")


def _requirement_ledger(work_dir: Path, target: str, parsed: dict | None) -> tuple[list[dict], list[tuple[str, str]]]:
    """Ledger rows for a subsection with an answer plan: one per requirement, one per candidate fact cluster."""
    plan_rows = answer_plan.load(work_dir / "convert" / target / "answer-plan.csv")
    outcomes = {(o.get("id") or "").strip() for o in _read_csv(work_dir / "convert" / target / "outcomes.csv")
                if _valid_outcome(o)}
    plan_ids: set[str] = set()
    moved: list[tuple[str, str]] = []
    gap_reqs: set[str] = set()
    for r in plan_rows:
        ids = _ids(r["legacy_ids"])
        plan_ids.update(ids)
        m = re.fullmatch(r"MOVED (\S+)", r["destination"].strip())
        if m:
            moved += [(i, m.group(1)) for i in ids]
        if r["statement_type"].strip() == "gap" and r["gap_generated"].strip():
            gap_reqs.add(r["req_id"].strip())
    for o in _read_csv(work_dir / "convert" / target / "outcomes.csv"):
        if _valid_outcome(o) and o["outcome"].strip().upper() == "MOVED":
            moved.append((o["id"].strip(), o["target"].strip()))

    reqs = [r for r in requirement_assign.load_requirements() if r["domain"] == target]
    rows: list[dict] = []

    section_reqs = {r["req_id"]: r for r in (parsed or {}).get("requirements", [])}
    di_rows = (parsed or {}).get("tables", {}).get("Discovery Information", [])
    header = (parsed or {}).get("table_headers", {}).get("Discovery Information", [])
    col = next((i for i, h in enumerate(header) if "coverage" in h.lower() or "source" in h.lower()),
               len(header) - 1 if header else -1)
    empty_source = [row for row in di_rows if col < 0 or col >= len(row) or not row[col].strip()]

    for r in reqs:
        rid = r["req_id"]
        sec = section_reqs.get(rid)
        problems = []
        if not sec or not sec["current_state"].strip():
            problems.append("no Current State")
        if not sec or not sec["rating"].strip():
            problems.append("no Rating")
        if not di_rows:
            problems.append("no Discovery Information row")
        elif empty_source:
            problems.append("a Discovery Information row has an empty Coverage / Source")
        if problems and rid in gap_reqs:
            problems = []          # answered as a recorded gap
        rows.append({"id": rid, "path": target, "outcome": "REQ_INCOMPLETE" if problems else "ANSWERED",
                     "evidence_ids": "", "target": "", "reason": "; ".join(problems), "req_id": rid,
                     "kind": "requirement"})

    facts_path = work_dir / "legacy" / "facts.jsonl"
    req_ids = {r["req_id"] for r in reqs}
    clusters: dict[str, list[dict]] = {}
    if facts_path.is_file():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            f = json.loads(line)
            ids = f.get("req_ids") or []
            ids = ids.split(";") if isinstance(ids, str) else ids
            if ids and ids[0] in req_ids and f["stype"] in _CANDIDATE_TYPES:
                clusters.setdefault(f.get("cluster") or f["fact_id"], []).append(f)
    for cid, members in clusters.items():
        lids = list(dict.fromkeys(m["legacy_id"] for m in members))
        ok = any(i in plan_ids or i in outcomes for i in lids)
        rows.append({"id": lids[0], "path": members[0]["path"], "outcome": "ACCOUNTED" if ok else "FACT_UNACCOUNTED",
                     "evidence_ids": "", "target": "", "reason": "" if ok else f"cluster {cid} is not in the answer plan",
                     "req_id": members[0]["req_ids"][0] if isinstance(members[0]["req_ids"], list) else "",
                     "kind": "fact"})
    return rows, moved


def _finish_requirement_ledger(work_dir: Path, target: str, parsed: dict | None) -> dict:
    ledger, moved = _requirement_ledger(work_dir, target, parsed)
    out_dir = work_dir / "convert" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "ledger.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLUMNS)
        w.writeheader()
        w.writerows(ledger)
    _append_moved(work_dir, moved)
    counts: dict[str, int] = {}
    for o in ledger:
        counts[o["outcome"]] = counts.get(o["outcome"], 0) + 1
    incomplete = [o["id"] for o in ledger if o["outcome"] == "REQ_INCOMPLETE"]
    missing = [o["id"] for o in ledger if o["outcome"] == "FACT_UNACCOUNTED"]
    if parsed is None:
        status = "NO_SECTION_FILE"
    else:
        status = "INCOMPLETE" if (incomplete or missing) else "COMPLETE"
    return {"status": status, "target": target, "mode": "requirement", "counts": counts,
            "incomplete_requirements": incomplete, "missing": missing, "moved": [i for i, _ in moved]}


def build_ledger(work_dir: Path, target: str) -> dict:
    work_dir = Path(work_dir)
    rows = [r for r in _read_csv(work_dir / "legacy" / "map.csv")
            if r.get("target") == target and r.get("job") in ("convert", "context")]
    matrix = _read_csv(work_dir / "evidence-matrix.csv")
    outcomes = {(o.get("id") or "").strip(): o
                for o in _read_csv(work_dir / "convert" / target / "outcomes.csv")
                if _valid_outcome(o)}
    parsed = _find_section_file(work_dir, _target_heading(target))
    in_section = {e for ids in (parsed or {}).get("evidence", {}).values() for e in ids}

    if (work_dir / "convert" / target / "answer-plan.csv").is_file():
        return _finish_requirement_ledger(work_dir, target, parsed)

    ledger, moved = [], []
    for r in rows:
        lid = r["id"]
        pat = re.compile(rf"legacy {re.escape(lid)}(?!\d)")
        matches = [m for m in matrix if pat.search(m.get("gap_or_action") or "")]
        used = [m["evidence_id"] for m in matches
                if (m.get("status") or "").upper() in ("VERIFIED", "INFERRED") and m["evidence_id"] in in_section]
        conflicts = [m["evidence_id"] for m in matches if (m.get("status") or "").upper() == "CONFLICTING"]
        out = {"id": lid, "path": r["path"], "outcome": "MISSING", "evidence_ids": "", "target": "", "reason": "",
               "req_id": "", "kind": "block"}
        if used:
            out.update(outcome="USED", evidence_ids=";".join(used))
        elif conflicts:
            out.update(outcome="SUPERSEDED", evidence_ids=";".join(conflicts))
        elif lid in outcomes:
            o = outcomes[lid]
            out.update(outcome=o["outcome"].strip().upper(), target=(o.get("target") or "").strip(),
                       reason=(o.get("reason") or "").strip())
            if out["outcome"] == "MOVED":
                moved.append(lid)
        ledger.append(out)

    out_dir = work_dir / "convert" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "ledger.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLUMNS)
        w.writeheader()
        w.writerows(ledger)

    if moved:
        path = work_dir / "legacy" / "moved.csv"
        have = {r.get("id") for r in _read_csv(path)}
        new = [o for o in ledger if o["id"] in moved and o["id"] not in have]
        if new:
            fresh = not path.is_file()
            with path.open("a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if fresh:
                    w.writerow(["id", "target"])
                w.writerows([o["id"], o["target"]] for o in new)

    counts: dict[str, int] = {}
    for o in ledger:
        counts[o["outcome"]] = counts.get(o["outcome"], 0) + 1
    missing = [o["id"] for o in ledger if o["outcome"] == "MISSING"]
    if parsed is None:
        status = "NO_SECTION_FILE"
    else:
        status = "INCOMPLETE" if missing else "COMPLETE"
    return {"status": status, "target": target, "counts": counts, "missing": missing, "moved": moved}


def write_parked(work_dir: Path) -> dict:
    """Everything with no place in the template: parked blocks, and the recommendation sentences of mined
    subsections (from legacy/facts.jsonl; without it, the mined blocks whole)."""
    work_dir = Path(work_dir)
    blocks = _read_blocks(work_dir)
    groups: dict[str, list[str]] = {}
    facts_path = work_dir / "legacy" / "facts.jsonl"
    rows = _read_csv(work_dir / "legacy" / "map.csv")
    for r in rows:
        if r["id"] not in blocks:
            continue
        if r.get("job") == "parked" or (r.get("job") == "mine" and not facts_path.is_file()):
            groups.setdefault(r["path"], []).append(f"- `{r['id']}` {blocks[r['id']]['text']}".rstrip())
    if facts_path.is_file():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            f = json.loads(line)
            if f.get("stype") == "recommendation":
                groups.setdefault(f.get("path", ""), []).append(
                    f"- `{f['fact_id']}` (`{f['legacy_id']}`) {f['text']}".rstrip())
    md = ["Content of the previous assessment that has no place in the CSA template (for the roadmap).", ""]
    for path, lines in groups.items():
        md += [f"### {path}", ""] + lines + [""]
    (work_dir / "convert").mkdir(parents=True, exist_ok=True)
    (work_dir / "convert" / "parked.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"status": "OK", "parked": sum(len(v) for v in groups.values())}


def write_figures(work_dir: Path) -> dict:
    work_dir = Path(work_dir)
    blocks = _read_blocks(work_dir)
    lines = []
    for r in _read_csv(work_dir / "legacy" / "map.csv"):
        if r.get("job") == "figure" and r["id"] in blocks:
            caption = blocks[r["id"]]["text"] or "(no caption)"
            lines.append(f"- `{r['id']}` {r['target'] or 'no target'} {caption} — {r['path']}")
    (work_dir / "convert").mkdir(parents=True, exist_ok=True)
    (work_dir / "convert" / "figures.md").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return {"status": "OK", "figures": len(lines)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coverage ledger, parked list and figure list for csa convert.")
    ap.add_argument("--work-dir", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--target")
    g.add_argument("--parked", action="store_true")
    g.add_argument("--figures", action="store_true")
    a = ap.parse_args(argv)
    if a.parked:
        res = write_parked(a.work_dir)
    elif a.figures:
        res = write_figures(a.work_dir)
    else:
        res = build_ledger(a.work_dir, a.target)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
