"""Read the active v2 store without consulting a project's old csa-work files."""

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


def active_db(workspace: Path | None = None) -> Path | None:
    configured = os.environ.get("CSA_WORK_DIR", "")
    work = Path(configured) if configured else (Path(workspace) / "csa-work-v2" if workspace else None)
    if work is None or work.name != "csa-work-v2":
        return None
    db = work / "csa.sqlite"
    if not db.is_file():
        raise FileNotFoundError(f"v2 store is missing: {db}")
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


def review_events(db: Path, subject_type: str = "evidence") -> list[dict]:
    """Read append-only V2 review history for a subject type."""
    with closing(connection(db)) as con:
        return [dict(row) for row in con.execute(
            "SELECT id,ts,actor,action,subject_type,subject_id,note FROM review_event "
            "WHERE subject_type=? ORDER BY id", (subject_type,))]


def matrix_command(db: Path, args: list[str], workspace: Path | None = None) -> dict:
    """Reuse the established matrix ranking for v2 read commands via a fresh temporary snapshot."""
    if not args or args[0] not in {"lookup", "get", "stats"}:
        return {"status": "ERROR", "code": "V2_COMMAND_UNAVAILABLE",
                "message": "this evidence command has no v2 implementation; old csa-work was not used"}
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
