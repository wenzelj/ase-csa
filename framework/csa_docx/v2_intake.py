"""S588: batched intake on the csa-work-v2 repository.

One model session handles a batch of files (`MAX_FILES`, default 5) instead of one file.
`build_batch` assembles the payload the model reads (indexed text chunks, the matrix rows and
hosts already known for each file, and the INTAKE mode rules). The model answers with one JSON
object per file. `apply_batch` validates every candidate row with evidence_matrix.py's quote
check (imported through `v2repo`, never copied), skips duplicates, inserts the survivors in a
single transaction, refreshes the graph once and marks each file processed or failed.

The model never writes the matrix or the graph itself.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .v2repo import Repo  # noqa: F401  (re-exported for callers)
from . import v2repo as _pkg
import csa_docx.v2repo.intake  # noqa: F401  # registers r.intake
import csa_docx.v2repo.graph  # noqa: F401  # registers r.graph

MAX_FILES = 5  # files per model session; tune here only

_AGENT_FILE = Path(__file__).resolve().parents[2] / "csa-evidence-investigator-agent.md"
_ROW_FIELDS = ("claim", "source_title", "page_or_location", "excerpt", "area", "confidence",
               "gap_or_action", "status", "question")
_STATUSES = ("VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND")


def batches(file_rel_paths, max_files: int = MAX_FILES) -> list[list[str]]:
    """Split a list of rel_paths into batches of at most `max_files`."""
    paths = list(file_rel_paths)
    n = max(1, int(max_files))
    return [paths[i:i + n] for i in range(0, len(paths), n)]


def intake_instructions() -> str:
    """The INTAKE mode section of the investigator agent definition, verbatim."""
    text = _AGENT_FILE.read_text(encoding="utf-8")
    m = re.search(r"^## Intake mode.*?(?=^## )", text, re.S | re.M)
    return m.group(0).strip() if m else ""


def build_batch(record_id, file_rel_paths, max_files: int = MAX_FILES, *, repo) -> dict:
    """Payload for one model session: the first `max_files` of `file_rel_paths`.

    Use `batches()` to split a longer list; call this once per batch.
    """
    con = repo.con
    hosts = [h[0] for h in con.execute("SELECT name FROM host ORDER BY name")]
    files = []
    for rel in list(file_rel_paths)[:max(1, int(max_files))]:
        chunks = [t or "" for (t,) in con.execute(
            "SELECT text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (rel,))]
        base = rel.rsplit("/", 1)[-1]
        ids = [e[0] for e in con.execute(
            "SELECT id FROM evidence WHERE source_title LIKE ? ORDER BY id", (f"%{base}%",))]
        blob = "\n".join(chunks).lower()
        known = [h for h in hosts if h.lower() in blob]
        files.append({"rel_path": rel, "chunks": chunks,
                      "existing_evidence_ids": ids, "existing_hosts": known})
    return {"record_id": record_id, "files": files, "instructions": intake_instructions()}


# ---------------------------------------------------------------------------
def _quote_index(repo) -> sqlite3.Connection:
    """An in-memory index in the shape evidence_matrix.source_check reads, built from the
    repository's indexed_file / indexed_chunk mirror."""
    idx = sqlite3.connect(":memory:")
    idx.executescript(
        "create table files(file_id integer primary key, rel_path text, dup_of integer, archived integer default 0);"
        "create table chunk_map(chunk_id integer, file_id integer, line_start integer);"
        "create table chunks_content(id integer primary key, c0 text);")
    fid = 0
    for (rel,) in repo.con.execute("SELECT rel_path FROM indexed_file ORDER BY rel_path").fetchall():
        fid += 1
        idx.execute("insert into files(file_id, rel_path) values (?, ?)", (fid, rel))
        for n, (cid, text) in enumerate(repo.con.execute(
                "SELECT id, text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (rel,)).fetchall()):
            idx.execute("insert into chunks_content(id, c0) values (?, ?)", (cid, text))
            idx.execute("insert into chunk_map values (?, ?, ?)", (cid, fid, n))
    return idx


def _check_row(row: dict, idx) -> tuple[bool, str]:
    status = row.get("status") or "VERIFIED"
    if status not in _STATUSES:
        return False, f"unknown status {status!r}"
    if not str(row.get("claim") or "").strip():
        return False, "no claim"
    if not str(row.get("source_title") or "").strip():
        return False, "no source_title"
    if status != "VERIFIED":
        return True, ""  # rests on reasoning or a search scope, not one quoted source
    em = _pkg._EM
    if em is None:
        return False, "evidence_matrix.py quote check not importable"
    res = em.source_check({"status": "VERIFIED", "source_title": row["source_title"],
                           "evidence_excerpt": row.get("excerpt")}, idx)
    if res.get("verdict") == "SOURCE_OK":
        return True, ""
    detail = {k: v for k, v in res.items() if k != "verdict"}
    return False, f"{res.get('verdict')}: {detail}" if detail else str(res.get("verdict"))


def _parse(agent_output_json):
    """Return {rel_path: entry-or-error-string}, or raise ValueError when nothing is usable."""
    data = agent_output_json
    if isinstance(data, (str, bytes)):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        text = text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
        data = json.loads(fence.group(1) if fence else text)
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        data = data["files"]
    if isinstance(data, dict) and "rel_path" in data:
        data = [data]
    if not isinstance(data, list):
        raise ValueError("agent output must be a list of per-file objects (or an empty batch)")
    out = {}
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("rel_path"), str):
            out[item["rel_path"]] = item
    return out


def apply_batch(record_id, agent_output_json, *, repo, rel_paths=None) -> dict:
    """Validate and append one batch's agent output; returns the summary dict.

    `rel_paths` limits the batch to those files; by default every pending file of the record.
    """
    r = repo
    pending = [f["rel_path"] for f in r.intake.pending(record_id)]
    if rel_paths is not None:
        keep = set(rel_paths)
        pending = [p for p in pending if p in keep]
    summary = {"files_total": len(pending), "files_ok": 0, "files_failed": 0, "rows_added": 0,
               "rows_rejected": 0, "graph_nodes": 0, "graph_edges": 0,
               "rejected": [], "errors": {}}
    try:
        entries = _parse(agent_output_json)
        parse_error = None
    except (ValueError, TypeError) as e:
        entries, parse_error = {}, f"agent output is not usable JSON: {e}"
    idx = _quote_index(r)
    try:
        with r.tx():
            seen = {(c or "", s or "", p or "") for c, s, p in r.con.execute(
                "SELECT claim, source_title, page_or_location FROM evidence")}
            for rel in pending:
                entry = entries.get(rel)
                error = parse_error
                rows = None
                if error is None:
                    if entry is None:
                        error = "no output for this file"
                    elif not isinstance(entry.get("rows", []), list) or \
                            not isinstance(entry.get("graph_items", []), list):
                        error = "malformed output: rows and graph_items must be lists"
                    else:
                        rows = entry.get("rows", [])
                        if any(not isinstance(x, dict) for x in rows):
                            error = "malformed output: every row must be an object"
                if error is not None:
                    r.intake.complete_file(record_id, rel, error=error)
                    summary["files_failed"] += 1
                    summary["errors"][rel] = error
                    continue
                added = 0
                for row in rows:
                    ok, reason = _check_row(row, idx)
                    if not ok:
                        summary["rows_rejected"] += 1
                        summary["rejected"].append({"rel_path": rel, "claim": row.get("claim"),
                                                    "reason": reason})
                        continue
                    key = (row.get("claim") or "", row.get("source_title") or "",
                           row.get("page_or_location") or "")
                    if key in seen:
                        continue
                    seen.add(key)
                    r.evidence.create(
                        **{k: row.get(k) for k in _ROW_FIELDS if k != "status" and k in row},
                        status=row.get("status") or "VERIFIED",
                        actor="csa-evidence-investigator", note=f"intake {record_id} {rel}")
                    added += 1
                for item in entry.get("graph_items", []):
                    if isinstance(item, dict) and item.get("kind") == "host" and item.get("name"):
                        if not r.con.execute("SELECT 1 FROM host WHERE name=?", (item["name"],)).fetchone():
                            r.hosts.create(item["name"], role=item.get("role"), site=item.get("site"),
                                           os=item.get("os"), actor="csa-evidence-investigator",
                                           note=f"intake {record_id} {rel}")
                if r.con.execute("SELECT 1 FROM evidence_source WHERE rel_path=?", (rel,)).fetchone() is None:
                    sha = r.con.execute("SELECT sha256 FROM intake_file WHERE record_id=? AND rel_path=?",
                                        (record_id, rel)).fetchone()
                    r.con.execute("INSERT INTO evidence_source (rel_path, sha256, indexed_at) VALUES (?, ?, ?)",
                                  (rel, sha[0] if sha else None, r._now()))
                r.intake.complete_file(record_id, rel, rows_added=added)
                summary["files_ok"] += 1
                summary["rows_added"] += added
            counts = r.graph.refresh()
            summary["graph_nodes"] = counts["graph_node"]
            summary["graph_edges"] = counts["graph_edge"]
    finally:
        idx.close()
    return summary
