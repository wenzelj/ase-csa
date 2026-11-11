"""S583: the v2repo `evidence` CRUD surface — create, get, update, reject, accept, verify, search, list."""
import sqlite3

import pytest

from csa_docx.v2repo import Repo


def _repo(tmp_path):
    return Repo(tmp_path / "csa.sqlite")


def _source_index(tmp_path, rel_path: str, text: str):
    """Build a minimal discovery index with one file containing `text`."""
    db = tmp_path / "discovery-index.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        create table files(file_id integer, rel_path text, dup_of integer, archived integer default 0);
        create table chunk_map(chunk_id integer, file_id integer, line_start integer);
        create table chunks_content(id integer, c0 text);
    """)
    con.execute("insert into files values (1, ?, null, 0)", (rel_path,))
    con.execute("insert into chunk_map values (1, 1, 1)")
    con.execute("insert into chunks_content values (1, ?)", (text,))
    con.commit()
    con.close()
    return db


# --------------------------------------------------------------------------- create / get


def test_create_and_get_roundtrip(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(
            claim="H1 is a Windows Server 2019 box",
            source_title="cap/001_hosts.txt",
            excerpt="H1  10.0.0.1  Windows Server 2019",
            area="infrastructure_and_hosting",
            status="VERIFIED",
        )
        assert eid == "E-001"
        row = r.evidence.get(eid)
        assert row["id"] == "E-001"
        assert row["claim"] == "H1 is a Windows Server 2019 box"
        assert row["status"] == "VERIFIED"
        assert row["review_state"] == "proposed"
        assert row["created_at"] is not None
        assert row["updated_at"] is not None
    r.close()


def test_create_outside_tx_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="transaction"):
        r.evidence.create(claim="x", source_title="s.txt")
    r.close()


def test_get_missing_raises_keyerror(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(KeyError):
        r.evidence.get("E-999")
    r.close()


def test_id_sequence_continues_from_max(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        e1 = r.evidence.create(claim="one", source_title="s.txt")
        e2 = r.evidence.create(claim="two", source_title="s.txt")
    assert e1 == "E-001"
    assert e2 == "E-002"
    r.close()

    r2 = _repo(tmp_path)
    with r2.tx():
        e3 = r2.evidence.create(claim="three", source_title="s.txt")
    assert e3 == "E-003"
    r2.close()


# --------------------------------------------------------------------------- update


def test_update_sets_fields_and_bumps_updated_at(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt", confidence="low")
    before = r.evidence.get(eid)["updated_at"]
    import time
    time.sleep(0.01)
    with r.tx():
        r.evidence.update(eid, confidence="high", area="security_posture")
    row = r.evidence.get(eid)
    assert row["confidence"] == "high"
    assert row["area"] == "security_posture"
    assert row["updated_at"] >= before
    r.close()


def test_update_refuses_direct_verified_write(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt", status="UNCONFIRMED")
    with pytest.raises(ValueError, match="VERIFIED"):
        with r.tx():
            r.evidence.update(eid, status="VERIFIED")
    assert r.evidence.get(eid)["status"] == "UNCONFIRMED"
    r.close()


def test_update_allows_other_statuses(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt", status="UNCONFIRMED")
    with r.tx():
        r.evidence.update(eid, status="INFERRED")
    assert r.evidence.get(eid)["status"] == "INFERRED"
    r.close()


def test_update_refuses_id_change(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt")
    with pytest.raises(ValueError, match="id"):
        with r.tx():
            r.evidence.update(eid, id="E-999")
    r.close()


def test_update_refuses_unknown_column(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt")
    with pytest.raises(ValueError, match="unknown column"):
        with r.tx():
            r.evidence.update(eid, no_such="x")
    r.close()


# --------------------------------------------------------------------------- reject / accept


def test_reject_does_not_delete(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt")
        r.evidence.reject(eid, by="wenzel", note="not supported")
    row = r.evidence.get(eid)
    assert row["review_state"] == "rejected"
    assert row["claim"] == "c"
    rows = r.evidence.list(review_state="rejected")
    assert [x["id"] for x in rows] == [eid]
    r.close()


def test_accept_sets_accepted(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt")
        r.evidence.reject(eid, by="wenzel", note="initial concern")
        r.evidence.accept(eid, by="wenzel", note="actually fine")
    assert r.evidence.get(eid)["review_state"] == "accepted"
    r.close()


# --------------------------------------------------------------------------- verify


def test_verify_sets_verified_when_quote_present(tmp_path):
    text = "H1  10.0.0.1  Windows Server 2019"
    _source_index(tmp_path, "cap/001_hosts.txt", text)
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(
            claim="H1 is a Windows Server 2019 box",
            source_title="cap/001_hosts.txt",
            excerpt="H1  10.0.0.1  Windows Server 2019",
            status="UNCONFIRMED",
        )
        res = r.evidence.verify(eid, actor="wenzel")
        assert res["verdict"] == "SOURCE_OK"
    row = r.evidence.get(eid)
    assert row["status"] == "VERIFIED"
    assert row["review_state"] == "accepted"
    r.close()


def test_verify_refuses_when_quote_not_in_source(tmp_path):
    text = "totally different content that does not mention the claim"
    _source_index(tmp_path, "002_notes.txt", text)
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(
            claim="H1 is a Windows Server 2019 box",
            source_title="002_notes.txt",
            excerpt="H1  10.0.0.1  Windows Server 2019",
            status="UNCONFIRMED",
        )
        res = r.evidence.verify(eid, actor="wenzel")
        assert res["verdict"] != "SOURCE_OK"
    row = r.evidence.get(eid)
    assert row["status"] == "UNCONFIRMED", "verify must not set VERIFIED when the quote is not in the source"
    events = r.con.execute(
        "SELECT action, note FROM review_event WHERE action='verify' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert events is not None, "a review_event must record the verify failure"
    assert "SOURCE_MISMATCH" in (events[1] or "") or "SOURCE_NOT_FOUND" in (events[1] or "")
    r.close()


# --------------------------------------------------------------------------- search / list


def test_search_matches_claim_question_excerpt(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.evidence.create(claim="H1 runs SQL Server 2019", source_title="001_hosts.txt")
        r.evidence.create(claim="H2 is a Linux box", source_title="001_hosts.txt")
    rows = r.evidence.search("SQL Server")
    assert [x["id"] for x in rows] == ["E-001"]
    r.close()


def test_search_filters_by_host_area_status(tmp_path):
    """`host` narrows to rows whose source_title names that host."""
    r = _repo(tmp_path)
    with r.tx():
        r.evidence.create(claim="H1 runs SQL Server", source_title="REVELOC_discovery_HOSTA01_20260605T010203Z: 001_hosts.txt",
                          area="infrastructure_and_hosting", status="VERIFIED")
        r.evidence.create(claim="H2 runs SQL Server", source_title="REVELOC_discovery_HOSTB02_20260605T010203Z: 002_hosts.txt",
                          area="security_posture", status="UNCONFIRMED")
    rows = r.evidence.search("SQL Server", host="HOSTA01")
    assert [x["id"] for x in rows] == ["E-001"]
    rows = r.evidence.search("SQL Server", host="HOSTB02")
    assert [x["id"] for x in rows] == ["E-002"]
    rows = r.evidence.search("SQL Server", area="security_posture")
    assert [x["id"] for x in rows] == ["E-002"]
    rows = r.evidence.search("SQL Server", status="VERIFIED")
    assert [x["id"] for x in rows] == ["E-001"]
    r.close()


def test_list_filters(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.evidence.create(claim="a", source_title="s.txt", status="VERIFIED", area="infra")
        r.evidence.create(claim="b", source_title="s.txt", status="UNCONFIRMED", area="sec")
        r.evidence.reject("E-002", by="wenzel")
    rows = r.evidence.list()
    assert len(rows) == 2
    rows = r.evidence.list(status="VERIFIED")
    assert [x["id"] for x in rows] == ["E-001"]
    rows = r.evidence.list(area="sec")
    assert [x["id"] for x in rows] == ["E-002"]
    rows = r.evidence.list(review_state="rejected")
    assert [x["id"] for x in rows] == ["E-002"]
    r.close()


# --------------------------------------------------------------------------- tx semantics


def test_mutation_visible_after_commit_and_invisible_after_rollback(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.evidence.create(claim="a", source_title="s.txt")
    assert len(r.evidence.list()) == 1

    with pytest.raises(RuntimeError, match="boom"):
        with r.tx():
            r.evidence.create(claim="b", source_title="s.txt")
            raise RuntimeError("boom")
    assert len(r.evidence.list()) == 1
    assert [x["id"] for x in r.evidence.list()] == ["E-001"]
    r.close()


def test_review_event_appended_for_each_mutation(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        eid = r.evidence.create(claim="c", source_title="s.txt", actor="wenzel", note="first")
    with r.tx():
        r.evidence.update(eid, confidence="high", actor="wenzel", note="graded")
    with r.tx():
        r.evidence.reject(eid, by="wenzel", note="disputed")
    with r.tx():
        r.evidence.accept(eid, by="wenzel", note="reinstated")
    events = r.con.execute(
        "SELECT actor, action, subject_type, subject_id FROM review_event ORDER BY id"
    ).fetchall()
    assert events == [
        ("wenzel", "create", "evidence", "E-001"),
        ("wenzel", "update", "evidence", "E-001"),
        ("wenzel", "reject", "evidence", "E-001"),
        ("wenzel", "accept", "evidence", "E-001"),
    ]
    r.close()
