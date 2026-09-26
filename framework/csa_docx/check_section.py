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

BLOCKS = ("domain", "executive-summary", "migration", "glossary", "coverage")
BLOCKS_JSON = (Path(__file__).resolve().parents[2]
               / "skills" / "csa-document-template" / "references" / "template-blocks.json")


def _load_blocks() -> dict:
    return json.loads(BLOCKS_JSON.read_text(encoding="utf-8"))


def _domain_for(blocks: dict, heading: str):
    for d in blocks.get("domains", []):
        if d.get("heading") == heading:
            return d
    return None


def _heading_for(blocks: dict, block: str) -> str | None:
    if block == "domain":
        return None  # many possible headings; validated per-domain below
    if block == "executive-summary":
        return blocks.get("executive_summary", {}).get("heading")
    if block == "glossary":
        return blocks.get("glossary", {}).get("heading")
    if block == "coverage":
        return blocks.get("coverage", {}).get("heading")
    if block == "migration":
        for m in blocks.get("migration", []):
            if m.get("heading"):
                return m.get("heading")
        return None
    return None


def _migration_headings(blocks: dict) -> set[str]:
    return {m.get("heading") for m in blocks.get("migration", []) if m.get("heading")}


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
    max_words = blocks.get("max_current_state_words", 50)
    ratings = set(blocks.get("ratings", []))

    if block not in BLOCKS:
        findings.append(finding("ERROR", "UNKNOWN_BLOCK", f"block {block!r} is not one of {', '.join(BLOCKS)}"))
    elif block == "domain":
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
            for rid in got:
                if rid not in exp_set:
                    findings.append(finding("ERROR", "EXTRA_REQ", f"requirement {rid} is not in domain {heading!r}"))
            for r in parsed["requirements"]:
                if r["rating"] not in ratings:
                    findings.append(finding("ERROR", "BAD_RATING", f"{r['req_id']}: rating {r['rating']!r} not in {sorted(ratings)}", r["req_id"]))
                if len(r["current_state"].split()) > max_words:
                    findings.append(finding("WARN", "LONG_CURRENT_STATE",
                                            f"{r['req_id']}: Current State is {len(r['current_state'].split())} words (max {max_words})", r["req_id"]))
    else:
        allowed = _heading_for(blocks, block)
        if block == "migration":
            allowed_set = _migration_headings(blocks)
            if heading not in allowed_set:
                findings.append(finding("ERROR", "UNKNOWN_HEADING", f"{heading!r} is not a 4.x subsection heading in the template"))
        elif heading != allowed:
            findings.append(finding("ERROR", "UNKNOWN_HEADING", f"{heading!r} is not the {block!r} heading {allowed!r}"))

    # Evidence traceability: every rendered statement needs a non-empty row.
    evidence = parsed.get("evidence", {})
    for key, _text in section_file.rendered_statements(parsed):
        ids = evidence.get(key)
        if not ids or not any(i.strip() for i in ids):
            findings.append(finding("ERROR", "MISSING_EVIDENCE", f"rendered statement {key!r} has no non-empty row in the Evidence table"))

    # Evidence IDs must exist in the matrix (skip coverage: its evidence is capture files).
    if workspace and block != "coverage":
        eids = _matrix_eids(workspace)
        if eids is not None:
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
        elif MARKDOWN_RE.search(text):
            findings.append(finding("ERROR", "MARKDOWN_IN_TEXT", f"{key!r}: Markdown (**, backticks, >, #) in rendered text", key))

    if lint:
        # Reuse check_change's lint runner by giving it record-like objects.
        records = [type("R", (), {"edit_id": k, "text": t})() for k, t in section_file.rendered_statements(parsed)]
        findings += lint_findings(records)

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
