"""Repository tests for v2 application scope metadata (S591)."""

from csa_docx.v2repo import Repo


def test_scope_crud_and_many_to_many(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        repo.hosts.create("APP01", role="application")
        repo.hosts.create("SHARED01", role="shared")
        repo.application_scope.add("tetra-reveloc", "APP01", "owned", basis="inventory",
                                   source_ref="hosts.csv", review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "SHARED01", "peer", basis="register_peer",
                                   source_ref="hosts.csv", active=False)
        repo.application_scope.add("iamps-08", "SHARED01", "owned", basis="inventory",
                                   source_ref="iamps-hosts.csv", review_state="accepted")
    assert repo.application_scope.get("tetra-reveloc", "APP01")["membership"] == "owned"
    assert repo.application_scope.list_app_hosts("tetra-reveloc", active=True)[0]["host_name"] == "APP01"
    assert repo.application_scope.list_app_hosts("tetra-reveloc", membership="peer", active=False)[0]["host_name"] == "SHARED01"
    assert len(repo.application_scope.list_app_hosts("iamps-08")) == 1
    assert repo.application_scope.count() == 3
    repo.close()


def test_scope_rejects_invalid_values(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        repo.hosts.create("APP01")
        for kwargs in ({"membership": "unknown"}, {"membership": "owned", "review_state": "unknown"}):
            try:
                repo.application_scope.add("tetra-reveloc", "APP01", **kwargs)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid scope value was accepted")
    repo.close()


def test_scope_export_is_available(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        repo.hosts.create("APP01")
        repo.application_scope.add("tetra-reveloc", "APP01", "owned")
    out = tmp_path / "scope.csv"
    result = repo.export.csv("application_scope", out)
    assert result["rows"] == 1
    assert "application_key" in out.read_text(encoding="utf-8").splitlines()[0]
    repo.close()


# --------------------------------------------------------------------------- S592

def _seed_projection_repo(tmp_path):
    """Two applications share one peer; a third application has a rejected peer.

    tetra-reveloc owns APP01, PEER01 is its active flow-linked peer, UNLINKED01
    is an unlinked peer, NEIGHBOUR01 carries only a neighbour classification,
    and REJECTED01 is rejected evidence. iamps-08 shares PEER01 as its only
    owned/peer link, proving many-to-many scope membership (S592).
    """
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for host in ("APP01", "PEER01", "UNLINKED01", "NEIGHBOUR01", "REJECTED01"):
            repo.hosts.create(host)
        repo.hosts.create("SHARED01", role="shared")
        # current flow: owned host -> linked peer, with a captured evidence row
        repo.evidence.create(
            claim="APP01 has an established connection to PEER01 on port 443.",
            source_title="cap/002_flow.txt",
            excerpt="TCP  APP01:443  PEER01:49999  ESTABLISHED",
            status="VERIFIED",
        )
        rejected_eid = repo.evidence.create(
            claim="NEIGHBOUR01 has an established connection to APP01 on port 22.",
            source_title="cap/003_rejected.txt",
            excerpt="rejected neighbour claim",
            status="VERIFIED",
        )
        repo.evidence.reject(rejected_eid, by="s592-test", note="neighbour claim rejected")
        con = repo.con
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES ('APP01', 'PEER01', 443, 'tcp')")
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES ('UNLINKED01', 'PEER01', 22, 'tcp')")
        con.execute("INSERT INTO service (host, port, protocol, name) VALUES ('APP01', 1433, 'tcp', 'SQL Server')")
        repo.application_scope.add("tetra-reveloc", "APP01", "owned", basis="inventory",
                                  source_ref="hosts.csv", review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "PEER01", "peer", basis="captured_flow",
                                  source_ref="cap/002_flow.txt", review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "UNLINKED01", "peer", basis="register_peer",
                                  source_ref="hosts.csv", active=False, review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "NEIGHBOUR01", "peer", basis="neighbour",
                                  source_ref="hosts.csv", active=True, review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "REJECTED01", "peer", basis="captured_flow",
                                  source_ref="cap/003_rejected.txt", active=True,
                                  review_state="rejected")
        # second application, sharing PEER01 through the same flow
        repo.application_scope.add("iamps-08", "APP01", "owned", basis="inventory",
                                  source_ref="iamps-hosts.csv", review_state="accepted")
        repo.application_scope.add("iamps-08", "PEER01", "peer", basis="captured_flow",
                                  source_ref="cap/002_flow.txt", review_state="accepted")
        repo.graph.refresh()
    return repo


def test_application_projection_keeps_owned_hosts_and_linked_peers(tmp_path):
    repo = _seed_projection_repo(tmp_path)
    from csa_docx.v2repo.scope import projected_graph
    app = projected_graph(repo, "tetra-reveloc")
    hosts = {n["node_id"] for n in app["nodes"] if n["node_id"].startswith("host/")}
    # owned hosts remain visible ...
    assert "host/APP01" in hosts
    # ... and the linked peer is included ...
    assert "host/PEER01" in hosts
    # ... while an unlinked, neighbour-labelled or rejected peer is excluded.
    assert "host/UNLINKED01" not in hosts
    assert "host/NEIGHBOUR01" not in hosts
    assert "host/REJECTED01" not in hosts
    # only the owned host and the evidence-backed peer host are projected
    assert hosts == {"host/APP01", "host/PEER01"}
    assert app["application_key"] == "tetra-reveloc"
    repo.close()


def test_rejected_or_inactive_or_neighbour_peer_is_invisible(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_projection_repo(tmp_path)
    app = projected_graph(repo, "tetra-reveloc")
    hosts = {n["node_id"] for n in app["nodes"] if n["node_id"].startswith("host/")}
    # inactive peer membership ...
    assert "host/UNLINKED01" not in hosts
    # ... a neighbour-only classification ...
    assert "host/NEIGHBOUR01" not in hosts
    # ... and a rejected evidence row cannot make a peer visible.
    assert "host/REJECTED01" not in hosts
    repo.close()


def test_shared_host_visible_to_both_applications(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_projection_repo(tmp_path)
    tetra = {n["node_id"] for n in projected_graph(repo, "tetra-reveloc")["nodes"] if n["node_id"].startswith("host/")}
    iamps = {n["node_id"] for n in projected_graph(repo, "iamps-08")["nodes"] if n["node_id"].startswith("host/")}
    # many-to-many membership: the shared peer appears for both applications
    assert "host/PEER01" in tetra and "host/PEER01" in iamps
    # ... and each application still sees only its own linked peer set.
    assert "host/UNLINKED01" not in iamps
    repo.close()


def test_global_projection_unchanged_by_scope(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_projection_repo(tmp_path)
    global_view = projected_graph(repo, view="global")
    global_hosts = {n["node_id"] for n in global_view["nodes"] if n["node_id"].startswith("host/")}
    # the complete active-host graph, scope rows and all
    assert {"host/APP01", "host/PEER01", "host/UNLINKED01", "host/NEIGHBOUR01",
            "host/REJECTED01", "host/SHARED01"} <= global_hosts
    assert global_view["application_key"] is None
    app_hosts = {n["node_id"] for n in projected_graph(repo, "tetra-reveloc")["nodes"] if n["node_id"].startswith("host/")}
    assert app_hosts < global_hosts
    # provenance survives in both projections
    flow_edges = [e for e in global_view["edges"] if e["kind"] == "flow"]
    assert any("E-001" in (e["evidence_ids"] or "") for e in flow_edges)
    repo.close()


def test_projection_keeps_node_and_edge_provenance(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_projection_repo(tmp_path)
    app = projected_graph(repo, "tetra-reveloc")
    flow_edges = [e for e in app["edges"] if (e["src"], e["dst"]) == ("host/APP01", "host/PEER01")]
    # the application projection retains the evidence IDs of its edges
    assert flow_edges and "E-001" in flow_edges[0]["evidence_ids"]
    for node in app["nodes"]:
        assert set(node) == {"node_id", "label", "kind", "evidence_ids"}
    # retired hosts drop out of the global view too
    with repo.tx():
        repo.hosts.retire("SHARED01", note="s592-test")
        repo.graph.refresh()
    global_hosts = {n["node_id"] for n in projected_graph(repo, view="global")["nodes"]}
    assert "host/SHARED01" not in global_hosts
    repo.close()
