import pytest

from csa_docx.improve_contract import ContractError, ImprovementProposal, validate_proposal


def valid_payload(**overrides):
    payload = {
        "section_key": "3.4",
        "base_document_hash": "sha256:abc",
        "base_answer_run_id": None,
        "status": "improve",
        "diagnosis": ["The current answer omits the fallback source."],
        "edits": [{
            "block_id": "B1",
            "operation": "insert_after",
            "before": "The system uses the primary source.",
            "after": "The system also has a fallback source.",
            "reason": "Fill the identified evidence gap.",
            "evidence_ids": ["E-004"],
        }],
        "rating_decision": "keep",
        "evidence_ids": ["E-004"],
        "remaining_questions": [],
    }
    payload.update(overrides)
    return payload


def test_valid_proposal_is_typed_and_round_trips():
    proposal = ImprovementProposal.from_dict(valid_payload()).checked()
    assert proposal.section_key == "3.4"
    assert proposal.edits[0].evidence_ids == ("E-004",)
    assert ImprovementProposal.from_dict(proposal.to_dict()) == proposal


def test_changed_rating_requires_basis_and_evidence():
    payload = valid_payload(rating_decision="change", new_rating="Partially Met")
    errors = validate_proposal(payload)
    assert "rating changes require rating_basis" in errors
    assert "rating changes require evidence_ids" not in errors


def test_no_material_change_cannot_contain_edits():
    errors = validate_proposal(valid_payload(status="no_material_change"))
    assert "no_material_change proposals cannot contain edits" in errors


def test_blocked_proposal_requires_diagnosis_and_no_edits():
    payload = valid_payload(status="blocked", edits=[], diagnosis=[])
    errors = validate_proposal(payload)
    assert "blocked proposals require diagnosis" in errors


def test_unknown_evidence_and_malformed_edit_are_rejected():
    payload = valid_payload()
    payload["edits"][0]["evidence_ids"] = ["L-001"]
    errors = validate_proposal(payload)
    assert any("invalid IDs" in error for error in errors)


def test_keep_edit_does_not_allow_replacement_text():
    payload = valid_payload(edits=[{
        "block_id": "B1", "operation": "keep", "before": "Existing text",
        "after": "Changed text", "reason": "No change", "evidence_ids": [],
    }])
    errors = validate_proposal(payload)
    assert "B1: keep edits cannot contain after text" in errors


def test_missing_required_fields_are_reported_without_raising_from_validator():
    assert validate_proposal({}) == ("status is required",)
    with pytest.raises(ContractError):
        ImprovementProposal.from_dict({})
