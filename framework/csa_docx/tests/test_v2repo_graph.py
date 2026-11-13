"""S584: `r.graph` — the derived-view graph over the core tables.

Covers: refresh() produces expected nodes and edges; idempotency; determinism;
read-only guard on derived tables; `nodes(host=...)` and `edges(kind=...)` filters;
`review_event` row per refresh.
"""
import tempfile
from pathlib import Path

import pytest

from csa_docx.v2repo import Repo
import csa_docx.v2repo.graph  # noqa: F401  # registers Repo.graph + guard


def _repo(tmp_path):
    return Repo(tmp_path / "csa.sqlite")


def _seed(r: Repo):
    """Populate a small set of hosts, services, flows, evidence, address and discovery rows."""
    con = r.con
    with r.tx():
        r.hosts.create("ROTPRDREV101", role="server", site="Site A")
        r.hosts.create("ROTPRDDB101", role="database", site="Site A")
        r.hosts.create("ROTPRDMON101", role="monitoring", site="Site B")
        # addresses
        con.execute("INSERT INTO address (ip, scope, owner_host) VALUES ('10.1.0.101', 'lan', 'ROTPRDREV101')")
        con.execute("INSERT INTO address (ip, scope, owner_host) VALUES ('10.1.0.201', 'lan', 'ROTPRDDB101')")
        # services
        con.execute("INSERT INTO service (host, port, protocol, name, configured) VALUES ('ROTPRDREV101', 1433, 'tcp', 'SQL Server', 1)")
        con.execute("INSERT INTO service (host, port, protocol, name, configured) VALUES ('ROTPRDDB101', 445, 'tcp', 'SMB', 1)")
        # flows
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) VALUES ('ROTPRDREV101', 'ROTPRDDB101', 1433, 'tcp', 'db access')")
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) VALUES ('ROTPRDMON101', 'ROTPRDREV101', 445, 'tcp', 'monitoring')")
        # evidence with link grammar claim
        r.evidence.create(
            claim="ROTPRDREV101 has an established connection to ROTPRDDB101 on port 1433, served by sqlservr on ROTPRDDB101.",
            source_title="cap/001_connections.txt",
            excerpt="TCP  10.1.0.101:1433  10.1.0.201:49832  ESTABLISHED",
            status="VERIFIED",
        )
        # discovery index mirror
        con.execute("INSERT INTO indexed_file (rel_path) VALUES ('cap/001_connections.txt')")
        con.execute(
            "INSERT INTO indexed_chunk (rel_path, heading, text) VALUES "
            "('cap/001_connections.txt', 'Connections', 'Host : ROTPRDREV101\nTCP  10.1.0.101:1433  10.1.0.201:49832  ESTABLISHED')")


def _snapshot(con):
    """Return a canonical (order-independent) snapshot of all four derived tables."""
    return (
        tuple(sorted(con.execute("SELECT node_id, label, kind, evidence_ids FROM graph_node").fetchall())),
        tuple(sorted(con.execute("SELECT edge_id, src, dst, kind, evidence_ids FROM graph_edge").fetchall())),
        tuple(sorted(con.execute("SELECT alias, subject_type, subject_id, scope FROM alias").fetchall())),
        tuple(sorted(con.execute("SELECT kind, norm, file_ref FROM entity").fetchall())),
    )


# --------------------------------------------------------------------------- refresh basics

def test_refresh_produces_expected_nodes(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        res = r.graph.refresh(actor="s584-test")
    nodes = r.graph.nodes()
    ids = {n["node_id"] for n in nodes}
    # one node per active host
    assert "host/ROTPRDREV101" in ids
    assert "host/ROTPRDDB101" in ids
    assert "host/ROTPRDMON101" in ids
    # one node per distinct service.name
    assert "service/SQL Server" in ids
    assert "service/SMB" in ids
    # host label format: NAME (role, site)
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id["host/ROTPRDREV101"]["label"] == "ROTPRDREV101 (server, Site A)"
    assert by_id["host/ROTPRDDB101"]["label"] == "ROTPRDDB101 (database, Site A)"
    # node kinds
    assert by_id["host/ROTPRDREV101"]["kind"] == "host"
    assert by_id["service/SQL Server"]["kind"] == "service"
    r.close()


def test_refresh_produces_expected_edges(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    edges = r.graph.edges()
    # flow edges: one per distinct (src, dst) pair in the flow table
    flow_edges = [e for e in edges if e["kind"] == "flow"]
    flow_pairs = {(e["src"], e["dst"]) for e in flow_edges}
    assert ("host/ROTPRDREV101", "host/ROTPRDDB101") in flow_pairs
    assert ("host/ROTPRDMON101", "host/ROTPRDREV101") in flow_pairs
    # the evidence link row adds an edge citing the evidence ID
    cited = [e for e in flow_edges if e["evidence_ids"]]
    assert any("E-001" in e["evidence_ids"] for e in cited)
    # runs edges: one per (host, service.name)
    runs_edges = [e for e in edges if e["kind"] == "runs"]
    runs_pairs = {(e["src"], e["dst"]) for e in runs_edges}
    assert ("host/ROTPRDREV101", "service/SQL Server") in runs_pairs
    assert ("host/ROTPRDDB101", "service/SMB") in runs_pairs
    r.close()


def test_refresh_produces_alias_and_entity(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    con = r.con
    alias = con.execute("SELECT alias, subject_type, subject_id, scope FROM alias ORDER BY alias").fetchall()
    alias_map = {(a[0], a[2]): a[3] for a in alias}
    # host name -> itself
    assert ("ROTPRDREV101", "ROTPRDREV101") in alias_map
    # ip -> owner host
    assert alias_map.get(("10.1.0.101", "ROTPRDREV101")) == "lan"
    assert alias_map.get(("10.1.0.201", "ROTPRDDB101")) == "lan"
    # entity: at least the host name from the indexed chunk text
    entity = con.execute("SELECT kind, norm, file_ref FROM entity").fetchall()
    host_entities = [(e[0], e[1]) for e in entity if e[0] == "host"]
    assert ("host", "ROTPRDREV101") in host_entities  # host norm is upper-case via index_entities
    r.close()


# --------------------------------------------------------------------------- idempotency

def test_refresh_is_idempotent(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    snap1 = _snapshot(r.con)
    with r.tx():
        r.graph.refresh()
    snap2 = _snapshot(r.con)
    assert snap1 == snap2
    r.close()


# --------------------------------------------------------------------------- determinism

def test_refresh_is_deterministic(tmp_path):
    """Two repos seeded with the same core data produce identical derived tables."""
    r1 = _repo(tmp_path / "a")
    _seed(r1)
    with r1.tx():
        r1.graph.refresh()
    snap1 = _snapshot(r1.con)
    r1.close()

    r2 = _repo(tmp_path / "b")
    _seed(r2)
    with r2.tx():
        r2.graph.refresh()
    snap2 = _snapshot(r2.con)
    r2.close()

    assert snap1 == snap2


# --------------------------------------------------------------------------- read-only guard

def test_direct_insert_into_graph_node_raises(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    con = r.con
    with pytest.raises(RuntimeError, match="read-only"):
        con.execute("INSERT INTO graph_node (node_id, label, kind, evidence_ids) VALUES ('x', 'x', 'x', 'x')")
    with pytest.raises(RuntimeError, match="read-only"):
        con.executemany("INSERT INTO graph_edge (edge_id, src, dst, kind, evidence_ids) VALUES (?, ?, ?, ?, ?)",
                        [("x", "x", "x", "x", "x")])
    with pytest.raises(RuntimeError, match="read-only"):
        con.execute("UPDATE alias SET scope='x' WHERE alias='x'")
    with pytest.raises(RuntimeError, match="read-only"):
        con.execute("DELETE FROM entity WHERE kind='x'")
    r.close()


def test_direct_insert_into_graph_edge_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="read-only"):
        r.con.execute("INSERT INTO graph_edge (edge_id, src, dst, kind, evidence_ids) VALUES ('x','x','x','x','x')")
    r.close()


def test_direct_insert_into_alias_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="read-only"):
        r.con.execute("INSERT INTO alias (alias, subject_type, subject_id, scope) VALUES ('x','x','x','x')")
    r.close()


def test_direct_insert_into_entity_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="read-only"):
        r.con.execute("INSERT INTO entity (kind, norm, file_ref) VALUES ('x','x','x')")
    r.close()


# --------------------------------------------------------------------------- filters

def test_nodes_host_filter(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    nodes = r.graph.nodes(host="ROTPRDREV101")
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "host/ROTPRDREV101"
    # a host that exists in the seed
    nodes2 = r.graph.nodes(host="ROTPRDDB101")
    assert len(nodes2) == 1
    assert nodes2[0]["node_id"] == "host/ROTPRDDB101"
    r.close()


def test_nodes_kind_filter(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    hosts = r.graph.nodes(kind="host")
    assert all(n["kind"] == "host" for n in hosts)
    services = r.graph.nodes(kind="service")
    assert all(n["kind"] == "service" for n in services)
    r.close()


def test_edges_kind_filter(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    flow = r.graph.edges(kind="flow")
    assert all(e["kind"] == "flow" for e in flow)
    runs = r.graph.edges(kind="runs")
    assert all(e["kind"] == "runs" for e in runs)
    r.close()


def test_edges_src_filter(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh()
    from_rev = r.graph.edges(src="host/ROTPRDREV101")
    assert all(e["src"] == "host/ROTPRDREV101" for e in from_rev)
    assert any(e["dst"] == "host/ROTPRDDB101" for e in from_rev)
    r.close()


# --------------------------------------------------------------------------- review_event

def test_review_event_row_per_refresh(tmp_path):
    r = _repo(tmp_path)
    _seed(r)
    with r.tx():
        r.graph.refresh(actor="s584-test")
    con = r.con
    rows1 = con.execute(
        "SELECT action, subject_type, note FROM review_event WHERE action='graph.refresh'").fetchall()
    assert len(rows1) == 1
    assert rows1[0][1] == "graph"
    assert "graph_node=" in rows1[0][2]

    with r.tx():
        r.graph.refresh(actor="s584-test")
    rows2 = con.execute(
        "SELECT action, subject_type, note FROM review_event WHERE action='graph.refresh'").fetchall()
    assert len(rows2) == 2
    r.close()


# --------------------------------------------------------------------------- outside tx

def test_refresh_outside_tx_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="transaction"):
        r.graph.refresh()
    r.close()
