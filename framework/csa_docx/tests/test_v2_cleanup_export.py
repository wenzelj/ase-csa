import json

import pytest

from csa_docx import v2_cleanup
from csa_docx.v2repo import Repo


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as con:
        r.hosts.create("H1")
        con.execute("INSERT INTO evidence(id, claim, review_state) VALUES ('E-1','old','rejected')")
        con.execute("INSERT INTO evidence(id, claim) VALUES ('E-2','keep')")
        con.execute("INSERT INTO lead(id, question, state) VALUES ('L-1','old','retired')")
        con.execute("INSERT INTO lead(id, question, state) VALUES ('L-2','keep','open')")
        con.execute("INSERT INTO application_scope(application_key,host_name,membership,review_state,active) VALUES ('app','H1','owned','rejected',0)")
    yield r
    r.close()


def test_dry_run_pack_contains_predicate_counts_and_hash(repo, tmp_path):
    out = tmp_path / "pack.json"
    result = v2_cleanup.create_pack(repo.path.parent, out=out)
    pack = json.loads(out.read_text())
    assert result["status"] == "DRY_RUN"
    assert pack["selection_predicate"] == v2_cleanup.PREDICATE
    assert pack["row_counts"] == {"evidence": 1, "leads": 1, "application_scope": 1, "review_events": 0}
    assert len(pack["database_sha256"]) == 64
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2


def test_hash_guard_and_restore(repo, tmp_path):
    out = tmp_path / "pack.json"
    v2_cleanup.create_pack(repo.path.parent, out=out)
    with repo.tx() as con:
        con.execute("UPDATE evidence SET claim='changed' WHERE id='E-2'")
    with pytest.raises(RuntimeError, match="database changed"):
        v2_cleanup.apply_pack(repo.path.parent, out)


def test_apply_and_restore_pack(repo, tmp_path):
    out = tmp_path / "pack.json"
    v2_cleanup.create_pack(repo.path.parent, out=out)
    v2_cleanup.apply_pack(repo.path.parent, out)
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    v2_cleanup.restore_pack(repo.path.parent, out)
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2
