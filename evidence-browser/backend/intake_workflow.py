"""Evidence intake page: what came into the index, what became evidence, which open questions it may answer.

Read only. The page's actions are framework jobs (commands.py: ingest, intake, gap_check); candidate rows are
settled through evidence_matrix.py review (app.py)."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CANDIDATE = re.compile(r"^Possible answer to (DR-[A-Za-z0-9_.-]+):")
_EID = re.compile(r"^E-(\d+)$")


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _num(eid: str) -> int:
    m = _EID.match(eid or "")
    return int(m.group(1)) if m else -1


def _reviews(work: Path) -> dict[str, str]:
    """Latest review state per evidence ID (evidence-reviews.jsonl is append-only, so the last line wins)."""
    path = work / "evidence-reviews.jsonl"
    latest: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                latest[str(rec.get("evidence_id", "")).upper()] = rec.get("state", "")
    return latest


def _intake_ids(work: Path, record: dict | None) -> set[str]:
    """Evidence IDs the evidence agent appended for this intake (and the unread intakes it carries), read from the
    matrix audit log: appends whose context is `intake <record id>`. Capture rows from graph sync and gap-check
    candidates are not new evidence from the documents."""
    if not record:
        return set()
    contexts = {f"intake {rid}" for rid in [record.get("id", ""), *record.get("carried_from", [])] if rid}
    path = work / "evidence-matrix-audit.jsonl"
    ids: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("action") == "append" and str(rec.get("context", "")).strip() in contexts:
                ids.update(str(i).upper() for i in rec.get("ids", []))
    return ids


def _index(work: Path) -> dict[str, Any]:
    db = work / "discovery-index.sqlite"
    out: dict[str, Any] = {"built_at_utc": None, "files_by_status": {}, "complete": False}
    if not db.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='built_at_utc'").fetchone()
            out["built_at_utc"] = row[0] if row else None
            done = con.execute("SELECT value FROM meta WHERE key='complete'").fetchone()
            out["complete"] = bool(done and done[0] == "1")
            out["files_by_status"] = dict(con.execute("SELECT status, COUNT(*) FROM files GROUP BY status").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


def _count_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def snapshot(project: dict[str, str]) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    intake_dir = work / "intake"
    record = _json(intake_dir / "latest.json")
    index = _index(work)
    nothing_new_since = None
    if record and index["complete"] and index["built_at_utc"] and index["built_at_utc"] > record.get("built_at_utc", ""):
        nothing_new_since = record.get("built_at_utc")

    reviews = _reviews(work)
    rows: list[dict[str, str]] = []
    matrix = work / "evidence-matrix.csv"
    if matrix.is_file():
        with matrix.open(encoding="utf-8-sig", newline="") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "")] = by_status.get(r.get("status", ""), 0) + 1
    mine = _intake_ids(work, record)
    added = [r for r in rows if r.get("evidence_id", "").upper() in mine]
    pending = sum(1 for r in rows if reviews.get(r.get("evidence_id", "").upper(), r.get("review_state", "pending"))
                  in ("", "pending"))
    candidates = []
    for r in rows:
        m = _CANDIDATE.match(r.get("claim", ""))
        if r.get("status") == "UNCONFIRMED" and m and reviews.get(r.get("evidence_id", "").upper()) not in ("rejected", "reviewed"):
            candidates.append({**r, "dr_id": m.group(1)})

    summary = None
    if record and record.get("id"):
        path = intake_dir / f"{record['id']}.evidence.md"
        if path.is_file():
            summary = {"path": str(path), "text": path.read_text(encoding="utf-8"),
                       "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    stale_doc = _json(work / "draft" / "stale.json") or {}
    stale = sum(1 for s in stale_doc.get("sections", []) if s.get("status") not in ("REUSE", None, ""))

    return {"project_key": project.get("key"), "index": index, "intake": record, "nothing_new_since": nothing_new_since,
            "matrix": {"rows": len(rows), "by_status": by_status, "pending_review": pending, "added_since_intake": added},
            "graph": {"nodes": _count_rows(work / "graph" / "nodes.csv"), "edges": _count_rows(work / "graph" / "edges.csv")},
            "candidates": candidates, "gap_check": _json(intake_dir / "gap-check-latest.json"),
            "stale": stale, "agent_summary": summary}
