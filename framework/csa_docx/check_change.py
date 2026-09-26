"""Check a ChangesCSA_*.md change file before approval.

    python -m csa_docx.check_change <change file> [--workspace <project root>] [--json]
                                    [--no-anchors] [--no-lint]

Run from .agents/framework. Exit code 1 when there is at least one ERROR;
warnings never fail the check. `csa check-change <N>` wraps this.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from csa_docx.change_parser import parse_change_records

FILENAME_RE = re.compile(r"^ChangesCSA_.+?_Section(?P<section>\d+)(?:_[^.]+)?\.md$")
ANY_ID_HEADING_RE = re.compile(r"^###\s+(?!REJECTED\b)(?P<id>[A-Za-z]*\d*-[A-Za-z]*\d+)\s+-\s+\S", re.M)
STATUS_RE = re.compile(r"^\*\*Status:\*\*", re.M)
STABLE_ID_RE = re.compile(r"@H[0-9][\w.\-]*")
ACTIONS = ("replace", "insert before", "insert after", "delete")


def finding(level: str, code: str, message: str, edit_id: str | None = None) -> dict:
    return {"level": level, "code": code, "edit_id": edit_id, "message": message}


def structure_findings(path: Path, text: str, records) -> list[dict]:
    out = []
    m = FILENAME_RE.match(path.name)
    section = m["section"] if m else None
    if not m:
        out.append(finding("ERROR", "FILENAME", f"{path.name} is not ChangesCSA_<App>_Section<N>.md or ..._Section<N>_<label>.md"))
    if not STATUS_RE.search(text):
        out.append(finding("ERROR", "NO_STATUS", "no **Status:** line"))
    valid = re.compile(rf"^S{section}-[EA]\d+$") if section else re.compile(r"^S\d+-[EA]\d+$")
    seen = set()
    for h in ANY_ID_HEADING_RE.finditer(text):
        eid = h["id"]
        if not valid.match(eid):
            out.append(finding("ERROR", "BAD_ID", f"{eid} is not S{section or '<N>'}-E<n> or S{section or '<N>'}-A<n>", eid))
        if eid in seen:
            out.append(finding("ERROR", "DUPLICATE_ID", f"{eid} is used more than once", eid))
        seen.add(eid)
    for r in records:
        if "@H" not in (r.where or ""):
            out.append(finding("ERROR", "WHERE_NOT_STABLE_ID", "Where: must be a stable ID (@H...) from lookupStableId", r.edit_id))
        action = (r.action or "").strip().lower()
        if not action.startswith(ACTIONS):
            out.append(finding("ERROR", "BAD_ACTION", f"Do: must start with Replace, Insert before, Insert after or Delete (got {r.action[:60]!r})", r.edit_id))
        elif not action.startswith("delete") and not (r.text or "").strip():
            out.append(finding("ERROR", "MISSING_TEXT", "no Text: for a Replace or Insert", r.edit_id))
    return out


def anchor_findings(records, workspace: str) -> list[dict]:
    from csa_docx import tools

    out, cache = [], {}
    for r in records:
        ids = sorted({i.rstrip(".-") for i in STABLE_ID_RE.findall(f"{r.where}\n{r.action}")})
        for sid in ids:
            if sid not in cache:
                cache[sid] = tools.lookupStableId(sid, workspace=workspace)
            res = cache[sid]
            if res.get("status") == "ERROR":
                return [finding("WARN", "ANCHOR_CHECK_UNAVAILABLE", f"anchors not checked: {str(res.get('message', ''))[:300]}")]
            if not res.get("unique_id"):
                out.append(finding("ERROR", "ANCHOR_UNRESOLVED",
                                   f"{sid} does not resolve to exactly one place (match_count {res.get('match_count')})", r.edit_id))
    return out


def hygiene_findings(records) -> list[dict]:
    return []  # S19 fills this in


def lint_findings(records) -> list[dict]:
    return []  # S20 fills this in


def check(path: Path, workspace: str | None = None, anchors: bool = True, lint: bool = True) -> dict:
    text = path.read_text(encoding="utf-8")
    records = parse_change_records(text)
    findings = structure_findings(path, text, records)
    if anchors:
        if workspace:
            findings += anchor_findings(records, workspace)
        else:
            findings.append(finding("INFO", "ANCHOR_CHECK_SKIPPED", "no --workspace given"))
    findings += hygiene_findings(records)
    if lint:
        findings += lint_findings(records)
    return {
        "file": str(path),
        "records": len(records),
        "findings": findings,
        "errors": sum(f["level"] == "ERROR" for f in findings),
        "warnings": sum(f["level"] == "WARN" for f in findings),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--workspace", help="project root, for resolving @H anchors")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-anchors", action="store_true")
    ap.add_argument("--no-lint", action="store_true")
    a = ap.parse_args(argv)
    res = check(Path(a.path), a.workspace, anchors=not a.no_anchors, lint=not a.no_lint)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"check-change: {Path(a.path).name}  records: {res['records']}  errors: {res['errors']}  warnings: {res['warnings']}")
        for f in res["findings"]:
            print(f"  {f['level']:<5} {f['code']:<22} {f['edit_id'] or '-':<8} {f['message']}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
