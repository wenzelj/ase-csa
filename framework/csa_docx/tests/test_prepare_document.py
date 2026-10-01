from pathlib import Path
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import tools
from csa_docx.ooxml import DocumentEditor, make_paragraph, qn, W_NS


def test_check_document_ready_flags_a_missing_docx(tmp_path):
    readiness = tools._check_document_ready(tmp_path / "nowhere.docx")
    assert readiness.ok is False
    assert readiness.reasons == ["missing_docx"]
    assert "does not exist" in readiness.message


def test_check_document_ready_flags_a_zero_byte_docx(tmp_path):
    docx = tmp_path / "empty.docx"
    docx.write_bytes(b"")
    readiness = tools._check_document_ready(docx)
    assert readiness.ok is False
    assert readiness.reasons == ["empty_docx"]


def test_check_document_ready_flags_a_package_that_is_not_a_zip(tmp_path):
    docx = tmp_path / "half-written.docx"
    docx.write_bytes(b"PK\x03\x04 truncated mid-write")
    readiness = tools._check_document_ready(docx)
    assert readiness.ok is False
    assert readiness.reasons == ["unreadable_archive"]


def test_word_lock_file_is_detected_under_both_naming_conventions(tmp_path):
    docx = _make_test_docx(tmp_path)

    truncated = docx.with_name(f"~${docx.name[2:]}")
    truncated.write_bytes(b"owner")
    assert tools._word_lock_files(docx) == [truncated]
    truncated.unlink()

    full = docx.with_name(f"~${docx.name}")
    full.write_bytes(b"owner")
    assert tools._word_lock_files(docx) == [full]


def test_prepare_document_reports_not_ready_when_the_docx_is_open_in_word(tmp_path):
    workspace = _make_workspace(tmp_path)
    docx = _workspace_docx(workspace)
    docx.with_name(f"~${docx.name[2:]}").write_bytes(b"owner file")

    result = tools.prepareDocument("1", workspace=workspace)

    assert result["status"] == "NOT_READY"
    assert result["reasons"] == ["locked_by_word"]
    assert "open in Word" in result["message"]
    assert result["section"] == "1"
    assert result["id_manifest_summary"]["regenerated"] is False
    assert not tools._id_manifest_path(workspace, docx).exists()


def test_prepare_document_reports_not_ready_when_the_resolved_docx_is_missing(tmp_path):
    workspace = _make_workspace(tmp_path)
    docx = _workspace_docx(workspace)
    # The section manifest still resolves the section (the name is still in
    # the folder listing) but the file behind it has gone -- a dropped
    # network/OneDrive mount, not a manifest problem.
    docx.unlink()
    docx.symlink_to(tmp_path / "gone.docx")

    result = tools.prepareDocument("1", workspace=workspace)

    assert result["status"] == "NOT_READY"
    assert result["reasons"] == ["missing_docx"]


def test_prepare_document_reports_not_ready_when_the_document_is_corrupt(tmp_path):
    workspace = _make_workspace(tmp_path)
    _workspace_docx(workspace).write_bytes(b"not a zip at all")

    result = tools.prepareDocument("1", workspace=workspace)

    assert result["status"] == "NOT_READY"
    assert result["reasons"] == ["unreadable_archive"]


def test_prepare_document_generates_the_id_manifest_for_a_clean_document(tmp_path):
    workspace = _make_workspace(tmp_path)

    result = tools.prepareDocument("1", workspace=workspace)

    assert result["status"] == "READY"
    assert result["reasons"] == []
    assert result["docx"] == str(_workspace_docx(workspace))
    summary = result["id_manifest_summary"]
    assert summary["regenerated"] is True
    assert summary["reason"] == "created"
    assert summary["headings"] == 2
    assert summary["paragraphs"] == 3
    assert summary["runs"] == summary["table_rows"]
    assert result["validation"]["archive_integrity"] == "Pass"

    manifest_path = tools._id_manifest_path(workspace, _workspace_docx(workspace))
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["generated_by_section"] == "1"
    assert [entry["id"] for entry in payload["entries"] if entry["kind"] == "heading"] == ["@H1", "@H1.1"]


def test_prepare_document_is_a_no_op_on_an_unchanged_document(tmp_path):
    workspace = _make_workspace(tmp_path)
    first = tools.prepareDocument("1", workspace=workspace)
    assert first["id_manifest_summary"]["regenerated"] is True

    manifest_path = tools._id_manifest_path(workspace, _workspace_docx(workspace))
    before = manifest_path.read_bytes()

    second = tools.prepareDocument("1", workspace=workspace)

    assert second["status"] == "READY"
    summary = second["id_manifest_summary"]
    assert summary["regenerated"] is False
    assert summary["reason"] == "unchanged"
    assert summary["paragraphs"] == first["id_manifest_summary"]["paragraphs"]
    assert manifest_path.read_bytes() == before


def test_prepare_document_rebuilds_when_the_heading_structure_drifts(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    _write_test_docx(_workspace_docx(workspace), extra_heading=True)
    result = tools.prepareDocument("1", workspace=workspace)

    summary = result["id_manifest_summary"]
    assert result["status"] == "READY"
    assert summary["regenerated"] is True
    assert summary["reason"] == "structure_drift"
    assert summary["headings"] == 3


def test_prepare_document_shares_one_manifest_across_sections_on_the_same_docx(tmp_path):
    """The real-world case this exists for: every section's change file
    points at the same working .docx, so preparing section 1 already
    prepares the whole document -- section 2's call must find the same
    manifest already built and report a no-op, not rebuild a duplicate."""
    workspace = _make_workspace(tmp_path)

    first = tools.prepareDocument("1", workspace=workspace)
    assert first["id_manifest_summary"]["regenerated"] is True
    assert first["docx"] == str(_workspace_docx(workspace))

    manifest_path = tools._id_manifest_path(workspace, _workspace_docx(workspace))
    before = manifest_path.read_bytes()

    second = tools.prepareDocument("2", workspace=workspace)

    assert second["status"] == "READY"
    assert second["docx"] == first["docx"]
    assert tools._id_manifest_path(workspace, _workspace_docx(workspace)) == manifest_path
    summary = second["id_manifest_summary"]
    assert summary["regenerated"] is False
    assert summary["reason"] == "unchanged"
    # It really is the whole document's manifest, not scoped to section 1:
    # section 2's own paragraph shows up in it even though section 1 was
    # the call that built it.
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert any(e["text"] == "DNS body paragraph." for e in payload["entries"])
    assert manifest_path.read_bytes() == before


def test_prepare_document_works_at_true_step_zero_with_only_the_bare_docx(tmp_path):
    """The actual entry point: before any reviews/ folder or ChangesCSA_*.md
    file exists -- just the raw .docx alone in a folder -- prepareDocument
    must still find it and build the ID manifest. There is no section
    manifest for it to lean on yet; that's the point of this test."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_test_docx(workspace / "Current State Assessment - IAMPS.docx")
    assert not (workspace / "reviews").exists()

    result = tools.prepareDocument(workspace=workspace)

    assert result["status"] == "READY"
    assert result["section"] is None
    assert result["change_file"] is None
    assert result["docx"] == str(workspace / "Current State Assessment - IAMPS.docx")
    summary = result["id_manifest_summary"]
    assert summary["regenerated"] is True
    assert summary["reason"] == "created"
    assert summary["headings"] == 2
    assert summary["paragraphs"] == 3


def test_lookup_stable_id_works_at_true_step_zero_with_only_the_bare_docx(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_test_docx(workspace / "Current State Assessment - IAMPS.docx")
    tools.prepareDocument(workspace=workspace)

    result = tools.lookupStableId("first body paragraph", workspace=workspace)

    assert result["status"] == "OK"
    assert result["section"] is None
    assert result["unique_id"] == "@H1-P1"


def test_prepare_document_at_step_zero_refuses_to_guess_among_two_bare_docs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_test_docx(workspace / "Current State Assessment - IAMPS.docx")
    _write_test_docx(workspace / "Other Document.docx")

    result = tools.prepareDocument(workspace=workspace)

    assert result["status"] == "ERROR"
    assert "2 .docx files found" in result["message"]


def test_prepare_document_at_step_zero_ignores_an_archived_docx(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "archive").mkdir(parents=True)
    _write_test_docx(workspace / "Current State Assessment - IAMPS.docx")
    _write_test_docx(workspace / "archive" / "Current State Assessment - IAMPS - old.docx")

    result = tools.prepareDocument(workspace=workspace)

    assert result["status"] == "READY"
    assert result["docx"] == str(workspace / "Current State Assessment - IAMPS.docx")


def test_prepare_document_still_works_after_reviews_are_added_on_top(tmp_path):
    """Once reviewDocument (or a human) adds the first ChangesCSA_*.md,
    a later prepareDocument() call must keep finding the same manifest
    it already built at step 0 -- not error, not silently rebuild."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docx = workspace / "Current State Assessment - IAMPS.docx"
    _write_test_docx(docx)

    first = tools.prepareDocument(workspace=workspace)
    assert first["section"] is None
    manifest_path = tools._id_manifest_path(workspace, docx)
    before = manifest_path.read_bytes()

    reviews = workspace / "reviews"
    reviews.mkdir()
    (reviews / "ChangesCSA_IAMPS_Section1.md").write_text(
        """# Section 1 - Network Services

### E-1 - Clarify the first body paragraph
**Where:** Section 1, sentence beginning exactly:
`First body paragraph.`

**Do:** Replace

**Text:**

> First body paragraph, clarified.

**Why:**
Fixture edit for the readiness tests.
""",
        encoding="utf-8",
    )

    second = tools.prepareDocument(workspace=workspace)

    assert second["status"] == "READY"
    assert second["section"] == "1"  # now resolvable via the section manifest
    assert tools._id_manifest_path(workspace, docx) == manifest_path
    assert second["id_manifest_summary"]["regenerated"] is False
    assert manifest_path.read_bytes() == before


def test_prepare_document_with_no_section_resolves_the_one_shared_docx(tmp_path):
    """section is optional: prepareDocument() with nothing passed prepares
    the whole document by finding the one working docx every section
    already shares, same as prepareDocument("1") or prepareDocument("2")."""
    workspace = _make_workspace(tmp_path)

    result = tools.prepareDocument(workspace=workspace)

    assert result["status"] == "READY"
    assert result["docx"] == str(_workspace_docx(workspace))
    # The lowest-numbered section is reported as a readable label, but it
    # has no other significance -- any section sharing the docx would do.
    assert result["section"] == "1"
    assert result["id_manifest_summary"]["regenerated"] is True


def test_lookup_stable_id_with_no_section_resolves_the_one_shared_docx(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument(workspace=workspace)

    result = tools.lookupStableId("first body paragraph", workspace=workspace)

    assert result["status"] == "OK"
    assert result["unique_id"] == "@H1-P1"


def test_prepare_document_requires_a_section_when_the_workspace_has_two_distinct_docs(tmp_path):
    workspace = _make_workspace_with_two_documents(tmp_path)

    result = tools.prepareDocument(workspace=workspace)

    assert result["status"] == "ERROR"
    assert "distinct working DOCX" in result["message"]
    assert "section" in result["message"]

    # Passing an explicit section still resolves unambiguously.
    explicit = tools.prepareDocument("1", workspace=workspace)
    assert explicit["status"] == "READY"


def test_lookup_stable_id_requires_a_section_when_the_workspace_has_two_distinct_docs(tmp_path):
    workspace = _make_workspace_with_two_documents(tmp_path)
    tools.prepareDocument("1", workspace=workspace)
    tools.prepareDocument("2", workspace=workspace)

    result = tools.lookupStableId("First body paragraph", workspace=workspace)

    assert result["status"] == "ERROR"
    assert "distinct working DOCX" in result["message"]


def test_prepare_document_force_regenerate_rebuilds_an_unchanged_document(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    result = tools.prepareDocument("1", workspace=workspace, force_regenerate=True)

    assert result["id_manifest_summary"]["regenerated"] is True
    assert result["id_manifest_summary"]["reason"] == "forced"


def test_prepare_document_surfaces_an_unresolvable_section_as_error(tmp_path):
    workspace = _make_workspace(tmp_path)

    result = tools.prepareDocument("9", workspace=workspace)

    assert result["status"] == "ERROR"
    assert "section 9" in result["message"]


def test_lookup_stable_id_reports_error_when_document_has_not_been_prepared(tmp_path):
    workspace = _make_workspace(tmp_path)

    result = tools.lookupStableId("First body paragraph", "1", workspace=workspace)

    assert result["status"] == "ERROR"
    assert "prepareDocument" in result["message"]


def test_lookup_stable_id_finds_a_unique_text_match(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    result = tools.lookupStableId("first body paragraph", "1", workspace=workspace)

    assert result["status"] == "OK"
    assert result["match_count"] == 1
    assert result["truncated"] is False
    assert result["unique_id"] == "@H1-P1"
    assert result["matches"][0]["text"] == "First body paragraph."
    assert result["possibly_stale"] is False


def test_lookup_stable_id_resolves_an_exact_stable_id(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    result = tools.lookupStableId("@H1-P1", "1", workspace=workspace)

    assert result["status"] == "OK"
    assert result["match_count"] == 1
    assert result["unique_id"] == "@H1-P1"
    assert result["matches"][0]["kind"] == "paragraph"


def test_lookup_stable_id_returns_no_matches_without_erroring(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    result = tools.lookupStableId("nothing in this document says this", "1", workspace=workspace)

    assert result["status"] == "OK"
    assert result["match_count"] == 0
    assert result["matches"] == []
    assert result["unique_id"] is None


def test_lookup_stable_id_filters_by_kind_and_respects_limit(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    # "paragraph." matches all three body paragraphs in the fixture doc
    # ("First body paragraph.", "Second body paragraph.", "DNS body
    # paragraph."); kind narrows it, limit caps it.
    all_paragraphs = tools.lookupStableId("paragraph.", "1", workspace=workspace)
    assert all_paragraphs["match_count"] == 3
    assert all_paragraphs["unique_id"] is None

    headings_only = tools.lookupStableId("s", "1", workspace=workspace, kind="heading")
    assert headings_only["match_count"] == 2  # "Network Services" and "DNS"
    assert all(m["kind"] == "heading" for m in headings_only["matches"])

    capped = tools.lookupStableId("paragraph.", "1", workspace=workspace, limit=1)
    assert capped["match_count"] == 3
    assert capped["truncated"] is True
    assert len(capped["matches"]) == 1


def test_lookup_stable_id_is_case_sensitive_when_requested(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)

    insensitive = tools.lookupStableId("FIRST BODY", "1", workspace=workspace)
    assert insensitive["match_count"] == 1

    sensitive = tools.lookupStableId("FIRST BODY", "1", workspace=workspace, case_sensitive=True)
    assert sensitive["match_count"] == 0


def test_lookup_stable_id_flags_a_manifest_older_than_the_docx(tmp_path):
    workspace = _make_workspace(tmp_path)
    tools.prepareDocument("1", workspace=workspace)
    manifest_path = tools._id_manifest_path(workspace, _workspace_docx(workspace))

    # Touch the docx to a later mtime than the cached manifest without
    # actually changing its content -- lookupStableId flags this from stat()
    # alone, it never re-opens the document to check.
    docx = _workspace_docx(workspace)
    future = manifest_path.stat().st_mtime + 5
    os.utime(docx, (future, future))

    result = tools.lookupStableId("First body paragraph", "1", workspace=workspace)

    assert result["status"] == "OK"
    assert result["possibly_stale"] is True


def test_lookup_stable_id_surfaces_an_unresolvable_section_as_error(tmp_path):
    workspace = _make_workspace(tmp_path)

    result = tools.lookupStableId("anything", "9", workspace=workspace)

    assert result["status"] == "ERROR"
    assert "section 9" in result["message"]


def test_apply_next_batch_returns_not_ready_and_touches_nothing_when_locked(tmp_path):
    workspace = _make_workspace(tmp_path)
    docx = _workspace_docx(workspace)
    lock = docx.with_name(f"~${docx.name[2:]}")
    lock.write_bytes(b"owner file")
    before = docx.read_bytes()

    result = tools.apply_next_batch("1", limit=1, workspace=workspace)

    assert result["status"] == "NOT_READY"
    assert result["reasons"] == ["locked_by_word"]
    assert result["batch_ids"] == ["E-1"]
    assert docx.read_bytes() == before
    assert list(docx.parent.glob("*.bak")) == []
    assert not tools.state_path(workspace, "1").exists()


def test_apply_next_batch_still_runs_when_no_lock_file_is_present(tmp_path):
    workspace = _make_workspace(tmp_path)

    result = tools.apply_next_batch("1", limit=1, workspace=workspace)

    # The readiness gate is a precondition, not a new blocker: a clean
    # document still applies its batch and returns the shape it always has.
    assert result["status"] == "SECTION_COMPLETE"
    assert result["applied"] == ["E-1"]
    assert "reasons" not in result
    assert result["backup"] is not None
    assert result["validation"]["archive_integrity"] == "Pass"


def _make_workspace(tmp_path) -> Path:
    """A minimal workspace laid out the way manifest.build_manifest expects:
    one ``reviews/ChangesCSA_..._Section<N>.md`` and one working
    ``.docx`` in the Final Version folder one level up."""
    final_version = tmp_path / "workspace" / "01 Current State AS Built" / "7 IAMPS" / "01 Final Version"
    reviews = final_version / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "ChangesCSA_IAMPS_Section1.md").write_text(
        """# Section 1 - Network Services

### E-1 - Clarify the first body paragraph
**Where:** Section 1, sentence beginning exactly:
`First body paragraph.`

**Do:** Replace

**Text:**

> First body paragraph, clarified.

**Why:**
Fixture edit for the readiness tests.
""",
        encoding="utf-8",
    )
    # A second section's change file in the same reviews/ folder --
    # manifest.build_manifest pairs it with the *same* single .docx in the
    # Final Version folder, exactly like every real CSA project's 16
    # sections sharing one working document.
    (reviews / "ChangesCSA_IAMPS_Section2.md").write_text(
        """# Section 2 - DNS

### E-2 - Clarify the DNS body paragraph
**Where:** Section 2, sentence beginning exactly:
`DNS body paragraph.`

**Do:** Replace

**Text:**

> DNS body paragraph, clarified.

**Why:**
Fixture edit for the readiness tests.
""",
        encoding="utf-8",
    )
    _write_test_docx(final_version / "Current State Assessment - IAMPS - v1.docx")
    return tmp_path / "workspace"


def _make_workspace_with_two_documents(tmp_path) -> Path:
    """The uncommon case _resolve_shared_document must refuse to guess on:
    two sections whose change files live under *different* Final Version
    folders, each pairing with its own distinct working .docx."""
    root = tmp_path / "workspace"

    project_a = root / "Project A" / "01 Final Version"
    reviews_a = project_a / "reviews"
    reviews_a.mkdir(parents=True)
    (reviews_a / "ChangesCSA_IAMPS_Section1.md").write_text(
        """# Section 1 - Network Services

### E-1 - Clarify the first body paragraph
**Where:** Section 1, sentence beginning exactly:
`First body paragraph.`

**Do:** Replace

**Text:**

> First body paragraph, clarified.

**Why:**
Fixture edit for the readiness tests.
""",
        encoding="utf-8",
    )
    _write_test_docx(project_a / "Current State Assessment - Project A.docx")

    project_b = root / "Project B" / "01 Final Version"
    reviews_b = project_b / "reviews"
    reviews_b.mkdir(parents=True)
    (reviews_b / "ChangesCSA_IAMPS_Section2.md").write_text(
        """# Section 2 - DNS

### E-2 - Clarify the DNS body paragraph
**Where:** Section 2, sentence beginning exactly:
`DNS body paragraph.`

**Do:** Replace

**Text:**

> DNS body paragraph, clarified.

**Why:**
Fixture edit for the readiness tests.
""",
        encoding="utf-8",
    )
    _write_test_docx(project_b / "Current State Assessment - Project B.docx")

    return root


def _workspace_docx(workspace: Path) -> Path:
    return (
        workspace
        / "01 Current State AS Built"
        / "7 IAMPS"
        / "01 Final Version"
        / "Current State Assessment - IAMPS - v1.docx"
    )


def _make_test_docx(tmp_path) -> Path:
    docx = tmp_path / "fixture.docx"
    _write_test_docx(docx)
    return docx


def _write_test_docx(docx: Path, *, extra_heading: bool = False) -> Path:
    package = docx.parent / f"{docx.stem}.pkg"
    document_xml = _make_test_docx_parts(package)
    editor = DocumentEditor(document_xml)
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    body.append(_make_heading("Network Services", 1))
    body.append(make_paragraph("First body paragraph."))
    body.append(make_paragraph("Second body paragraph."))
    body.append(_make_heading("DNS", 2))
    if extra_heading:
        body.append(_make_heading("DHCP", 2))
    body.append(make_paragraph("DNS body paragraph."))
    editor.save()

    with zipfile.ZipFile(docx, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(package.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(package).as_posix())
    return docx


def _make_test_docx_parts(tmp_path) -> Path:
    word_dir = tmp_path / "word"
    rels_dir = word_dir / "_rels"
    rels_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "[Content_Types].xml").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        encoding="utf-8",
    )
    (rels_dir / "document.xml.rels").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>""",
        encoding="utf-8",
    )
    document_xml = word_dir / "document.xml"
    document_xml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body /></w:document>""",
        encoding="utf-8",
    )
    return document_xml


def _make_heading(text: str, level: int) -> ET.Element:
    paragraph = make_paragraph(text)
    ppr = ET.Element(qn(W_NS, "pPr"))
    ET.SubElement(ppr, qn(W_NS, "pStyle"), {qn(W_NS, "val"): f"Heading{level}"})
    paragraph.insert(0, ppr)
    return paragraph


def test_id_manifest_and_run_state_live_beside_the_working_docx(tmp_path):
    """DECISION-002: state files sit next to the .docx, not in the workspace root."""
    workspace = _make_workspace(tmp_path)
    docx = _workspace_docx(workspace)
    from csa_docx.run_state import state_path

    assert tools._id_manifest_path(workspace, docx).parent == docx.parent / "run-state"
    assert state_path(docx.parent, "1").parent == docx.parent / "run-state"
    assert state_path(docx.parent, "1").name == "current-state-assessment-document-section-1.md"


def test_get_section_status_reads_run_state_from_beside_the_docx(tmp_path):
    workspace = _make_workspace(tmp_path)
    docx = _workspace_docx(workspace)
    from csa_docx.run_state import state_path

    assert tools.get_section_status("1", workspace=workspace)["status"] == "NOT_STARTED"

    state = state_path(docx.parent, "1")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("# Run State\n\n- Section: 1\n- Status: PARTIAL_COMPLETE\n- Next edit ID: S1-E2\n", encoding="utf-8")
    status = tools.get_section_status("1", workspace=workspace)
    assert status["status"] == "PARTIAL_COMPLETE"
    assert status["next_edit_id"] == "S1-E2"

    # A file in the old workspace-root location must be ignored.
    state.unlink()
    old = workspace / "run-state" / "current-state-assessment-document-section-1.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("- Status: SECTION_COMPLETE\n", encoding="utf-8")
    assert tools.get_section_status("1", workspace=workspace)["status"] == "NOT_STARTED"


def test_manifest_resolves_unnumbered_change_file_names_and_flags_a_duplicate_legacy_one(tmp_path):
    """New change files carry no edit-ID numbers in the name. The legacy
    numbered form is still matched, but two files for one section is an error."""
    from csa_docx import manifest

    workspace = _make_workspace(tmp_path)
    entry = manifest.build_manifest(workspace)["1"]
    assert Path(entry.change_file).name == "ChangesCSA_IAMPS_Section1.md"

    reviews = Path(entry.change_file).parent
    (reviews / "ChangesCSA_IAMPS_Section1_E1_E13.md").write_text("# legacy copy\n", encoding="utf-8")
    try:
        manifest.build_manifest(workspace)
    except manifest.ManifestError as exc:
        assert "Section 1 has 2 matching change files" in str(exc)
    else:
        raise AssertionError("expected ManifestError for a duplicate legacy-named file")
