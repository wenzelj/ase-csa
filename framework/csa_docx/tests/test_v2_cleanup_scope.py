from csa_docx import v2scope

def test_scope_rebuild_uses_v2_provenance(tmp_path):
    root = tmp_path / "root"; (root / "csa-work/hosts").mkdir(parents=True)
    (root / "csa-work/hosts/hosts.csv").write_text("host,in_scope\nH1,yes\n")
    result = v2scope.rebuild(root, tmp_path / "v2", "app", dry_run=True)
    assert result["owned_count"] == 1
    assert result["owned"][0]["source_ref"].startswith("v2:")
