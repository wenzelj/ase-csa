import sqlite3

from backend import intake_errors


def test_v2_failed_file_warning_is_cleared_by_later_processed_record(tmp_path):
    work = tmp_path / "csa-work-v2"
    work.mkdir()
    con = sqlite3.connect(work / "csa.sqlite")
    con.executescript("""
        CREATE TABLE intake_record (id TEXT PRIMARY KEY, started_at TEXT);
        CREATE TABLE intake_file (record_id TEXT, rel_path TEXT, status TEXT);
        CREATE TABLE gap_check (id TEXT);
    """)
    con.execute("INSERT INTO intake_record VALUES ('old','2026-11-12T00:00:00Z')")
    con.execute("INSERT INTO intake_file VALUES ('old','a.csv','failed')")
    con.execute("INSERT INTO intake_record VALUES ('new','2026-11-13T00:00:00Z')")
    con.execute("INSERT INTO intake_file VALUES ('new','a.csv','processed')")
    con.commit(); con.close()
    warnings = intake_errors.intake_warnings(work)
    assert not any(w["code"] == "failed_intake_files" for w in warnings)
