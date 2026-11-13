"""S583: the v2repo `hosts` CRUD surface — create, get, update, retire, reactivate, list."""
import pytest

from csa_docx.v2repo import Repo


def _repo(tmp_path):
    return Repo(tmp_path / "csa.sqlite")


def test_crud_roundtrip(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1", role="server", site="Site A")
        row = r.hosts.get("H1")
        assert row["name"] == "H1"
        assert row["status"] == "active"
        assert row["role"] == "server"
        assert row["site"] == "Site A"
        assert row["created_at"] is not None
        assert row["updated_at"] is not None

        r.hosts.update("H1", role="db", site="Site B")
        row = r.hosts.get("H1")
        assert row["role"] == "db"
        assert row["site"] == "Site B"

        r.hosts.retire("H1", note="no longer in use")
        assert r.hosts.get("H1")["status"] == "retired"

        r.hosts.reactivate("H1")
        assert r.hosts.get("H1")["status"] == "active"
    r.close()


def test_create_outside_tx_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="transaction"):
        r.hosts.create("H1")
    r.close()


def test_get_missing_raises_keyerror(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(KeyError):
        r.hosts.get("missing")
    r.close()


def test_update_refuses_name_change(tmp_path):
    """The host name is the key — `hosts.update` refuses a fields-dict that tries to rename it."""
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1", role="server")
    # `name` is the positional key, not a kwarg: any attempt to smuggle a new name in via the
    # fields kwarg must be refused.
    with pytest.raises((ValueError, TypeError), match="name"):
        with r.tx():
            r.hosts.update("H1", role="db", **{"name": "H2"})
    r.close()


def test_update_refuses_unknown_column(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1")
    with pytest.raises(ValueError, match="unknown column"):
        with r.tx():
            r.hosts.update("H1", no_such_field="x")
    r.close()


def test_retire_does_not_delete(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1", site="Site A")
        r.hosts.retire("H1")
    assert r.hosts.get("H1")["status"] == "retired"
    rows = r.hosts.list()
    assert [h["name"] for h in rows] == ["H1"]
    r.close()


def test_list_filters(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("A", role="server", site="S1")
        r.hosts.create("B", role="database", site="S1")
        r.hosts.create("C", role="server", site="S2")
        r.hosts.retire("B")
    rows = r.hosts.list()
    assert {h["name"] for h in rows} == {"A", "B", "C"}
    rows = r.hosts.list(status="active")
    assert {h["name"] for h in rows} == {"A", "C"}
    rows = r.hosts.list(status="retired")
    assert {h["name"] for h in rows} == {"B"}
    rows = r.hosts.list(site="S1")
    assert {h["name"] for h in rows} == {"A", "B"}
    rows = r.hosts.list(role_like="serv")
    assert {h["name"] for h in rows} == {"A", "C"}
    r.close()


def test_mutation_visible_after_commit_and_invisible_after_rollback(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1")
    assert len(r.hosts.list()) == 1

    with pytest.raises(RuntimeError, match="boom"):
        with r.tx():
            r.hosts.create("H2")
            raise RuntimeError("boom")
    assert [h["name"] for h in r.hosts.list()] == ["H1"]
    r.close()


def test_review_event_appended_for_each_mutation(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.hosts.create("H1", actor="wenzel", note="first host")
        r.hosts.update("H1", role="db", actor="wenzel", note="promoted")
        r.hosts.retire("H1", actor="wenzel", note="no longer needed")
        r.hosts.reactivate("H1", actor="wenzel", note="back in service")
    events = r.con.execute(
        "SELECT actor, action, subject_type, subject_id FROM review_event ORDER BY id"
    ).fetchall()
    assert events == [
        ("wenzel", "create", "host", "H1"),
        ("wenzel", "update", "host", "H1"),
        ("wenzel", "retire", "host", "H1"),
        ("wenzel", "reactivate", "host", "H1"),
    ]
    r.close()
