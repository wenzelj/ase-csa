from csa_docx.improve_contract import ImprovementProposal
from csa_docx.improve_lane import check, validate_for_context


def context(**overrides):
    value = {
        "section_key": "3.4",
        "document_hash": "sha256:current",
        "answer_text": "The system uses the primary time source.",
        "supporting_evidence_ids": ["E-001"],
        "new_evidence": [{"evidence_id": "E-004", "source": "capture.txt"}],
        "related_evidence": [],
    }
    value.update(overrides)
    return value


def proposal(**overrides):
    value = {
        "section_key": "3.4",
        "base_document_hash": "sha256:current",
        "status": "improve",
        "edits": [{
            "block_id": "B1", "operation": "insert_after",
            "before": "The system uses the primary time source.",
            "after": "The system also has a fallback time source.",
            "reason": "Add the verified fallback detail.", "evidence_ids": ["E-004"],
        }],
        "rating_decision": "keep", "evidence_ids": [],
    }
    value.update(overrides)
    return value


def test_validates_against_current_context():
    result = check(proposal(), context())
    assert result["valid"] is True
    assert result["errors"] == []


def test_stale_hash_and_wrong_section_are_refused():
    errors = validate_for_context(proposal(base_document_hash="sha256:old", section_key="3.5"), context())
    assert "proposal section_key does not match the context" in errors
    assert "proposal base_document_hash is stale" in errors


def test_edit_must_anchor_in_current_answer():
    errors = validate_for_context(proposal(edits=[{
        "block_id": "B1", "operation": "replace_sentence", "before": "Text no longer present",
        "after": "Replacement", "reason": "Correction", "evidence_ids": ["E-004"],
    }]), context())
    assert "B1: before text is not in the current answer" in errors


def test_unknown_evidence_and_future_state_are_refused():
    errors = validate_for_context(proposal(edits=[{
        "block_id": "B1", "operation": "insert_after",
        "before": "The system uses the primary time source.",
        "after": "The system should use a new future state source.",
        "reason": "Recommendation", "evidence_ids": ["E-999"],
    }]), context())
    assert any("outside the supplied context" in error for error in errors)
    assert "B1: future-state recommendations are not current-state edits" in errors


def test_not_met_cannot_rest_only_on_absence():
    errors = validate_for_context(proposal(
        rating_decision="change", new_rating="Not Met", rating_basis="No evidence was found",
        evidence_ids=["E-001"], edits=[{
            "block_id": "B1", "operation": "keep",
            "before": "The system uses the primary time source.",
            "reason": "Retain the current fact", "evidence_ids": [],
        }]
    ), context())
    assert "Not Met cannot be based only on an absence of evidence" in errors
