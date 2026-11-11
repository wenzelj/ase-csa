"""S587: on-demand exports (`r.export.csv` / `md` / `report`). Read-only snapshots.

Exports never mutate the DB: they do not bump `updated_at`, do not append a `review_event`,
and are not auto-refreshed after mutations. The DB stays the single source of truth and each
export is a snapshot taken when it is run.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path


class _Export:
    """`r.export` — `csv(table, out_path, **filters)`, `md(host_name, out_path)`, `report(out_path)`."""

    #: user-facing table name -> sqlite table
    _TABLES = {
        "hosts": "host",
        "evidence": "evidence",
        "addresses": "address",
        "services": "service",
        "flows": "flow",
        "leads": "lead",
        "gap_checks": "gap_check",
        "intake_records": "intake_record",
        "intake_files": "intake_file",
        "graph_nodes": "graph_node",
        "graph_edges": "graph_edge",
        "aliases": "alias",
        "entities": "entity",
        "review_events": "review_event",
        "evidence_sources": "evidence_source",
        "indexed_files": "indexed_file",
    }

    def __init__(self, repo):
        self._repo = repo

    @staticmethod
    def _prepare(out_path) -> Path:
        out = Path(out_path)
        if str(out.parent) not in ("", "."):
            out.parent.mkdir(parents=True, exist_ok=True)
        return out

    def _resolve_table(self, table):
        t = str(table).strip()
        if t not in self._TABLES:
            known = ", ".join(sorted(self._TABLES))
            raise ValueError(f"v2 export: unknown table {t!r}. Known tables: {known}")
        return self._TABLES[t]

    def _table_columns(self, sql_table):
        return [r[1] for r in self._repo.con.execute(f"PRAGMA table_info({sql_table})")]

    # ------------------------------------------------------------- table export
    def csv(self, table, out_path, **filters):
        """Write the named table (or a filtered subset) to `out_path` as CSV.

        `**filters` are column=value pairs; a column the table lacks raises `ValueError`.
        """
        sql_table = self._resolve_table(table)
        cols = self._table_columns(sql_table)
        where, params = [], []
        for k, v in filters.items():
            if k not in cols:
                raise ValueError(
                    f"v2 export: {table!r} has no column {k!r}. Columns: {', '.join(cols)}"
                )
            where.append(f"{k} = ?")
            params.append(v)
        sql = f"SELECT * FROM {sql_table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rowid"
        rows = self._repo.con.execute(sql, params).fetchall()
        out = self._prepare(out_path)
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(cols)
            for row in rows:
                w.writerow(["" if v is None else v for v in row])
        return {"status": "READY", "table": table, "rows": len(rows), "out": str(out)}

    # ------------------------------------------------------------- host card
    def md(self, host_name, out_path):
        """Write a per-host Markdown card: role, site, OS, status, addresses, services, flows
        and the evidence rows that cite the host. Raises `KeyError` for an unknown host."""
        r = self._repo
        h = r.hosts.get(host_name)
        con = r.con
        addrs = con.execute("SELECT ip, scope FROM address WHERE owner_host = ? ORDER BY ip",
                            (host_name,)).fetchall()
        svcs = con.execute("SELECT port, protocol, name, configured FROM service WHERE host = ? "
                           "ORDER BY port, protocol", (host_name,)).fetchall()
        fl = con.execute("SELECT src_host, dst_host, port, protocol, purpose FROM flow "
                         "WHERE src_host = ? OR dst_host = ? ORDER BY id",
                         (host_name, host_name)).fetchall()
        like = f"%{host_name}%"
        evs = con.execute(
            "SELECT id, area, claim, status, source_title, excerpt FROM evidence "
            "WHERE (claim LIKE ? OR question LIKE ? OR source_title LIKE ?) ORDER BY id",
            (like, like, like)).fetchall()
        out = self._prepare(out_path)
        lines = [f"# {host_name}", "",
                 f"- **role:** {h['role'] or '—'}",
                 f"- **site:** {h['site'] or '—'}",
                 f"- **OS:** {h['os'] or '—'}",
                 f"- **status:** {h['status'] or '—'}"]
        lines += ["", "## Addresses"]
        if addrs:
            lines += ["| IP | scope |", "| --- | --- |"]
            lines += [f"| {ip or '—'} | {scope or '—'} |" for ip, scope in addrs]
        else:
            lines.append("_no addresses recorded_")
        lines += ["", "## Services"]
        if svcs:
            lines += ["| port | protocol | name | configured |", "| --- | --- | --- | --- |"]
            for port, proto, name, cfg in svcs:
                lines.append(f"| {port if port is not None else '—'} | {proto or '—'} | {name or '—'} | {cfg} |")
        else:
            lines.append("_no services recorded_")
        lines += ["", "## Flows"]
        if fl:
            lines += ["| direction | peer | port | protocol | purpose |", "| --- | --- | --- | --- | --- |"]
            for src, dst, port, proto, purpose in fl:
                direction = "out" if src == host_name else "in"
                peer = dst if src == host_name else src
                lines.append(f"| {direction} | {peer} | {port if port is not None else '—'} | "
                             f"{proto or '—'} | {purpose or '—'} |")
        else:
            lines.append("_no flows recorded_")
        lines += ["", "## Evidence citing this host"]
        if evs:
            for eid, area, claim, status, source, excerpt in evs:
                lines.append(f"- **{eid}** — {claim or ''} ({status or '—'}; {area or '—'})"
                             + (f" — {excerpt}" if excerpt else ""))
        else:
            lines.append("_no evidence rows cite this host_")
        lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return {"status": "READY", "host": host_name, "out": str(out)}

    # ------------------------------------------------------------- summary
    def report(self, out_path):
        """Write a one-page Markdown summary: counts per table, last migration, last graph
        refresh, pending intake files and open leads."""
        con = self._repo.con
        counts = {name: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for name, t in sorted(self._TABLES.items())}

        def last_event(pattern):
            row = con.execute("SELECT ts FROM review_event WHERE action LIKE ? ORDER BY id DESC LIMIT 1",
                              (pattern,)).fetchone()
            return row[0] if row else None

        last_migration = last_event("%migrat%")
        last_graph_refresh = last_event("graph.refresh")
        pending = con.execute(
            "SELECT record_id, rel_path, status FROM intake_file WHERE status = 'pending' "
            "ORDER BY record_id, rel_path").fetchall()
        open_leads = con.execute("SELECT id, question FROM lead WHERE state = 'open' ORDER BY id").fetchall()
        out = self._prepare(out_path)
        lines = ["# csa-work-v2 report", "", "## Table counts", "",
                 "| table | rows |", "| --- | --- |"]
        lines += [f"| {name} | {counts[name]} |" for name in sorted(counts)]
        lines += ["", "## State",
                  f"- last migration: {last_migration or '—'}",
                  f"- last graph refresh: {last_graph_refresh or '—'}",
                  "", "## Pending intake files"]
        lines += ([f"- {rid}: {rel} ({st})" for rid, rel, st in pending] or ["_none_"])
        lines += ["", "## Open leads"]
        lines += ([f"- {lid}: {q}" for lid, q in open_leads] or ["_none_"])
        lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return {"status": "READY", "out": str(out), "counts": counts}
