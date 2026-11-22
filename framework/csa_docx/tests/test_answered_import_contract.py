from pathlib import Path

from csa_docx.answered_import import (
    ImportOutcome,
    ImportState,
    RatingStatus,
    answer_sheet_hash,
    document_hash,
    result_from,
    source_outcome,
)


def test_import_state_and_rating_are_explicitly_separate():
    result = result_from({
        "outcome": "READY", "state": "ready-for-improve", "section_key": "NET",
        "rating": {"assessment_status": "unresolved", "quality_status": "rated", "quality_score": 7.5},
        "provenance": {"label": "document-imported baseline"},
    })
    assert result.state is ImportState.READY_FOR_IMPROVE
    assert result.eligible_for_improve
    assert result.rating.assessment_rating is None
    assert result.rating.quality_score == 7.5
    assert result.provenance.label == "document-imported baseline"


def test_source_outcomes_cover_missing_ready_unchanged_and_changed(tmp_path: Path):
    missing = tmp_path / "missing.docx"
    assert source_outcome(missing) is ImportOutcome.MISSING
    source = tmp_path / "assessment.docx"
    source.write_bytes(b"one")
    current = document_hash(source)
    assert source_outcome(source) is ImportOutcome.READY
    assert source_outcome(source, recorded_hash=current) is ImportOutcome.UNCHANGED
    source.write_bytes(b"two")
    assert source_outcome(source, recorded_hash=current) is ImportOutcome.SOURCE_CHANGED


def test_hashes_are_stable_and_provenance_is_document_import():
    assert answer_sheet_hash("answer") == answer_sheet_hash("answer")
    rating = RatingStatus(assessment_status="unresolved", quality_status="unrated")
    assert rating.assessment_status != rating.quality_status
