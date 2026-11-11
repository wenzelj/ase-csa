"""csa-work-v2 repository: one SQLite store (csa-work-v2/csa.sqlite) with a small CRUD API.

The schema lives in `schema.sql` (single source of truth for table shapes). Every mutation
goes through `Repo.tx()`, which commits or rolls back all-or-nothing and writes a timestamped
pre-mutation copy of the DB into a `backups/` sibling folder before the first write of the
transaction. Later stories (S583-S585) add behaviour to the `hosts` / `evidence` / `intake` /
`leads` namespaces; `backup()` and `export` land in S587. Nothing in the framework points at
csa-work-v2/ until the switch story.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DB_NAME = "csa.sqlite"
BACKUPS_DIR = "backups"


class _Namespace:
    """CRUD stub namespace (S583-S585 add the real logic).

    Only `create` / `get` / `update` / `list` exist: the API deliberately exposes no
    `delete` — reject / retire set a status, and `review_event` keeps the audit trail.
    """

    def __init__(self, repo: "Repo", table: str):
        self._repo = repo
        self._table = table

    def create(self, **fields):
        raise NotImplementedError("added in S583-S585")

    def get(self, key):
        raise NotImplementedError("added in S583-S585")

    def update(self, key, **fields):
        raise NotImplementedError("added in S583-S585")

    def list(self, **where):
        raise NotImplementedError("added in S583-S585")


class _Export:
    """On-demand CSV/MD exports (real work in S587). Not auto-refreshed."""

    def __init__(self, repo: "Repo"):
        self._repo = repo

    def csv(self, table, out_path):
        raise NotImplementedError("added in S587")

    def md(self, table, key, out_path):
        raise NotImplementedError("added in S587")


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
        self._in_tx = False
        self.backup_dir = self.path.parent / BACKUPS_DIR
        self.hosts = _Namespace(self, "host")
        self.evidence = _Namespace(self, "evidence")
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

    def _apply_schema(self):
        """Apply `schema.sql` (idempotent), then create the `fts` table — FTS5 when
        available, a plain-text fallback otherwise. Re-creating `fts` when its shape has
        changed (e.g. FTS5 was added after a plain-text build) is safe because `fts` is a
        read-only mirror and is rebuilt by the ingest rewrite (S584+)."""
        con = self.con
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
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


class _ReviewEvent:
    """Light audit log: who, when, what, note, before/after hash. No row snapshot.

    Append-only at the API level — `append` is the only operation exposed; there is no
    `update` or `delete` on this namespace.
    """

    def __init__(self, repo: Repo):
        self._repo = repo

    def append(self, actor, action, subject_type, subject_id, note=None):
        con = self._repo.con
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        con.execute(
            "INSERT INTO review_event (ts, actor, action, subject_type, subject_id, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, actor, action, subject_type, subject_id, note),
        )
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]
