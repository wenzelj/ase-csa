"""The requirement-answer plan of one subsection, and its checks.

`csa-work/convert/<N>/answer-plan.csv` says, for each fact of the previous assessment, which requirement
it answers, what is being stated, on what evidence scope, where in the subsection it goes, how far it is
trusted, how it was reworded and which gap it raises. The evidence agent writes it, the writer writes
from it, and the ledger checks it.

    python3 -m csa_docx.answer_plan <answer-plan.csv> --target 3.5 [--req SEP-DNS-01 ...] [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

COLUMNS = ["legacy_ids", "req_id", "statement_type", "fact", "evidence_scope", "destination",
           "confidence", "transformation", "gap_generated"]

STATEMENT_TYPES = ("observed", "scope", "assessment", "gap", "consequence", "recommendation", "evidence-ref")
CONFIDENCE = ("high", "medium", "low", "n/a")

_DESTINATIONS = [re.compile(p) for p in (
    r"REQ SEP-[A-Z]+-\d+ / (?:Current State|Rating)",
    r"\d+\.\d+\.1 Discovery Information / .+",
    r"\d+\.\d+\.2 Drawbridge Impact",
    r"5\.\d .+",
    r"2\.1 Executive Summary",
    r"8 Discovery Required",
    r"MOVED \d+(?:\.\d+)?",
    r"roadmap(?: \(convert/parked\.md\))?",
    r"none",
)]
_GAP = re.compile(r"(DR-[A-Z]+-\d{2}) (.+)", re.DOTALL)
_ABSOLUTE = re.compile(r"\b(no [\w\- ]{0,40}(?:exists?|is present|in place)|does not exist|there is no)", re.IGNORECASE)
_SUBSECTION = re.compile(r"(\d+\.\d+)\.[12] ")
_NOT_IN_CSA = re.compile(r"(?:roadmap.*|none|MOVED .*)")

REQUIREMENT_MAP = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template"
                   / "references" / "requirement-map.csv")


class PlanRows(list):
    """The rows of a plan, with the CSV header it was read with."""
    columns: list[str] = COLUMNS


def load(path: Path | str) -> PlanRows:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = PlanRows({k: (v or "") for k, v in r.items() if k is not None} for r in reader)
        rows.columns = list(reader.fieldnames or [])
    return rows


def _valid_destination(dest: str) -> bool:
    return any(p.fullmatch(dest) for p in _DESTINATIONS)


def validate(rows, target: str, req_ids: list[str]) -> list[dict]:
    findings: list[dict] = []

    def add(level: str, code: str, n: int, message: str) -> None:
        findings.append({"level": level, "code": code, "row": n, "message": message})

    if list(getattr(rows, "columns", COLUMNS)) != COLUMNS:
        add("ERROR", "BAD_COLUMNS", 0, f"columns must be exactly: {', '.join(COLUMNS)}")
        return findings

    seen: dict[tuple[str, str], int] = {}
    answered: set[str] = set()
    rated: set[str] = set()
    for n, r in enumerate(rows, start=1):
        dest = r["destination"].strip()
        stype = r["statement_type"].strip()
        legacy = r["legacy_ids"].strip()
        bad = []
        if stype not in STATEMENT_TYPES:
            bad.append(f"statement_type {stype!r}")
        if r["confidence"].strip() not in CONFIDENCE:
            bad.append(f"confidence {r['confidence']!r}")
        if not _valid_destination(dest):
            bad.append(f"destination {dest!r}")
        gap = r["gap_generated"].strip()
        if gap and not _GAP.fullmatch(gap):
            bad.append(f"gap_generated {gap!r} (expected 'DR-XXX-01 <what to confirm>')")
        for b in bad:
            add("ERROR", "BAD_VALUE", n, f"bad {b}")

        if stype == "recommendation" and not _NOT_IN_CSA.fullmatch(dest):
            add("ERROR", "RECOMMENDATION_IN_CSA", n,
                "a recommendation never goes into a current-state field; use roadmap, none or MOVED")
        if (stype == "gap" or dest == "8 Discovery Required") and not gap:
            add("ERROR", "GAP_WITHOUT_DR", n, "a gap needs gap_generated: DR-XXX-01 <what to confirm>")

        is_req = dest.startswith("REQ ")
        is_discovery = bool(re.fullmatch(r"\d+\.\d+\.1 Discovery Information / .+", dest))
        if (is_req or is_discovery) and not r["evidence_scope"].strip():
            add("ERROR", "NO_SCOPE", n, "name the hosts and evidence type in evidence_scope")
        if (is_req or is_discovery) and _ABSOLUTE.search(r["fact"]) \
                and "qualify" not in r["transformation"] and "verified absence" not in r["transformation"]:
            add("ERROR", "ABSOLUTE_NOT_QUALIFIED", n,
                "an absolute ('no X exists') needs 'qualify' or 'verified absence' in transformation")

        if is_req:
            m = re.fullmatch(r"REQ (SEP-[A-Z]+-\d+) / (Current State|Rating)", dest)
            if m:
                (answered if m.group(2) == "Current State" else rated).add(m.group(1))
        sub = _SUBSECTION.match(dest)
        if sub and sub.group(1) != target:
            add("WARN", "OTHER_SUBSECTION", n, f"destination is in subsection {sub.group(1)}; use MOVED {sub.group(1)}")
        key = (legacy, dest)
        if legacy and key in seen:
            add("WARN", "DUPLICATE_ROW", n, f"same legacy_ids and destination as row {seen[key]}")
        seen.setdefault(key, n)

    for rid in req_ids:
        if rid not in answered:
            add("ERROR", "REQ_NOT_ANSWERED", 0, f"no 'REQ {rid} / Current State' row")
        if rid not in rated:
            add("ERROR", "REQ_NOT_RATED", 0, f"no 'REQ {rid} / Rating' row")
    return findings


def gaps(rows) -> list[dict]:
    out = []
    for r in rows:
        m = _GAP.fullmatch(r["gap_generated"].strip())
        if m:
            out.append({"dr_id": m.group(1), "text": m.group(2).strip(), "req_id": r["req_id"].strip(),
                        "fact": r["fact"], "evidence_scope": r["evidence_scope"]})
    return out


def requirement_ids(target: str, path: Path | None = None) -> list[str]:
    """Requirement IDs of the target's domain, from requirement-map.csv."""
    with Path(path or REQUIREMENT_MAP).open(newline="", encoding="utf-8") as fh:
        return [r["req_id"] for r in csv.DictReader(fh) if r["domain"] == target]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a requirement-answer plan.")
    ap.add_argument("plan", type=Path)
    ap.add_argument("--target", required=True)
    ap.add_argument("--req", action="append")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.plan.is_file():
        print(json.dumps({"status": "ERROR", "message": f"plan not found: {a.plan}"}))
        return 2
    req_ids = a.req or requirement_ids(a.target)
    findings = validate(load(a.plan), a.target, req_ids)
    errors = sum(f["level"] == "ERROR" for f in findings)
    warnings = len(findings) - errors
    if a.json:
        print(json.dumps({"status": "ERROR" if errors else "OK", "errors": errors, "warnings": warnings,
                          "findings": findings}, ensure_ascii=False))
    else:
        print(f"answer plan {a.plan.name} ({a.target}): {errors} error(s), {warnings} warning(s)")
        for f in findings:
            print(f"  {f['level']:<5} {f['code']:<24} row {f['row']:<3} {f['message']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
