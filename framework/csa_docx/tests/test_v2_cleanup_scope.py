from csa_docx import v2scope
from csa_docx.v2repo import Repo


def test_scope_rebuild_uses_v2_provenance(tmp_path):
    root = tmp_path / "root"
    legacy = root / "csa-work" / "hosts"
    legacy.mkdir(parents=True)
    # a stale V1 register that disagrees with V2: it must not be read
    (legacy / "hosts.csv").write_text("host,in_scope\nSTALE1,yes\nH1,peer\n", encoding="utf-8")
    repo = Repo(tmp_path / "v2")
    with repo.tx():
        repo.hosts.create("H1")
        repo.hosts.create("STALE1")
        repo.application_ownership.add("app", "H1", "inventory/assets.xlsx", review_state="accepted", by="test")
    repo.close()
    result = v2scope.rebuild(root, tmp_path / "v2", "app", dry_run=True)
    assert result["owned_count"] == 1
    assert [row["host_name"] for row in result["owned"]] == ["H1"]
    assert result["owned"][0]["source_ref"].startswith("v2:")
    assert result["owned"][0]["ownership_source_ref"] == "inventory/assets.xlsx"
    assert result["source"].startswith("csa.sqlite") and "hosts.csv" not in str(result)
    assert result["unclassified_hosts"] == ["STALE1"]
    assert (legacy / "hosts.csv").read_text(encoding="utf-8") == "host,in_scope\nSTALE1,yes\nH1,peer\n"
