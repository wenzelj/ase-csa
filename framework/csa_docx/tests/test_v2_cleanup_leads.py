from csa_docx.v2repo import Repo
from csa_docx.v2_cleanup import archive_migrated_leads

def test_migrated_leads_are_separate_from_v2_leads(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as c:
        c.execute("INSERT INTO lead(id,question,searched_scope,state) VALUES ('L-1','old','DR-X','open')")
        c.execute("INSERT INTO lead(id,question,searched_scope,state) VALUES ('L-2','new','v2 discovery index: x','open')")
    result = archive_migrated_leads(tmp_path / "v2")
    assert result["migrated_count"] == 1 and result["v2_count"] == 1
    r.close()
