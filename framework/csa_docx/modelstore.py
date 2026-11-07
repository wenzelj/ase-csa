"""The system model store: csa-work/model.sqlite (improvements/PLAN-system-model.md).

Two kinds of table. Derived tables are dropped and rebuilt by `build` from the files the existing extractors write, with
the files' own column names (a migration is a copy). Reviewed tables hold what a person decided or what is append-only;
they are created when missing and never dropped, and `build` refuses to run if one has fewer rows than before.

    python3 -m csa_docx.modelstore build|counts|export --work-dir <csa-work> [--project KEY]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = "model.sqlite"

#: derived table -> source file under csa-work (one row per source row, every source column kept as text)
SOURCES = {
    "host": "hosts/hosts.csv",
    "address": "hosts/addresses.csv",
    "service": "hosts/host_services.csv",
    "flow": "hosts/flows.csv",
    "host_link": "hosts/host_links.csv",
    "observation": "hosts/host_settings.csv",
    "host_fact": "hosts/host_facts.csv",
    "graph_node": "graph/nodes.csv",
    "graph_edge": "graph/edges.csv",
}
#: derived from hosts.csv: one row per host and capture it was seen in
COVERAGE = ("coverage", "hosts/hosts.csv")

#: reviewed tables: filled by later steps (parts import, evidence mirror, review import); created empty here
REVIEWED = {
    "review": ["subject_type", "subject_id", "state", "reviewer", "reviewed_on", "note"],
    "assign": ["subject_type", "subject_id", "value", "note"],
    "alias_edit": ["alias", "subject_type", "subject_id", "action", "note"],
    "application": ["application_id", "name", "purpose", "purpose_source", "basis", "data", "ord"],
    "application_part": ["application_id", "part_id", "role_in", "ord"],
    "chain": ["chain_id", "application_id", "function", "data", "ord"],
    "chain_step": ["chain_id", "step_no", "from_part", "to_part", "flows", "data"],
    "evidence": ["evidence_id"],
    "answered_fact": ["fact", "evidence_ids", "hosts", "basis", "section", "question", "kind", "sheet_sha", "added", "rec_hash"],
    "verdict": ["finding_id", "requirement", "run_id", "verdict", "note", "text", "evidence_ids", "added"],
}


def path(work_dir: Path) -> Path:
    return Path(work_dir) / DB


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rows(file: Path) -> tuple[list[str], list[list[str]]]:
    if not file.is_file():
        return [], []
    with file.open(newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        head = next(r, [])
        return head, [(row + [""] * (len(head) - len(row)))[:len(head)] for row in r if row]


def _make(con: sqlite3.Connection, table: str, cols: list[str], rows: list[list[str]], project: str) -> None:
    """``project`` is added as the first column unless the source already has one (its own values stay). The source's
    own columns are recorded in ``model_meta`` so an export gives the file back."""
    con.execute("CREATE TABLE IF NOT EXISTS model_meta (table_name TEXT PRIMARY KEY, columns TEXT)")
    con.execute("INSERT OR REPLACE INTO model_meta VALUES (?, ?)", (table, json.dumps(cols)))
    own = "project" in cols
    names = cols if own else ["project"] + cols
    con.execute(f"CREATE TABLE {_q(table)} ({', '.join(_q(c) + ' TEXT' for c in names)})")
    con.executemany(f"INSERT INTO {_q(table)} VALUES ({', '.join('?' * len(names))})", [r if own else [project] + r for r in rows])


#: derived by import_parts, not by the file loaders
PART_TABLES = ("part", "part_member")


def _create(con: sqlite3.Connection, table: str, cols: list[str]) -> None:
    con.execute(f"CREATE TABLE IF NOT EXISTS {_q(table)} (project TEXT, {', '.join(_q(c) + ' TEXT' for c in cols)})")


def import_parts(con: sqlite3.Connection, doc: dict, project: str = "") -> None:
    """Load a parts.json document. ``part`` and ``part_member`` are derived: replaced. The reviewed tables (application,
    application_part, chain, chain_step, assign, review) are written for every application and chain in ``doc`` and never
    lose a row that ``doc`` no longer has. Keys the tables have no column for stay in the ``data`` column, so
    export_parts gives back the same document."""
    for t in PART_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {_q(t)}")
    _create(con, "part", ["part_id", "name", "kind", "side", "basis", "note", "data", "ord"])
    _create(con, "part_member", ["part_id", "host", "ord"])
    for n, p in enumerate(doc.get("parts", [])):
        rest = {k: v for k, v in p.items() if k != "members"}
        con.execute("INSERT INTO part VALUES (?,?,?,?,?,?,?,?,?)", [project, p["id"], p.get("name", ""), p.get("kind", ""),
                    p.get("side", ""), p.get("basis", ""), p.get("note", ""), json.dumps(rest, ensure_ascii=False), n])
        con.executemany("INSERT INTO part_member VALUES (?,?,?,?)", [[project, p["id"], m, i] for i, m in enumerate(p.get("members", []))])
    con.execute("DELETE FROM review WHERE project=? AND subject_type='parts'", (project,))
    con.execute("DELETE FROM assign WHERE project=? AND subject_type='member'", (project,))
    con.execute("INSERT INTO review (project, subject_type, subject_id, state, reviewed_on, note) VALUES (?,?,?,?,?,?)",
                (project, "parts", "all", "reviewed" if doc.get("reviewed") else "not reviewed", doc.get("reviewed_on", ""),
                 json.dumps([k for k in ("applications", "chains") if k in doc])))
    con.executemany("INSERT INTO assign (project, subject_type, subject_id, value) VALUES (?,?,?,?)",
                    [(project, "member", k, v) for k, v in (doc.get("assign") or {}).items()])
    for n, a in enumerate(doc.get("applications", [])):
        data = {k: v for k, v in a.items() if k not in ("id", "parts", "reviewed", "role_in")}
        for t in ("application", "application_part"):
            con.execute(f"DELETE FROM {_q(t)} WHERE project=? AND application_id=?", (project, a["id"]))
        con.execute("INSERT INTO application VALUES (?,?,?,?,?,?,?,?)", [project, a["id"], a.get("name", ""), a.get("purpose", ""),
                    a.get("purpose_source", ""), a.get("basis", ""), json.dumps(data, ensure_ascii=False), n])
        con.executemany("INSERT INTO application_part VALUES (?,?,?,?,?)",
                        [[project, a["id"], pid, (a.get("role_in") or {}).get(pid, ""), i] for i, pid in enumerate(a.get("parts", []))])
        con.execute("DELETE FROM review WHERE project=? AND subject_type='application' AND subject_id=?", (project, a["id"]))
        if "reviewed" in a:
            con.execute("INSERT INTO review (project, subject_type, subject_id, state) VALUES (?,?,?,?)",
                        (project, "application", a["id"], "reviewed" if a["reviewed"] else "not reviewed"))
    for n, c in enumerate(doc.get("chains", [])):
        data = {k: v for k, v in c.items() if k not in ("id", "application", "steps", "reviewed")}
        for t in ("chain", "chain_step"):
            con.execute(f"DELETE FROM {_q(t)} WHERE project=? AND chain_id=?", (project, c["id"]))
        con.execute("INSERT INTO chain VALUES (?,?,?,?,?,?)", [project, c["id"], c.get("application", ""), c.get("function", ""),
                    json.dumps(data, ensure_ascii=False), n])
        con.executemany("INSERT INTO chain_step VALUES (?,?,?,?,?,?,?)",
                        [[project, c["id"], i, st.get("from", ""), st.get("to", ""), json.dumps(st.get("flows", [])),
                          json.dumps({k: v for k, v in st.items() if k not in ("from", "to", "flows")}, ensure_ascii=False)]
                         for i, st in enumerate(c.get("steps", []))])
        con.execute("DELETE FROM review WHERE project=? AND subject_type='chain' AND subject_id=?", (project, c["id"]))
        if "reviewed" in c:
            con.execute("INSERT INTO review (project, subject_type, subject_id, state) VALUES (?,?,?,?)",
                        (project, "chain", c["id"], "reviewed" if c["reviewed"] else "not reviewed"))


def export_parts(con: sqlite3.Connection, project: str = "") -> dict:
    """The parts.json document the tables hold (the inverse of import_parts)."""
    def q(sql, *a):
        return con.execute(sql, (project, *a)).fetchall()
    rv = {(t, i): (st, on, nt) for t, i, st, on, nt in q("SELECT subject_type, subject_id, state, reviewed_on, note FROM review WHERE project=?")}
    st, on, keys = rv.get(("parts", "all"), ("not reviewed", "", "[]"))
    doc: dict = {"reviewed": st == "reviewed", "reviewed_on": on or "",
                 "assign": {k: v for k, v in q("SELECT subject_id, value FROM assign WHERE project=? AND subject_type='member'")}}
    members: dict[str, list[str]] = {}
    for pid, host in q("SELECT part_id, host FROM part_member WHERE project=? ORDER BY CAST(ord AS INTEGER)"):
        members.setdefault(pid, []).append(host)
    doc["parts"] = [{"id": pid, **json.loads(data), "members": members.get(pid, [])}
                    for pid, data in q("SELECT part_id, data FROM part WHERE project=? ORDER BY CAST(ord AS INTEGER)")]
    apps = []
    for aid, data in q("SELECT application_id, data FROM application WHERE project=? ORDER BY CAST(ord AS INTEGER)"):
        links = q("SELECT part_id, role_in FROM application_part WHERE project=? AND application_id=? ORDER BY CAST(ord AS INTEGER)", aid)
        a = {"id": aid, **json.loads(data), "parts": [p for p, _ in links]}
        role_in = {p: r for p, r in links if r}
        if role_in or "role_in" in json.loads(data):
            a["role_in"] = role_in
        if ("application", aid) in rv:
            a["reviewed"] = rv[("application", aid)][0] == "reviewed"
        apps.append(a)
    chains = []
    for cid, app, fn, data in q("SELECT chain_id, application_id, function, data FROM chain WHERE project=? ORDER BY CAST(ord AS INTEGER)"):
        steps = [{"from": f, "to": t, "flows": json.loads(fl), **json.loads(dt)} for f, t, fl, dt in
                 q("SELECT from_part, to_part, flows, data FROM chain_step WHERE project=? AND chain_id=? ORDER BY CAST(step_no AS INTEGER)", cid)]
        c = {"id": cid, "application": app, "function": fn, **json.loads(data), "steps": steps}
        if ("chain", cid) in rv:
            c["reviewed"] = rv[("chain", cid)][0] == "reviewed"
        chains.append(c)
    keys = json.loads(keys or "[]")
    if "applications" in keys or apps:
        doc["applications"] = apps
    if "chains" in keys or chains:
        doc["chains"] = chains
    return doc


MATRIX = "evidence-matrix.csv"
REVIEWS = "evidence-reviews.jsonl"


def row_hash(cells: list[str]) -> str:
    return hashlib.sha256("\x1f".join(cells).encode("utf-8")).hexdigest()


def mirror_evidence(con: sqlite3.Connection, work: Path, project: str = "") -> dict:
    """Phase 1: the CSV stays the source and ``evidence`` mirrors it (same columns, same E-ids, in file order, plus
    ``row_hash``). A row whose cells changed in the CSV is updated; an E-id the CSV no longer has is kept, never reused.
    The view ``evidence_matrix`` returns exactly the CSV's columns in its order; ``evidence_review`` is the latest
    row per E-id of evidence-reviews.jsonl, also written to ``review`` (subject_type evidence)."""
    head, rows = _rows(Path(work) / MATRIX)
    if "evidence_id" not in head:
        return {"evidence": 0, "added": 0, "changed": 0}
    have = {c[1] for c in con.execute("PRAGMA table_info(evidence)")}
    for c in head:
        if c not in have:
            con.execute(f"ALTER TABLE evidence ADD COLUMN {_q(c)} TEXT")
    if "row_hash" not in have:
        con.execute("ALTER TABLE evidence ADD COLUMN row_hash TEXT")
    old = dict(con.execute("SELECT evidence_id, row_hash FROM evidence WHERE project=?", (project,)).fetchall())
    canonical = is_canonical(con)
    if canonical:                    # the store is the source: the file may only have gained rows from an older writer
        diff = sorted(r[head.index("evidence_id")] for r in rows if r[head.index("evidence_id")] in old
                      and old[r[head.index("evidence_id")]] != row_hash(r))
        if diff:
            raise RuntimeError(f"evidence-matrix.csv changed rows the store owns ({', '.join(diff[:6])}): the store is canonical; "
                               "change a row with update_evidence, not in the file")
        rows = [r for r in rows if r[head.index("evidence_id")] not in old]
    ph, cols = ", ".join("?" * (len(head) + 2)), ", ".join(_q(c) for c in ["project"] + head + ["row_hash"])
    added = changed = 0
    for r in rows:
        eid, h = r[head.index("evidence_id")], row_hash(r)
        if eid in old and old[eid] == h:
            continue
        if eid in old:
            changed += 1
            con.execute(f"UPDATE evidence SET {', '.join(_q(c) + '=?' for c in head + ['row_hash'])} WHERE project=? AND evidence_id=?",
                        r + [h, project, eid])
        else:
            added += 1
            con.execute(f"INSERT INTO evidence ({cols}) VALUES ({ph})", [project] + r + [h])
    con.execute("DROP VIEW IF EXISTS evidence_matrix")
    con.execute(f"CREATE VIEW evidence_matrix AS SELECT {', '.join(_q(c) for c in head)} FROM evidence WHERE project={_lit(project)} ORDER BY rowid")
    n = con.execute("SELECT COUNT(*) FROM evidence WHERE project=?", (project,)).fetchone()[0]
    latest: dict[str, dict] = {}
    rv = Path(work) / REVIEWS
    if rv.is_file():
        for line in rv.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("evidence_id"):
                    latest[d["evidence_id"]] = d
    con.execute("DELETE FROM review WHERE project=? AND subject_type='evidence'", (project,))
    con.executemany("INSERT INTO review (project, subject_type, subject_id, state, reviewer, reviewed_on, note) VALUES (?,?,?,?,?,?,?)",
                    [(project, "evidence", i, d.get("state", ""), d.get("by", ""), d.get("at", ""), d.get("note", ""))
                     for i, d in latest.items()])
    con.execute("DROP VIEW IF EXISTS evidence_review")
    con.execute(f"CREATE VIEW evidence_review AS SELECT subject_id AS evidence_id, state, reviewer AS \"by\", reviewed_on AS \"at\", note "
                f"FROM review WHERE subject_type='evidence' AND project={_lit(project)}")
    return {"evidence": n, "added": added, "changed": changed}


# ---------------------------------------------------------------- phase 2: the store holds the matrix

def is_canonical(con: sqlite3.Connection) -> bool:
    con.execute("CREATE TABLE IF NOT EXISTS model_meta (table_name TEXT PRIMARY KEY, columns TEXT)")
    return con.execute("SELECT columns FROM model_meta WHERE table_name='matrix_canonical'").fetchone() == ("1",)


def set_canonical(work_dir: Path, project: str = "") -> int:
    """Make the store the source of the evidence matrix (one way: it is never switched back). The CSV is mirrored first, so
    no row is lost; from here on rows are added with append_evidence and the CSV is written from the store."""
    work = Path(work_dir)
    con = sqlite3.connect(path(work))
    try:
        _create(con, "evidence", REVIEWED["evidence"])
        n = mirror_evidence(con, work, project)["evidence"]
        con.execute("INSERT OR REPLACE INTO model_meta VALUES ('matrix_canonical', '1')")
        con.commit()
        return n
    finally:
        con.close()


def _next_eid(con: sqlite3.Connection, project: str) -> str:
    top = max([int(m) for (e,) in con.execute("SELECT evidence_id FROM evidence WHERE project=?", (project,))
               for m in re.findall(r"^E-(\d+)$", e or "")] or [0])
    return f"E-{top + 1:03d}"


def _write_matrix(con: sqlite3.Connection, work: Path, project: str, append: list[list[str]] | None = None) -> None:
    """Write evidence-matrix.csv from the store. A pure append adds lines to the end of the existing file, so every old row stays
    byte-identical; a changed row rewrites the file (same dialect) and the rows that did not change keep their bytes."""
    f = Path(work) / MATRIX
    head = [c[1] for c in con.execute("PRAGMA table_info(evidence)") if c[1] not in ("project", "row_hash")]
    nl = "\r\n" if f.is_file() and b"\r\n" in f.read_bytes()[:4000] else "\n"
    if append is not None and f.is_file() and f.stat().st_size:
        raw = f.read_bytes()
        with f.open("a", encoding="utf-8", newline="") as fh:
            if not raw.endswith(b"\n"):
                fh.write(nl)
            csv.writer(fh, lineterminator=nl).writerows(append)
    else:
        cur = con.execute(f"SELECT {', '.join(_q(c) for c in head)} FROM evidence WHERE project=? ORDER BY rowid", (project,))
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator=nl)
            w.writerow(head)
            w.writerows(cur.fetchall())
    con.execute("INSERT OR REPLACE INTO model_meta VALUES (?, ?)", ("src:" + MATRIX, json.dumps(fingerprint(f))))


def _store(work_dir: Path):
    con = sqlite3.connect(path(Path(work_dir)))
    if not is_canonical(con):
        con.close()
        raise RuntimeError("the store is not canonical for the matrix: run set_canonical first")
    return con


def append_evidence(work_dir: Path, row: dict, project: str = "") -> str:
    """Add one row and return its E-id. The id is always the next one; a row that names an id must name that id, so an
    existing id is never reused and none is skipped or renumbered. The CSV gets the row appended."""
    con = _store(work_dir)
    try:
        eid = _next_eid(con, project)
        if row.get("evidence_id") not in (None, "", eid):
            raise ValueError(f"{row['evidence_id']} is not the next E-id ({eid}): an E-id is never reused or renumbered")
        head = [c[1] for c in con.execute("PRAGMA table_info(evidence)") if c[1] not in ("project", "row_hash")]
        cells = [eid if c == "evidence_id" else str(row.get(c, "")) for c in head]
        con.execute(f"INSERT INTO evidence ({', '.join(_q(c) for c in ['project'] + head + ['row_hash'])}) "
                    f"VALUES ({', '.join('?' * (len(head) + 2))})", [project] + cells + [row_hash(cells)])
        _write_matrix(con, Path(work_dir), project, append=[cells])
        con.commit()
        return eid
    finally:
        con.close()


def update_evidence(work_dir: Path, eid: str, changes: dict, project: str = "") -> None:
    """Change cells of an existing row (status, review_state, ...). The evidence_id cannot change."""
    if "evidence_id" in changes and changes["evidence_id"] != eid:
        raise ValueError("an E-id is never renumbered")
    con = _store(work_dir)
    try:
        head = [c[1] for c in con.execute("PRAGMA table_info(evidence)") if c[1] not in ("project", "row_hash")]
        cur = con.execute(f"SELECT {', '.join(_q(c) for c in head)} FROM evidence WHERE project=? AND evidence_id=?", (project, eid)).fetchone()
        if not cur:
            raise KeyError(f"{eid} does not exist")
        cells = [str(changes.get(c, v)) if c in changes else v for c, v in zip(head, cur)]
        con.execute(f"UPDATE evidence SET {', '.join(_q(c) + '=?' for c in head + ['row_hash'])} WHERE project=? AND evidence_id=?",
                    cells + [row_hash(cells), project, eid])
        _write_matrix(con, Path(work_dir), project)
        con.commit()
    finally:
        con.close()


def rename_evidence(*_a, **_k) -> None:
    raise ValueError("an E-id is never renumbered or reused")


# ---------------------------------------------------------------- answered facts and verdicts


def _project(con: sqlite3.Connection, given: str = "") -> str:
    """The project key the store was built for (model_meta), unless one is given."""
    if given:
        return given
    try:
        r = con.execute("SELECT columns FROM model_meta WHERE table_name='project'").fetchone()
    except sqlite3.Error:
        return ""
    return json.loads(r[0]) if r else ""

FACTS = "facts/facts.jsonl"


def _fact_row(rec: dict) -> list[str]:
    return [rec.get("fact", ""), ";".join(rec.get("evidence_ids", [])), ";".join(rec.get("hosts", [])), rec.get("basis", ""),
            rec.get("section", ""), rec.get("question", ""), rec.get("kind", "fact"), rec.get("sheet_sha", ""), rec.get("added", ""),
            hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()]


def add_answered_facts(con: sqlite3.Connection, recs: list[dict], project: str = "") -> int:
    """Insert fact records ({fact, evidence_ids, hosts, section, question, basis, kind, sheet_sha, added}) not yet in
    ``answered_fact`` (same record = same hash). Append-only: nothing is updated or deleted. Returns the rows added."""
    have = {r[0] for r in con.execute("SELECT rec_hash FROM answered_fact WHERE project=?", (project,))}
    n = 0
    for rec in recs:
        row = _fact_row(rec)
        if row[-1] in have:
            continue
        have.add(row[-1])
        con.execute(f"INSERT INTO answered_fact VALUES ({', '.join('?' * (len(row) + 1))})", [project] + row)
        n += 1
    return n


def sync_facts(con: sqlite3.Connection, work: Path, project: str = "") -> int:
    """Load facts/facts.jsonl into ``answered_fact`` (the file stays the writer in phase 1)."""
    f = Path(work) / FACTS
    recs = []
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    return add_answered_facts(con, recs, project)


def record_facts(work_dir: Path, recs: list[dict], project: str = "") -> int:
    """Called by fact_store when a sheet's facts are written: add them to the table too, when a store exists."""
    if not path(Path(work_dir)).is_file() or not recs:
        return 0
    con = sqlite3.connect(path(Path(work_dir)))
    try:
        _create(con, "answered_fact", REVIEWED["answered_fact"])
        n = add_answered_facts(con, recs, _project(con, project))
        con.commit()
        return n
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def answered_facts(work_dir: Path, project: str = "") -> list[dict]:
    """The facts as fact_store._read gives them (same keys), oldest first, from the table."""
    f = path(Path(work_dir))
    if not f.is_file():
        return []
    con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    try:
        project = _project(con, project)
        out = []
        for fact, ev, hosts, basis, section, question, kind, sha, added, _ in con.execute(
                "SELECT fact, evidence_ids, hosts, basis, section, question, kind, sheet_sha, added, rec_hash FROM answered_fact "
                "WHERE project=? ORDER BY rowid", (project,)):
            rec = {"fact": fact, "evidence_ids": [i for i in ev.split(";") if i], "hosts": [h for h in hosts.split(";") if h],
                   "section": section, "question": question, "basis": basis, "sheet_sha": sha, "added": added}
            if kind and kind != "fact":
                rec["kind"] = kind
            out.append(rec)
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def record_verdicts(work_dir: Path, run_id: str, results: dict, project: str = "") -> int:
    """Store the per-requirement verdicts of one run ({qid: {"view", "reply"}} from requirement_answer): one row per finding
    keyed by finding id, requirement and run. A run is recorded once; recording it again adds nothing."""
    f = path(Path(work_dir))
    if not f.is_file():
        return 0
    con = sqlite3.connect(f)
    try:
        project = _project(con, project)
        _create(con, "verdict", REVIEWED["verdict"])
        if con.execute("SELECT 1 FROM verdict WHERE project=? AND run_id=?", (project, run_id)).fetchone():
            return 0
        n = 0
        for qid, r in results.items():
            view, reply = r.get("view") or {}, r.get("reply") or {}
            by = {x["key"]: x for x in view.get("findings", [])}
            for j in reply.get("judgements") or []:
                x = by.get(j.get("finding"), {})
                con.execute("INSERT INTO verdict VALUES (?,?,?,?,?,?,?,?,?)",
                            (project, f"{x.get('slot', '')}:{j.get('finding')}", view.get("req_id") or qid, run_id, j.get("verdict", ""),
                             j.get("note", ""), x.get("text", ""), ";".join(x.get("ids", [])),
                             __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
                n += 1
        con.commit()
        return n
    finally:
        con.close()


def verdicts(work_dir: Path, run_id: str | None = None, project: str = "") -> list[dict]:
    f = path(Path(work_dir))
    if not f.is_file():
        return []
    con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    try:
        project = _project(con, project)
        q, a = "SELECT finding_id, requirement, run_id, verdict, note, text, evidence_ids FROM verdict WHERE project=?", [project]
        if run_id:
            q, a = q + " AND run_id=?", a + [run_id]
        cols = ("finding_id", "requirement", "run_id", "verdict", "note", "text", "evidence_ids")
        return [dict(zip(cols, r)) for r in con.execute(q + " ORDER BY rowid", a)]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def link_evidence(con: sqlite3.Connection, work: Path, project: str = "") -> int:
    """Derived ``evidence_link`` (evidence_id, subject_type, subject_id): the hosts each row is about (evidence_hosts.csv),
    the part each of those hosts belongs to, and the addresses, graph nodes and graph edges that cite the row."""
    con.execute("DROP TABLE IF EXISTS evidence_link")
    _create(con, "evidence_link", ["evidence_id", "subject_type", "subject_id"])
    links: set[tuple] = set()
    part_of = dict(con.execute("SELECT host, part_id FROM part_member WHERE project=?", (project,)).fetchall()) \
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='part_member'").fetchone() else {}
    head, rows = _rows(Path(work) / "hosts" / "evidence_hosts.csv")
    if "evidence_id" in head and "hosts" in head:
        for r in rows:
            for h in r[head.index("hosts")].replace(",", ";").split(";"):
                if h.strip():
                    links.add((r[0], "host", h.strip()))
                    if h.strip() in part_of:
                        links.add((r[0], "part", part_of[h.strip()]))
    for table, kind, key in (("address", "address", "address"), ("graph_node", "node", "node_id"), ("graph_edge", "edge", "edge_id")):
        if not {key, "evidence_ids"} <= {c[1] for c in con.execute(f"PRAGMA table_info({_q(table)})")}:
            continue
        for subject, ids in con.execute(f"SELECT {_q(key)}, evidence_ids FROM {_q(table)}"):
            for i in (ids or "").replace(",", ";").split(";"):
                if i.strip():
                    links.add((i.strip(), kind, subject))
    con.executemany("INSERT INTO evidence_link VALUES (?,?,?,?)", [(project, *x) for x in sorted(links)])
    return len(links)


def reviewed_counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0] for t in REVIEWED
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()}


def build(work_dir: Path, project: str = "") -> dict[str, int]:
    """Rebuild every derived table; return {table: rows}. Raises if a reviewed table lost rows."""
    work = Path(work_dir)
    con = sqlite3.connect(path(work))
    try:
        before = reviewed_counts(con)
        for t in list(SOURCES) + [COVERAGE[0]]:
            con.execute(f"DROP TABLE IF EXISTS {_q(t)}")
        counts = {}
        for table, rel in SOURCES.items():
            head, rows = _rows(work / rel)
            _make(con, table, head, rows, project)
            counts[table] = len(rows)
        head, rows = _rows(work / COVERAGE[1])
        if "host" in head:
            hi = head.index("host")
            cis = [head.index(c) for c in ("capture", "captured_in") if c in head]
            cov = sorted({(r[hi], c.strip()) for r in rows for ci in cis for c in r[ci].replace(",", ";").split(";") if c.strip()})
            cov = [list(x) for x in cov]
        else:
            cov = []
        _make(con, COVERAGE[0], ["host", "capture_id"], cov, project)
        counts[COVERAGE[0]] = len(cov)
        for t, cols in REVIEWED.items():
            _create(con, t, cols)
        con.execute("CREATE TABLE IF NOT EXISTS model_meta (table_name TEXT PRIMARY KEY, columns TEXT)")
        con.execute("INSERT OR REPLACE INTO model_meta VALUES ('project', ?)", (json.dumps(project),))
        for rel in list(SOURCES.values()) + [MATRIX]:
            fp = fingerprint(work / rel)
            con.execute("CREATE TABLE IF NOT EXISTS model_meta (table_name TEXT PRIMARY KEY, columns TEXT)")
            con.execute("INSERT OR REPLACE INTO model_meta VALUES (?, ?)", ("src:" + rel, json.dumps(fp)))
        pj = work / "parts.json"
        if pj.is_file():
            import_parts(con, json.loads(pj.read_text(encoding="utf-8")), project)
            counts["part"] = con.execute("SELECT COUNT(*) FROM part").fetchone()[0]
            counts["part_member"] = con.execute("SELECT COUNT(*) FROM part_member").fetchone()[0]
        counts["answered_fact"] = con.execute("SELECT COUNT(*) FROM answered_fact WHERE project=?", (project,)).fetchone()[0] \
            if sync_facts(con, work, project) >= 0 else 0
        if (work / MATRIX).is_file():
            counts["evidence"] = mirror_evidence(con, work, project)["evidence"]
        counts["evidence_link"] = link_evidence(con, work, project)
        after = reviewed_counts(con)
        lost = {t: (before[t], after.get(t, 0)) for t in before if after.get(t, 0) < before[t]}
        if lost:
            con.rollback()
            raise RuntimeError(f"a reviewed table lost rows: {lost}")
        con.commit()
        return counts
    finally:
        con.close()


# ---------------------------------------------------------------- the read API and the export


def fingerprint(f: Path) -> list | None:
    """[size, mtime_ns] of a source file, or None when it is missing: what a reader compares to know the store is current."""
    try:
        st = Path(f).stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def rows(work_dir: Path, rel: str) -> list[dict] | None:
    """The rows of a mirrored source file (``rel`` under csa-work, e.g. "hosts/hosts.csv" or "evidence-matrix.csv") as
    dicts keyed by the file's own columns, exactly as csv.DictReader gives them; or None when the store is missing,
    does not hold that file or the file changed since the last build, so the caller reads the file."""
    work = Path(work_dir)
    if not path(work).is_file() or (rel not in FILES and rel != MATRIX):
        return None
    try:
        con = sqlite3.connect(f"file:{path(work)}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        r = con.execute("SELECT columns FROM model_meta WHERE table_name=?", ("src:" + rel,)).fetchone()
        if not r or json.loads(r[0]) != fingerprint(work / rel) or fingerprint(work / rel) is None:
            return None
        if rel == MATRIX:
            cur = con.execute("SELECT * FROM evidence_matrix")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, x)) for x in cur.fetchall()]
        table = FILES[rel]
        cols = json.loads(con.execute("SELECT columns FROM model_meta WHERE table_name=?", (table,)).fetchone()[0])
        cur = con.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)} ORDER BY rowid")
        return [dict(zip(cols, x)) for x in cur.fetchall()]
    except (sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        con.close()


#: file under csa-work -> table, for the exports that are a plain copy of a derived table
FILES = {rel: table for table, rel in SOURCES.items()}


class Model:
    """Read access to model.sqlite: lists of dicts with the source files' own column names (no ``project``)."""

    def __init__(self, work_dir: Path, project: str = ""):
        self.work, self.project = Path(work_dir), project
        if not path(self.work).is_file():
            raise FileNotFoundError(f"{path(self.work)} does not exist: run `csa model build`")
        self.con = sqlite3.connect(path(self.work))

    def close(self) -> None:
        self.con.close()

    def _cols(self, table: str) -> list[str]:
        r = self.con.execute("SELECT columns FROM model_meta WHERE table_name=?", (table,)).fetchone()
        return json.loads(r[0]) if r else [c[1] for c in self.con.execute(f"PRAGMA table_info({_q(table)})") if c[1] != "project"]

    def table(self, name: str) -> tuple[list[str], list[list[str]]]:
        """(source columns, rows) of a derived table, in the source file's order."""
        cols = self._cols(name)
        return cols, [list(r) for r in self.con.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(name)} ORDER BY rowid")]

    def _dicts(self, name: str) -> list[dict]:
        cols, rows = self.table(name)
        return [dict(zip(cols, r)) for r in rows]

    def hosts(self) -> list[dict]:
        return self._dicts("host")

    def flows(self) -> list[dict]:
        return self._dicts("flow")

    def settings(self) -> list[dict]:
        return self._dicts("observation")

    def parts(self) -> dict:
        return export_parts(self.con, self.project)

    def evidence_matrix(self) -> tuple[list[str], list[list[str]]]:
        cur = self.con.execute("SELECT * FROM evidence_matrix")
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]

    def evidence_for(self, subject_type: str, subject_id: str) -> list[str]:
        """The E-ids that rest on or cite a host, part, address, node or edge."""
        return [r[0] for r in self.con.execute(
            "SELECT evidence_id FROM evidence_link WHERE subject_type=? AND subject_id=? ORDER BY evidence_id", (subject_type, subject_id))]


def locate(file: Path) -> tuple[Path, str] | None:
    """(work dir, relative name) of a file the store mirrors, from its path, or None for any other file."""
    f = Path(file)
    for rel in list(FILES) + [MATRIX]:
        n = len(Path(rel).parts)
        if f.parts[-n:] == Path(rel).parts and len(f.parts) > n:
            return Path(*f.parts[:-n]), rel
    return None


def read_csv(file: Path) -> list[dict]:
    """The rows of a mirrored CSV as csv.DictReader gives them: from the store when it is current for that file, else
    from the file (FileNotFoundError when it is missing, as open() would). The one reader the other modules use."""
    loc = locate(file)
    got = rows(*loc) if loc else None
    if got is not None:
        return got
    with Path(file).open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def host_parts(work_dir: Path, project: str = "") -> dict[str, dict]:
    """{HOST: {"part_id", "part", "applications": [name], "reviewed": bool}} from the store's part, part_member and
    application_part tables ({} when the store or the parts are missing). Never reads parts.json."""
    f = path(Path(work_dir))
    if not f.is_file():
        return {}
    con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    try:
        names = {t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"part", "part_member", "application_part", "application", "review"} <= names:
            return {}
        apps: dict[str, list[str]] = {}
        for pid, name in con.execute("SELECT ap.part_id, a.name FROM application_part ap JOIN application a "
                                     "ON a.application_id=ap.application_id AND a.project=ap.project WHERE ap.project=? "
                                     "ORDER BY CAST(a.ord AS INTEGER)", (project,)):
            apps.setdefault(pid, []).append(name)
        rv = con.execute("SELECT state FROM review WHERE project=? AND subject_type='parts' AND subject_id='all'", (project,)).fetchone()
        reviewed = bool(rv and rv[0] == "reviewed")
        return {h.upper(): {"part_id": pid, "part": name, "applications": apps.get(pid, []), "reviewed": reviewed}
                for h, pid, name in con.execute("SELECT m.host, m.part_id, p.name FROM part_member m JOIN part p "
                                                "ON p.part_id=m.part_id AND p.project=m.project WHERE m.project=?", (project,))}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def export(work_dir: Path, out_dir: Path, project: str = "") -> dict[str, int]:
    """Write every current file the store mirrors under ``out_dir`` (same relative paths), never over the sources:
    the host, flow, setting, graph files, evidence-matrix.csv (from the view) and parts.json. {file: rows}."""
    m = Model(work_dir, project)
    out, done = Path(out_dir), {}
    try:
        for rel, table in FILES.items():
            if not (Path(work_dir) / rel).is_file():
                continue
            cols, rows = m.table(table)
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            with (out / rel).open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                w.writerows(rows)
            done[rel] = len(rows)
        if (Path(work_dir) / MATRIX).is_file():
            cols, rows = m.evidence_matrix()
            with (out / MATRIX).open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                w.writerows(rows)
            done[MATRIX] = len(rows)
        if (Path(work_dir) / "parts.json").is_file():
            (out / "parts.json").write_text(json.dumps(m.parts(), indent=1, ensure_ascii=False), encoding="utf-8")
            done["parts.json"] = len(m.parts().get("parts", []))
        return done
    finally:
        m.close()


def counts(work_dir: Path) -> dict[str, int]:
    f = path(work_dir)
    if not f.is_file():
        return {}
    con = sqlite3.connect(f)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0] for t in names}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "counts", "export"))
    ap.add_argument("--out", help="export: the folder to write into (default: <work-dir>/model-export)")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--project", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            out = export(Path(a.work_dir), Path(a.out or Path(a.work_dir) / "model-export"), a.project)
        else:
            out = build(Path(a.work_dir), a.project) if a.cmd == "build" else counts(Path(a.work_dir))
    except (RuntimeError, FileNotFoundError) as e:
        print(json.dumps({"status": "ERROR", "message": str(e)}))
        return 2
    print(json.dumps({"status": "OK", "tables": out}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
