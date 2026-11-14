from csa_docx.v2repo import Repo
from csa_docx.v2repo.scope import projected_graph


def test_application_projection_filters_hosts_and_preserves_global_graph(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for host in ("APP01", "PEER01", "OTHER01"):
            repo.hosts.create(host)
        repo.con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES (?, ?, ?, ?)",
                         ("APP01", "PEER01", 443, "tcp"))
        repo.con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES (?, ?, ?, ?)",
                         ("OTHER01", "APP01", 22, "tcp"))
        repo.application_scope.add("tetra-reveloc", "APP01", "owned", review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "PEER01", "peer", active=True)
        repo.application_scope.add("tetra-reveloc", "OTHER01", "peer", active=False)
        repo.graph.refresh()

    app = projected_graph(repo, "tetra-reveloc")
    names = {n["node_id"] for n in app["nodes"] if n["node_id"].startswith("host/")}
    assert names == {"host/APP01", "host/PEER01"}
    assert all(edge["src"] in {"host/APP01", "host/PEER01"} and
               edge["dst"] in {"host/APP01", "host/PEER01"} for edge in app["edges"])
    assert len(projected_graph(repo, view="global")["nodes"]) > len(app["nodes"])
    repo.close()


def test_application_projection_requires_explicit_key(tmp_path):
    repo = Repo(tmp_path / "v2")
    try:
        projected_graph(repo)
    except ValueError as exc:
        assert "application_key" in str(exc)
    else:
        raise AssertionError("application view accepted an omitted application key")
    repo.close()


def _raises(fn, text):
    try:
        fn()
    except ValueError as exc:
        assert text in str(exc)
    else:
        raise AssertionError(f"expected a ValueError naming {text!r}")


def test_scoped_views_reject_omitted_unknown_key_and_unknown_view(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        repo.hosts.create("APP01")
        repo.application_scope.add("tetra-reveloc", "APP01", "owned", review_state="accepted")
        repo.graph.refresh()
    for view in ("owned", "application"):
        _raises(lambda: projected_graph(repo, view=view), "application_key")
        _raises(lambda: projected_graph(repo, "  ", view=view), "application_key")
        _raises(lambda: projected_graph(repo, "missing-app", view=view), "unknown application_key")
    _raises(lambda: projected_graph(repo, "tetra-reveloc", view="everything"), "view")
    # the global view needs no key and ignores one
    assert projected_graph(repo, view="global")["application_key"] is None
    repo.close()


def test_owned_view_returns_only_owned_hosts(tmp_path):
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for host in ("APP01", "APP02", "PEER01"):
            repo.hosts.create(host)
        for src, dst in (("APP01", "APP02"), ("APP01", "PEER01")):
            repo.con.execute("INSERT INTO flow (src_host, dst_host, port, protocol) VALUES (?, ?, 443, 'tcp')",
                             (src, dst))
        for host in ("APP01", "APP02"):
            repo.application_scope.add("tetra-reveloc", host, "owned", review_state="accepted")
        repo.application_scope.add("tetra-reveloc", "PEER01", "peer", review_state="accepted")
        repo.graph.refresh()
    owned = projected_graph(repo, "tetra-reveloc", view="owned")
    assert {n["node_id"] for n in owned["nodes"]} == {"host/APP01", "host/APP02"}
    assert [(e["src"], e["dst"]) for e in owned["edges"]] == [("host/APP01", "host/APP02")]
    assert "host/PEER01" in {n["node_id"] for n in projected_graph(repo, "tetra-reveloc")["nodes"]}
    repo.close()
