"""Reversible, hash-guarded cleanup packs for the V2 repository (S601).

The default selection is deliberately conservative: rejected evidence, retired leads,
and rejected/inactive application-scope rows.  A pack is a complete snapshot of the
selected rows and can therefore be validated or imported after a cleanup.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .v2repo import DB_NAME, Repo

TABLES = ("evidence", "lead", "application_scope", "review_event")
PREDICATE = (
    "evidence.review_state='rejected' OR lead.state IN ('retired','not_an_answer') "
    "OR application_scope.review_state='rejected' OR application_scope.active=0"
)

def _write_report(v2_dir, name, payload):
    path = Path(v2_dir) / "cleanup-packs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def cleanup_retired_evidence(v2_dir, retired_paths, *, dry_run=True):
    """Archive and optionally remove exact retired-CSA evidence matches.

    A basename is accepted only when it resolves to one indexed file; ambiguous
    matches are reported and never removed.
    """
    repo = Repo(v2_dir)
    try:
        indexed = [r[0] for r in repo.con.execute("SELECT rel_path FROM indexed_file")]
        wanted = {str(Path(p).name).lower() for p in retired_paths}
        candidates = []
        ambiguous = []
        for row in repo.con.execute("SELECT * FROM evidence ORDER BY id"):
            cols = [x[1] for x in repo.con.execute("PRAGMA table_info(evidence)")]
            item = dict(zip(cols, row)); source = item.get("source_title") or ""
            exact = source in retired_paths or any(source.startswith(p + ":") for p in retired_paths)
            basename = Path(source.split(":", 1)[0]).name.lower() in wanted
            matches = [p for p in indexed if Path(p).name.lower() == Path(source.split(":", 1)[0]).name.lower()]
            if (exact or (basename and len(matches) == 1)) and item.get("review_state") == "rejected": candidates.append(item)
            elif basename and len(matches) != 1: ambiguous.append(item["id"])
        result = {"status": "DRY-RUN" if dry_run else "OK", "selected": len(candidates),
                  "ambiguous": sorted(ambiguous), "rows": candidates,
                  "exact_retired_paths": list(retired_paths)}
        result["report"] = _write_report(v2_dir, "retired-evidence.json", result)
        if not dry_run:
            with repo.tx() as con:
                con.executemany("DELETE FROM evidence WHERE id=?", [(r["id"],) for r in candidates])
                repo._audit("csa-cleanup", "cleanup.retired-evidence", "evidence", "batch",
                            f"removed={len(candidates)} ambiguous={len(ambiguous)}")
        return result
    finally:
        repo.close()


def archive_migrated_leads(v2_dir, *, dry_run=True):
    """Export migrated DR leads and remove them, retaining V2 index leads."""
    repo = Repo(v2_dir)
    try:
        cols = [r[1] for r in repo.con.execute("PRAGMA table_info(lead)")]
        rows = [dict(zip(cols, r)) for r in repo.con.execute(
            "SELECT * FROM lead WHERE searched_scope LIKE 'DR-%' ORDER BY id")]
        result = {"status": "DRY-RUN" if dry_run else "OK", "migrated_count": len(rows),
                  "v2_count": repo.con.execute("SELECT COUNT(*) FROM lead WHERE searched_scope LIKE 'v2 discovery index:%'").fetchone()[0],
                  "rows": rows}
        result["report"] = _write_report(v2_dir, "migrated-leads.json", result)
        if not dry_run:
            with repo.tx() as con:
                con.executemany("DELETE FROM lead WHERE id=?", [(r["id"],) for r in rows])
                repo._audit("csa-cleanup", "cleanup.migrated-leads", "lead", "batch", str(len(rows)))
        return result
    finally:
        repo.close()


def repair_provenance(v2_dir, *, dry_run=True):
    """Canonicalise uniquely matched evidence source names against indexed_file."""
    repo = Repo(v2_dir)
    try:
        indexed = [r[0] for r in repo.con.execute("SELECT rel_path FROM indexed_file")]
        repaired, ambiguous, unresolved = [], [], []
        for eid, source in repo.con.execute("SELECT id,source_title FROM evidence"):
            if not source: continue
            base = Path(source.split(":", 1)[0]).name.lower()
            matches = [p for p in indexed if Path(p).name.lower() == base]
            if len(matches) == 1 and matches[0] != source:
                repaired.append((eid, source, matches[0]))
            elif len(matches) > 1: ambiguous.append(eid)
            elif not source.startswith("REVELOC_discovery_") and "/" not in source: unresolved.append(eid)
        result = {"status": "DRY-RUN" if dry_run else "OK", "repaired": len(repaired),
                  "ambiguous": len(ambiguous), "unresolved": len(unresolved),
                  "rows": [{"evidence_id": e, "from": a, "to": b} for e, a, b in repaired]}
        result["report"] = _write_report(v2_dir, "provenance-repair.json", result)
        if not dry_run:
            with repo.tx() as con:
                con.executemany("UPDATE evidence SET source_title=?, updated_at=? WHERE id=?",
                                [(b, repo._now(), e) for e, a, b in repaired])
                repo._audit("csa-cleanup", "cleanup.provenance", "evidence", "batch", json.dumps(result))
        return result
    finally:
        repo.close()


def db_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _rows(con, table):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    return cols, [dict(zip(cols, row)) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _selected(repo, application_key=None):
    con = repo.con
    evidence = [dict(zip([r[1] for r in con.execute("PRAGMA table_info(evidence)")], row))
                for row in con.execute("SELECT * FROM evidence WHERE review_state='rejected' ORDER BY id")]
    leads = [dict(zip([r[1] for r in con.execute("PRAGMA table_info(lead)")], row))
             for row in con.execute("SELECT * FROM lead WHERE state IN ('retired','not_an_answer') ORDER BY id")]
    scope_sql = "SELECT * FROM application_scope WHERE review_state='rejected' OR active=0"
    args = []
    if application_key:
        scope_sql += " AND application_key=?"
        args.append(application_key)
    scope = [dict(zip([r[1] for r in con.execute("PRAGMA table_info(application_scope)")], row))
             for row in con.execute(scope_sql + " ORDER BY application_key,host_name", args)]
    ev_ids = {r["id"] for r in evidence}
    lead_ids = {r["id"] for r in leads}
    scope_keys = {(r["application_key"], r["host_name"]) for r in scope}
    events = []
    for row in _rows(con, "review_event")[1]:
        subject = (row.get("subject_type"), row.get("subject_id"))
        if ((subject[0] == "evidence" and subject[1] in ev_ids) or
            (subject[0] == "lead" and subject[1] in lead_ids) or
            (subject[0] == "application_scope" and
             any(subject[1] == f"{a}:{h}" for a, h in scope_keys))):
            events.append(row)
    return {"evidence": evidence, "leads": leads, "application_scope": scope,
            "review_events": events}


def _migration_reference(v2_dir):
    for name in ("MIGRATION-REPORT.md", "MIGRATION-CLEANUP-AUDIT.md"):
        p = Path(v2_dir) / name
        if p.is_file():
            return str(p)
    return None


def create_pack(v2_dir, *, application_key=None, out=None, dry_run=True):
    """Create a cleanup manifest/pack.  This function never mutates the database."""
    v2_dir = Path(v2_dir)
    repo = Repo(v2_dir)
    try:
        selected = _selected(repo, application_key)
        digest = db_hash(v2_dir / DB_NAME)
    finally:
        repo.close()
    created = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    counts = {k: len(v) for k, v in selected.items()}
    pack = {"schema_version": 1, "kind": "csa-v2-cleanup-pack", "created_at": created,
            "database": str(v2_dir / DB_NAME), "database_sha256": digest,
            "selection_predicate": PREDICATE,
            "application_key": application_key,
            "migration_report_reference": _migration_reference(v2_dir),
            "row_counts": counts, "rows": selected,
            "rollback": {"validated": True, "method": "import rows with INSERT OR IGNORE"},
            "dry_run": bool(dry_run)}
    if out is None:
        out = v2_dir / "cleanup-packs" / f"{created}-cleanup.json"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "DRY_RUN" if dry_run else "READY", "pack": str(out),
            "database_sha256": digest, "row_counts": counts,
            "migration_report_reference": pack["migration_report_reference"]}


def validate_pack(pack_path):
    pack = json.loads(Path(pack_path).read_text(encoding="utf-8"))
    if pack.get("kind") != "csa-v2-cleanup-pack" or pack.get("schema_version") != 1:
        raise ValueError("invalid V2 cleanup pack")
    if pack.get("selection_predicate") != PREDICATE:
        raise ValueError("cleanup pack selection predicate is not recognised")
    for table in ("evidence", "leads", "application_scope", "review_events"):
        if table not in pack.get("rows", {}) or pack["row_counts"].get(table) != len(pack["rows"][table]):
            raise ValueError(f"cleanup pack row count mismatch: {table}")
    return pack


def apply_pack(v2_dir, pack_path):
    """Apply the selected cleanup only when the audited DB hash is unchanged."""
    pack = validate_pack(pack_path)
    db = Path(v2_dir) / DB_NAME
    actual = db_hash(db)
    if actual != pack["database_sha256"]:
        raise RuntimeError("cleanup refused: database changed since the cleanup audit")
    repo = Repo(v2_dir)
    try:
        with repo.tx() as con:
            eids = [r["id"] for r in pack["rows"]["evidence"]]
            lids = [r["id"] for r in pack["rows"]["leads"]]
            if eids:
                con.executemany("DELETE FROM evidence WHERE id=?", [(x,) for x in eids])
            if lids:
                con.executemany("DELETE FROM lead WHERE id=?", [(x,) for x in lids])
            for row in pack["rows"]["application_scope"]:
                con.execute("DELETE FROM application_scope WHERE application_key=? AND host_name=?",
                            (row["application_key"], row["host_name"]))
            repo._audit("csa-cleanup", "cleanup.apply", "cleanup_pack", str(pack_path),
                        json.dumps(pack["row_counts"], sort_keys=True))
    finally:
        repo.close()
    return {"status": "APPLIED", "pack": str(pack_path), "removed": pack["row_counts"],
            "rollback": "use the pack rows or the automatic V2 backup"}


def restore_pack(v2_dir, pack_path):
    """Restore exported rows into a DB; intended for rollback validation/recovery."""
    pack = validate_pack(pack_path)
    repo = Repo(v2_dir)
    try:
        with repo.tx() as con:
            for table, pack_name in (("evidence", "evidence"), ("lead", "leads")):
                rows = pack["rows"][pack_name]
                if not rows:
                    continue
                cols = list(rows[0]); marks = ",".join("?" for _ in cols)
                con.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})",
                                [tuple(r.get(c) for c in cols) for r in rows])
            for r in pack["rows"]["application_scope"]:
                cols = list(r); marks = ",".join("?" for _ in cols)
                con.execute(f"INSERT OR IGNORE INTO application_scope ({','.join(cols)}) VALUES ({marks})",
                            tuple(r.get(c) for c in cols))
            repo._audit("csa-cleanup", "cleanup.restore", "cleanup_pack", str(pack_path), "rollback import")
    finally:
        repo.close()
    return {"status": "RESTORED", "pack": str(pack_path)}
