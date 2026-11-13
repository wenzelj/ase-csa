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
