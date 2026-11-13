import sqlite3

def test_tetra_cleanup_acceptance():
    db = sqlite3.connect("../../TETRA/06 REVELOC TETRA/csa-work-v2/csa.sqlite")
    try:
        assert db.execute("select count(*) from evidence where review_state != 'rejected' and lower(source_title) like '%current_state_assessment%'").fetchone()[0] == 0
        assert db.execute("select count(*) from lead where state='open' and searched_scope not like 'v2 discovery index:%'").fetchone()[0] == 0
        assert db.execute("select count(*) from application_scope where application_key='tetra-reveloc' and membership='owned' and active=1").fetchone()[0] == 26
        assert db.execute("select count(*) from application_scope where application_key='tetra-reveloc' and membership='peer' and active=1").fetchone()[0] == 14
    finally:
        db.close()
