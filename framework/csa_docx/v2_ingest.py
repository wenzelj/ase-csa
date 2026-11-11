"""S589: `csa ingest` against the v2 repository (csa-work-v2/csa.sqlite).

The same six steps as the v1 command, with one DB behind all of them:

1. discovery index   -> `indexed_file`, `indexed_chunk`, `fts`. Each new or changed file is read by
                        `discovery_index.index_file` (imported, never copied) into a scratch index and its
                        chunks are copied across. What came in is one `intake_record` with one `intake_file`
                        row per new or changed file (`pending`) and per removed file (`removed`).
2. graph sync        -> `r.graph.refresh()` (graph_node, graph_edge, alias and entity are derived there).
3. evidence refresh  -> a row citing a removed file is rejected (`source removed`); a row whose quote is no
                        longer in a changed file gets an `evidence.refresh.recheck` review_event. The quote
                        check is `evidence_matrix.source_check`, run over the v2 index tables.
4. estate register   -> the DNS and time servers the active hosts in `r.hosts` are configured to use.
5. system model      -> none: the DB is the model (one `model.build.skipped` review_event).
6. stale subsections -> the answered subsections (`cards/*.answer.md`) citing an evidence row that
                        `r.evidence` no longer offers, or that this run listed for re-check.

    run_ingest(project_root, v2_dir, rebuild=False, sources=None, log=None) -> summary dict

Importable without a project: everything it needs is passed in. Standard library only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
from pathlib import Path

from csa_docx import evidence_stale
from csa_docx.estate import SERVICES, _short
from csa_docx.evidence_refresh import _cites, _em
from csa_docx.v2repo import Repo
from csa_docx.v2repo import graph as _graph    # noqa: F401  (adds `r.graph`)
from csa_docx.v2repo import intake as _intake  # noqa: F401  (adds `r.intake`)

ACTOR = "csa-ingest"
BY = "evidence-refresh"
MODEL_BUILD = "skipped (DB is the model)"
STEP_NAMES = ("discovery index", "graph sync", "evidence refresh", "estate register",
              "system model", "stale subsections")
SUMMARY_KEYS = ("indexed_files_added", "indexed_files_changed", "indexed_files_removed",
                "graph_nodes", "graph_edges", "evidence_rejected", "evidence_recheck",
                "estate_servers", "model_build", "stale_subsections", "pending_intake_files")
_DI_SCRIPT = (Path(__file__).resolve().parents[2] / "skills" / "csa-discovery-index"
              / "scripts" / "discovery_index.py")
# evidence_matrix.source_check reads the v1 index shape; these temp views give it the v2 tables.
_SOURCE_VIEWS = {
    "files": "SELECT rowid AS file_id, rel_path, NULL AS dup_of, 0 AS archived FROM indexed_file",
    "chunks_content": "SELECT id, text AS c0 FROM indexed_chunk",
    "chunk_map": "SELECT c.id AS chunk_id, f.rowid AS file_id, c.id AS line_start "
                 "FROM indexed_chunk c JOIN indexed_file f ON f.rel_path = c.rel_path",
}

_di_mod = None


def _di():
    """discovery_index.py, imported (never copied) for its file extraction."""
    global _di_mod
    if _di_mod is None:
        spec = importlib.util.spec_from_file_location("_csa_v2_ingest_discovery_index", _DI_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _di_mod = mod
    return _di_mod


# ------------------------------------------------------------------ step 1: index
def _walk(di, sources, root: Path, v2_dir: Path) -> dict[str, Path]:
    """{rel_path: Path} for every file under the sources, named relative to the project root (also for a
    source outside it), the way discovery_index names them."""
    found = {}
    root, v2_dir = root.resolve(), v2_dir.resolve()
    for src in sources:
        for dirpath, dirnames, filenames in os.walk(Path(src).resolve()):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if d not in di.SKIP_DIRS and (here / d) != v2_dir)
            for fname in sorted(filenames):
                if fname in di.SKIP_FILES or fname.startswith("~$"):
                    continue
                path = here / fname
                rel = path.relative_to(root).as_posix() if root in path.parents else \
                    Path(os.path.relpath(path, root)).as_posix()
                found[rel] = path
    return found


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _same_content(path: Path, stored: str | None) -> bool:
    """Whether the file still has the stored hash. A migrated row carries the v1 index's SHA-1 (40 hex
    characters) in the same column, so it is compared as SHA-1."""
    if not stored:
        return False
    return _digest(path, "sha1" if len(stored) == 40 else "sha256") == stored


def _not_read(di, path: Path, ext: str, size: int) -> bool:
    """The files discovery_index records but does not read: binary types, oversize text, empty files."""
    if ext in di.BINARY_EXT or size == 0:
        return True
    limit = di.MAX_CSV_BYTES if ext == ".csv" else di.MAX_TEXT_BYTES
    return size > limit and ext not in (".xlsx", ".docx", ".pdf", ".xml", ".html", ".htm")


def _file_chunks(di, scratch, path: Path) -> list[tuple[str, str]]:
    """[(heading, text)] for one file, extracted by `discovery_index.index_file` into the scratch index."""
    ext = path.suffix.lower()
    try:
        st = path.stat()
    except OSError:
        return []
    if _not_read(di, path, ext, st.st_size):
        return []
    fid = scratch.execute("INSERT INTO files(rel_path, ext, size, mtime) VALUES(?,?,?,?)",
                          (str(path), ext, st.st_size, st.st_mtime)).lastrowid
    try:
        di.index_file(scratch, fid, path, ext, path.name)
        out = [(f"lines {a}-{b}", text) for a, b, text in scratch.execute(
            "SELECT m.line_start, m.line_end, c.content FROM chunk_map m JOIN chunks c ON c.rowid = m.chunk_id "
            "WHERE m.file_id=? ORDER BY m.chunk_id", (fid,))]
    except Exception:                      # one unreadable file never stops the run (as in discovery_index)
        out = []
    di.drop_content(scratch, fid)
    scratch.execute("DELETE FROM files WHERE file_id=?", (fid,))
    return out


def _allow_removed_status(con) -> None:
    """`intake_file.status` also takes `removed` (a file that left the source set). A table created from
    schema.sql allows only pending / processed / failed, so the CHECK is widened once, keeping every row."""
    sql = (con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='intake_file'")
           .fetchone() or ("",))[0] or ""
    if "'removed'" in sql or "'failed')" not in sql:
        return
    con.execute("ALTER TABLE intake_file RENAME TO _intake_file_v2_ingest")
    con.execute(sql.replace("'failed')", "'failed', 'removed')", 1))
    con.execute("INSERT INTO intake_file SELECT * FROM _intake_file_v2_ingest")
    con.execute("DROP TABLE _intake_file_v2_ingest")


def _drop_file(con, rel: str) -> None:
    con.execute("DELETE FROM fts WHERE rel_path=?", (rel,))
    con.execute("DELETE FROM indexed_chunk WHERE rel_path=?", (rel,))
    con.execute("DELETE FROM indexed_file WHERE rel_path=?", (rel,))


def _new_record(r: Repo, con, todo, shas) -> str:
    """One intake_record for the run; its files are pending (new or changed) or removed. Written here
    because `r.intake.start` creates `pending` rows only; the ID follows its convention."""
    ts = r._now()
    prefix = f"I-{ts[0:4]}{ts[5:7]}{ts[8:10]}-{ts.split('T')[1][:8].replace(':', '')}."
    top = 0
    for (existing,) in con.execute("SELECT id FROM intake_record WHERE id LIKE ?", (prefix + "%",)):
        top = max(top, int(existing.rsplit(".", 1)[1]))
    rid = f"{prefix}{top + 1}"
    con.execute("INSERT INTO intake_record (id, started_at, file_count) VALUES (?, ?, ?)", (rid, ts, len(todo)))
    for rel, status in todo:
        con.execute("INSERT INTO intake_file (record_id, rel_path, sha256, status) VALUES (?, ?, ?, ?)",
                    (rid, rel, shas.get(rel), status))
    r._audit(ACTOR, "intake.start", "intake_record", rid, "csa ingest")
    return rid


def _step_index(r: Repo, root: Path, v2_dir: Path, sources, rebuild: bool) -> dict:
    di = _di()
    current = _walk(di, sources, root, v2_dir)
    previous = dict(r.con.execute("SELECT rel_path, sha256 FROM indexed_file").fetchall())
    added = sorted(rel for rel in current if rel not in previous)
    changed = sorted(rel for rel in current if rel in previous and not _same_content(current[rel], previous[rel]))
    removed = sorted(rel for rel in previous if rel not in current)
    # A rebuild empties the index and reads every file again; the intake record still reports only real changes.
    redo = sorted(current) if rebuild else sorted(set(added) | set(changed))
    shas = {rel: _digest(current[rel], "sha256") for rel in redo}
    scratch = sqlite3.connect(":memory:")
    try:
        di.init_db(scratch)
        with r.tx() as con:
            if rebuild:
                con.execute("DELETE FROM fts")
                con.execute("DELETE FROM indexed_chunk")
                con.execute("DELETE FROM indexed_file")
            for rel in removed:
                _drop_file(con, rel)
            for rel in redo:
                path = current[rel]
                _drop_file(con, rel)
                con.execute("INSERT INTO indexed_file (rel_path, sha256, size, indexed_at) VALUES (?, ?, ?, ?)",
                            (rel, shas[rel], path.stat().st_size, r._now()))
                for heading, text in _file_chunks(di, scratch, path):
                    cur = con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES (?, ?, ?)",
                                      (rel, heading, text))
                    con.execute("INSERT INTO fts (chunk_id, rel_path, heading, text) VALUES (?, ?, ?, ?)",
                                (cur.lastrowid, rel, heading, text))
            record = None
            todo = [(rel, "pending") for rel in sorted(set(added) | set(changed))] + [(rel, "removed") for rel in removed]
            if removed:
                _allow_removed_status(con)
            if todo:
                record = _new_record(r, con, todo, shas)
            r._audit(ACTOR, "index.refresh", "indexed_file", "all",
                     f"added={len(added)} changed={len(changed)} removed={len(removed)} rebuild={int(rebuild)}")
    finally:
        scratch.close()
    return {"added": added, "changed": changed, "removed": removed, "record": record}


# ------------------------------------------------------------ step 3: evidence
def _source_check(r: Repo, em, row: dict) -> dict:
    """`evidence_matrix.source_check` (the existing quote check) for one v2 evidence row."""
    return em.source_check({"status": row["status"], "source_title": row["source_title"],
                            "evidence_excerpt": row["excerpt"]}, r.raw_con)


def _step_evidence(r: Repo, changes: dict) -> dict:
    """Inside `with r.tx():`. Rows on a removed file are rejected; VERIFIED rows whose quote is no longer
    in a changed file are listed for re-check."""
    removed, changed = changes["removed"], changes["changed"]
    out = {"checked": 0, "rejected": [], "recheck": []}
    if not removed and not changed:
        return out
    em = _em() if changed else None
    raw = r.raw_con
    for name, select in _SOURCE_VIEWS.items():
        raw.execute(f"CREATE TEMP VIEW IF NOT EXISTS {name} AS {select}")
    try:
        for row in r.evidence.list():
            if row["review_state"] == "rejected":
                continue
            gone = next((rel for rel in removed if _cites(row, rel)), None)
            if gone:
                out["checked"] += 1
                r.evidence.reject(row["id"], by=BY, note="source removed")
                out["rejected"].append(row["id"])
                continue
            rel = next((rel for rel in changed if _cites(row, rel)), None)
            if not rel or row["status"] != "VERIFIED":
                continue
            out["checked"] += 1
            verdict = _source_check(r, em, row).get("verdict")
            if verdict in ("SOURCE_MISMATCH", "SOURCE_NOT_FOUND"):
                r.review_event().append(BY, "evidence.refresh.recheck", "evidence", row["id"],
                                        f"quote no longer in the changed file ({verdict}): {rel}")
                out["recheck"].append(row["id"])
    finally:
        for name in _SOURCE_VIEWS:
            raw.execute(f"DROP VIEW IF EXISTS temp.{name}")
    return out


# ------------------------------------------------------------- step 4: estate
def estate_servers(r: Repo) -> list[str]:
    """The DNS and time servers the active hosts in `r.hosts` are configured to use: one name per server
    (the short host name, as in the estate register), from the hosts' dns / time service rows."""
    active = {h["name"] for h in r.hosts.list(status="active")}
    out = set()
    for client, provider, service in r.con.execute(
            "SELECT host, provider_host, name FROM service WHERE provider_host IS NOT NULL AND provider_host != ''"):
        if client in active and (service or "").lower() in SERVICES:
            out.add(_short(provider))
    return sorted(out)


# --------------------------------------------------------------- step 6: stale
def stale_subsections(r: Repo, v2_dir, recheck=()) -> dict[str, list[str]]:
    """{sheet key: [evidence IDs]} for every answered subsection (`cards/<KEY>.answer.md`) that cites a row
    `r.evidence` no longer offers (rejected, or not in the table) or one listed for re-check."""
    state = {row["id"]: row["review_state"] for row in r.evidence.list()}
    recheck = set(recheck)
    out = {}
    cards = Path(v2_dir) / "cards"
    for f in sorted(cards.glob("*.answer.md")) if cards.is_dir() else []:
        key = f.name.split(".")[0]
        if key in evidence_stale._SKIP:
            continue
        cited = sorted(set(evidence_stale._EID.findall(f.read_text(encoding="utf-8"))), key=lambda s: int(s[2:]))
        bad = [i for i in cited if state.get(i, "rejected") == "rejected" or i in recheck]
        if bad:
            out[key] = bad
    return out


# ------------------------------------------------------------------- the run
def default_sources(project_root) -> list[Path]:
    """`<project_root>/Discovery Data` when it exists, else the project root."""
    dd = Path(project_root) / "Discovery Data"
    return [dd if dd.is_dir() else Path(project_root)]


def run_ingest(project_root, v2_dir, rebuild: bool = False, sources=None, log=None) -> dict:
    """The six steps against `<v2_dir>/csa.sqlite`; returns the summary dict (SUMMARY_KEYS).

    `sources`: the evidence folders to index (default: `default_sources(project_root)`). A missing source
    folder raises FileNotFoundError before anything is changed, so a disconnected share never looks like
    the removal of the whole evidence set. `log(step_no, step_name, line)` is called once per step.
    """
    root, v2_dir = Path(project_root), Path(v2_dir)
    sources = [Path(s) for s in (sources if sources is not None else default_sources(root))]
    missing = [str(s) for s in sources if not s.is_dir()]
    if missing:
        raise FileNotFoundError("evidence source folder(s) missing; nothing was changed: " + "; ".join(missing))
    say = log or (lambda *_a: None)
    r = Repo(v2_dir)
    try:
        ch = _step_index(r, root, v2_dir, sources, rebuild)
        say(1, STEP_NAMES[0], f"{len(ch['added'])} added, {len(ch['changed'])} changed, {len(ch['removed'])} removed")
        with r.tx():
            g = r.graph.refresh(actor=ACTOR)
        say(2, STEP_NAMES[1], f"{g['graph_node']} nodes, {g['graph_edge']} edges")
        with r.tx():
            ev = _step_evidence(r, ch)
            if ev["rejected"]:                       # a rejected row no longer supports a graph link
                g = r.graph.refresh(actor=ACTOR)
            say(3, STEP_NAMES[2], f"Re-checked {ev['checked']} row(s); {len(ev['rejected'])} retired; "
                                  f"{len(ev['recheck'])} to re-check in intake")
            servers = estate_servers(r)
            say(4, STEP_NAMES[3], f"{len(servers)} servers")
            r.review_event().append(ACTOR, "model.build.skipped", "model", "csa.sqlite", "the DB is the model")
            say(5, STEP_NAMES[4], MODEL_BUILD)
        stale = stale_subsections(r, v2_dir, ev["recheck"])
        say(6, STEP_NAMES[5], f"{len(stale)} answered subsection(s) cite evidence that changed"
                              + (f": {', '.join(stale)}" if stale else ""))
        pending = r.con.execute("SELECT COUNT(DISTINCT rel_path) FROM intake_file WHERE status='pending' "
                            "AND rel_path IN (SELECT rel_path FROM indexed_file)").fetchone()[0]
        return {
            "indexed_files_added": len(ch["added"]),
            "indexed_files_changed": len(ch["changed"]),
            "indexed_files_removed": len(ch["removed"]),
            "graph_nodes": g["graph_node"],
            "graph_edges": g["graph_edge"],
            "evidence_rejected": len(ev["rejected"]),
            "evidence_recheck": len(ev["recheck"]),
            "estate_servers": len(servers),
            "model_build": MODEL_BUILD,
            "stale_subsections": len(stale),
            "pending_intake_files": pending,
        }
    finally:
        r.close()
