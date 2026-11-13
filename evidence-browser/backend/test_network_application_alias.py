from pathlib import Path

from backend import network


def test_v2_project_key_resolves_to_unique_application_key(tmp_path):
    from csa_docx.v2repo import Repo
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx() as con:
        repo.hosts.create("H1")
        repo.application_scope.add("tetra-reveloc", "H1", "owned", active=True)
    repo.close()
    result = network.build(work, Path(tmp_path), view="application", application_key="tetra")
    assert result["application_key"] == "tetra-reveloc"
    assert {node["id"] for node in result["nodes"]} == {"H1"}
