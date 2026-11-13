import sqlite3

from backend import app as browser


def test_v2_evidence_and_files_come_from_database(tmp_path, monkeypatch):
    work = tmp_path / "csa-work-v2"
    work.mkdir()
    db = work / "csa.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE evidence(id TEXT, area TEXT, question TEXT, claim TEXT, status TEXT, "
                    "source_title TEXT, page_or_location TEXT, excerpt TEXT, confidence TEXT, "
                    "gap_or_action TEXT, review_state TEXT)")
        con.execute("CREATE TABLE indexed_file(rel_path TEXT, size INTEGER, indexed_at TEXT)")
        con.execute("INSERT INTO evidence VALUES ('E-001','dns','Resolver?','RMS uses DNS','VERIFIED',"
                    "'capture','line 1','resolver','high','','accepted')")
        con.execute("INSERT INTO indexed_file VALUES ('Discovery/RMS_discovery_HOST1_20261112T010101Z/03_dns.txt',"
                    "10,'2026-11-12T01:01:01Z')")
    project = {"key": "test", "label": "Test", "project_root": str(tmp_path), "work_dir": str(work)}
    monkeypatch.setattr(browser, "system_project", lambda key: project)

    assert browser.matrix_rows(project)[0]["evidence_id"] == "E-001"
    assert browser.evidence("test", limit=10)["total"] == 1
    assert browser.files("test", limit=10)["total"] == 1
    assert browser.get_summary("test")["evidence_rows"] == 1


def test_v1_matrix_reader_stays_on_csv(tmp_path):
    work = tmp_path / "csa-work"
    work.mkdir()
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,review_state\n"
        "E-009,dns,Old?,V1 remains,VERIFIED,old,reviewed\n", encoding="utf-8")
    rows = browser.matrix_rows({"work_dir": str(work)})
    assert rows[0]["claim"] == "V1 remains"
