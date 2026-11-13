from csa_docx.v2repo import Repo
from csa_docx.v2_cleanup import cleanup_retired_evidence

def test_retired_evidence_cleanup_is_conservative(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as c:
        c.execute("INSERT INTO evidence(id,claim,source_title,review_state) VALUES ('E-1','x','old/Retired.docx','rejected')")
        c.execute("INSERT INTO indexed_file(rel_path) VALUES ('new/Retired.docx')")
    result = cleanup_retired_evidence(tmp_path / "v2", ["old/Retired.docx"])
    assert result["selected"] == 1
    assert r.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    r.close()
