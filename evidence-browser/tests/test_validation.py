from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands, validation


PROPOSAL = {"section": {"visible_number": "3.1", "stable_key": "ASSET", "heading": "Assets",
                         "stable_id": "@H3.1"}, "lane": "revise", "file": "ChangesCSA_App_Section3_3-1.md",
            "etag": '"abc"'}


def run(report, exit_code=0):
    def executor(_operation, _request):
        return {"parsed": report, "exit_code": exit_code}
    return executor


def test_lane_selects_allowlisted_framework_gate():
    assert validation.operation_for("revise") == "check_change"
    assert validation.operation_for("build") == "check_section"
    assert commands.validation_operation("revise").key == "check_change"
    with pytest.raises(HTTPException): validation.operation_for("unknown")


@pytest.mark.parametrize("finding,field", [
    ({"level": "ERROR", "code": "UNKNOWN_EVIDENCE", "edit_id": "S3-E1", "message": "missing E-999"}, "evidence_ids"),
    ({"level": "ERROR", "code": "ANCHOR_UNRESOLVED", "edit_id": "S3-E2", "message": "@H3.1-P9 unresolved"}, "target"),
    ({"level": "ERROR", "code": "BAD_RATING", "edit_id": "S3-E3", "message": "rating invalid"}, "rating"),
    ({"level": "ERROR", "code": "BAD_ACTION", "edit_id": "S3-E4", "message": "operation unsupported"}, "operation"),
])
def test_findings_are_traceable_to_record_field_anchor_and_evidence(finding, field):
    result = validation.validate(Path(".agents"), {}, "3.1", {"etag": '"abc"', "file": PROPOSAL["file"]},
                                 loader=lambda _: dict(PROPOSAL), executor=run({"findings": [finding], "errors": 1}))
    item = result["findings"][0]
    assert item["field"] == field and item["record_id"] == finding["edit_id"]
    if "@H" in finding["message"]: assert item["stable_anchor"] == "@H3.1-P9"
    if "E-" in finding["message"]: assert item["evidence_ids"] == ["E-999"]


def test_warnings_only_and_clean_reports_pass_with_hash_binding():
    warning = validation.validate(Path(".agents"), {}, "3.1", {"etag": '"abc"', "file": PROPOSAL["file"]},
                                  loader=lambda _: dict(PROPOSAL), executor=run({"findings": [{"level": "WARN", "code": "NO_BRIEF", "message": "brief missing"}]}))
    clean = validation.validate(Path(".agents"), {}, "3.1", {"etag": '"abc"', "file": PROPOSAL["file"]},
                                loader=lambda _: dict(PROPOSAL), executor=run({"findings": []}))
    assert warning["valid"] and warning["warnings"] == 1
    assert clean["valid"] and clean["file_hash"] == '"abc"'


def test_stale_identity_is_rejected_without_running_validator():
    called = False
    def executor(*_args):
        nonlocal called; called = True
    with pytest.raises(HTTPException) as error:
        validation.validate(Path(".agents"), {}, "3.1", {"etag": '"old"', "file": PROPOSAL["file"]},
                            loader=lambda _: dict(PROPOSAL), executor=executor)
    assert error.value.status_code == 409 and not called


def test_validation_does_not_mutate_proposal_or_document(tmp_path):
    proposal_file = tmp_path / PROPOSAL["file"]; document = tmp_path / "assessment.docx"
    proposal_file.write_text("proposal", encoding="utf-8"); document.write_bytes(b"docx")
    before = proposal_file.read_bytes(), document.read_bytes()
    validation.validate(Path(".agents"), {}, "3.1", {"etag": '"abc"', "file": PROPOSAL["file"]},
                        loader=lambda _: dict(PROPOSAL), executor=run({"findings": []}))
    assert before == (proposal_file.read_bytes(), document.read_bytes())
