from pathlib import Path

from csa_docx.answered_import import extract_section, map_current_content, resolve_section


def test_maps_rendered_paragraphs_tables_and_questions_without_evidence_ids(tmp_path: Path):
    document = tmp_path / "assessment.txt"
    document.write_text(
        "3.4 Time Synchronisation\n"
        "Current state is documented.\n"
        "QUESTION: Which fallback source is used?\n"
        "3.5 DNS\nOther answer.\n", encoding="utf-8"
    )
    card = {"questions": [{"id": "B1", "kind": "requirement"}, {"id": "B2", "kind": "narrative"}]}
    section = extract_section(document, "3.4")
    mapped = map_current_content(card, section)
    assert mapped["sheet"]["B1"]["provenance"] == "document-imported"
    assert "Current state is documented." in mapped["sheet"]["B1"]["text"]
    assert mapped["sheet"]["B1"]["unknown"] == ["Which fallback source is used?"]
    assert not mapped["sheet"]["B1"]["facts"]


def test_empty_card_content_is_reported_as_unmappable(tmp_path: Path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nExisting answer.\n", encoding="utf-8")
    result = map_current_content({}, extract_section(document, "3.4"))
    assert result["sheet"] == {}
    assert result["unmappable"] == ("Existing answer.",)


def test_resolves_from_document_spec_and_keeps_nested_heading_content(tmp_path: Path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\n### Discovery Information\nAnswer.\n3.5 DNS\nOther.\n", encoding="utf-8")
    spec = {"nodes": [{"key": "TIME", "number": "3.4", "title": "Time Synchronisation"}]}
    selected = resolve_section(spec, section_key="TIME")
    assert selected["number"] == "3.4"
    assert selected["title"] == "Time Synchronisation"


def test_deterministic_requirement_rows_and_invalid_rating_are_reported(tmp_path: Path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nRating: Unknown\n", encoding="utf-8")
    card = {"ratings": ["Met", "Not Met"], "questions": [{"id": "B1", "kind": "requirement"}, {"id": "B2", "kind": "requirement"}]}
    section = {"blocks": [{"kind": "paragraph", "text": "Rating: Unknown"}, {"kind": "table", "rows": [["B2", "value"]]}]}
    mapped = map_current_content(card, section)
    assert mapped["sheet"]["B2"]["rows"] == [["B2", "value"]]
    assert mapped["sheet"]["B1"]["rating"] == ""
    assert any("Invalid or unsupported" in item for item in mapped["unmappable"])
