"""Evidence intake page: what came into the index, what became evidence, which open questions it may answer.

Read only. The page's actions are framework jobs (commands.py: ingest, intake, gap_check); discovery leads are
settled through the append-only lead review API (app.py)."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))
from csa_docx import leads as lead_store
from csa_docx import modelstore

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


def _review_records(work: Path) -> dict[str, dict[str, Any]]:
    path = work / "evidence-reviews.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            latest[str(rec.get("evidence_id", "")).upper()] = rec
    return latest


def _leads(work: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows, row_errors, _ = lead_store._read_jsonl(work / "intake" / "leads.jsonl")
    reviews, review_errors, _ = lead_store._read_jsonl(work / "intake" / "leads-reviews.jsonl")
    if row_errors or review_errors:
        raise ValueError(f"Malformed lead store: {row_errors + review_errors}")
    overlaid = lead_store._overlay(rows, reviews)
    counts: dict[str, int] = {state: 0 for state in sorted(lead_store.STATES)}
    for row in overlaid:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return [row for row in overlaid if row["state"] == "open"], counts


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


def _last_sync(work: Path) -> dict[str, Any] | None:
    """The newest graph sync report (graph-audit.jsonl): did the host files rebuild?"""
    path = work / "graph-audit.jsonl"
    if not path.is_file():
        return None
    with path.open("rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 65536))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("action") == "sync":
            rep = rec.get("report") or {}
            return {"at": rec.get("ts", ""), "status": rep.get("status", ""), "hosts_index": rep.get("hosts_index", ""),
                    "merged_nodes": rep.get("merged_nodes", [])}
    return None


def _sync_health(work: Path) -> dict[str, Any]:
    """Are the host files current with the evidence? The last sync must have rebuilt them, and the per-host
    evidence file must be no older than the matrix and the review log."""
    last = _last_sync(work)
    matrix, reviews_log = work / "evidence-matrix.csv", work / "evidence-reviews.jsonl"
    per_host = work / "hosts" / "evidence_hosts.csv"
    newest = max((f.stat().st_mtime for f in (matrix, reviews_log) if f.is_file()), default=0)
    behind = bool(newest) and (not per_host.is_file() or per_host.stat().st_mtime + 1 < newest)
    failed = bool(last) and last["status"] != "OK"
    return {"ok": not failed and not behind, "failed": failed, "behind": behind, "last": last}


def _hosts_to_classify(work: Path, rejected: set[str]) -> list[dict[str, str]]:
    """Register hosts that only the evidence names (no capture, no inventory, no role): they need a role,
    site and scope (roles.csv or an inventory) before the CSA can group them."""
    out = []
    path = work / "hosts" / "hosts.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            src = [x for x in (r.get("sources") or "").split(";") if x]
            ev = [x for x in src if _EID.match(x) and x.upper() not in rejected]
            if r.get("capture") or r.get("role") or not ev or len(ev) != len(src):
                continue
            out.append({"host": r["host"], "ips": r.get("ips", ""), "evidence_ids": ";".join(ev)})
    return out


def _snapshot_v2(project: dict[str, str], work: Path, db: Path) -> dict[str, Any]:
    """Read the V2 intake store without falling back to the legacy file tree.

    V2 keeps intake, evidence, leads and graph state in ``csa.sqlite``.  The
    intake page still uses the historical snapshot shape, so this adapter
    deliberately translates the read-only tables into that shape rather than
    teaching the page about two storage formats.
    """
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        indexed = con.execute("SELECT COUNT(*) AS n, MAX(indexed_at) AS latest FROM indexed_file").fetchone()
        statuses = {row[0]: row[1] for row in con.execute(
            "SELECT 'indexed', COUNT(*) FROM indexed_file")}
        records = con.execute(
            "SELECT id, started_at, finished_at, file_count, row_count "
            "FROM intake_record ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1").fetchone()

        record = None
        if records:
            files = [dict(row) for row in con.execute(
                "SELECT rel_path, status, error FROM intake_file WHERE record_id=? ORDER BY rel_path",
                (records["id"],))]
            added = [{"rel_path": row["rel_path"], "status": "indexed",
                      "reason": "", "source_class": ""}
                     for row in files if row["status"] == "processed"]
            unreadable = [{"rel_path": row["rel_path"], """reason""": row["error"] or "not processed"}
                          for row in files if row["status"] == "failed"]
            record = {"id": records["id"], "built_at_utc": records["finished_at"] or records["started_at"],
                      "added": added, "changed": [], "removed": [], "unreadable": unreadable,
                      "file_count": records["file_count"], "row_count": records["row_count"] or 0}

        evidence = [dict(row) for row in con.execute(
            "SELECT id AS evidence_id, area AS csa_area, question, claim, status, source_title, "
            "page_or_location, excerpt AS evidence_excerpt, confidence, gap_or_action, review_state "
            "FROM evidence ORDER BY id")]
        by_status: dict[str, int] = {}
        for row in evidence:
            by_status[row.get("status", "")] = by_status.get(row.get("status", ""), 0) + 1

        # V2 does not yet persist evidence-to-intake ownership.  Do not claim
        # rows were added by the latest run until that relation exists.
        leads = [dict(row) for row in con.execute(
            "SELECT id, question, searched_scope, state, evidence_ids FROM lead ORDER BY id")]
        open_leads = [{"lead_id": row["id"], "dr_id": "", "question": row["question"],
                       "excerpt": "", "source_ref": row["searched_scope"], "page_or_location": "",
                       "state": row["state"]}
                      for row in leads if row["state"] == "open"]
        lead_counts: dict[str, int] = {}
        for row in leads:
            lead_counts[row["state"]] = lead_counts.get(row["state"], 0) + 1

        hosts = con.execute("SELECT COUNT(*) FROM host").fetchone()[0]
        unnamed = con.execute("SELECT COUNT(*) FROM address WHERE owner_host IS NULL OR owner_host='' ").fetchone()[0]
        graph_nodes = con.execute("SELECT COUNT(*) FROM graph_node").fetchone()[0]
        graph_edges = con.execute("SELECT COUNT(*) FROM graph_edge").fetchone()[0]
        latest_gap = con.execute("SELECT id, ts, dr_id, text, leads_found FROM gap_check ORDER BY ts DESC LIMIT 1").fetchone()
        gap = None
        if latest_gap:
            gap = {"schema_version": 4, "checked_at": latest_gap["ts"], "questions": [], "affected": []}

        return {"project_key": project.get("key"),
                "index": {"built_at_utc": indexed["latest"], "files_by_status": statuses,
                          "complete": bool(indexed["n"])},
                "intake": record, "nothing_new_since": None,
                "model": {"status": "current", "changed_sources": []},
                "sync": {"ok": True, "failed": False, "behind": False, "last": None},
                "refresh": {"at": "", "retired": [], "recheck": []},
                "hosts": {"to_classify": [], "unnamed_addresses": unnamed},
                "matrix": {"rows": len(evidence), "evidence_rows": len(evidence), "raw_rows": len(evidence),
                           "not_found": sum(1 for row in evidence if row.get("status") == "NOT_FOUND"),
                           "legacy_candidate_tombstones": 0, "rejected": sum(1 for row in evidence if row.get("review_state") == "rejected"),
                           "by_status": by_status, "pending_review": sum(1 for row in evidence if row.get("review_state") in (None, "", "pending")),
                           "added_since_intake": []},
                "graph": {"nodes": graph_nodes, "edges": graph_edges},
                "leads": {"by_state": lead_counts}, "open_leads": open_leads,
                "gap_check": gap, "stale": 0, "agent_summary": None}
    finally:
        con.close()


def snapshot(project: dict[str, str]) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    db = work / "csa.sqlite"
    if work.name == "csa-work-v2" and db.is_file():
        return _snapshot_v2(project, work, db)
    intake_dir = work / "intake"
    record = _json(intake_dir / "latest.json")
    index = _index(work)
    nothing_new_since = None
    if record and index["complete"] and index["built_at_utc"] and index["built_at_utc"] > record.get("built_at_utc", ""):
        nothing_new_since = record.get("built_at_utc")

    review_records = _review_records(work)
    reviews = {evidence_id: rec.get("state", "") for evidence_id, rec in review_records.items()}
    rows: list[dict[str, str]] = []
    matrix = work / "evidence-matrix.csv"
    if matrix.is_file():
        with matrix.open(encoding="utf-8-sig", newline="") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]
    def legacy_candidate(row: dict[str, str]) -> bool:
        return (row.get("csa_area") == "gap_lookup" and row.get("status") == "UNCONFIRMED"
                and bool(_CANDIDATE.match(row.get("claim", ""))))

    live_rows = [r for r in rows if reviews.get(r.get("evidence_id", "").upper()) != "rejected"]
    evidence_rows = [r for r in live_rows if not legacy_candidate(r) and r.get("status") != "NOT_FOUND"]
    not_found = [r for r in live_rows if r.get("status") == "NOT_FOUND"]
    by_status: dict[str, int] = {}
    for r in evidence_rows:
        by_status[r.get("status", "")] = by_status.get(r.get("status", ""), 0) + 1
    mine = _intake_ids(work, record)
    added = [r for r in evidence_rows if r.get("evidence_id", "").upper() in mine]
    pending = sum(1 for r in evidence_rows if reviews.get(r.get("evidence_id", "").upper(), r.get("review_state", "pending"))
                  in ("", "pending"))
    open_leads, lead_counts = _leads(work)
    tombstones = sum(1 for r in rows if legacy_candidate(r)
                     and reviews.get(r.get("evidence_id", "").upper()) == "rejected"
                     and "migrated to lead L-" in str(review_records.get(r.get("evidence_id", "").upper(), {}).get("note", "")))

    summary = None
    if record and record.get("id"):
        path = intake_dir / f"{record['id']}.evidence.md"
        if path.is_file():
            summary = {"path": str(path), "text": path.read_text(encoding="utf-8"),
                       "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    stale_doc = _json(work / "draft" / "stale.json") or {}
    stale = sum(1 for s in stale_doc.get("sections", []) if s.get("status") not in ("REUSE", None, ""))

    rejected = {i for i, st in reviews.items() if st == "rejected"}
    refresh = _json(intake_dir / "refresh-latest.json") or {}
    recheck = [x for x in refresh.get("recheck", []) if str(x.get("evidence_id", "")).upper() not in rejected]
    unnamed = _count_rows(work / "hosts" / "addresses.csv")
    return {"project_key": project.get("key"), "index": index, "intake": record, "nothing_new_since": nothing_new_since,
            "model": modelstore.freshness(work),
            "sync": _sync_health(work), "refresh": {"at": refresh.get("at", ""), "retired": refresh.get("rejected", []),
                                                   "recheck": recheck},
            "hosts": {"to_classify": _hosts_to_classify(work, rejected), "unnamed_addresses": unnamed},
            "matrix": {"rows": len(evidence_rows), "evidence_rows": len(evidence_rows), "raw_rows": len(rows),
                       "not_found": len(not_found), "legacy_candidate_tombstones": tombstones,
                       "rejected": len(rejected), "by_status": by_status, "pending_review": pending, "added_since_intake": added},
            "graph": {"nodes": _count_rows(work / "graph" / "nodes.csv"), "edges": _count_rows(work / "graph" / "edges.csv")},
            "leads": {"by_state": lead_counts}, "open_leads": open_leads,
            "gap_check": _json(intake_dir / "gap-check-latest.json"),
            "stale": stale, "agent_summary": summary}
