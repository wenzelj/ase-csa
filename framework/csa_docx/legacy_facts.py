"""Split the blocks of an old-format CSA into typed facts.

A legacy paragraph often mixes an observed configuration, an assessment, a consequence and a
recommendation, and a dependency table row mixes impact and mitigation. The unit for requirement
mapping is one fact with its statement type. Qualifiers such as "not tested" are kept, and absolute
claims ("no X exists") are flagged so they can be qualified.

    python3 -m csa_docx.legacy_facts --legacy-dir <csa-work/legacy>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_SKIP_JOBS = ("skip", "controlled", "figure")

# Column roles from a table header, first match wins.
_COLUMN_ROLES = [
    (re.compile(r"\b(?:mitigation|recommend|remediation|action)", re.I), "recommendation"),
    (re.compile(r"\b(?:ready|readiness|score)", re.I), "legacy-score"),
    (re.compile(r"\b(?:impact|risk|consequence|survives)", re.I), "consequence"),
]
_SCOPE_HEADER = re.compile(r"(?:source|destination|applies to|server|node role|ip address|host)", re.I)

# Sentence rules, first match wins.
_RECOMMENDATION = re.compile(
    r"\b(recommend|should|must be|must\b|needs? to|required? (?:before|to)|is a prerequisite|prerequisite|deploy|"
    r"implement|establish|introduce|plan to|to be (?:deployed|implemented)|mitigat)", re.I)
_GAP = re.compile(
    r"\b(not (?:observed|confirmed|tested|captured|verified|established|evidenced|determined|known|assessed|available)|"
    r"unknown|unconfirmed|no evidence|could not be|requires? follow-up|follow-up required|to be confirmed|tbc)", re.I)
_CONSEQUENCE = re.compile(
    r"\b(drawbridge activation|on isolation|at activation|will (?:fail|break|stop|lose|halt)|"
    r"would (?:fail|break|stop|lose|halt)|breaks?|severs?|halting|fails? immediately|loss of|"
    r"at the moment of activation)", re.I)
_METHOD = re.compile(
    r"\b(discovery script|was captured|were captured|role-aware discovery|discovery output|txt outputs|"
    r"evidence files referenced)", re.I)
_ABSOLUTE = re.compile(
    r"\b(no [\w\- ]{0,40}(?:exists?|is present|is deployed|in place)|does not exist|there is no|none exist)", re.I)

_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9\"(])")


def _sentences(text: str) -> list[str]:
    text = " ".join((text or "").split())
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 3]


def _sentence_type(sentence: str, path: str) -> str:
    if _RECOMMENDATION.search(sentence):
        return "recommendation"
    if _GAP.search(sentence):
        return "gap"
    if _CONSEQUENCE.search(sentence):
        return "consequence"
    if _METHOD.search(sentence):
        return "method"
    if "Design and functionality expected" in path:
        return "design"
    return "observed"


def _column_role(header: str) -> str | None:
    for rx, role in _COLUMN_ROLES:
        if rx.search(header):
            return role
    return None


def split(blocks: list[dict], map_rows: list[dict]) -> list[dict]:
    mapping = {r["id"]: r for r in map_rows}
    facts: list[dict] = []

    def add(block, mrow, path, sentence, stype, subject="", column="", scope=""):
        qualifier = _GAP.search(sentence)
        facts.append({
            "fact_id": f"F-{len(facts) + 1:04d}", "legacy_id": block["id"], "path": path,
            "old_job": mrow["job"], "old_target": mrow["target"], "subject": subject, "column": column,
            "text": sentence, "stype": stype, "qualifier": qualifier.group(0) if qualifier else "",
            "absolute": bool(_ABSOLUTE.search(sentence)) and not qualifier, "scope": scope,
        })

    for b in blocks:
        m = mapping.get(b["id"])
        if not m or m["job"] in _SKIP_JOBS or m["target"] == "7" or b["kind"] in ("heading", "figure"):
            continue
        path = " > ".join(b["path"])
        header, cells = b.get("header") or [], b.get("cells") or []
        if b["kind"] == "table_row" and header and cells:
            pairs = list(zip(header, cells))
            subject = cells[0].strip()
            scope = "; ".join(f"{h}: {c.strip()}" for h, c in pairs[1:]
                              if c.strip() and _SCOPE_HEADER.match(h.strip()))
            for h, c in pairs[1:]:
                if not c.strip() or _SCOPE_HEADER.match(h.strip()):
                    continue
                role = _column_role(h)
                for s in _sentences(c):
                    stype = "evidence-ref" if m["job"] == "evidence-only" else (role or _sentence_type(s, path))
                    add(b, m, path, s, stype, subject=subject, column=h, scope=scope)
        else:
            for s in _sentences(b["text"]):
                stype = "evidence-ref" if m["job"] == "evidence-only" else _sentence_type(s, path)
                add(b, m, path, s, stype)
    return facts


def write(facts: list[dict], legacy_dir: Path) -> dict:
    legacy_dir = Path(legacy_dir)
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "facts.jsonl").write_text(
        "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts), encoding="utf-8")
    by_type: dict[str, int] = {}
    for f in facts:
        by_type[f["stype"]] = by_type.get(f["stype"], 0) + 1
    return {"status": "OK", "facts": len(facts), "by_type": by_type}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Split legacy blocks into typed facts.")
    ap.add_argument("--legacy-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    bpath, mpath = a.legacy_dir / "blocks.jsonl", a.legacy_dir / "map.csv"
    if not bpath.is_file() or not mpath.is_file():
        print(json.dumps({"status": "ERROR", "message": "blocks.jsonl and map.csv are needed; run csa convert --prepare"}))
        return 2
    blocks = [json.loads(line) for line in bpath.read_text(encoding="utf-8").splitlines() if line.strip()]
    with mpath.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    print(json.dumps(write(split(blocks, rows), a.legacy_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
