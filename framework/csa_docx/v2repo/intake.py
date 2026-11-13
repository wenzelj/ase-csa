"""S585: `r.intake`, `r.leads` and `r.gap_checks` — intake state, leads and gap checks as tables.

Replaces the v1 file soup in `csa-work/intake/` (`latest.json`, per-record JSON,
per-file checkpoints, `.evidence.md`, `leads.jsonl`, `gap-check-latest.json`):
one `intake_record` row per run, one `intake_file` row per file, one `lead` row
per question, one `gap_check` row per sweep. Every mutation requires
`with r.tx():` and appends a `review_event` row. The `.evidence.md` report
format is unchanged by this story (S588 decides what it becomes).

ID conventions (documented here, the schema is fixed in S582):

- `intake_record.id`: `I-<compact UTC timestamp>` (YYYYMMDD, HHMMSS — same
  clock as the pre-mutation backup file names) with a per-repo counter for
  repeats inside one second — e.g. `I-20261111-105841.2`.
- `lead.id`: `L-<n:06d>`, the next free number after the existing
  `L-(\\d{6,})` rows — the same `L-NNNNNN` convention the v1 `leads.jsonl`
  store uses (`csa_docx/leads.py`).
- `gap_check.id`: `G-<n:06d>`, the next free number.
- `dr_id`: a caller-supplied stable gap ID (e.g. `DR-<area>-<nn>`); it is
  appended to the `lead` row's `searched_scope` (the fixed schema has no
  dedicated column) and stored in its own column on `gap_check`;
  `list(dr_id=...)` filters on the stored text.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# ID helpers


def _next_seq(con, table: str, pattern: re.Pattern) -> int:
    top = 0
    for (existing,) in con.execute(f"SELECT id FROM {table}"):
        m = pattern.fullmatch(existing or "")
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


_LEAD_ID_RE = re.compile(r"L-(\d{6,})")
_GAP_CHECK_ID_RE = re.compile(r"G-(\d{6,})")

_LEAD_COLS = ("id", "question", "searched_scope", "state", "evidence_ids")
_RECORD_COLS = ("id", "started_at", "finished_at", "file_count", "row_count")
_FILE_COLS = ("record_id", "rel_path", "sha256", "status", "rows_added", "error")
_GAP_CHECK_COLS = ("id", "ts", "dr_id", "text", "leads_found")

_LEAD_STATES = ("open", "resolved", "not_an_answer", "retired")


class _Intake:
    """`r.intake` — one `intake_record` row per run, one `intake_file` row per file.

    `start(files)` must be called inside `with r.tx():`; `complete_file` the same.
    A record finishes (its `finished_at` / `row_count` are set) the moment its
    last pending file is completed — a failed file counts as completed.
    """

    def __init__(self, repo):
        self._repo = repo

    # --------------------------------------------------------------------- start
    def start(self, files, actor=None, note=None) -> str:
        r = self._repo
        r._require_tx()
        con = r.con
        files = list(files)
        if not files:
            raise ValueError("intake.start: files is required (non-empty list of dicts)")
        seen = set()
        for f in files:
            if not isinstance(f, dict):
                raise ValueError("intake.start: every file entry must be a dict with a 'rel_path'")
            rel = f.get("rel_path")
            if not rel:
                raise ValueError("intake.start: every file entry must have a 'rel_path'")
            if rel in seen:
                raise ValueError(f"intake.start: duplicate rel_path {rel!r}")
            seen.add(rel)

        ts = r._now()
        date = ts[0:4] + ts[5:7] + ts[7:9]           # YYYY, MM, DD
        clock = ts.split("T")[1][:8].replace(":", "")  # HH:MM:SS -> HHMMSS
        prefix = f"I-{date}-{clock}."
        top = 0
        for (existing,) in con.execute("SELECT id FROM intake_record WHERE id LIKE ?",
                                      (prefix + "%",)):
            n = int(existing.rsplit(".", 1)[1])
            if n > top:
                top = n
        record_id = f"{prefix}{top + 1}"
        con.execute(
            "INSERT INTO intake_record (id, started_at, file_count) VALUES (?, ?, ?)",
            (record_id, ts, len(files)),
        )
        for f in files:
            con.execute(
                "INSERT INTO intake_file (record_id, rel_path, sha256, status) "
                "VALUES (?, ?, ?, 'pending')",
                (record_id, f["rel_path"], f.get("sha256")),
            )
        r._audit(actor, "intake.start", "intake_record", record_id, note)
        return record_id

    # ------------------------------------------------------------- complete_file
    def complete_file(self, record_id, rel_path, rows_added=0, graph_items=None,
                      error=None, actor=None, note=None):
        """Mark one file of a record as `processed` (or `failed` when `error` is set).

        Completing the record's last pending file also finishes the record:
        `intake_record.finished_at` is set and `row_count` becomes the sum of
        the files' `rows_added`.
        """
        r = self._repo
        r._require_tx()
        con = r.con
        rec = con.execute("SELECT id FROM intake_record WHERE id=?", (record_id,)).fetchone()
        if not rec:
            raise KeyError(record_id)
        row = con.execute(
            "SELECT record_id, rel_path, status FROM intake_file WHERE record_id=? AND rel_path=?",
            (record_id, rel_path)).fetchone()
        if not row:
            raise KeyError(f"intake.complete_file: {record_id} has no file {rel_path!r}")
        status = "failed" if error else "processed"
        con.execute(
            "UPDATE intake_file SET status=?, rows_added=?, error=? WHERE record_id=? AND rel_path=?",
            (status, int(rows_added or 0), error, record_id, rel_path),
        )
        remaining = con.execute(
            "SELECT COUNT(*) FROM intake_file WHERE record_id=? AND status='pending'",
            (record_id,)).fetchone()[0]
        if remaining == 0:
            total = con.execute(
                "SELECT COALESCE(SUM(rows_added), 0) FROM intake_file WHERE record_id=?",
                (record_id,)).fetchone()[0]
            con.execute(
                "UPDATE intake_record SET finished_at=?, row_count=? WHERE id=?",
                (r._now(), total, record_id),
            )
        r._audit(actor, f"intake.complete_file:{status}", "intake_file",
                 f"{record_id}/{rel_path}", note or (error or None))

    # ---------------------------------------------------- generic CRUD surface
    # The framework's namespaces expose `create` / `get` / `update` / `list` as a
    # minimum surface (see test_v2repo_tx). For intake the concrete methods are
    # `start` / `complete_file` / `pending` / `latest` / `records`; the generic
    # names below are thin aliases so both interfaces work.
    def create(self, files, actor=None, note=None) -> str:
        """Alias for `start` — begins an intake run inside the active transaction."""
        return self.start(files, actor=actor, note=note)

    def get(self, record_id):
        """Alias for a lookup by record id — returns one `intake_record` row."""
        for row in self.records():
            if row["id"] == record_id:
                return row
        raise KeyError(record_id)

    def update(self, record_id, **fields):
        """Refused: `intake_record` rows are mutated only through `complete_file`."""
        raise ValueError(
            "intake.update: not supported — use `complete_file` to mark a file done"
        )

    def list(self, **where) -> list[dict]:
        """Alias for `records()` — all records, newest first."""
        return self.records()

    # ------------------------------------------------------------------- reads
    def pending(self, record_id=None) -> list[dict]:
        r = self._repo
        con = r.con
        sql = "SELECT * FROM intake_file WHERE status='pending'"
        params: list = []
        if record_id is not None:
            sql += " AND record_id=?"
            params.append(record_id)
        sql += " ORDER BY record_id, rel_path"
        return [dict(zip(_FILE_COLS, row)) for row in con.execute(sql, params).fetchall()]

    def latest(self):
        r = self._repo
        row = r.con.execute(
            "SELECT * FROM intake_record ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return dict(zip(_RECORD_COLS, row))

    def records(self) -> list[dict]:
        """All records, newest first.

        The record id embeds the UTC timestamp (`I-YYYYMMDD-HHMMSS.N`), so
        sorting by `(started_at, id) DESC` is monotonic even when two records
        share a second.
        """
        r = self._repo
        rows = r.con.execute(
            "SELECT * FROM intake_record ORDER BY started_at DESC, id DESC").fetchall()
        return [dict(zip(_RECORD_COLS, row)) for row in rows]


class _Leads:
    """`r.leads` — open questions with a state machine.

    States: `open` → `resolved` | `not_an_answer` | `retired`. Once a lead is no
    longer `open`, `resolve` / `mark_not_an_answer` / `retire` refuse it (raise
    `ValueError`) — a second `resolve` is therefore an error, not a no-op, and
    the audit trail never carries a silent overwrite.
    """

    def __init__(self, repo):
        self._repo = repo

    def create(self, question, searched_scope, dr_id=None, actor=None, note=None) -> str:
        r = self._repo
        r._require_tx()
        con = r.con
        if not question or not str(question).strip():
            raise ValueError("leads.create: question is required")
        if not searched_scope or not str(searched_scope).strip():
            raise ValueError("leads.create: searched_scope is required")
        lead_id = f"L-{_next_seq(con, 'lead', _LEAD_ID_RE):06d}"
        scope = str(searched_scope).strip()
        if dr_id:
            scope = f"{scope} (dr: {dr_id})"
        con.execute(
            "INSERT INTO lead (id, question, searched_scope, state) VALUES (?, ?, ?, 'open')",
            (lead_id, str(question).strip(), scope),
        )
        r._audit(actor, "leads.create", "lead", lead_id, note)
        return lead_id

    def get(self, lead_id):
        r = self._repo
        row = r.con.execute("SELECT * FROM lead WHERE id=?", (lead_id,)).fetchone()
        if not row:
            raise KeyError(lead_id)
        return dict(zip(_LEAD_COLS, row))

    def _require_open(self, lead_id, action: str) -> dict:
        row = self.get(lead_id)
        if row["state"] != "open":
            raise ValueError(
                f"leads.{action}: lead {lead_id} is already {row['state']!r} — "
                "a lead leaves `open` exactly once"
            )
        return row

    def resolve(self, lead_id, evidence_ids, by=None, note=None):
        r = self._repo
        r._require_tx()
        self._require_open(lead_id, "resolve")
        ids = list(evidence_ids or [])
        con = r.con
        con.execute("UPDATE lead SET state='resolved', evidence_ids=? WHERE id=?",
                    (";".join(ids), lead_id))
        r._audit(by, "leads.resolve", "lead", lead_id, note or f"evidence: {';'.join(ids) or '(none)'}")

    def mark_not_an_answer(self, lead_id, by=None, note=None):
        r = self._repo
        r._require_tx()
        self._require_open(lead_id, "mark_not_an_answer")
        con = r.con
        con.execute("UPDATE lead SET state='not_an_answer' WHERE id=?", (lead_id,))
        r._audit(by, "leads.mark_not_an_answer", "lead", lead_id, note)

    def retire(self, lead_id, reason, by=None, note=None):
        r = self._repo
        r._require_tx()
        if not reason or not str(reason).strip():
            raise ValueError("leads.retire: reason is required")
        self._require_open(lead_id, "retire")
        con = r.con
        con.execute("UPDATE lead SET state='retired' WHERE id=?", (lead_id,))
        r._audit(by, "leads.retire", "lead", lead_id,
                 note or f"reason: {str(reason).strip()}")

    def update(self, lead_id, **fields):
        """Refused: leads change state only via `resolve` / `mark_not_an_answer` / `retire`."""
        raise ValueError(
            "leads.update: not supported — use `resolve` / `mark_not_an_answer` / `retire`"
        )

    def list(self, state=None, dr_id=None) -> list[dict]:
        r = self._repo
        sql = "SELECT * FROM lead"
        params: list = []
        where = []
        if state is not None:
            if state not in _LEAD_STATES:
                raise ValueError(f"leads.list: unknown state {state!r}")
            where.append("state=?"); params.append(state)
        if dr_id is not None:
            where.append("searched_scope LIKE ?"); params.append(f"%{dr_id}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        return [dict(zip(_LEAD_COLS, row)) for row in r.con.execute(sql, params).fetchall()]


class _GapChecks:
    """`r.gap_checks` — one `gap_check` row per sweep, with the lead IDs it found.

    `run(dr_id, text, leads_found)` stores the sweep; `latest()` returns the
    most recent row, `list(dr_id=None)` all rows for a DR (or all).
    """

    def __init__(self, repo):
        self._repo = repo

    def run(self, dr_id, text, leads_found, actor=None, note=None) -> str:
        r = self._repo
        r._require_tx()
        con = r.con
        ids = list(leads_found or [])
        gap_check_id = f"G-{_next_seq(con, 'gap_check', _GAP_CHECK_ID_RE):06d}"
        con.execute(
            "INSERT INTO gap_check (id, ts, dr_id, text, leads_found) VALUES (?, ?, ?, ?, ?)",
            (gap_check_id, r._now(), dr_id, text, len(ids)),
        )
        # The lead IDs themselves are the `leads_found` list — stored in the
        # note of the audit row (the table holds the count only).
        r._audit(actor, "gap_checks.run", "gap_check", gap_check_id,
                 note or (f"leads: {';'.join(ids)}" if ids else "no leads found"))
        return gap_check_id

    def latest(self):
        r = self._repo
        row = r.con.execute(
            "SELECT * FROM gap_check ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return dict(zip(_GAP_CHECK_COLS, row))

    def list(self, dr_id=None) -> list[dict]:
        r = self._repo
        sql = "SELECT * FROM gap_check"
        params: list = []
        if dr_id is not None:
            sql += " WHERE dr_id=?"
            params.append(dr_id)
        sql += " ORDER BY ts DESC, id DESC"
        return [dict(zip(_GAP_CHECK_COLS, row)) for row in r.con.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Wire the three namespaces into Repo without modifying `__init__.py`.
# (Same pattern as graph.py: patch `Repo.__init__` once, at import time.)
# ---------------------------------------------------------------------------

def _patch_repo():
    from . import Repo as _Repo

    if getattr(_Repo, "_v2repo_intake_patched", False):
        return

    original_init = _Repo.__init__

    def _init(self, path):
        original_init(self, path)
        self.intake = _Intake(self)
        self.leads = _Leads(self)
        self.gap_checks = _GapChecks(self)

    _Repo.__init__ = _init
    _Repo._v2repo_intake_patched = True


_patch_repo()
