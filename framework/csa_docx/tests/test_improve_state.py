import json

from csa_docx.improve_state import (
    improve_root, latest_run, new_run, proposal_path, read_proposal, read_runs,
    write_proposal, write_run,
)


def test_improve_state_is_separate_from_draft_runs(tmp_path):
    root = improve_root(tmp_path)
    run = new_run("3.4", context_hash="ctx-1", base_document_hash="doc-1")
    run["status"] = "proposed"
    saved = write_run(root, run)
    assert saved["run_id"] == run["run_id"]
    assert (tmp_path / "csa-work" / "improve" / "runs.json").is_file()
    assert not (tmp_path / "csa-work" / "draft" / "runs.json").exists()
    assert latest_run(root, "3.4")["status"] == "proposed"


def test_state_replaces_same_run_and_keeps_history(tmp_path):
    root = improve_root(tmp_path)
    run = new_run("3.4")
    write_run(root, run)
    run["status"] = "failed"
    write_run(root, run)
    rows = read_runs(root)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"


def test_proposal_round_trip_is_atomic_and_section_scoped(tmp_path):
    root = improve_root(tmp_path)
    payload = {"section_key": "3.4", "status": "no_material_change"}
    path = write_proposal(root, "3.4", payload)
    assert path == proposal_path(root, "3.4")
    assert read_proposal(root, "3.4") == payload
    assert not list(root.rglob("*.json.tmp"))


def test_legacy_or_missing_state_is_read_as_empty(tmp_path):
    root = improve_root(tmp_path)
    assert read_runs(root) == []
    assert latest_run(root, "3.4") is None
    assert read_proposal(root, "3.4") is None


def test_invalid_run_is_rejected(tmp_path):
    root = improve_root(tmp_path)
    try:
        write_run(root, {"version": 1, "run_id": "x", "section_key": "3.4", "status": "answering"})
    except ValueError as exc:
        assert "unsupported Improve run status" in str(exc)
    else:
        raise AssertionError("invalid Improve run was accepted")
