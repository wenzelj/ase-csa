"""csa-work-v2 repository: one SQLite store (csa-work-v2/csa.sqlite) with a small CRUD API.

The schema lives in `schema.sql` (single source of truth for table shapes). Every mutation
goes through `Repo.tx()`, which commits or rolls back all-or-nothing and writes a timestamped
pre-mutation copy of the DB into a `backups/` sibling folder before the first write of the
transaction. S583 adds the real `hosts` and `evidence` CRUD surface; `intake` / `leads` land
in S584-S585 and `backup()` / `export` in S587. Nothing in the framework points at
csa-work-v2/ until the switch story.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .exports import _Export

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DB_NAME = "csa.sqlite"
BACKUPS_DIR = "backups"

# ---------------------------------------------------------------------------
# evidence_matrix.py's quote check, imported — never re-implemented (S583)
_EM_SCRIPT = (Path(__file__).resolve().parents[3] / "skills" / "csa-evidence-matrix"
              / "scripts" / "evidence_matrix.py")


def _load_em():
    spec = importlib.util.spec_from_file_location("_csa_v2repo_evidence_matrix", _EM_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _EM = _load_em()
except Exception:
    _EM = None


# ---------------------------------------------------------------------------
# namespaced CRUD
_HOST_COLS = {"name", "role", "site", "os", "status"}
_EVIDENCE_COLS = {"id", "area", "question", "claim", "status", "source_title",
                  "page_or_location", "excerpt", "confidence", "gap_or_action",
                  "review_state", "created_at", "updated_at"}


class Repo:
    """The csa-work-v2 repository: `Repo("<csa-work-v2>/csa.sqlite")`.

    `tx()` is the only path into writes; the `hosts` / `evidence` / `intake` / `leads`
    namespaces and `review_event.append` write inside it. `review_event` is append-only
    at the API level — no `update` or `delete` is exposed.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.name != DB_NAME:
            self.path = self.path / DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con: sqlite3.Connection | None = None
        self._tx_active = False
        self.backup_dir = self.path.parent / BACKUPS_DIR
        self.hosts = _Hosts(self)
        self.evidence = _Evidence(self)
        self.application_scope = _ApplicationScope(self)
        self.intake = _Namespace(self, "intake_file")
        self.leads = _Namespace(self, "lead")
        self.export = _Export(self)
        self._apply_schema()

    # ------------------------------------------------------------------ plumbing
    @property
    def con(self) -> sqlite3.Connection:
        """One connection per Repo, held for the Repo's lifetime (transactions and backups
        must act on the same file handle)."""
        if self._con is None:
            self._con = sqlite3.connect(f"file:{self.path}?mode=rwc", uri=True, isolation_level=None)
            self._con.execute("PRAGMA foreign_keys = ON")
        return self._con

    def close(self):
        if self._con is not None:
            self._con.close()
            self._con = None

    def _require_tx(self):
        if not self._tx_active:
            raise RuntimeError("not inside a transaction — call it inside `with r.tx():`")

    def _require_fields(self, cols, allowed, table, key):
        unknown = set(cols) - allowed
        if unknown:
            raise ValueError(f"{table}.{key or ''}: unknown column(s) {', '.join(sorted(unknown))}")

    def _now(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _audit(self, actor, action, subject_type, subject_id, note=None):
        con = self.con
        ts = self._now()
        con.execute(
            "INSERT INTO review_event (ts, actor, action, subject_type, subject_id, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, actor, action, subject_type, subject_id, note),
        )
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _next_evidence_id(self):
        m = self.con.execute("SELECT id FROM evidence").fetchall()
        top = 0
        for (eid,) in m:
            mm = re.fullmatch(r"E-(\d+)", eid) if eid else None
            if mm:
                top = max(top, int(mm.group(1)))
        return f"E-{top + 1:03d}"
    def _apply_schema(self):
        """Apply `schema.sql` (idempotent), then create the `fts` table — FTS5 when
        available, a plain-text fallback otherwise. Re-creating `fts` when its shape has
        changed (e.g. FTS5 was added after a plain-text build) is safe because `fts` is a
        read-only mirror and is rebuilt by the ingest rewrite (S584+)."""
        con = self.con
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope_cols = {r[1] for r in con.execute("PRAGMA table_info(application_scope)")}
        if "app" in scope_cols and "application_key" not in scope_cols:
            # S591 was prototyped with shorter column names. Preserve those rows while
            # upgrading the table to the canonical application-scope contract.
            con.execute("DROP INDEX IF EXISTS application_scope_app")
            con.execute("DROP INDEX IF EXISTS application_scope_membership")
            con.execute("ALTER TABLE application_scope RENAME TO application_scope_legacy")
            con.executescript("""
                CREATE TABLE application_scope (
                    application_key TEXT NOT NULL,
                    host_name TEXT NOT NULL REFERENCES host(name),
                    membership TEXT CHECK (membership IN ('owned', 'peer')) NOT NULL,
                    basis TEXT,
                    evidence_ids TEXT,
                    source_ref TEXT,
                    review_state TEXT DEFAULT 'proposed' CHECK (review_state IN ('proposed', 'accepted', 'rejected')),
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    PRIMARY KEY (application_key, host_name)
                );
                CREATE INDEX application_scope_app ON application_scope(application_key);
                CREATE INDEX application_scope_membership ON application_scope(membership);
            """)
            con.execute(
                "INSERT INTO application_scope(application_key, host_name, membership, basis, source_ref, review_state, active) "
                "SELECT app, host, membership, basis, source_provenance, review_state, active "
                "FROM application_scope_legacy"
            )
            con.execute("DROP TABLE application_scope_legacy")
        # provider_host is a v2 addition (DNS/time providers): CREATE TABLE IF NOT EXISTS
        # does not add a column to a pre-existing table, so add it if missing.
        svc_cols = {r[1] for r in con.execute("PRAGMA table_info(service)")}
        if "provider_host" not in svc_cols:
            con.execute("ALTER TABLE service ADD COLUMN provider_host TEXT")
        fts5 = self._has_fts5(con)
        current = con.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table', 'view') AND name = 'fts'"
        ).fetchone()
        if fts5:
            if not current or "fts5" not in (current[0] or ""):
                if current:
                    con.execute("DROP TABLE fts")
                con.execute(
                    "CREATE VIRTUAL TABLE fts USING fts5(chunk_id UNINDEXED, rel_path, heading, text, tokenize='porter unicode61')"
                )
        else:
            if not current or "fts5" in (current[0] or ""):
                if current:
                    con.execute("DROP TABLE fts")
                con.execute("CREATE TABLE fts(chunk_id INTEGER PRIMARY KEY, rel_path TEXT, heading TEXT, text TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS v2_meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT OR REPLACE INTO v2_meta VALUES ('fts5', ?)", ("1" if fts5 else "0",))

    @staticmethod
    def _has_fts5(con: sqlite3.Connection) -> bool:
        try:
            con.execute("CREATE VIRTUAL TABLE temp._v2repo_fts_probe USING fts5(x)")
            con.execute("DROP TABLE temp._v2repo_fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    # ------------------------------------------------------------------- backup
    def backup(self) -> Path:
        """A timestamped copy of the DB file into `backups/` (real work in S587)."""
        raise NotImplementedError("added in S587")

    def _pre_write_backup(self) -> Path:
        """Timestamped pre-mutation copy of the DB file into `backups/`."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / f"{DB_NAME}.{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}"
        n = 1
        while target.exists():
            target = self.backup_dir / f"{DB_NAME}.{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}.{n}"
            n += 1
        if self.path.exists():
            shutil.copy2(self.path, target)
        return target

    # ----------------------------------------------------------------------- tx
    @contextmanager
    def tx(self):
        """All-or-nothing write unit.

        Commits on success, rolls back on exception, and writes a timestamped copy of the
        DB file into `backups/` before the first write of the transaction — the copy is the
        pre-mutation state. On rollback the connection's own transaction rollback restores
        the file byte-for-byte.
        """
        with self._lock:
            self._tx_active = True
            con = self.con
            con.execute("BEGIN IMMEDIATE")
            backed_up = False
            try:
                def _ensure_backup():
                    nonlocal backed_up
                    if not backed_up:
                        self._pre_write_backup()
                        backed_up = True

                self._ensure_write_hook(con, _ensure_backup)
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
            finally:
                self._clear_write_hook(con)
                self._tx_active = False

    def _ensure_write_hook(self, con: sqlite3.Connection, hook):
        _WRITE = ("INSERT", "UPDATE", "DELETE", "REPLACE", "DROP", "ALTER")
        def _cb(stmt: str) -> None:
            head = stmt.lstrip().split(None, 1)
            if head and head[0].upper() in _WRITE:
                hook()
        con.set_trace_callback(_cb)

    @staticmethod
    def _clear_write_hook(con: sqlite3.Connection):
        con.set_trace_callback(None)

    # ------------------------------------------------------------------ review
    def review_event(self):
        return _ReviewEvent(self)


class _Namespace:
    """CRUD stub namespace (S584-S585 add the real logic for intake / leads).

    Only `create` / `get` / `update` / `list` exist: the API deliberately exposes no
    `delete` — reject / retire set a status, and `review_event` keeps the audit trail.
    """

    def __init__(self, repo: Repo, table: str):
        self._repo = repo
        self._table = table

    def create(self, **fields):
        raise NotImplementedError("added in S584-S585")

    def get(self, key):
        raise NotImplementedError("added in S584-S585")

    def update(self, key, **fields):
        raise NotImplementedError("added in S584-S585")

    def list(self, **where):
        raise NotImplementedError("added in S584-S585")


class _Hosts:
    """`r.hosts` CRUD. Every mutation requires `with r.tx():` and appends a review_event."""

    def __init__(self, repo: Repo):
        self._repo = repo

    def create(self, name, role=None, site=None, os=None, actor=None, note=None):
        r = self._repo
        r._require_tx()
        con = r.con
        if name is None or not str(name).strip():
            raise ValueError("hosts.create: name is required")
        if r.con.execute("SELECT 1 FROM host WHERE name=?", (name,)).fetchone():
            raise ValueError(f"hosts.create: host {name!r} already exists")
        ts = r._now()
        con.execute(
            "INSERT INTO host (name, role, site, os, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (name, role, site, os, ts, ts),
        )
        r._audit(actor, "create", "host", name, note)

    def get(self, name):
        r = self._repo
        row = r.con.execute("SELECT name, role, site, os, status, created_at, updated_at "
                            "FROM host WHERE name=?", (name,)).fetchone()
        if not row:
            raise KeyError(name)
        return dict(zip(("name", "role", "site", "os", "status", "created_at", "updated_at"), row))

    def update(self, name, **kw):
        r = self._repo
        actor = kw.pop("actor", None)
        note = kw.pop("note", None)
        if "name" in kw:
            raise ValueError("hosts.update: name is the key and cannot be changed")
        if not kw:
            raise ValueError("hosts.update: no fields to set")
        r._require_fields(kw, _HOST_COLS, "host", "update")
        self.get(name)
        con = r.con
        sets = ", ".join(f"{k} = ?" for k in kw)
        con.execute(f"UPDATE host SET {sets}, updated_at = ? WHERE name = ?",
                    (*kw.values(), r._now(), name))
        r._audit(actor, "update", "host", name, note)

    def retire(self, name, note=None, actor=None):
        r = self._repo
        r._require_tx()
        self.get(name)
        con = r.con
        con.execute("UPDATE host SET status='retired', updated_at=? WHERE name=?", (r._now(), name))
        r._audit(actor, "retire", "host", name, note)

    def reactivate(self, name, note=None, actor=None):
        r = self._repo
        r._require_tx()
        self.get(name)
        con = r.con
        con.execute("UPDATE host SET status='active', updated_at=? WHERE name=?", (r._now(), name))
        r._audit(actor, "reactivate", "host", name, note)

    def list(self, status=None, site=None, role_like=None):
        r = self._repo
        sql = "SELECT name, role, site, os, status, created_at, updated_at FROM host"
        where, params = [], []
        if status is not None:
            where.append("status = ?"); params.append(status)
        if site is not None:
            where.append("site = ?"); params.append(site)
        if role_like is not None:
            where.append("role LIKE ?"); params.append(f"%{role_like}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY name"
        cols = ("name", "role", "site", "os", "status", "created_at", "updated_at")
        return [dict(zip(cols, row)) for row in r.con.execute(sql, params).fetchall()]


class _Evidence:
    """`r.evidence` CRUD. Every mutation requires `with r.tx():` and appends a review_event.

    `status='VERIFIED'` is set only by `verify()`; `update()` refuses a direct VERIFIED write.
    `reject()` / `accept()` change `review_state` and never delete the row.
    """

    def __init__(self, repo: Repo):
        self._repo = repo

    def create(self, claim, source_title, page_or_location=None, excerpt=None, area=None,
               confidence=None, gap_or_action=None, status="VERIFIED", question=None,
               actor=None, note=None):
        r = self._repo
        r._require_tx()
        con = r.con
        if claim is None or not str(claim).strip():
            raise ValueError("evidence.create: claim is required")
        eid = r._next_evidence_id()
        ts = r._now()
        con.execute(
            "INSERT INTO evidence (id, area, question, claim, status, source_title, "
            "page_or_location, excerpt, confidence, gap_or_action, review_state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, area, question, claim, status, source_title, page_or_location, excerpt,
             confidence, gap_or_action, "proposed", ts, ts),
        )
        r._audit(actor, "create", "evidence", eid, note)
        return eid

    def get(self, eid):
        r = self._repo
        row = r.con.execute(
            "SELECT id, area, question, claim, status, source_title, page_or_location, "
            "excerpt, confidence, gap_or_action, review_state, created_at, updated_at "
            "FROM evidence WHERE id=?", (eid,)).fetchone()
        if not row:
            raise KeyError(eid)
        cols = ("id", "area", "question", "claim", "status", "source_title", "page_or_location",
                "excerpt", "confidence", "gap_or_action", "review_state", "created_at", "updated_at")
        return dict(zip(cols, row))

    def update(self, eid, actor=None, note=None, **fields):
        r = self._repo
        r._require_tx()
        if "id" in fields:
            raise ValueError("evidence.update: id is the key and cannot be changed")
        if "status" in fields and fields["status"] == "VERIFIED":
            raise ValueError("evidence.update: status cannot be set to 'VERIFIED' directly; use verify()")
        if not fields:
            raise ValueError("evidence.update: no fields to set")
        r._require_fields(fields, _EVIDENCE_COLS, "evidence", "update")
        self.get(eid)
        con = r.con
        sets = ", ".join(f"{k} = ?" for k in fields)
        con.execute(f"UPDATE evidence SET {sets}, updated_at = ? WHERE id = ?",
                    (*fields.values(), r._now(), eid))
        r._audit(actor, "update", "evidence", eid, note)

    def reject(self, eid, by, note=None, actor=None):
        r = self._repo
        r._require_tx()
        self.get(eid)
        con = r.con
        con.execute("UPDATE evidence SET review_state='rejected', updated_at=? WHERE id=?", (r._now(), eid))
        r._audit(by, "reject", "evidence", eid, note)

    def accept(self, eid, by=None, note=None, actor=None):
        r = self._repo
        r._require_tx()
        self.get(eid)
        con = r.con
        con.execute("UPDATE evidence SET review_state='accepted', updated_at=? WHERE id=?", (r._now(), eid))
        r._audit(by or actor, "accept", "evidence", eid, note)

    def verify(self, eid, actor=None, note=None):
        """Re-check the excerpt against the cited source using evidence_matrix's quote check.

        SOURCE_OK → sets status='VERIFIED', review_state='accepted'.
        Anything else → status unchanged, returns a diagnostic.
        Appends a review_event either way.
        """
        r = self._repo
        r._require_tx()
        row = self.get(eid)
        # build the evidence_matrix-style row dict for source_check.
        # `source_check` returns NOT_CHECKABLE for non-VERIFIED rows by design (those rows rest on
        # reasoning, not a quoted source) — but in v2repo the caller is explicitly asking to verify
        # a quote, so we always check the quote and surface SOURCE_OK / SOURCE_MISMATCH / SOURCE_NOT_FOUND.
        em_row = {"status": "VERIFIED", "source_title": row["source_title"],
                  "evidence_excerpt": row["excerpt"]}
        if _EM is None:
            res = {"verdict": "NOT_CHECKABLE", "reason": "evidence_matrix.py not importable"}
        else:
            try:
                idx = self._source_index()
                if idx is None:
                    res = {"verdict": "SOURCE_NOT_FOUND",
                           "reason": "no discovery index next to the matrix; citations not resolved"}
                else:
                    res = _EM.source_check(em_row, idx)
            except Exception as e:
                res = {"verdict": "NOT_CHECKABLE", "reason": f"source check failed: {e}"}

        con = r.con
        if res.get("verdict") == "SOURCE_OK":
            con.execute("UPDATE evidence SET status='VERIFIED', review_state='accepted', updated_at=? WHERE id=?",
                        (r._now(), eid))
            r._audit(actor, "verify", "evidence", eid, note or "SOURCE_OK")
            return {"verdict": "SOURCE_OK", "files": res.get("files", []), "eid": eid}
        # not OK — leave status unchanged, record failure
        r._audit(actor, "verify", "evidence", eid, note or f"verify failed: {res}")
        return {"verdict": res.get("verdict"), "reason": res.get("reason"), **{k: v for k, v in res.items() if k not in ("verdict", "reason")}, "eid": eid}

    def _source_index(self):
        """Open the discovery index next to the DB (csa-work-v2/discovery-index.sqlite), if present."""
        p = self._repo.path.parent / "discovery-index.sqlite"
        if p.is_file():
            return sqlite3.connect(str(p))
        return None

    def search(self, text, host=None, area=None, status=None):
        r = self._repo
        text = (text or "").strip()
        if not text:
            return []
        # Use the fts table when it is populated; otherwise LIKE over claim/question/excerpt.
        like = f"%{text}%"
        sql = ("SELECT id, area, question, claim, status, source_title, excerpt FROM evidence "
               "WHERE (claim LIKE ? OR question LIKE ? OR excerpt LIKE ?)")
        params = [like, like, like]
        if host is not None:
            sql += " AND source_title LIKE ?"; params.append(f"%{host}%")
        if area is not None:
            sql += " AND area = ?"; params.append(area)
        if status is not None:
            sql += " AND status = ?"; params.append(status)
        sql += " ORDER BY id"
        cols = ("id", "area", "question", "claim", "status", "source_title", "excerpt")
        return [dict(zip(cols, row)) for row in r.con.execute(sql, params).fetchall()]

    def list(self, status=None, area=None, review_state=None):
        r = self._repo
        sql = ("SELECT id, area, question, claim, status, source_title, page_or_location, "
               "excerpt, confidence, gap_or_action, review_state, created_at, updated_at FROM evidence")
        where, params = [], []
        if status is not None:
            where.append("status = ?"); params.append(status)
        if area is not None:
            where.append("area = ?"); params.append(area)
        if review_state is not None:
            where.append("review_state = ?"); params.append(review_state)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        cols = ("id", "area", "question", "claim", "status", "source_title", "page_or_location",
                "excerpt", "confidence", "gap_or_action", "review_state", "created_at", "updated_at")
        return [dict(zip(cols, row)) for row in r.con.execute(sql, params).fetchall()]


class _ReviewEvent:
    """Light audit log: who, when, what, note, before/after hash. No row snapshot.

    Append-only at the API level — `append` is the only operation exposed; there is no
    `update` or `delete` on this namespace.
    """

    def __init__(self, repo: Repo):
        self._repo = repo

    def append(self, actor, action, subject_type, subject_id, note=None):
        self._repo._require_tx()
        return self._repo._audit(actor, action, subject_type, subject_id, note)


class _ApplicationScope:
    """CRUD for application_scope table (S591).

    Manages many-to-many relationships between applications and hosts with
    membership metadata. Supports owned/peer classification with provenance tracking.
    """

    def __init__(self, repo: Repo):
        self._repo = repo
        self._table = "application_scope"
        self._cols = {"application_key", "host_name", "membership", "basis",
                      "evidence_ids", "source_ref", "review_state", "active"}

    def add(self, application_key: str, host_name: str, membership: str,
            basis: str | None = None, evidence_ids: str | None = None,
            source_ref: str | None = None, review_state: str = 'proposed',
            active: bool = True):
        """Add or update an application-host relationship.

        Args:
            application_key: Registered application identifier (e.g. "tetra-reveloc")
            host_name: Host name or FQDN
            membership: 'owned' or 'peer'
            basis: Classification basis (optional)
            evidence_ids: Source-checked evidence IDs supporting this relationship
            source_ref: Source file/path that established this relationship
            review_state: 'proposed', 'accepted', or 'rejected'
            active: Whether this relationship is currently valid

        Returns dict with insert/update info.
        """
        self._repo._require_tx()
        if not application_key or not host_name:
            raise ValueError("application_key and host_name are required")
        if membership not in {"owned", "peer"}:
            raise ValueError("membership must be 'owned' or 'peer'")
        if review_state not in {"proposed", "accepted", "rejected"}:
            raise ValueError("review_state must be proposed, accepted or rejected")
        cursor = self._repo.con.cursor()
        cursor.execute(
            "SELECT application_key, host_name FROM application_scope "
            "WHERE application_key = ? AND host_name = ?",
            (application_key, host_name)
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """UPDATE application_scope SET 
                   membership = ?, basis = ?, evidence_ids = ?, source_ref = ?,
                   review_state = ?, active = ?
                  WHERE application_key = ? AND host_name = ?""",
                (membership, basis, evidence_ids, source_ref, review_state,
                 1 if active else 0, application_key, host_name)
            )
            return {"action": "updated", "application_key": application_key, "host_name": host_name}
        else:
            cursor.execute(
                """INSERT INTO application_scope 
                   (application_key, host_name, membership, basis, evidence_ids, source_ref, review_state, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (application_key, host_name, membership, basis, evidence_ids, source_ref,
                 review_state, 1 if active else 0)
            )
            return {"action": "inserted", "application_key": application_key, "host_name": host_name}

    def get(self, application_key: str, host_name: str):
        """Get application-host relationship."""
        cursor = self._repo.con.cursor()
        cursor.execute(
            "SELECT * FROM application_scope WHERE application_key = ? AND host_name = ?",
            (application_key, host_name)
        )
        row = cursor.fetchone()
        if row:
            return dict(zip([desc[0] for desc in cursor.description], row))
        return None

    def list_app_hosts(self, application_key: str | None = None, membership: str | None = None,
                       active: bool | None = None):
        """List hosts for an application or filter by membership."""
        cursor = self._repo.con.cursor()
        
        sql = "SELECT application_key, host_name, membership, basis, evidence_ids, source_ref, review_state, active FROM application_scope"
        clauses, params = [], []
        if application_key:
            clauses.append("application_key = ?"); params.append(application_key)
        if membership:
            clauses.append("membership = ?"); params.append(membership)
        if active is not None:
            clauses.append("active = ?"); params.append(1 if active else 0)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY application_key, host_name"
        
        cursor.execute(sql, params)
        return [dict(zip([desc[0] for desc in cursor.description], row)) for row in cursor.fetchall()]

    def count(self):
        """Count all relationships."""
        cursor = self._repo.con.cursor()
        cursor.execute("SELECT COUNT(*) FROM application_scope")
        return cursor.fetchone()[0]

    def owned_count(self):
        """Count owned hosts."""
        cursor = self._repo.con.cursor()
        cursor.execute("""SELECT COUNT(*) FROM application_scope WHERE membership = 'owned'""")
        return cursor.fetchone()[0]

    def peer_count(self):
        """Count peer hosts."""
        cursor = self._repo.con.cursor()
        cursor.execute("""SELECT COUNT(*) FROM application_scope WHERE membership = 'peer'""")
        return cursor.fetchone()[0]

    def active_count(self):
        """Count active relationships."""
        cursor = self._repo.con.cursor()
        cursor.execute("""SELECT COUNT(*) FROM application_scope WHERE active = 1""")
        return cursor.fetchone()[0]
