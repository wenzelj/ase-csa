"""Facts already established by validated answer sheets, shared across sections.

The same facts (where time comes from, which DNS servers resolve, which hosts hold data) are answered again in
several sections. After a sheet validates, each fact line is appended to `<work_dir>/facts/facts.jsonl`:

    {fact, evidence_ids, hosts, section, question, basis, sheet_sha, added}

The next card for another section lists the ones that match its questions, so the answer agent can reuse them
(it still cites the evidence IDs). A fact whose evidence rows are no longer in the evidence matrix is never offered.

    python3 -m csa_docx.fact_store lookup <work_dir> --words "time ntp" --hosts HOST1 [--json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_WORD = re.compile(r"[a-z0-9]{4,}")


def store_path(work_dir: Path) -> Path:
    return Path(work_dir) / "facts" / "facts.jsonl"


def _read(work_dir: Path) -> list[dict]:
    path = store_path(work_dir)
    out: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def _matrix_ids(work_dir: Path) -> set[str]:
    path = Path(work_dir) / "evidence-matrix.csv"
    if not path.is_file():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {r.get("evidence_id", "").upper() for r in csv.DictReader(fh)}


def _hosts(fact: dict) -> list[str]:
    found = _HOST.findall(fact.get("text", "")) + _HOST.findall(fact.get("scope", ""))
    return sorted(set(found))


def add_from_sheet(work_dir: Path, sheet: Path, card_json: Path) -> int:
    """Append the sheet's facts; exact duplicates (same text and evidence IDs) are skipped. Returns how many were added."""
    from csa_docx import answer_sheet

    sheet, card_json = Path(sheet), Path(card_json)
    card = json.loads(card_json.read_text(encoding="utf-8"))
    raw = sheet.read_bytes()
    parsed = answer_sheet.parse(raw.decode("utf-8"))
    have = {(f["fact"], tuple(sorted(f["evidence_ids"]))) for f in _read(work_dir)}
    sha = hashlib.sha256(raw).hexdigest()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new: list[dict] = []
    for qid, block in parsed.items():
        for f in block.get("facts", []):
            ids = sorted(set(f.get("ids") or []))
            key = (f["text"], tuple(ids))
            if not ids or key in have:
                continue
            have.add(key)
            new.append({"fact": f["text"], "evidence_ids": ids, "hosts": _hosts(f), "section": card.get("key", ""),
                        "question": qid, "basis": f.get("basis", ""), "sheet_sha": sha, "added": now})
    if new:
        path = store_path(work_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for rec in new:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(new)


def lookup(work_dir: Path, words: set[str], hosts: set[str], limit: int = 8, exclude_section: str | None = None) -> list[dict]:
    """Facts that share a host or at least three topic words with the question, newest first. A fact whose evidence
    IDs are no longer all in the matrix is dropped; the same fact text is offered once."""
    live = _matrix_ids(work_dir)
    hosts = {h.upper() for h in hosts}
    words = {w.lower() for w in words}
    out: list[dict] = []
    seen: set[str] = set()
    for rec in sorted(_read(work_dir), key=lambda r: r.get("added", ""), reverse=True):
        if exclude_section and rec.get("section") == exclude_section:
            continue
        if not rec.get("evidence_ids") or any(i.upper() not in live for i in rec["evidence_ids"]):
            continue
        if rec["fact"] in seen:
            continue
        shares_host = bool(hosts & {h.upper() for h in rec.get("hosts", [])})
        if not shares_host and len(words & set(_WORD.findall(rec["fact"].lower()))) < 3:
            continue
        seen.add(rec["fact"])
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lookup")
    s.add_argument("work_dir", type=Path)
    s.add_argument("--words", default="")
    s.add_argument("--hosts", default="")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("add")
    s.add_argument("work_dir", type=Path)
    s.add_argument("sheet", type=Path)
    s.add_argument("--card", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "add":
        print(json.dumps({"status": "OK", "added": add_from_sheet(a.work_dir, a.sheet, a.card)}))
        return 0
    found = lookup(a.work_dir, set(a.words.split()), {h for h in a.hosts.replace(",", " ").split() if h}, a.limit)
    print(json.dumps(found, indent=2) if a.json else "\n".join(f"{r['section']} {r['question']}: {r['fact']}" for r in found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
