"""S586: migrate a project's `csa-work/` into `csa-work-v2/csa.sqlite`.

    python3 -m csa_docx.v2migrate --project-root <root> --v2-dir <dir>

`<root>` is the project folder that holds `csa-work/` (or the `csa-work/` folder itself).
The migration only reads the old tree. It writes `csa.sqlite`, `exports/*.csv` and
`MIGRATION-REPORT.md` into `<dir>`. It is idempotent: every load is an upsert on a stable
key, so a second run updates the rows it finds rather than duplicating them.

Rows that cannot be mapped (blank key, unknown host, duplicate host) are skipped and listed
in the report. `roles.csv` and `zones.csv` are classification rules with no v2 table; they
are counted in the report, not loaded. The `rows` table of the discovery index has no v2
table either and is not copied.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from .v2repo import Repo
from .v2repo import graph as _graph  # noqa: F401  (patches Repo with `r.graph`)

EVIDENCE_HEADERS = ["evidence_id", "csa_area", "question", "claim", "status", "source_title",
                    "source_version", "section", "page_or_location", "evidence_excerpt",
                    "inference_reason", "confidence", "gap_or_action", "review_state"]
_EV_COL = {"evidence_id": "id", "csa_area": "area", "evidence_excerpt": "excerpt"}
# Source columns with no v2 evidence column: not loaded, exported blank.
_EV_DROPPED = ("source_version", "section", "inference_reason")
_EV_LOADED = [h for h in EVIDENCE_HEADERS if h not in _EV_DROPPED]
_EV_STATUS = {"VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND"}
_LEAD_STATES = {"open", "resolved", "not_an_answer", "retired"}
_RECORD_FILE = re.compile(r"^\d{8}T\d{6}Z\.json$")


# ------------------------------------------------------------------ helpers
def _csv_rows(path: Path):
    if not path.is_file():
        return None, []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        return list(rd.fieldnames or []), list(rd)


def _jsonl(path: Path):
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _s(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


class _Report:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.skipped: list[tuple[str, str, str]] = []
        self.notes: list[str] = []

    def add(self, table, n=1):
        self.counts[table] = self.counts.get(table, 0) + n

    def skip(self, source, key, reason):
        self.skipped.append((source, str(key), reason))


class _Hosts:
    """Resolves a name, FQDN or IP found in a source row to a loaded host name."""

    def __init__(self):
        self.names: set[str] = set()
        self.upper: dict[str, str] = {}
        self.ips: dict[str, str] = {}

    def add(self, name):
        self.names.add(name)
        self.upper[name.upper()] = name

    def resolve(self, token):
        t = _s(token)
        if not t:
            return None
        if t in self.names:
            return t
        u = t.upper()
        if u in self.upper:
            return self.upper[u]
        short = u.split(".")[0]
        if "." in t and not re.fullmatch(r"[\d.]+", t) and short in self.upper:
            return self.upper[short]
        return self.ips.get(t)


# ------------------------------------------------------------------ loaders
def _load_evidence(con, cw: Path, rep):
    _hdr, rows = _csv_rows(cw / "evidence-matrix.csv")
    reviews = {}
    for rec in sorted(_jsonl(cw / "evidence-reviews.jsonl"), key=lambda x: str(x.get("at", ""))):
        if rec.get("evidence_id"):
            reviews[str(rec["evidence_id"])] = str(rec.get("state") or "").lower()
    for row in rows:
        eid = _s(row.get("evidence_id"))
        if not eid:
            rep.skip("evidence-matrix.csv", "(blank evidence_id)", "no evidence_id")
            continue
        vals = {_EV_COL.get(h, h): row.get(h) for h in EVIDENCE_HEADERS}
        vals["id"] = eid
        status = (_s(vals.get("status")) or "").upper()
        vals["status"] = status if status in _EV_STATUS else "UNCONFIRMED"
        st = reviews.get(eid)
        vals["review_state"] = ("rejected" if st == "rejected" else
                                "proposed" if st in ("proposed", "pending") else "accepted")
        cols = [_EV_COL.get(h, h) for h in _EV_LOADED]
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        con.execute(
            f"INSERT INTO evidence ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(id) DO UPDATE SET {sets}", [vals[c] for c in cols])
        rep.add("evidence")
    if rows:
        rep.notes.append("evidence-matrix.csv columns source_version, section and inference_reason have no "
                         "v2 evidence column; not loaded, exported blank.")


def _load_hosts(con, cw: Path, rep, hosts: _Hosts):
    hd = cw / "hosts"
    _h, rows = _csv_rows(hd / "hosts.csv")
    seen = set()
    for i, row in enumerate(rows, 2):
        name = _s(row.get("host"))
        if not name:
            rep.skip("hosts/hosts.csv", f"line {i}", "blank host name")
            continue
        if name in seen:
            rep.skip("hosts/hosts.csv", name, "duplicate host name (first row kept)")
            continue
        seen.add(name)
        con.execute(
            "INSERT INTO host (name, role, site, os, status) VALUES (?, ?, ?, ?, 'active') "
            "ON CONFLICT(name) DO UPDATE SET role=excluded.role, site=excluded.site, os=excluded.os, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE host.role IS NOT excluded.role OR host.site IS NOT excluded.site "
            "OR host.os IS NOT excluded.os",
            (name, _s(row.get("role")), _s(row.get("site")), _s(row.get("os"))))
        hosts.add(name)
        rep.add("host")
        for ip in re.split(r"[;,\s]+", row.get("ips") or ""):
            if ip:
                hosts.ips.setdefault(ip, name)

    _h, rows = _csv_rows(hd / "addresses.csv")
    for i, row in enumerate(rows, 2):
        ip = _s(row.get("address"))
        if not ip:
            rep.skip("hosts/addresses.csv", f"line {i}", "blank address")
            continue
        owner = hosts.resolve(row.get("name")) if _s(row.get("name")) else None
        if owner:
            hosts.ips.setdefault(ip, owner)
    # one address row per known IP: addresses.csv scope, hosts.csv ips owner
    scope_of = {}
    for row in rows:
        if _s(row.get("address")):
            scope_of[_s(row["address"])] = _s(row.get("kind"))
    for ip in sorted(set(scope_of) | set(hosts.ips)):
        con.execute(
            "INSERT INTO address (ip, scope, owner_host) VALUES (?, ?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET scope=excluded.scope, owner_host=excluded.owner_host",
            (ip, scope_of.get(ip), hosts.ips.get(ip)))
        rep.add("address")

    _h, rows = _csv_rows(hd / "host_services.csv")
    for i, row in enumerate(rows, 2):
        client = hosts.resolve(row.get("client_host"))
        svc = _s(row.get("service"))
        if not client or not svc:
            rep.skip("hosts/host_services.csv", f"line {i}",
                     "client host not in hosts.csv" if not client else "blank service")
            continue
        prov = (hosts.resolve(row.get("server_host")) or _s(row.get("server_host"))
                or hosts.resolve(row.get("server_ip")) or _s(row.get("server_ip")))
        found = con.execute("SELECT id FROM service WHERE host=? AND name=? AND provider_host IS ?",
                            (client, svc, prov)).fetchone()
        if not found:
            con.execute("INSERT INTO service (host, provider_host, name) VALUES (?, ?, ?)",
                        (client, prov, svc))
        rep.add("service")

    def _flow(src_tok, dst_tok, port, purpose, flow_id, source, key):
        src, dst = hosts.resolve(src_tok), hosts.resolve(dst_tok)
        if not src or not dst:
            rep.skip(source, key, "src not a known host" if not src else "dst not a known host")
            return
        port = _int(port)
        if flow_id is not None:
            con.execute(
                "INSERT INTO flow (id, src_host, dst_host, port, purpose) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET src_host=excluded.src_host, dst_host=excluded.dst_host, "
                "port=excluded.port, purpose=excluded.purpose", (flow_id, src, dst, port, purpose))
        elif not con.execute("SELECT 1 FROM flow WHERE src_host=? AND dst_host=? AND port IS ? AND purpose IS ?",
                             (src, dst, port, purpose)).fetchone():
            con.execute("INSERT INTO flow (src_host, dst_host, port, purpose) VALUES (?, ?, ?, ?)",
                        (src, dst, port, purpose))
        rep.add("flow")

    _h, rows = _csv_rows(hd / "flows.csv")
    for i, row in enumerate(rows, 2):
        fid = _s(row.get("flow_id")) or f"line {i}"
        m = re.search(r"(\d+)$", fid)
        _flow(row.get("src"), row.get("dst"), row.get("port"), _s(row.get("mechanism")),
              int(m.group(1)) if m else None, "hosts/flows.csv", fid)
    _h, rows = _csv_rows(hd / "host_links.csv")
    for i, row in enumerate(rows, 2):
        _flow(row.get("src_host"), row.get("dst_host"), row.get("dst_port"), _s(row.get("basis")),
              None, "hosts/host_links.csv", f"line {i}")

    for name in ("roles.csv", "zones.csv"):
        _h, rows = _csv_rows(hd / name)
        rep.notes.append(f"hosts/{name}: {len(rows)} classification rules read; no v2 table, not loaded.")


def _load_scope(con, cw: Path, rep, application_key: str):
    """Restore application ownership and peer metadata without changing the global graph."""
    rows = _csv_rows(cw / "hosts" / "hosts.csv")[1]
    owned = {r.get("host", "") for r in rows if (_s(r.get("in_scope")) or "").lower() in {"yes", "no"}}
    peers = {r.get("host", "") for r in rows if (_s(r.get("in_scope")) or "").lower() == "peer"}
    for row in rows:
        host = _s(row.get("host"))
        scope = (_s(row.get("in_scope")) or "").lower()
        if not host or scope not in {"yes", "no", "peer"}:
            continue
        membership = "owned" if scope in {"yes", "no"} else "peer"
        active = 1 if membership == "owned" else 0
        con.execute(
            "INSERT INTO application_scope "
            "(application_key, host_name, membership, basis, source_ref, review_state, active) "
            "VALUES (?, ?, ?, ?, ?, 'proposed', ?) "
            "ON CONFLICT(application_key, host_name) DO UPDATE SET membership=excluded.membership, "
            "basis=excluded.basis, source_ref=excluded.source_ref, active=excluded.active",
            (application_key, host, membership, f"hosts.csv:in_scope={scope}", "hosts/hosts.csv", active),
        )
        rep.add("application_scope")

    # A peer is active in the application view only when a loaded flow or service row
    # connects it to an owned host. The global host/flow/service graph is unchanged.
    linked: dict[str, list[str]] = {h: [] for h in peers}
    for src, dst in con.execute("SELECT src_host, dst_host FROM flow"):
        if src in owned and dst in peers:
            linked[dst].append("captured_flow")
        if dst in owned and src in peers:
            linked[src].append("captured_flow")
    for client, provider in con.execute("SELECT host, provider_host FROM service WHERE provider_host IS NOT NULL"):
        if client in owned and provider in peers:
            linked[provider].append("captured_service")
        if provider in owned and client in peers:
            linked[client].append("captured_service")
    for host, bases in linked.items():
        if not bases:
            continue
        basis = ";".join(sorted(set(bases)))
        con.execute(
            "UPDATE application_scope SET active=1, basis=?, review_state='proposed' "
            "WHERE application_key=? AND host_name=?",
            (basis, application_key, host),
        )
        rep.add("application_scope_active_peer")
    rep.notes.append(f"scope {application_key}: owned={len(owned)}, peers={len(peers)}, "
                     f"active_peers={sum(bool(v) for v in linked.values())}")


def _load_graph(con, cw: Path, rep):
    _h, nodes = _csv_rows(cw / "graph" / "nodes.csv")
    for row in nodes:
        nid = _s(row.get("node_id"))
        if not nid:
            rep.skip("graph/nodes.csv", "(blank node_id)", "no node_id")
            continue
        con.execute(
            "INSERT INTO graph_node (node_id, label, kind, evidence_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(node_id) DO UPDATE SET label=excluded.label, kind=excluded.kind, "
            "evidence_ids=excluded.evidence_ids",
            (nid, row.get("label"), row.get("node_type"), row.get("evidence_ids")))
    _h, edges = _csv_rows(cw / "graph" / "edges.csv")
    for row in edges:
        eid = _s(row.get("edge_id"))
        if not eid:
            rep.skip("graph/edges.csv", "(blank edge_id)", "no edge_id")
            continue
        con.execute(
            "INSERT INTO graph_edge (edge_id, src, dst, kind, evidence_ids) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(edge_id) DO UPDATE SET src=excluded.src, dst=excluded.dst, kind=excluded.kind, "
            "evidence_ids=excluded.evidence_ids",
            (eid, row.get("source_node_id"), row.get("target_node_id"),
             row.get("relationship_type"), row.get("evidence_ids")))
    return len(nodes), len(edges)


def _load_intake(con, cw: Path, rep):
    idir = cw / "intake"
    if not idir.is_dir():
        return
    for p in sorted(idir.iterdir()):
        if not (p.is_file() and _RECORD_FILE.match(p.name)):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            rep.skip(f"intake/{p.name}", p.stem, "not valid JSON")
            continue
        if not isinstance(rec, dict):
            rep.skip(f"intake/{p.name}", p.stem, "not a JSON object")
            continue
        rid = _s(rec.get("id")) or p.stem
        n = len(rec.get("added") or []) + len(rec.get("changed") or [])
        con.execute(
            "INSERT INTO intake_record (id, started_at, finished_at, file_count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET started_at=excluded.started_at, "
            "finished_at=excluded.finished_at, file_count=excluded.file_count",
            (rid, rec.get("built_at_utc"), rec.get("built_at_utc"), n))
        rep.add("intake_record")
    known = {r[0] for r in con.execute("SELECT id FROM intake_record")}
    for d in sorted(idir.glob("*.files")):
        for p in sorted(d.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                rep.skip(f"intake/{d.name}/{p.name}", p.stem, "not valid JSON")
                continue
            if not isinstance(rec, dict):
                rep.skip(f"intake/{d.name}/{p.name}", p.stem, "not a JSON object")
                continue
            rid = _s(rec.get("record_id")) or d.name[:-len(".files")]
            rel = _s(rec.get("rel_path"))
            if rid not in known or not rel:
                rep.skip(f"intake/{d.name}/{p.name}", p.stem,
                         "record not in intake/*.json" if rid not in known else "blank rel_path")
                continue
            status = rec.get("status") if rec.get("status") in ("pending", "processed", "failed") else "processed"
            con.execute(
                "INSERT INTO intake_file (record_id, rel_path, sha256, status, rows_added, error) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(record_id, rel_path) DO UPDATE SET "
                "sha256=excluded.sha256, status=excluded.status, rows_added=excluded.rows_added, "
                "error=excluded.error",
                (rid, rel, rec.get("source_sha256") or rec.get("sha256"), status,
                 _int(rec.get("rows_added")) or 0, _s(rec.get("error"))))
            rep.add("intake_file")

    reviews = {}
    for item in _jsonl(idir / "leads-reviews.jsonl"):
        reviews[str(item.get("lead_id", "")).upper()] = item
    for i, rec in enumerate(_jsonl(idir / "leads.jsonl"), 1):
        lid = _s(rec.get("lead_id"))
        if not lid:
            rep.skip("intake/leads.jsonl", f"line {i}", "no lead_id")
            continue
        rv = reviews.get(lid.upper()) or {}
        state = rv.get("state") if rv.get("state") in _LEAD_STATES else "open"
        scope = " ".join(x for x in (_s(rec.get("dr_id")), _s(rec.get("source_ref"))) if x) or None
        con.execute(
            "INSERT INTO lead (id, question, searched_scope, state, evidence_ids) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET question=excluded.question, searched_scope=excluded.searched_scope, "
            "state=excluded.state, evidence_ids=excluded.evidence_ids",
            (lid, rec.get("question"), scope, state, ";".join(rv.get("evidence_ids") or []) or None))
        rep.add("lead")

    gc = idir / "gap-check-latest.json"
    if gc.is_file():
        try:
            data = json.loads(gc.read_text(encoding="utf-8"))
        except ValueError:
            data = None
            rep.skip("intake/gap-check-latest.json", "(file)", "not valid JSON")
        for i, q in enumerate((data or {}).get("questions") or [], 1):
            con.execute(
                "INSERT INTO gap_check (id, ts, dr_id, text, leads_found) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, dr_id=excluded.dr_id, "
                "text=excluded.text, leads_found=excluded.leads_found",
                (f"G-{i:06d}", data.get("checked_at"), q.get("dr_id"), q.get("text"),
                 len(q.get("lead_ids") or [])))
            rep.add("gap_check")


def _load_index(r, con, cw: Path, rep):
    src = cw / "discovery-index.sqlite"
    if not src.is_file():
        rep.notes.append("discovery-index.sqlite not found; indexed_* tables not loaded.")
        return
    ix = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        files = {}
        for fid, rel, sha, size, mtime in ix.execute("SELECT file_id, rel_path, sha1, size, mtime FROM files"):
            if not rel:
                continue
            files[fid] = rel
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime)) if mtime else None
            con.execute(
                "INSERT INTO indexed_file (rel_path, sha256, size, indexed_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(rel_path) DO UPDATE SET sha256=excluded.sha256, size=excluded.size, "
                "indexed_at=excluded.indexed_at", (rel, sha, size, stamp))
            rep.add("indexed_file")
        batch = []
        for cid, fid, a, b, text in ix.execute(
                "SELECT m.chunk_id, m.file_id, m.line_start, m.line_end, c.content "
                "FROM chunk_map m JOIN chunks c ON c.rowid = m.chunk_id"):
            if fid not in files:
                rep.skip("discovery-index.sqlite chunks", f"chunk {cid}", "file not in files table")
                continue
            batch.append((cid, files[fid], f"lines {a}-{b}", text))
        con.executemany(
            "INSERT INTO indexed_chunk (id, rel_path, heading, text) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET rel_path=excluded.rel_path, heading=excluded.heading, "
            "text=excluded.text", batch)
        rep.add("indexed_chunk", len(batch))
        ents = [(k, n, files[f]) for k, n, f in
                ix.execute("SELECT DISTINCT kind, norm, file_id FROM entities") if f in files]
        r.raw_con.executemany("INSERT OR IGNORE INTO entity (kind, norm, file_ref) VALUES (?, ?, ?)", ents)
        rep.add("entity", len(ents))
        rep.notes.append("discovery-index.sqlite `rows` has no v2 table and was not copied.")
    finally:
        ix.close()
    con.execute("DELETE FROM fts")
    con.execute("INSERT INTO fts (chunk_id, rel_path, heading, text) "
                "SELECT id, rel_path, heading, text FROM indexed_chunk")
    rep.add("fts", con.execute("SELECT COUNT(*) FROM fts").fetchone()[0])


# ------------------------------------------------------------------ outputs
def _write_csv(path: Path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)


def _exports(con, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    sel = ", ".join("''" if h in _EV_DROPPED else _EV_COL.get(h, h) for h in EVIDENCE_HEADERS)
    _write_csv(out / "evidence.csv", EVIDENCE_HEADERS,
               con.execute(f"SELECT {sel} FROM evidence ORDER BY rowid"))
    for name, sql, hdr in (
        ("hosts.csv", "SELECT name, role, site, os, status FROM host ORDER BY name",
         ["name", "role", "site", "os", "status"]),
        ("application-scope.csv", "SELECT application_key, host_name, membership, basis, evidence_ids, "
         "source_ref, review_state, active FROM application_scope ORDER BY application_key, host_name",
         ["application_key", "host_name", "membership", "basis", "evidence_ids", "source_ref",
          "review_state", "active"]),
        ("addresses.csv", "SELECT ip, scope, owner_host FROM address ORDER BY ip",
         ["ip", "scope", "owner_host"]),
        ("services.csv", "SELECT id, host, provider_host, port, protocol, name, configured FROM service ORDER BY id",
         ["id", "host", "provider_host", "port", "protocol", "name", "configured"]),
        ("flows.csv", "SELECT id, src_host, dst_host, port, protocol, purpose FROM flow ORDER BY id",
         ["id", "src_host", "dst_host", "port", "protocol", "purpose"]),
        ("leads.csv", "SELECT id, question, searched_scope, state, evidence_ids FROM lead ORDER BY id",
         ["id", "question", "searched_scope", "state", "evidence_ids"]),
        ("graph-nodes.csv", "SELECT node_id, label, kind, evidence_ids FROM graph_node ORDER BY node_id",
         ["node_id", "label", "kind", "evidence_ids"]),
        ("graph-edges.csv", "SELECT edge_id, src, dst, kind, evidence_ids FROM graph_edge ORDER BY edge_id",
         ["edge_id", "src", "dst", "kind", "evidence_ids"]),
        ("intake-files.csv", "SELECT record_id, rel_path, sha256, status, rows_added, error FROM intake_file "
         "ORDER BY record_id, rel_path", ["record_id", "rel_path", "sha256", "status", "rows_added", "error"]),
    ):
        _write_csv(out / name, hdr, con.execute(sql))


def _report(v2: Path, cw: Path, rep: _Report, src_graph, refresh):
    L = ["# Migration report", "",
         f"- Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
         f"- Source: `{cw}`", f"- Target: `{v2 / 'csa.sqlite'}`", "", "## Rows loaded", "",
         "| Table | Rows |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in sorted(rep.counts.items())]
    L += ["", "## Graph refresh", "",
          f"- Source graph (graph/nodes.csv, edges.csv): {src_graph[0]} nodes, {src_graph[1]} edges.",
          f"- After `graph.refresh()`: {refresh['graph_node']} nodes, {refresh['graph_edge']} edges "
          f"(alias {refresh['alias']}, entity {refresh['entity']}).",
          f"- Delta: {refresh['graph_node'] - src_graph[0]:+d} nodes, {refresh['graph_edge'] - src_graph[1]:+d} edges. "
          "The v2 graph is a provider-aware model derived from the core tables, so exact parity with the "
          "old typed graph is not expected.", "", "## Notes", ""]
    L += [f"- {n}" for n in rep.notes] or ["- None."]
    L += ["", f"## Skipped rows ({len(rep.skipped)})", ""]
    if rep.skipped:
        L += ["| Source | Row | Reason |", "| --- | --- | --- |"]
        L += [f"| {s} | {k.replace('|', '/')} | {why} |" for s, k, why in rep.skipped]
    else:
        L.append("None.")
    (v2 / "MIGRATION-REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ entry
def migrate(project_root, v2_dir, application_key: str | None = None) -> dict:
    root = Path(project_root)
    cw = root if root.name == "csa-work" else root / "csa-work"
    v2 = Path(v2_dir)
    if not cw.is_dir():
        return {"status": "ERROR", "error": f"no csa-work folder at {cw}"}
    application_key = application_key or root.parent.name.lower().replace(" ", "-")
    v2.mkdir(parents=True, exist_ok=True)
    rep = _Report()
    hosts = _Hosts()
    r = Repo(v2)
    try:
        with r.tx():
            con = r.con
            _load_evidence(con, cw, rep)
            _load_hosts(con, cw, rep, hosts)
            _load_scope(con, cw, rep, application_key)
            n_src, e_src = _load_graph(r.raw_con, cw, rep)
            _load_intake(con, cw, rep)
            _load_index(r, con, cw, rep)
            refresh = r.graph.refresh(actor="v2migrate")
        _exports(r.con, v2 / "exports")
        rep.add("graph_node", refresh["graph_node"])
        rep.add("graph_edge", refresh["graph_edge"])
        _report(v2, cw, rep, (n_src, e_src), refresh)
        return {"status": "OK", "counts": dict(rep.counts), "skipped": len(rep.skipped),
                "refresh": refresh, "source_graph": {"nodes": n_src, "edges": e_src},
                "report": str(v2 / "MIGRATION-REPORT.md")}
    finally:
        r.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m csa_docx.v2migrate",
                                 description="Migrate csa-work/ into csa-work-v2/csa.sqlite.")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--v2-dir", required=True)
    ap.add_argument("--application-key", required=False)
    a = ap.parse_args(argv)
    res = migrate(a.project_root, a.v2_dir, a.application_key)
    print(json.dumps(res, indent=2))
    return 0 if res["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
