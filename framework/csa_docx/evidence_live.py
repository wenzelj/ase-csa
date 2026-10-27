"""The live evidence matrix: evidence-matrix.csv with each row's latest review applied.

The matrix CSV is append-only and every row is written with review_state "pending"; a person's or a
check's decision (reviewed / rejected) is appended to evidence-reviews.jsonl next to it. Every reader
that builds hosts, links, the graph or answer input must see that decision, so they all read the
matrix through here. Standard library only.

    rows = evidence_live.read(work_dir / "evidence-matrix.csv")      # review_state = latest review
    live = evidence_live.read(path, drop_rejected=True)              # rejected rows left out
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def reviews(matrix: Path) -> dict[str, str]:
    """{EVIDENCE_ID: latest state} from evidence-reviews.jsonl beside the matrix (last line wins)."""
    log = Path(matrix).with_name("evidence-reviews.jsonl")
    out: dict[str, str] = {}
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("evidence_id"):
                out[str(rec["evidence_id"]).upper()] = str(rec.get("state") or "")
    return out


def rejected(matrix: Path) -> set[str]:
    return {i for i, s in reviews(matrix).items() if s == "rejected"}


def apply(rows: list[dict], matrix: Path) -> list[dict]:
    """Rows with review_state set from the review log (rows are copied, not changed in place)."""
    rv = reviews(matrix)
    if not rv:
        return rows
    out = []
    for r in rows:
        st = rv.get(str(r.get("evidence_id") or "").upper())
        out.append({**r, "review_state": st} if st else r)
    return out


def read(matrix: Path, drop_rejected: bool = False) -> list[dict]:
    matrix = Path(matrix)
    if not matrix.is_file():
        return []
    with matrix.open(encoding="utf-8-sig", newline="") as fh:
        rows = apply(list(csv.DictReader(fh)), matrix)
    return [r for r in rows if r.get("review_state") != "rejected"] if drop_rejected else rows
