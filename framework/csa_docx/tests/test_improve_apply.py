from pathlib import Path

import pytest

from csa_docx.improve_lane import apply_proposal


def context_for(path: Path):
    from hashlib import sha256
    return {"section_key": "3.4", "document_hash": "sha256:" + sha256(path.read_bytes()).hexdigest(),
            "answer_text": "The current answer.", "supporting_evidence_ids": [],
            "new_evidence": [{"evidence_id": "E-004"}], "related_evidence": []}


def proposal():
    return {"section_key": "3.4", "base_document_hash": "sha256:placeholder", "status": "improve",
            "edits": [{"block_id": "B1", "operation": "replace_sentence", "before": "The current answer.",
                       "after": "The improved answer.", "reason": "Correct the named gap.", "evidence_ids": ["E-004"]}],
            "rating_decision": "keep", "evidence_ids": []}


def test_apply_creates_backup_and_changes_only_the_bounded_text(tmp_path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time\nThe current answer.\n3.5 DNS\nLeave this alone.\n", encoding="utf-8")
    context = context_for(document)
    payload = proposal(); payload["base_document_hash"] = context["document_hash"]
    result = apply_proposal(document, payload, context, tmp_path / "backups")
    assert result["status"] == "OK"
    assert document.read_text(encoding="utf-8") == "3.4 Time\nThe improved answer.\n3.5 DNS\nLeave this alone.\n"
    assert Path(result["backup"]).is_file()


def test_apply_refuses_document_drift_without_mutation(tmp_path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time\nThe current answer.\n", encoding="utf-8")
    context = context_for(document)
    payload = proposal(); payload["base_document_hash"] = context["document_hash"]
    document.write_text("3.4 Time\nA newer answer.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since"):
        apply_proposal(document, payload, context, tmp_path / "backups")
    assert list((tmp_path / "backups").glob("*")) == []
