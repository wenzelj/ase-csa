import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import audit_workflow, commands


def project(tmp_path: Path):
    work = tmp_path / "work"; work.mkdir()
    return {"key": "tetra-reveloc", "work_dir": str(work), "project_root": str(tmp_path), "label": "TETRA"}


def write_audit(row):
    folder = Path(row["work_dir"]) / "audit" / "20261005-010101"; folder.mkdir(parents=True)
    document = Path(row["project_root"]) / "assessment.docx"; document.write_bytes(b"doc")
    (folder / "audit.json").write_text(json.dumps({"audit_id": folder.name, "generated_at": "2026-10-05T01:01:01Z", "docx": str(document),
        "requirements": {"rows": [{"section": "3.1 Overview", "req": "APP-01", "issues": ["No owner named"]}]},
        "unknowns": {"4.2": ["Backup retention is unknown"]}, "placeholders": []}))
    return folder


def test_audit_snapshot_preserves_distinct_findings(tmp_path):
    row = project(tmp_path); write_audit(row); result = audit_workflow.snapshot(row)
    assert result["state"] == "ready"
    assert {item["disposition"] for item in result["findings"]} == {"OPEN", "DISCOVERY_REQUIRED"}
    assert result["document_hash"]


def test_audit_job_is_read_only(tmp_path):
    row = project(tmp_path); calls = []
    class Manager:
        def submit(self, _project, operation, _request): calls.append(operation); return SimpleNamespace(model_dump=lambda: {"id": "a1", "state": "queued"})
    result = audit_workflow.submit(Path(".agents"), Manager(), row)
    assert result["read_only"] is True and calls == ["audit"]
    assert commands.OPERATIONS["audit"].mutating is False


def test_gap_record_is_explicit_append_only_and_invalidates_validation(tmp_path):
    row = project(tmp_path)
    payload = {"finding_id": "AUD-001", "section": "3.1", "disposition": "NOT_FOUND", "scope": "Current captures",
               "searched_locations": "Matrix and discovery index", "recommended_action": "Ask owner for design record"}
    result = audit_workflow.record_gap(row, payload)
    assert result["record"]["statement"].startswith("This records an evidence gap")
    assert (Path(row["work_dir"]) / "proposal-validation-invalidated").exists()
    with pytest.raises(HTTPException): audit_workflow.record_gap(row, payload)


def test_gap_record_rejects_unsupported_state(tmp_path):
    row = project(tmp_path)
    with pytest.raises(HTTPException): audit_workflow.record_gap(row, {"finding_id":"x","section":"1","disposition":"VERIFIED","scope":"s","searched_locations":"m","recommended_action":"a"})
