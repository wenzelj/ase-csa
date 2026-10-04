"""Check a build-lane section file before it can be approved and built.

    python -m csa_docx.check_section <section file> [--workspace <project root>]
                                   [--json] [--no-lint]

Run from .agents/framework. Built like ``check_change.py``: the same
``finding()`` shape, the same JSON keys (``file``, ``findings``, ``errors``,
``warnings``) and the same exit codes -- exit 1 when there is at least one
ERROR, warnings never fail the check. ``csa check-section <file>`` wraps this.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from csa_docx import section_file
from csa_docx.check_change import EID_RE, MARKDOWN_RE, STABLE_ID_RE, finding, lint_findings

BLOCKS = ("domain", "executive-summary", "governance", "migration", "glossary", "coverage", "discovery-required")
MODES = ("move",)
BLOCKS_JSON = (Path(__file__).resolve().parents[2]
               / "skills" / "csa-document-template" / "references" / "template-blocks.json")


QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


def normalise_heading(text: str) -> str:
    """Compare headings without caring about curly vs straight quotes or extra spaces.
    build_plan (S57) uses this too, so a section file may type either kind of quote."""
    return " ".join((text or "").translate(QUOTES).split())


# The ## sections each block kind must have (Evidence always). Domain files
# may add that domain's tables from template-blocks.json; migration files
# allow whatever their subsection entry provides; everything a kind allows is
# optional except the entries listed here.
REQUIRED_SECTIONS = {
    "domain": ["Requirements", "Discovery Information", "Drawbridge Impact"],
    "executive-summary": ["Summary"],
    "governance": ["Actions"],
    "glossary": ["Terms"],
    "coverage": ["Hosts"],
    "discovery-required": ["Items"],
    "migration": [],  # every subsection section is optional; Table/Findings shape below
}

# ## sections that must hold pipe-table rows (a bullets or prose section in
# their place is BAD_TABLE); the others hold bullets or prose.
TABLE_SECTIONS = {
    "domain": {"Requirements", "Discovery Information"},
    "migration": {"Table"},
    "coverage": {"Hosts"},
    "glossary": {"Terms"},
    "discovery-required": {"Items"},
}


def _load_blocks() -> dict:
    return json.loads(BLOCKS_JSON.read_text(encoding="utf-8"))


def _domain_for(blocks: dict, heading: str):
    for d in blocks.get("domains", []):
        if normalise_heading(d.get("heading")) == normalise_heading(heading):
            return d
    return None


def _heading_for(blocks: dict, block: str) -> str | None:
    if block == "domain":
        return None  # many possible headings; validated per-domain below
    if block == "executive-summary":
        return blocks.get("executive_summary", {}).get("heading")
    if block == "governance":
        return blocks.get("governance", {}).get("heading")
    if block == "glossary":
        return blocks.get("glossary", {}).get("heading")
    if block == "coverage":
        return blocks.get("coverage", {}).get("heading")
    if block == "discovery-required":
        return blocks.get("discovery_required", {}).get("heading")
    if block == "migration":
        for m in blocks.get("migration", []):
            if m.get("heading"):
                return m.get("heading")
        return None
    return None


def _migration_headings(blocks: dict) -> set[str]:
    heads = {normalise_heading(m.get("heading")) for m in blocks.get("migration", []) if m.get("heading")}
    intro = blocks.get("migration_intro", {})
    if intro.get("heading"):
        heads.add(normalise_heading(intro["heading"]))
    return heads


def _migration_entry(blocks: dict, heading: str):
    for m in blocks.get("migration", []):
        if normalise_heading(m.get("heading")) == normalise_heading(heading):
            return m
    return None


def _expected_columns(blocks: dict, block: str, heading: str, name: str) -> int | None:
    """Template column count for a table ## section, or None if it is not one."""
    if block == "domain":
        dom = _domain_for(blocks, heading)
        if dom is None:
            return None
        if name == "Requirements":
            return 3
        if name == "Discovery Information":
            dt = dom.get("discovery_table") or {}
            return len(dt.get("columns") or []) or None
        entry = (dom.get("tables") or {}).get(name) or {}
        return len(entry.get("columns") or []) or None
    if block == "migration" and name == "Table":
        entry = _migration_entry(blocks, heading) or {}
        table = entry.get("table") or {}
        return len(table.get("columns") or []) or None
    if block == "coverage" and name == "Hosts":
        cov = blocks.get("coverage", {})
        return len(cov.get("columns") or []) or None
    if block == "glossary" and name == "Terms":
        return len((blocks.get("glossary", {}).get("columns") or [])) or None
    if block == "discovery-required" and name == "Items":
        return len(blocks.get("discovery_required", {}).get("columns") or []) or None
    return None


def _matrix_eids(workspace: str | None) -> set[str] | None:
    """First column of <workspace>/csa-work/evidence-matrix.csv, or None if absent."""
    if not workspace:
        return None
    path = Path(workspace) / "csa-work" / "evidence-matrix.csv"
    if not path.is_file():
        return None
    eids: set[str] = set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip():
                eids.add(row[0].strip())
    return eids


def check(path: Path, workspace: str | None = None, lint: bool = True) -> dict:
    findings: list[dict] = []

    try:
        parsed = section_file.parse_section_file(path)
    except ValueError as e:
        return {"file": str(path), "findings": [finding("ERROR", "PARSE", str(e))],
                "errors": 1, "warnings": 0}

    blocks = _load_blocks()
    block = parsed["block"]
    heading = parsed["heading"]
    from csa_docx.prose_budget import budgets
    budget = budgets(path.parent, workspace)
    # A size in the template spec wins; otherwise the guide follows the host register.
    max_words = blocks.get("max_current_state_words") or budget["current_state_words"]
    ratings = set(blocks.get("ratings", []))
    # mode: move (csa move): old content copied into the template. Every structural ERROR stays;
    # an empty Rating and a missing Evidence table are allowed, and the Evidence checks are skipped.
    mode = parsed.get("mode", "")
    move = mode == "move"
    if mode and mode not in MODES:
        findings.append(finding("ERROR", "UNKNOWN_MODE", f"mode {mode!r} is not one of {', '.join(MODES)}"))

    if block not in BLOCKS:
        findings.append(finding("ERROR", "UNKNOWN_BLOCK", f"block {block!r} is not one of {', '.join(BLOCKS)}"))
    dom = None
    mig = None
    if block == "domain":
        dom = _domain_for(blocks, heading)
        if dom is None:
            findings.append(finding("ERROR", "UNKNOWN_HEADING", f"{heading!r} is not a domain heading in the template"))
        else:
            expected = dom["req_ids"]
            got = [r["req_id"] for r in parsed["requirements"]]
            exp_set, got_set = set(expected), set(got)
            for rid in expected:
                if rid not in got_set:
                    findings.append(finding("ERROR", "MISSING_REQ", f"domain {heading!r} is missing requirement {rid}"))
            seen: set[str] = set()
            for rid in got:
                if rid in seen:
                    findings.append(finding("ERROR", "DUPLICATE_REQ", f"requirement {rid} appears more than once", rid))
                seen.add(rid)
            for rid in sorted(set(got)):
                if rid not in exp_set:
                    findings.append(finding("ERROR", "EXTRA_REQ", f"requirement {rid} is not in domain {heading!r}"))
            for r in parsed["requirements"]:
                if r["rating"] not in ratings and not (move and not r["rating"]):
                    findings.append(finding("ERROR", "BAD_RATING", f"{r['req_id']}: rating {r['rating']!r} not in {sorted(ratings)}", r["req_id"]))
                if len(r["current_state"].split()) > max_words:
                    findings.append(finding("WARN", "LONG_CURRENT_STATE",
                                            f"{r['req_id']}: Current State is {len(r['current_state'].split())} words (max {max_words})", r["req_id"]))
    elif block == "migration":
        mig = _migration_entry(blocks, heading)
        intro = blocks.get("migration_intro", {})
        if mig is None and normalise_heading(heading) != normalise_heading(intro.get("heading") or ""):
            findings.append(finding("ERROR", "UNKNOWN_HEADING", f"{heading!r} is not a 4.x subsection heading in the template"))
    else:
        allowed = _heading_for(blocks, block)
        if normalise_heading(heading) != normalise_heading(allowed):
            findings.append(finding("ERROR", "UNKNOWN_HEADING", f"{heading!r} is not the {block!r} heading {allowed!r}"))

    # Sections: every required ## heading present, and no ## heading the build would not know where to put.
    if block in REQUIRED_SECTIONS:
        required = REQUIRED_SECTIONS[block] + ([] if move else ["Evidence"])
        allowed_sections = set(required) | {"Evidence"}
        table_sections: set[str] = set()
        if block == "domain" and dom is not None:
            allowed_sections |= set(dom.get("tables", {}))
            table_sections |= set(TABLE_SECTIONS["domain"])
            table_sections |= set(dom.get("tables", {}))
        elif block == "migration":
            allowed_sections.add("Summary")
            if mig is not None:
                if mig.get("table"):
                    allowed_sections.add("Table")
                    table_sections.add("Table")
                if (mig.get("bullets") or 0) > 0:
                    allowed_sections.add("Findings")
                if (mig.get("note_paragraphs") or 0) > 0:
                    allowed_sections.add("Notes")
        else:
            allowed_sections.add("Summary")
            table_sections |= set(TABLE_SECTIONS.get(block, ()))
        if block == "domain":
            allowed_sections.add("Discovery Notes")
        present = parsed.get("order", [])
        for name in required:
            if name not in present:
                findings.append(finding("ERROR", "MISSING_SECTION", f"section '## {name}' is missing (a {block} file needs {', '.join(required)})"))
        for name in present:
            if name not in allowed_sections:
                findings.append(finding("ERROR", "UNKNOWN_SECTION",
                                        f"section '## {name}' is not part of a {block} block; expected {', '.join(sorted(allowed_sections))}"))
        if block == "migration" and mig is not None and "Summary" in present and mig.get("intro_paragraphs") is None:
            findings.append(finding("ERROR", "UNKNOWN_SECTION",
                                    f"section '## Summary' is not part of a {block} block; expected {', '.join(sorted(allowed_sections))}"))
        seen_sections: set[str] = set()
        for name in present:
            if name in seen_sections:
                findings.append(finding("ERROR", "DUPLICATE_SECTION", f"section '## {name}' appears more than once"))
            seen_sections.add(name)

        # Table shape: every section that must be a table holds table rows, and
        # every table row (and its header) has exactly the template's columns.
        for name in present:
            if name == "Evidence":
                continue
            if name in table_sections and name not in parsed.get("tables", {}):
                if name != "Requirements" or not parsed.get("requirements"):
                    findings.append(finding("ERROR", "BAD_TABLE",
                                            f"section '## {name}' must be a table (bullets or prose there are not)"))
            for name_t, rows in parsed.get("tables", {}).items():
                if name_t == "Evidence" or name_t not in present:
                    continue
                expected = _expected_columns(blocks, block, heading, name_t)
                if expected is None:
                    continue
                header = parsed.get("table_headers", {}).get(name_t)
                if header is not None and len(header) != expected:
                    findings.append(finding("ERROR", "BAD_COLUMNS",
                                            f"section '## {name_t}' header has {len(header)} columns; the template has {expected} ({', '.join(header)})"))
                for n, cells in enumerate(rows, start=1):
                    if len(cells) != expected:
                        findings.append(finding("ERROR", "BAD_COLUMNS",
                                                f"section '## {name_t}' row {n} has {len(cells)} columns; the template has {expected} ({', '.join(cells)})"))

        # Move mode: an extra table the template ships for this domain (hosts, accounts) that the file
        # leaves out keeps its bracketed placeholder rows in the document.
        if move and block == "domain" and dom is not None:
            for name in dom.get("tables", {}):
                if name not in parsed.get("tables", {}):
                    findings.append(finding("WARN", "MISSING_TABLE",
                                            f"section '## {name}' is missing; its placeholder rows stay in the document"))

        # Notes under a table (template v1.3): one optional plain paragraph, never bullets.
        for name in ("Discovery Notes", "Notes"):
            if name not in present:
                continue
            paras = parsed.get("paragraphs", {}).get(name, [])
            if name in parsed.get("bullets", {}) or name in parsed.get("tables", {}) or len(paras) != 1:
                findings.append(finding("ERROR", "NOT_ONE_PARAGRAPH",
                                        f"section '## {name}' must be one short paragraph (no bullets, tables or several paragraphs); "
                                        "it fills the optional note under the table"))

    # Evidence traceability: every rendered statement needs a non-empty row.
    evidence = parsed.get("evidence", {})
    for key, _text in section_file.rendered_statements(parsed):
        ids = evidence.get(key)
        if not move and (not ids or not any(i.strip() for i in ids)):
            findings.append(finding("ERROR", "MISSING_EVIDENCE", f"rendered statement {key!r} has no non-empty row in the Evidence table"))

    rendered_keys = {k for k, _t in section_file.rendered_statements(parsed)}
    for key in evidence:
        if key not in rendered_keys:
            findings.append(finding("WARN", "UNUSED_EVIDENCE_ROW", f"Evidence row {key!r} matches no statement in the file (renamed or deleted?)"))

    # Evidence IDs must exist in the matrix (skip coverage: its evidence is capture files).
    if workspace and block != "coverage" and not move:
        eids = _matrix_eids(workspace)
        if eids is None:
            findings.append(finding("WARN", "NO_MATRIX",
                                    f"no evidence matrix at {Path(workspace) / 'csa-work' / 'evidence-matrix.csv'}; evidence IDs were not checked"))
        else:
            for _key, ids in evidence.items():
                for i in ids:
                    i = i.strip()
                    if i and i not in eids:
                        findings.append(finding("ERROR", "EVIDENCE_NOT_IN_MATRIX", f"{_key!r}: {i} is not in the evidence matrix"))

    # Hygiene on every rendered text (patterns shared with check_change).
    for key, text in section_file.rendered_statements(parsed):
        if EID_RE.search(text):
            findings.append(finding("ERROR", "EID_IN_TEXT", f"{key!r}: evidence ID in rendered text; it belongs in the Evidence table", key))
        if STABLE_ID_RE.search(text):
            findings.append(finding("ERROR", "STABLE_ID_IN_TEXT", f"{key!r}: stable ID (@H...) in rendered text", key))
        if MARKDOWN_RE.search(text):
            findings.append(finding("ERROR", "MARKDOWN_IN_TEXT", f"{key!r}: Markdown (**, backticks, >, #) in rendered text", key))

    if lint:
        # Reuse check_change's lint runner by giving it record-like objects.
        records = [type("R", (), {"edit_id": k, "text": t})() for k, t in section_file.rendered_statements(parsed)]
        findings += lint_findings(records, budget["section_words"])

    return {
        "file": str(path),
        "findings": findings,
        "errors": sum(f["level"] == "ERROR" for f in findings),
        "warnings": sum(f["level"] == "WARN" for f in findings),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--workspace", help="project root, for the evidence-matrix check")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-lint", action="store_true")
    a = ap.parse_args(argv)
    res = check(Path(a.path), a.workspace, lint=not a.no_lint)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"check-section: {Path(a.path).name}  errors: {res['errors']}  warnings: {res['warnings']}")
        for f in res["findings"]:
            print(f"  {f['level']:<5} {f['code']:<24} {f['edit_id'] or '-':<28} {f['message']}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
