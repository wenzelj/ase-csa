import csv
import json
import sqlite3

import pytest

from csa_docx.v2migrate import EVIDENCE_HEADERS, migrate
from csa_docx.v2repo import Repo


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture
def project(tmp_path):
    cw = tmp_path / "proj" / "csa-work"
    ev = {h: "" for h in EVIDENCE_HEADERS}
    rows = []
    for i, (st, claim) in enumerate([("VERIFIED", "SRV1 is a server"), ("odd", "SRV2 is a server")], 1):
        d = dict(ev, evidence_id=f"E-{i:03d}", csa_area="network", claim=claim, status=st,
                 evidence_excerpt="x", review_state="pending")
        rows.append([d[h] for h in EVIDENCE_HEADERS])
    _csv(cw / "evidence-matrix.csv", EVIDENCE_HEADERS, rows)
    _w(cw / "evidence-reviews.jsonl",
       json.dumps({"evidence_id": "E-002", "state": "rejected", "at": "2026-01-01"}) + "\n")
    _csv(cw / "hosts" / "hosts.csv", ["host", "role", "site", "ips"],
         [["SRV1", "app", "A", "10.0.0.1"], ["SRV2", "dc", "A", "10.0.0.2"], ["SRV1", "dup", "", ""], ["", "x", "", ""]])
    _csv(cw / "hosts" / "addresses.csv", ["address", "name", "kind"], [["8.8.8.8", "name not captured", "public"]])
    _csv(cw / "hosts" / "host_services.csv", ["client_host", "service", "server_ip", "server_host"],
         [["SRV1", "dns", "10.0.0.2", "SRV2"], ["GHOST", "time", "", "SRV2"]])
    _csv(cw / "hosts" / "flows.csv", ["flow_id", "mechanism", "src", "dst", "port"],
         [["F001", "sql", "SRV1", "10.0.0.2", "1433"], ["F002", "web", "SRV1", "8.8.8.8", "443"]])
    _csv(cw / "hosts" / "host_links.csv", ["src_host", "dst_host", "dst_port", "basis"], [["SRV2", "SRV1", "53", "seen"]])
    _csv(cw / "hosts" / "roles.csv", ["kind", "match"], [["process", "a.exe"]])
    _csv(cw / "hosts" / "zones.csv", ["zone", "kind"], [["OT", "ot"]])
    _csv(cw / "graph" / "nodes.csv", ["node_id", "label", "node_type"], [["N-001", "SRV1", "host"]])
    _csv(cw / "graph" / "edges.csv", ["edge_id", "source_node_id", "target_node_id", "relationship_type"],
         [["R-001", "N-001", "N-001", "data-flow"]])
    _w(cw / "intake" / "20260101T000000Z.json",
       json.dumps({"id": "20260101T000000Z", "built_at_utc": "2026-01-01T00:00:00Z", "added": [{"rel_path": "a"}]}))
    _w(cw / "intake" / "20260101T000000Z.files" / "f1.json",
       json.dumps({"record_id": "20260101T000000Z", "rel_path": "a.txt", "source_sha256": "abc"}))
    _w(cw / "intake" / "leads.jsonl", json.dumps({"lead_id": "L-000001", "question": "q?", "dr_id": "DR-1"}) + "\n")
    _w(cw / "intake" / "gap-check-latest.json",
       json.dumps({"checked_at": "2026-01-02T00:00:00Z",
                   "questions": [{"dr_id": "DR-1", "text": "what?", "lead_ids": ["L-000001"]}]}))
    ix = sqlite3.connect(cw / "discovery-index.sqlite")
    ix.executescript("""
      CREATE TABLE files(file_id INTEGER PRIMARY KEY, rel_path TEXT, sha1 TEXT, size INTEGER, mtime REAL);
      CREATE TABLE rows(file_id INTEGER);
      CREATE TABLE chunks(rowid INTEGER PRIMARY KEY, content TEXT);
      CREATE TABLE chunk_map(chunk_id INTEGER PRIMARY KEY, file_id INTEGER, line_start INTEGER, line_end INTEGER);
      CREATE TABLE entities(entity_id INTEGER PRIMARY KEY, kind TEXT, value TEXT, norm TEXT, file_id INTEGER);
      INSERT INTO files VALUES (1, 'cap/a.txt', 'sha', 10, 1.0);
      INSERT INTO chunks VALUES (1, 'SRV1 resolves via 10.0.0.2');
      INSERT INTO chunk_map VALUES (1, 1, 1, 3);
      INSERT INTO entities VALUES (1, 'ip', '10.0.0.2', '10.0.0.2', 1);
    """)
    ix.commit()
    ix.close()
    return tmp_path / "proj"


APP_KEY = "tetra-reveloc"


def _count(db, table):
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_migrate_loads_every_table(project, tmp_path):
    v2 = tmp_path / "v2"
    res = migrate(project, v2, APP_KEY)
    assert res["status"] == "OK"
    db = v2 / "csa.sqlite"
    assert _count(db, "evidence") == 2
    con = sqlite3.connect(db)
    states = dict(con.execute("SELECT id, review_state FROM evidence"))
    assert states == {"E-001": "accepted", "E-002": "rejected"}
    assert con.execute("SELECT status FROM evidence WHERE id='E-002'").fetchone()[0] == "UNCONFIRMED"
    assert _count(db, "host") == 2
    assert con.execute("SELECT owner_host FROM address WHERE ip='10.0.0.2'").fetchone()[0] == "SRV2"
    assert _count(db, "service") == 1
    assert con.execute("SELECT provider_host FROM service").fetchone()[0] == "SRV2"
    assert _count(db, "flow") == 2  # F001, host link; F002 (8.8.8.8) skipped
    assert _count(db, "intake_record") == 1 and _count(db, "intake_file") == 1
    assert _count(db, "lead") == 1 and _count(db, "gap_check") == 1
    assert _count(db, "indexed_file") == 1 and _count(db, "indexed_chunk") == 1
    assert con.execute("SELECT COUNT(*) FROM fts WHERE text LIKE '%SRV1%'").fetchone()[0] == 1
    con.close()
    # graph.refresh ran: provider-aware nodes and a dns edge exist
    assert res["refresh"]["graph_node"] > 0
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM graph_edge WHERE kind='dns'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM graph_node WHERE node_id LIKE 'N-%'").fetchone()[0] == 0
    con.close()
    for name in ("evidence", "hosts", "addresses", "services", "flows", "leads",
                 "graph-nodes", "graph-edges", "intake-files"):
        assert (v2 / "exports" / f"{name}.csv").is_file()
    with (v2 / "exports" / "evidence.csv").open(encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == EVIDENCE_HEADERS
    report = (v2 / "MIGRATION-REPORT.md").read_text(encoding="utf-8")
    assert "duplicate host name" in report and "GHOST" not in report
    assert "host_services.csv" in report and "F002" in report


def test_migrate_is_idempotent(project, tmp_path):
    v2 = tmp_path / "v2"
    migrate(project, v2, APP_KEY)
    db = v2 / "csa.sqlite"
    tables = ("evidence", "host", "address", "service", "flow", "intake_record", "intake_file",
              "lead", "gap_check", "indexed_file", "indexed_chunk", "fts", "graph_node", "graph_edge")
    before = {t: _count(db, t) for t in tables}
    migrate(project, v2, APP_KEY)
    assert {t: _count(db, t) for t in tables} == before


def test_migrate_never_writes_into_source(project, tmp_path):
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    migrate(project, tmp_path / "v2", APP_KEY)
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == before
    Repo(tmp_path / "v2").close()
