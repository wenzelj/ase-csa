import json
from pathlib import Path

from csa_docx.section_state import project


def test_imported_state_is_ready_for_improve(tmp_path: Path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "NET.IMPORT.json").write_text(json.dumps({
        "state": "ready-for-improve",
        "provenance": {"label": "document-imported baseline", "source_document_hash": "sha256:x"},
        "rating": {"assessment_status": "unresolved", "quality_status": "unrated"},
        "warnings": ["revalidate evidence"],
    }))
    state = project(tmp_path, "NET")
    assert state["draft_state"] == "answered-imported"
    assert state["eligible_for_improve"] is True
    assert state["provenance"] == "document-imported baseline"


def test_missing_state_remains_not_answered(tmp_path: Path):
    assert project(tmp_path, "NET")["eligible_for_improve"] is False
