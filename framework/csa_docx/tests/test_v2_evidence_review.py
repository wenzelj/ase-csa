"""S652: project-scoped V2 evidence verification and acceptance commands."""
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path

from csa_docx.v2repo import Repo


def _load_cli():
    path = Path(__file__).parents[3] / "bin" / "csa"
    loader = SourceFileLoader("csa_cli_s652", str(path))
    spec = importlib.util.spec_from_loader("csa_cli_s652", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        eid = repo.evidence.create(claim="APP01 is a Windows host", source_title="captures/app01.txt",
                                   excerpt="APP01 is a Windows host", area="Security", status="VERIFIED")
    repo.close()
    (work / "discovery-index.sqlite").touch()
    return work, eid


def _fake_source_check(monkeypatch, verdict):
    import csa_docx.v2repo as v2repo

    class EvidenceMatrix:
        @staticmethod
        def source_check(row, index):
            if verdict == "SOURCE_OK":
                return {"verdict": verdict}
            return {"verdict": verdict, "reason": "quote does not match"}

    monkeypatch.setattr(v2repo, "_EM", EvidenceMatrix)


def _args(action, ids):
    from types import SimpleNamespace
    return SimpleNamespace(project="test-project", v2_action="evidence", evidence_action=action,
                           evidence_ids=ids, actor="tester", note="S652 test")


def test_verify_without_ids_discovers_all_proposed_rows(tmp_path, monkeypatch, capsys):
    work, eid = _repo(tmp_path)
    repo = Repo(work)
    with repo.tx():
        no_source = repo.evidence.create(claim="A source is not attached yet", source_title="", excerpt="",
                                         status="UNCONFIRMED")
    repo.close()
    cli = _load_cli()
    monkeypatch.setattr(cli, "project", lambda _: {"key": "test-project", "work_dir": str(work)})
    _fake_source_check(monkeypatch, "SOURCE_OK")

    assert cli.cmd_v2(_args("verify", None)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "all proposed source-backed evidence"
    assert result["verified"] == 1 and result["unresolved"] == 1
    repo = Repo(work)
    assert repo.evidence.get(eid)["review_state"] == "accepted"
    assert repo.evidence.get(no_source)["review_state"] == "proposed"
    repo.close()


def test_verify_promotes_source_match_and_records_audit(tmp_path, monkeypatch, capsys):
    work, eid = _repo(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "project", lambda _: {"key": "test-project", "work_dir": str(work)})
    _fake_source_check(monkeypatch, "SOURCE_OK")

    assert cli.cmd_v2(_args("verify", [eid])) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "OK"
    assert result["results"][0]["verdict"] == "SOURCE_OK"
    repo = Repo(work)
    row = repo.evidence.get(eid)
    audit = repo.con.execute("SELECT action, subject_id FROM review_event WHERE subject_id=? ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
    repo.close()
    assert row["status"] == "VERIFIED" and row["review_state"] == "accepted"
    assert tuple(audit) == ("verify", eid)


def test_verify_failure_leaves_row_unchanged(tmp_path, monkeypatch, capsys):
    work, eid = _repo(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "project", lambda _: {"key": "test-project", "work_dir": str(work)})
    _fake_source_check(monkeypatch, "SOURCE_MISMATCH")

    assert cli.cmd_v2(_args("verify", [eid])) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["verdict"] == "SOURCE_MISMATCH"
    repo = Repo(work)
    row = repo.evidence.get(eid)
    repo.close()
    assert row["status"] == "VERIFIED" and row["review_state"] == "proposed"


def test_accept_changes_only_review_state_and_reports_missing_id(tmp_path, monkeypatch, capsys):
    work, eid = _repo(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "project", lambda _: {"key": "test-project", "work_dir": str(work)})

    assert cli.cmd_v2(_args("accept", [eid, "E-999"])) == 2
    result = json.loads(capsys.readouterr().out)
    assert [r["verdict"] for r in result["results"]] == ["ACCEPTED", "NOT_FOUND"]
    repo = Repo(work)
    row = repo.evidence.get(eid)
    repo.close()
    assert row["status"] == "VERIFIED" and row["review_state"] == "accepted"
