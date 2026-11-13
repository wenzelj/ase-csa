"""The v2repo schema: applies cleanly, idempotent, and has every table the plan lists."""
import sqlite3

import pytest

from csa_docx.v2repo import SCHEMA_PATH, Repo

EXPECTED_TABLES = {
    "host", "address", "service", "flow", "evidence", "evidence_source",
    "intake_record", "intake_file", "lead", "gap_check", "review_event",
    "graph_node", "graph_edge", "alias", "entity",
    "indexed_file", "indexed_chunk", "fts",
}


def _tables(con):
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'")}


def test_schema_applies_cleanly_to_a_fresh_db(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    missing = EXPECTED_TABLES - _tables(r.con)
    assert not missing, f"missing tables: {sorted(missing)}"
    r.close()


def test_schema_is_idempotent_and_keeps_data(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    with r.tx():
        r.con.execute("INSERT INTO host (name, role) VALUES ('H1', 'server')")
        r.con.execute("INSERT INTO evidence (id, claim, status) VALUES ('E-001', 'a claim', 'VERIFIED')")
    r.close()

    r2 = Repo(tmp_path / "csa.sqlite")
    with r2.tx():
        r2.con.execute("INSERT INTO host (name, role) VALUES ('H2', 'server')")
    assert r2.con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == 2
    assert r2.con.execute("SELECT claim FROM evidence WHERE id='E-001'").fetchone()[0] == "a claim"
    r2.close()

    # a third apply, in a brand-new connection, must not error and must not drop data
    con = sqlite3.connect(tmp_path / "csa.sqlite")
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == 2
    assert EXPECTED_TABLES - {"fts"} <= _tables(con)
    con.close()


def test_review_event_columns_match_the_plan(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    cols = [r[1] for r in r.con.execute("PRAGMA table_info(review_event)")]
    assert cols == ["id", "ts", "actor", "action", "subject_type", "subject_id", "note", "before_hash", "after_hash"]
    r.close()


def test_evidence_columns_match_the_plan(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    cols = {r[1] for r in r.con.execute("PRAGMA table_info(evidence)")}
    assert cols == {"id", "area", "question", "claim", "status", "source_title", "page_or_location",
                    "excerpt", "confidence", "gap_or_action", "review_state", "created_at", "updated_at"}
    r.close()


def test_review_event_is_append_only_at_the_api_level(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    ns = r.review_event()
    assert hasattr(ns, "append")
    assert not hasattr(ns, "update"), "review_event must not expose update"
    assert not hasattr(ns, "delete"), "review_event must not expose delete"
    assert not hasattr(ns, "remove"), "review_event must not expose delete under another name"
    r.close()


def test_fts_uses_fts5_when_available(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    if r.con.execute("SELECT value FROM v2_meta WHERE key='fts5'").fetchone()[0] == "1":
        sql = r.con.execute("SELECT sql FROM sqlite_master WHERE name='fts'").fetchone()[0]
        assert "fts5" in sql
    else:  # the plain-text fallback still exists with the mirror's columns
        cols = {r[1] for r in r.con.execute("PRAGMA table_info(fts)")}
        assert {"chunk_id", "rel_path", "heading", "text"} <= cols
    r.close()
