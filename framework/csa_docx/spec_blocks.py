"""template-blocks.json, generated from the template's document spec (S253).

The block map used to be written by hand: one entry per requirement domain (number, heading, requirement IDs,
tables), one per Migration Discovery subsection and one per singleton block (governance, coverage, glossary,
boundary appendix, Discovery Required). Every one of those facts is in the template itself, so this module
derives them from `doc_spec.read(template)` and reports or writes the difference. Keys that are not structure
(`ratings` from the dropdown, `max_current_state_words`, `_note`) are kept.

    python3 -m csa_docx.spec_blocks <template.dotx> [--blocks template-blocks.json] [--write]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from csa_docx import doc_spec

BLOCKS = Path(__file__).resolve().parents[2] / "skills" / "csa-document-template" / "references" / "template-blocks.json"
SINGLETONS = {"governance": "GOVERNANCE_NOTE_NEXT_STEPS", "coverage": "DISCOVERY_COVERAGE",
              "glossary": "GLOSSARY_ACRONYMS", "boundary_appendix": "OT_3_5_DESTINATION_BOUNDARY",
              "discovery_required": "DISCOVERY_REQUIRED", "executive_summary": "EXECUTIVE_SUMMARY",
              "migration_intro": "MIGRATION_DISCOVERY"}


def _rows(p: dict) -> int:
    return p.get("rows", 0)


def domain(n: dict) -> dict:
    parts = n["parts"]
    reqs = [r["id"] for p in parts if p["kind"] == "requirement" for r in p["requirements"]]
    disc = next((p for p in parts if p["kind"] == "observation"), None)
    tables = {re.sub(r"\s*\([^)]*\)\s*$", "", p["label"]): {"columns": p["columns"], "placeholder_rows": _rows(p)}
              for p in parts if p["kind"] == "register" and p.get("label")}
    return {"number": n["number"], "heading": n["title"], "req_ids": reqs, "tables": tables,
            "discovery_table": {"columns": disc["columns"], "placeholder_rows": _rows(disc)} if disc else {},
            "drawbridge_paragraphs": sum(1 for p in parts if p["kind"] == "narrative" and (p.get("facet") or "").lower() == "drawbridge impact"),
            "discovery_note_paragraphs": sum(1 for p in parts if p["kind"] == "note" and (p.get("facet") or "").lower() == "discovery information"),
            "key": n["key"]}


def migration(n: dict) -> dict:
    parts = n["parts"]
    out = {"number": n["number"], "heading": n["title"], "key": n["key"]}
    intro = sum(1 for p in parts if p["kind"] == "narrative")
    table = next((p for p in parts if p["kind"] in ("register", "observation")), None)
    bullets = sum(p.get("placeholders", 0) for p in parts if p["kind"] == "findings")
    notes = sum(1 for p in parts if p["kind"] == "note")
    if intro:
        out["intro_paragraphs"] = intro
    if table:
        out["table"] = {"columns": table["columns"], "placeholder_rows": _rows(table)}
        holder_cols = [i for i, c in enumerate(table["columns"]) if doc_spec.is_placeholder(c)]
        if holder_cols:
            out["table"]["project_columns_from"] = holder_cols[0]   # header columns the project renames
    out["bullets"] = bullets
    if notes:
        out["note_paragraphs"] = notes
    return out


def generate(spec: dict, current: dict) -> dict:
    nodes = spec["nodes"]
    new = dict(current)
    new["domains"] = [domain(n) for n in nodes if n["kind"] == "requirement-block"]
    mig = next((n for n in nodes if n["key"] == "MIGRATION_DISCOVERY"), None)
    if mig:
        new["migration"] = [migration(n) for n in nodes if n.get("parent") == mig["path"] and n["key"] != "DISCOVERY_COVERAGE"]
    for k, key in SINGLETONS.items():
        n = next((x for x in nodes if x["key"] == key), None)
        if n and isinstance(current.get(k), dict):
            upd = {"heading": n["title"], "key": n["key"]}
            if "number" in current[k]:
                upd["number"] = n["number"]
            new[k] = dict(current[k], **upd)
    new["ratings"] = spec.get("ratings") or current.get("ratings")
    new["_generated_from"] = Path(spec["source"]).name
    return new


def _strip(x):
    """Compare structure only: the generated `key` and `_generated_from` fields are additions, not differences."""
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in ("key", "_generated_from")}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def diff(current: dict, new: dict) -> list[str]:
    out = []
    for k in sorted(set(current) | set(new)):
        a, b = _strip(current.get(k)), _strip(new.get(k))
        if k.startswith("_") or a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else None
                y = b[i] if i < len(b) else None
                if x != y:
                    out.append(f"{k}[{i}]: file {json.dumps(x)[:160]} | template {json.dumps(y)[:160]}")
        else:
            out.append(f"{k}: file {json.dumps(a)[:160]} | template {json.dumps(b)[:160]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", type=Path)
    ap.add_argument("--blocks", type=Path, default=BLOCKS)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    current = json.loads(a.blocks.read_text(encoding="utf-8"))
    new = generate(doc_spec.read(a.template), current)
    d = diff(current, new)
    if a.write:
        a.blocks.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"differences": d, "written": a.write}) if a.json else ("\n".join(d) or "template-blocks.json matches the template"))
    return 0 if not d or a.write else 1


if __name__ == "__main__":
    sys.exit(main())
