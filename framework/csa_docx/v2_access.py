"""Read the active v2 store without consulting a project's old csa-work files.

Every read reports its route: `v1-native`, `v2-native` or `v2-compatibility-adapter` (`route()`). A V2 project never opens a csa-work/ file, and a V2 route never falls back to one."""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def _db_file(workspace: Path | None = None) -> Path | None:
    """The csa-work-v2 store's path (or None when not on a V2 route); it may not exist yet."""
    configured = os.environ.get("CSA_WORK_DIR", "")
    work = Path(configured) if configured else (Path(workspace) / "csa-work-v2" if workspace else None)
    if work is None or work.name != "csa-work-v2":
        return None
    return work / "csa.sqlite"


def active_db(workspace: Path | None = None) -> Path | None:
    db = _db_file(workspace)
    if db is None:
        return None
    if not db.is_file():
        raise FileNotFoundError(f"v2 store is missing: {db}; a V2 project never falls back to csa-work/")
    return db


def connection(db: Path):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def evidence_rows(db: Path) -> list[dict]:
    with closing(connection(db)) as con:
        rows = con.execute("SELECT id AS evidence_id, area AS csa_area, question, claim, status, "
                           "source_title, page_or_location, excerpt AS evidence_excerpt, confidence, "
                           "gap_or_action, review_state FROM evidence ORDER BY id").fetchall()
        return [dict(row) for row in rows]


def evidence_sources(db: Path) -> list[dict]:
    """Return V2 source fingerprints and intake status without opening legacy indexes."""
    with closing(connection(db)) as con:
        return [dict(row) for row in con.execute(
            "SELECT s.rel_path, s.sha256, s.indexed_at, "
            "COALESCE(i.status, 'indexed') AS intake_status "
            "FROM evidence_source s LEFT JOIN indexed_file i ON i.rel_path=s.rel_path ORDER BY s.rel_path")]


def evidence_provenance(db: Path, evidence_id: str | None = None) -> dict[str, dict]:
    """{evidence ID: provenance} for the rows a provenance repair has checked (S618).

    `state` is `canonical`, `ambiguous` or `unresolved`; `paths` are canonical
    `indexed_file.rel_path` values and are filled only for a canonical row, so an ambiguous or
    unresolved row can never be read as a resolved source. A store that has not been checked
    returns nothing."""
    with closing(connection(db)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_provenance'").fetchone():
            return {}
        sql = ("SELECT evidence_id, state, canonical_paths, candidates, original_source, reason, checked_at "
               "FROM evidence_provenance")
        rows = con.execute(sql + " WHERE evidence_id=?", (evidence_id,)) if evidence_id else con.execute(sql + " ORDER BY evidence_id")
        out = {}
        for row in rows:
            canonical = row["state"] == "canonical"
            out[row["evidence_id"]] = {
                "evidence_id": row["evidence_id"], "state": row["state"],
                "paths": json.loads(row["canonical_paths"] or "[]") if canonical else [],
                "candidates": json.loads(row["candidates"] or "[]"),
                "original_source": row["original_source"] or "", "reason": row["reason"] or "",
                "checked_at": row["checked_at"] or ""}
        return out


def source_provenance(db: Path, evidence_id: str, source_title: str | None) -> dict:
    """One row's provenance: the recorded one, or the same resolver run now for an unchecked row."""
    recorded = evidence_provenance(db, evidence_id).get(evidence_id)
    if recorded:
        return {**recorded, "recorded": True}
    from csa_docx import v2_cleanup
    with closing(connection(db)) as con:
        indexed = [row[0] for row in con.execute("SELECT rel_path FROM indexed_file ORDER BY rel_path")]
    found = v2_cleanup.resolve_source(source_title, indexed)
    return {"evidence_id": evidence_id, "state": found["state"], "paths": found["paths"],
            "candidates": found["candidates"], "original_source": source_title or "",
            "reason": found["reason"], "checked_at": "", "recorded": False}


def review_events(db: Path, subject_type: str = "evidence") -> list[dict]:
    """Read append-only V2 review history for a subject type."""
    with closing(connection(db)) as con:
        return [dict(row) for row in con.execute(
            "SELECT id,ts,actor,action,subject_type,subject_id,note FROM review_event "
            "WHERE subject_type=? ORDER BY id", (subject_type,))]


# ------------------------------------------------------------------ route inventory (S622)

REQUIRED_TABLES = ("evidence", "indexed_file", "indexed_chunk", "lead", "graph_node", "graph_edge",
                  "host", "address", "service", "flow")
ROUTE_LABELS = ("v1-native", "v2-native", "v2-compatibility-adapter")
ROUTE_STATES = ("v1", "v2-compatibility", "v2-quarantine", "v2-native")
ROUTE_STATE_LABELS = {
    "v1": "v1-native",
    "v2-compatibility": "v2-compatibility-adapter",
    "v2-quarantine": "v2-compatibility-adapter",
    "v2-native": "v2-native",
}


def store_revision(db: Path) -> dict:
    """Bounded, deterministic revision of one V2 store: per-table row counts plus the newest write
    timestamp SQLite knows (file change time, so it stays stable between reads)."""
    with closing(connection(db)) as con:
        names = sorted(name for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        tables = {}
        for name in names:
            tables[name] = {"rows": con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]}
        try:
            mtime = db.stat().st_mtime_ns
        except OSError:
            mtime = None
    return {"tables": tables, "modified_ns": mtime}


def missing_tables(db: Path) -> list[str]:
    """V2 route tables that are absent (or not yet migrated in). A non-empty list fails the route."""
    have = set()
    try:
        with closing(connection(db)) as con:
            have = {name for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    except (sqlite3.Error, OSError):
        have = set()
    return [name for name in REQUIRED_TABLES if name not in have]


def route(command: str, *, work_dir: Path | None = None, db: Path | None = None,
          adapter: bool = False, project: str = "", route_state: str = "") -> dict:
    """Route diagnostic for one command of one project.

    `route` is `v1-native`, `v2-native` or `v2-compatibility-adapter` (the V2 command still reaches
    its evidence through a matrix-shaped CSV, e.g. the section card and the answer validator). V2
    results carry the SQLite path and the database revision; a V2 store with a missing table or the
    missing store is `BLOCKED`, never a silent csa-work/ fallback."""
    work = work_dir or (Path(db).parent if db is not None else None)
    is_v2 = bool(work is not None and Path(work).name == "csa-work-v2")
    state = str(route_state or "").strip().lower()
    if state and state not in ROUTE_STATE_LABELS:
        return {"route": "v1-native" if not is_v2 else "v2-compatibility-adapter",
                "command": command, "project": project, "status": "ERROR",
                "code": "V2_ROUTE_STATE_INVALID",
                "message": f"unknown project route state {route_state!r}; expected one of {', '.join(ROUTE_STATES)}"}
    selected = ROUTE_STATE_LABELS[state] if state else ("v2-compatibility-adapter" if adapter else ("v2-native" if is_v2 else "v1-native"))
    out: dict = {"route": selected,
                 "route_state": state or ("v2-native" if is_v2 and selected == "v2-native" else
                                            "v2-compatibility" if selected == "v2-compatibility-adapter" else "v1"),
                 "command": command, "project": project}
    if state == "v2-quarantine":
        out["status"] = "QUARANTINED"
        out["warning"] = "project is quarantined; compatibility is explicit and native fallback is refused"
    elif state == "v2-compatibility":
        out["warning"] = "compatibility adapter selected explicitly; native V2 is not active"
    if is_v2:
        candidate = Path(db) if db is not None else _db_file(work)
        out["store"] = str(candidate)
        if candidate.is_file():
            out["revision"] = store_revision(candidate)
            gaps = missing_tables(candidate)
            out["missing_tables"] = gaps
            if gaps:
                out["status"] = "BLOCKED"
                out["message"] = ("missing V2 table(s) " + ", ".join(gaps) +
                                 "; no fallback to csa-work/ files")
        else:
            out["status"] = "BLOCKED"
            out["message"] = f"v2 store is missing: {candidate}; no fallback to csa-work/ files"
    elif adapter:
        out["status"] = "ERROR"
        out["message"] = "v2-compatibility-adapter is not a V1 route"
    return out


def matrix_command(db: Path, args: list[str], workspace: Path | None = None) -> dict:
    """Reuse the established matrix ranking for v2 read commands via a fresh temporary snapshot."""
    if not args or args[0] not in {"lookup", "get", "stats"}:
        return {"status": "ERROR", "code": "V2_COMMAND_UNAVAILABLE",
                "message": "this evidence command has no v2 implementation; old csa-work was not used"}
    gaps = missing_tables(db)
    if gaps:
        return {"status": "BLOCKED", "code": "V2_TABLES_MISSING",
                "message": "missing V2 table(s) " + ", ".join(gaps) + "; no fallback to csa-work/ files"}
    script = Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
    rows = evidence_rows(db)
    fields = ["evidence_id", "csa_area", "question", "claim", "status", "source_title",
              "source_version", "section", "page_or_location", "evidence_excerpt",
              "inference_reason", "confidence", "gap_or_action", "review_state"]
    with tempfile.TemporaryDirectory(prefix="csa-v2-matrix-") as folder:
        path = Path(folder) / "evidence-matrix.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows({**{key: "" for key in fields}, **row} for row in rows)
        proc = subprocess.run([sys.executable, str(script), "--workspace", str(workspace or db.parent.parent),
                               "--matrix", str(path), *args],
                              capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return {"status": "ERROR", "code": "V2_LOOKUP_FAILED", "message": (proc.stderr or proc.stdout)[-1000:]}
    if proc.returncode == 0 and result.get("matrix"):
        result["matrix"] = str(db)
    if "route" not in result:
        diag = route("ev", work_dir=workspace or db.parent, db=db, adapter=True)
        result["route"] = diag["route"]
        if diag.get("revision"):
            result["revision"] = diag["revision"]
    return result


def index_status(db: Path) -> dict:
    with closing(connection(db)) as con:
        count = lambda table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return {"status": "OK", "store": str(db), "indexed_files": count("indexed_file"),
                "text_chunks": count("indexed_chunk"), "entities": count("entity")}


def index_search(db: Path, terms: str, *, limit: int = 50, per_file: int = 1,
                 path_like: str = "", host: str = "", any_terms: bool = False) -> dict:
    words = re.findall(r"[\w.-]+", terms)
    if not words:
        return {"status": "ERROR", "code": "EMPTY_QUERY", "message": "query has no searchable terms"}
    query = (" OR " if any_terms else " AND ").join('"' + w.replace('"', '') + '"' for w in words)
    with closing(connection(db)) as con:
        sql = ("SELECT c.rel_path, c.heading, c.text, bm25(fts) AS score FROM fts "
               "JOIN indexed_chunk c ON c.id=fts.chunk_id WHERE fts MATCH ?")
        params: list = [query]
        if path_like:
            sql += " AND c.rel_path LIKE ?"; params.append(f"%{path_like}%")
        if host:
            sql += " AND (c.rel_path LIKE ? OR c.text LIKE ?)"; params.extend([f"%{host}%", f"%{host}%"])
        sql += " ORDER BY score LIMIT ?"; params.append(max(limit * max(per_file, 1) * 4, limit))
        rows = con.execute(sql, params).fetchall()
    hits, files = [], {}
    for row in rows:
        rel = row["rel_path"]
        if files.get(rel, 0) >= per_file:
            continue
        files[rel] = files.get(rel, 0) + 1
        excerpt = " ".join(row["text"].split())[:650]
        hits.append({"rel_path": rel, "source_title": rel, "source_version": "",
                     "page_or_location": row["heading"] or "indexed chunk", "evidence_excerpt": excerpt,
                     "score": round(row["score"], 2)})
        if len(hits) >= limit:
            break
    return {"status": "OK", "query": terms, "count": len(hits), "results": hits}
