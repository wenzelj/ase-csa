from csa_docx.v2repo import Repo
from csa_docx.v2_cleanup import repair_provenance

def test_unique_provenance_repair_preserves_claim_and_id(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as c:
        c.execute("INSERT INTO indexed_file(rel_path) VALUES ('captures/source.txt')")
        c.execute("INSERT INTO evidence(id,claim,source_title,status) VALUES ('E-1','keep','source.txt','VERIFIED')")
    result = repair_provenance(tmp_path / "v2", dry_run=False)
    assert result["repaired"] == 1
    assert r.con.execute("SELECT id,claim,source_title FROM evidence").fetchone() == ('E-1','keep','captures/source.txt')
    r.close()
