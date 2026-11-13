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
