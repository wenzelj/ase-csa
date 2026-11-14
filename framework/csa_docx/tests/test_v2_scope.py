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


# --------------------------------------------------------------------------- S614

def _seed_contract_repo(tmp_path):
    """One application with every case the projection contract names.

    app-a owns APP01 and APP02 and shares SHARED01 with app-b.  PEER01 is a
    flow-linked scoped peer, UNLINKED01 an active peer with no relationship,
    INACTIVE01 a flow-linked peer whose scope row is inactive, REJECTED01 a
    peer linked only by rejected evidence, RETIRED01 a retired flow-linked
    peer and OTHER01 a registered host with a flow but no scope row.
    203.0.113.10 and 198.51.100.7 are external IPs that evidence rows link to
    an owned host (the flow table holds registered hosts only) and
    time.example.net is a provider endpoint.
    """
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for host in ("APP01", "APP02", "SHARED01", "PEER01", "UNLINKED01", "INACTIVE01",
                     "REJECTED01", "RETIRED01", "OTHER01", "FAR01"):
            repo.hosts.create(host)
        repo.evidence.create(
            claim="APP01 has an established connection to PEER01 on port 443.",
            source_title="cap/001_flow.txt", excerpt="TCP APP01 PEER01:443 ESTABLISHED", status="VERIFIED")
        rejected = repo.evidence.create(
            claim="APP01 has an established connection to REJECTED01 on port 22.",
            source_title="cap/002_rejected.txt", excerpt="rejected", status="VERIFIED")
        repo.evidence.reject(rejected, by="s614-test", note="rejected relationship")
        repo.evidence.create(
            claim="APP02 has an established connection to 198.51.100.7 on port 8443.",
            source_title="cap/003_external.txt", excerpt="TCP APP02 198.51.100.7:8443 ESTABLISHED",
            status="VERIFIED")
        repo.evidence.create(
            claim="APP02 has an outbound connection from svc.exe to 203.0.113.10 port 443.",
            source_title="cap/004_external.txt", excerpt="svc.exe APP02 203.0.113.10:443",
            status="VERIFIED")
        repo.evidence.create(                      # names no source: not a source-backed relationship
            claim="APP02 has an established connection to 192.0.2.99 on port 25.",
            source_title="", excerpt="", status="UNCONFIRMED")
        con = repo.con
        for src, dst, port in (("APP01", "APP02", 1433), ("APP01", "PEER01", 443),
                               ("APP01", "INACTIVE01", 445), ("APP01", "RETIRED01", 3389),
                               ("OTHER01", "APP01", 22),
                               ("PEER01", "FAR01", 80), ("SHARED01", "APP01", 135)):
            con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES (?, ?, ?, 'tcp')",
                        (src, dst, port))
        con.execute("INSERT INTO service (host, provider_host, port, protocol, name) "
                    "VALUES ('APP01', 'time.example.net', 123, 'udp', 'time')")
        add = repo.application_scope.add
        for host in ("APP01", "APP02", "SHARED01"):
            add("app-a", host, "owned", basis="inventory", source_ref="inventory", review_state="accepted")
        add("app-a", "PEER01", "peer", basis="captured_flow", review_state="accepted")
        add("app-a", "UNLINKED01", "peer", basis="neighbour", review_state="accepted")
        add("app-a", "INACTIVE01", "peer", basis="captured_flow", review_state="accepted", active=False)
        add("app-a", "REJECTED01", "peer", basis="captured_evidence", review_state="accepted")
        add("app-a", "RETIRED01", "peer", basis="captured_flow", review_state="accepted")
        add("app-b", "SHARED01", "owned", basis="inventory", review_state="accepted")
        add("app-b", "APP01", "peer", basis="captured_flow", review_state="accepted")
        repo.hosts.retire("RETIRED01", note="s614-test")
        repo.graph.refresh()
    return repo


def _ids(projection):
    return {n["node_id"] for n in projection["nodes"]}


def test_contract_documents_the_three_views():
    from csa_docx.v2repo import scope
    assert set(scope.PROJECTION_CONTRACT["views"]) == set(scope.VIEWS) == {"owned", "application", "global"}
    assert scope.PROJECTION_CONTRACT["version"] == scope.CONTRACT_VERSION
    for word in ("scoped peer host", "external endpoint", "owned", "global"):
        assert word in scope.__doc__


def test_owned_view_is_only_the_owned_hosts(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    owned = projected_graph(repo, "app-a", view="owned")
    assert _ids(owned) == {"host/APP01", "host/APP02", "host/SHARED01"}
    assert owned["view"] == "owned" and owned["application_key"] == "app-a"
    assert owned["scope"]["peers"] == [] and owned["scope"]["external"] == []
    assert {(e["src"], e["dst"]) for e in owned["edges"]} == {
        ("host/APP01", "host/APP02"), ("host/SHARED01", "host/APP01")}
    repo.close()


def test_application_view_adds_qualifying_peers_and_external_endpoints(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    app = projected_graph(repo, "app-a", view="application")
    assert _ids(app) == {"host/APP01", "host/APP02", "host/SHARED01", "host/PEER01",
                         "host/203.0.113.10", "host/198.51.100.7", "host/time.example.net",
                         "service/time"}
    # an unlinked peer, an inactive scope row, a rejected relationship, a retired host and a
    # registered host with no scope row stay out, whatever touches them
    for hidden in ("UNLINKED01", "INACTIVE01", "REJECTED01", "RETIRED01", "OTHER01", "FAR01", "192.0.2.99"):
        assert f"host/{hidden}" not in _ids(app)
    # every edge touches an owned host and stays inside the projection
    owned = set(app["scope"]["owned"])
    for edge in app["edges"]:
        assert edge["src"] in owned or edge["dst"] in owned
        assert edge["src"] in _ids(app) and edge["dst"] in _ids(app)
        assert edge["application_key"] == "app-a" and edge["source"] in ("graph_edge", "evidence")
    assert ("host/PEER01", "host/FAR01") not in {(e["src"], e["dst"]) for e in app["edges"]}
    repo.close()


def test_application_view_tells_peer_hosts_from_external_endpoints(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    scope = projected_graph(repo, "app-a")["scope"]
    assert scope["peers"] == ["host/PEER01"]
    external = {e["node_id"]: e for e in scope["external"]}
    assert external["host/203.0.113.10"]["class"] == "external_ip"
    assert external["host/203.0.113.10"]["basis"] == ["evidence"]
    assert external["host/198.51.100.7"]["class"] == "external_ip"
    assert external["host/198.51.100.7"]["basis"] == ["evidence"]
    assert external["host/time.example.net"]["class"] == "provider_endpoint"
    assert external["service/time"]["class"] == "service_name"
    assert not set(external) & (set(scope["peers"]) | set(scope["owned"]))
    repo.close()


def test_projected_edges_keep_evidence_ids(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    edges = {(e["src"], e["dst"]): e for e in projected_graph(repo, "app-a")["edges"] if e["kind"] == "flow"}
    assert edges[("host/APP01", "host/PEER01")]["evidence_ids"] == "E-001"
    external = edges[("host/APP02", "host/198.51.100.7")]
    assert external["evidence_ids"] == "E-003" and external["source"] == "evidence"
    assert edges[("host/APP02", "host/203.0.113.10")]["evidence_ids"] == "E-004"
    assert not any("E-002" in (e["evidence_ids"] or "") for e in edges.values())
    repo.close()


def test_shared_host_is_owned_by_both_applications(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    assert "host/SHARED01" in _ids(projected_graph(repo, "app-a", view="owned"))
    assert _ids(projected_graph(repo, "app-b", view="owned")) == {"host/SHARED01"}
    # app-b sees app-a's APP01 only as its own scoped peer
    assert _ids(projected_graph(repo, "app-b")) == {"host/SHARED01", "host/APP01"}
    repo.close()


def test_global_view_is_unchanged_by_scope_metadata(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    before = projected_graph(repo, view="global")
    assert before["nodes"] == repo.graph.nodes() and before["edges"] == repo.graph.edges()
    with repo.tx():
        repo.application_scope.add("app-a", "PEER01", "peer", active=False)
        repo.application_scope.add("app-a", "APP02", "owned", review_state="rejected")
    after = projected_graph(repo, view="global")
    assert (after["nodes"], after["edges"]) == (before["nodes"], before["edges"])
    assert {"host/OTHER01", "host/UNLINKED01", "host/FAR01"} <= _ids(after)
    # ... while the scoped views follow the metadata
    assert "host/PEER01" not in _ids(projected_graph(repo, "app-a"))
    assert "host/APP02" not in _ids(projected_graph(repo, "app-a", view="owned"))
    repo.close()


def test_projection_does_not_write_the_graph(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = _seed_contract_repo(tmp_path)
    counts = [repo.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("graph_node", "graph_edge", "review_event")]
    for view in ("owned", "application"):
        projected_graph(repo, "app-a", view=view)
    assert counts == [repo.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("graph_node", "graph_edge", "review_event")]
    repo.close()


def test_address_relationships_resolve_before_application_scope(tmp_path):
    from csa_docx.v2repo.scope import projected_graph
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for host in ("APP01", "PEER01", "INACTIVE01", "NOSCOPE01"):
            repo.hosts.create(host)
        repo.application_scope.add("app-a", "APP01", "owned", review_state="accepted")
        repo.application_scope.add("app-a", "PEER01", "peer", review_state="accepted")
        repo.application_scope.add("app-a", "INACTIVE01", "peer", active=False, review_state="accepted")
        for address, owner in (("10.0.0.1", "APP01"), ("10.0.0.2", "PEER01"),
                               ("10.0.0.3", "INACTIVE01"), ("10.0.0.4", "NOSCOPE01"),
                               ("127.0.0.1", "NOSCOPE01")):
            repo.con.execute("INSERT INTO address (ip, owner_host) VALUES (?, ?)", (address, owner))
        for address in ("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "203.0.113.20"):
            repo.evidence.create(
                claim=f"APP01 has an established connection to {address} on port 443.",
                source_title="cap/addresses.txt", excerpt=address, status="VERIFIED")
        repo.graph.refresh()
    app = projected_graph(repo, "app-a")
    node_ids = {node["node_id"] for node in app["nodes"]}
    assert {"host/APP01", "host/PEER01", "host/203.0.113.20"} <= node_ids
    for hidden in ("INACTIVE01", "NOSCOPE01", "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "127.0.0.1"):
        assert f"host/{hidden}" not in node_ids
    edges = {(edge["src"], edge["dst"]): edge for edge in app["edges"]}
    assert edges[("host/APP01", "host/PEER01")]["evidence_ids"] == "E-002"
    assert edges[("host/APP01", "host/203.0.113.20")]["evidence_ids"] == "E-005"
    assert not any(edge["src"] == edge["dst"] for edge in app["edges"])
    repo.close()
