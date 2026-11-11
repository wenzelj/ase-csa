"""The v2repo transaction: all-or-nothing, byte-identical on rollback, auto-backup before the first write."""
import filecmp
import sqlite3

import pytest

from csa_docx.v2repo import BACKUPS_DIR, DB_NAME, Repo


def test_failed_tx_leaves_db_byte_identical(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    with r.tx():
        r.con.execute("INSERT INTO host (name, role) VALUES ('H1', 'server')")
    before = (tmp_path / DB_NAME).read_bytes()

    with pytest.raises(RuntimeError, match="boom"):
        with r.tx():
            r.con.execute("INSERT INTO host (name, role) VALUES ('H2', 'server')")
            raise RuntimeError("boom")

    assert (tmp_path / DB_NAME).read_bytes() == before
    assert r.con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == 1
    r.close()


def test_successful_tx_commits_all_writes_atomically(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    with r.tx():
        r.con.execute("INSERT INTO host (name, role) VALUES ('H1', 'server')")
        r.con.execute("INSERT INTO host (name, role) VALUES ('H2', 'server')")
        r.con.execute("INSERT INTO evidence (id, claim) VALUES ('E-001', 'first')")
    assert r.con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == 2
    assert r.con.execute("SELECT claim FROM evidence WHERE id='E-001'").fetchone()[0] == "first"

    # and they are visible to a brand-new connection: committed, not in-flight
    con = sqlite3.connect(tmp_path / DB_NAME)
    assert con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == 2
    con.close()
    r.close()


def test_tx_creates_timestamped_backup_with_pre_mutation_state(tmp_path):
    db = tmp_path / DB_NAME
    r = Repo(db)
    # pre-existing state to be captured in the backup
    with r.tx():
        r.con.execute("INSERT INTO host (name, role) VALUES ('H0', 'old')")
    first_backup = sorted((tmp_path / BACKUPS_DIR).glob(f"{DB_NAME}.*"))
    # the first tx backed up the then-empty (schema-only) file
    assert first_backup, "a backup copy was not created before the first write"

    r2 = Repo(db)
    with r2.tx():
        r2.con.execute("INSERT INTO host (name, role) VALUES ('H1', 'new')")
    backups = sorted((tmp_path / BACKUPS_DIR).glob(f"{DB_NAME}.*"))
    assert len(backups) > len(first_backup), "second write must add a second backup copy"
    latest = backups[-1]

    # the backup taken before the second tx still holds only H0
    con = sqlite3.connect(latest)
    assert {r[0] for r in con.execute("SELECT name FROM host")} == {"H0"}
    con.close()
    r2.close()


def test_backup_name_is_timestamped(tmp_path):
    r = Repo(tmp_path / DB_NAME)
    with r.tx():
        r.con.execute("INSERT INTO host (name) VALUES ('H1')")
    names = [p.name for p in (tmp_path / BACKUPS_DIR).glob(f"{DB_NAME}.*")]
    assert names, "no backup created"
    for name in names:
        ts = name[len(DB_NAME) + 1:].split(".")[0]
        assert len(ts) == 15 and ts[8] == "T", f"backup {name!r} is not a csa.sqlite.<ts> copy"
    r.close()


def test_review_event_append_writes_one_row_per_call(tmp_path):
    r = Repo(tmp_path / DB_NAME)
    with r.tx():
        r.review_event().append("wenzel", "create", "host", "H1", note="first")
        r.review_event().append("wenzel", "update", "evidence", "E-001", note="second")
    rows = r.con.execute(
        "SELECT actor, action, subject_type, subject_id, note FROM review_event ORDER BY id"
    ).fetchall()
    assert rows == [("wenzel", "create", "host", "H1", "first"),
                    ("wenzel", "update", "evidence", "E-001", "second")]
    ts = r.con.execute("SELECT ts FROM review_event WHERE id=1").fetchone()[0]
    assert ts.startswith("20") and "T" in ts and ts.endswith("Z")
    r.close()


def test_namespaces_expose_crud_and_nothing_else(tmp_path):
    r = Repo(tmp_path / DB_NAME)
    for ns in (r.hosts, r.evidence, r.intake, r.leads):
        for op in ("create", "get", "update", "list"):
            assert hasattr(ns, op), f"{op} missing from namespace"
        assert not hasattr(ns, "delete"), "namespaces must not expose delete"
    r.close()


def test_backup_and_export_stubs_exist(tmp_path):
    r = Repo(tmp_path / DB_NAME)
    assert callable(r.backup)
    assert hasattr(r.export, "csv") and hasattr(r.export, "md")
    r.close()


def test_backup_stub_raises_not_implemented(tmp_path):
    r = Repo(tmp_path / DB_NAME)
    with pytest.raises(NotImplementedError):
        r.backup()
    with pytest.raises(NotImplementedError):
        r.export.csv("hosts", tmp_path / "hosts.csv")
    r.close()
