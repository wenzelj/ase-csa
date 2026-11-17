from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from csa_docx.improve_context import ContextError, build_context, extract_section


def write_docx(path, paragraphs):
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{("Heading2" if text[:1].isdigit() else "Normal")}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'''
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)


def test_extracts_only_the_selected_current_subsection(tmp_path):
    docx = tmp_path / "assessment.docx"
    write_docx(docx, ["3.4 Time Synchronisation", "The current answer.", "3.5 DNS", "Another answer."])
    result = extract_section(docx, "3.4")
    assert result["heading"] == "3.4 Time Synchronisation"
    assert [block["text"] for block in result["blocks"]] == ["The current answer."]


def test_context_hashes_document_and_marks_legacy_provenance(tmp_path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nThe current answer.\n3.5 DNS\nDNS answer.\n", encoding="utf-8")
    context = build_context("3.4", document, rating="Partially Met", supporting_evidence=["E-002", "E-001"])
    assert context["document_hash"].startswith("sha256:")
    assert context["provenance"] == "legacy/unknown"
    assert context["supporting_evidence_ids"] == ["E-001", "E-002"]
    assert context["answer_text"] == "The current answer."


def test_context_preserves_run_findings_questions_and_bounded_evidence(tmp_path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.4 Time Synchronisation\nThe current answer.\n", encoding="utf-8")
    context = build_context(
        "3.4", document, answer_run_id="run-1", findings=["Missing fallback"],
        open_questions=["What is the fallback source?"],
        new_evidence=[{"evidence_id": "E-004", "source": "capture.txt", "line": 8}],
    )
    assert context["provenance"] == "recorded"
    assert context["findings"] == ["Missing fallback"]
    assert context["open_questions"] == ["What is the fallback source?"]
    assert context["new_evidence"][0]["evidence_id"] == "E-004"


def test_missing_or_unanswered_section_is_refused(tmp_path):
    document = tmp_path / "assessment.txt"
    document.write_text("3.5 DNS\nDNS answer.\n", encoding="utf-8")
    with pytest.raises(ContextError, match="subsection 3.4 is not present"):
        build_context("3.4", document)

    document.write_text("3.4 Time Synchronisation\n3.5 DNS\nDNS answer.\n", encoding="utf-8")
    with pytest.raises(ContextError, match="has no current answer"):
        build_context("3.4", document)


def test_missing_working_document_is_refused(tmp_path):
    with pytest.raises(ContextError, match="working document is missing"):
        build_context("3.4", tmp_path / "missing.docx")
