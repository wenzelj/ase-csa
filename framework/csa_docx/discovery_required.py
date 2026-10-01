"""Appendix E Discovery Required rows from the answer plans of every converted subsection.

Every gap an answer plan raises (`gap_generated: DR-XXX-01 <what to confirm>`) becomes one structured
row: requirement IDs, what is needed, why, rating impact, owner, how to obtain it and status. Each row
is backed by a NOT_FOUND evidence row. Rows already in the section file that no plan produces (added by
hand) are kept.

    python3 -m csa_docx.discovery_required --workspace <project root>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from csa_docx import answer_plan, check_section, gap_lookup, section_file

MATRIX_SCRIPT = (Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix"
                 / "scripts" / "evidence_matrix.py")
REQUIREMENT_MAP = answer_plan.REQUIREMENT_MAP

HEADER = ["ID", "Requirement(s)", "Discovery needed", "Why it's needed", "Rating impact",
          "Owner / source", "How to obtain", "Status"]


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _target_key(name: str) -> tuple:
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (10**6, name)


def _cell(text: str) -> str:
    return " ".join((text or "").replace("|", "/").split())


def _rating_impact(reqs: list[str]) -> str:
    return f"May change the {reqs[0]} rating" if len(reqs) == 1 else f"May change the {', '.join(reqs)} ratings"


def _collect(work: Path) -> list[dict]:
    """One item per DR id, in target order; the first text, fact and scope win."""
    items: dict[str, dict] = {}
    plans = sorted((work / "convert").glob("*/answer-plan.csv"), key=lambda p: _target_key(p.parent.name))
    for plan in plans:
        for g in answer_plan.gaps(answer_plan.load(plan)):
            it = items.setdefault(g["dr_id"], {"dr_id": g["dr_id"], "text": g["text"], "reqs": [],
                                               "fact": g["fact"], "scope": g["evidence_scope"]})
            if g["req_id"] and g["req_id"] not in it["reqs"]:
                it["reqs"].append(g["req_id"])
    return list(items.values())


def _evidence_id(workspace: Path, work: Path, item: dict, searched: str) -> str:
    found = [r["evidence_id"] for r in _read_csv(work / "evidence-matrix.csv")
             if r.get("status") == "NOT_FOUND" and re.search(rf"{re.escape(item['dr_id'])}(?!\d)", r.get("gap_or_action") or "")]
    if found:
        return found[-1]           # the latest: a `gap_lookup confirm` row names what was searched and considered
    scope = f"searched: {searched}" + (f"; plan scope: {item['scope']}" if item["scope"] else "")
    row = {"csa_area": "discovery_required", "question": item["text"], "claim": item["fact"],
           "status": "NOT_FOUND", "source_title": scope[:1400],
           "source_version": "", "section": "8 Discovery Required", "page_or_location": "",
           "evidence_excerpt": "", "inference_reason": "", "confidence": "low",
           "gap_or_action": item["dr_id"]}
    proc = subprocess.run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append",
                           "--agent", "csa discovery-required", "--context", f"discovery required {item['dr_id']}",
                           "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)],
                          capture_output=True, text=True)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        return ""
    if out.get("written"):
        return out["written"][0]["evidence_id"]
    return (out.get("skipped_duplicates") or [{}])[0].get("duplicate_of", "")


def build(workspace: Path, legacy_docx: Path | None = None) -> dict:
    workspace = Path(workspace)
    work = workspace / "csa-work"
    items = _collect(work)
    if not items:
        return {"status": "EMPTY"}

    answer_from = {r["req_id"]: r["answer_from"] for r in _read_csv(REQUIREMENT_MAP)}
    exclude = (Path(legacy_docx).name,) if legacy_docx else ()
    rows: list[tuple[list[str], str]] = []  # (cells, evidence id)
    possibly_answered: list[dict] = []
    for it in items:
        # A gap is only a gap when the evidence matrix and the discovery index do not answer it.
        look = gap_lookup.lookup_gap(workspace, it["dr_id"], it["text"], exclude=exclude)
        if look["verdict"] != "NOT_FOUND":
            possibly_answered.append({"dr_id": it["dr_id"], "verdict": look["verdict"], "evidence_ids": look["evidence_ids"]})
            continue
        how = answer_from.get(it["reqs"][0], "") if it["reqs"] else ""
        cells = [it["dr_id"], ", ".join(it["reqs"]), it["text"], it["fact"], _rating_impact(it["reqs"] or ["requirement"]),
                 "To be assigned", how, "Open"]
        rows.append(([_cell(c) for c in cells], _evidence_id(workspace, work, it, look["searched"])))

    out = work / "sections" / "8-discovery-required.md"
    if not rows and not out.is_file():
        return {"status": "EMPTY", "possibly_answered": possibly_answered}
    if out.is_file():                        # keep rows added by hand
        try:
            old = section_file.parse_section_file(out)
            ev = old.get("evidence", {})
            have = {r[0][0] for r in rows}
            for n, cells in enumerate(old.get("tables", {}).get("Items", []), start=1):
                if cells and cells[0] not in have:
                    rows.append((cells, (ev.get(f"Items {n}") or [""])[0]))
        except ValueError:
            pass

    lines = ["---", "block: discovery-required", "heading: Discovery Required", "status: draft", "---", "",
             "## Items", "", "| " + " | ".join(HEADER) + " |", "| " + " | ".join(["---"] * len(HEADER)) + " |"]
    lines += ["| " + " | ".join(cells) + " |" for cells, _ in rows]
    lines += ["", "## Evidence", "", "| Statement | Evidence |", "| --- | --- |"]
    lines += [f"| Items {n} | {eid} |" for n, (_, eid) in enumerate(rows, start=1) if eid]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = check_section.check(out, workspace=str(workspace), lint=False)
    return {"status": "ERROR" if res.get("errors") else "OK", "file": str(out), "items": len(rows),
            "findings": res.get("findings", []), "possibly_answered": possibly_answered}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Discovery Required section file from answer-plan gaps.")
    ap.add_argument("--workspace", type=Path, required=True)
    a = ap.parse_args(argv)
    res = build(a.workspace)
    print(json.dumps(res, ensure_ascii=False))
    return 2 if res.get("status") == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
