import json
from pathlib import Path

from csa_docx.answered_import import ImportState, import_state


def test_import_state_writes_framework_artifacts_without_mutating_document(tmp_path: Path, monkeypatch):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nCurrent answer.\n", encoding="utf-8")
    before = document.read_bytes()
    seen = {}
    def rate(*args, **kwargs):
        seen["call"] = (args, kwargs)
        return {"status": "OK", "average": 7.4}
    monkeypatch.setattr("csa_docx.answered_import.rating_pass.rate_text", rate)
    result = import_state(tmp_path / "work", {"key": "TIME", "number": "3.4", "title": "Time Synchronisation",
                                               "questions": [{"id": "B1", "kind": "requirement"}]}, document,
                         rating_template="rating")
    assert result.state is ImportState.READY_FOR_IMPROVE
    cards = tmp_path / "work" / "cards"
    assert (cards / "TIME.json").is_file()
    assert (cards / "TIME.answer.md").is_file()
    manifest = json.loads((cards / "TIME.manifest.json").read_text())
    assert manifest["status"] == "IMPORTED"
    assert manifest["source_document_hash"].startswith("sha256:")
    assert result.rating.quality_status == "rated"
    assert result.rating.quality_score == 7.4
    assert seen["call"][0][5] == "rating"
    assert document.read_bytes() == before


def test_import_state_persists_quality_rating_failure(tmp_path: Path, monkeypatch):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nCurrent answer.\n", encoding="utf-8")
    monkeypatch.setattr("csa_docx.answered_import.rating_pass.rate_text",
                        lambda *args, **kwargs: {"status": "ERROR", "message": "rating endpoint unavailable"})
    result = import_state(tmp_path / "work", {"key": "TIME", "number": "3.4", "title": "Time Synchronisation",
                                               "questions": [{"id": "B1", "kind": "requirement"}]}, document,
                         rating_template="rating")
    assert result.rating.quality_status == "error"
    assert result.rating.quality_error == "rating endpoint unavailable"
    record = json.loads((tmp_path / "work" / "cards" / "TIME.IMPORT.json").read_text())
    assert record["rating"]["quality_error"] == "rating endpoint unavailable"


def test_import_state_refuses_a_changed_source(tmp_path: Path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nCurrent answer.\n", encoding="utf-8")
    first = import_state(tmp_path / "work", {"key": "TIME", "number": "3.4", "title": "Time Synchronisation",
                                               "questions": [{"id": "B1"}]}, document)
    document.write_text("3.4 Time Synchronisation\nChanged answer.\n", encoding="utf-8")
    second = import_state(tmp_path / "work", {"key": "TIME", "number": "3.4", "title": "Time Synchronisation",
                                                "questions": [{"id": "B1"}]}, document,
                         recorded_hash=first.provenance.source_document_hash)
    assert second.outcome.value == "SOURCE_CHANGED"
    assert second.state is ImportState.STALE
