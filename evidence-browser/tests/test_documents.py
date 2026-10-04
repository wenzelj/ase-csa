from __future__ import annotations

import zipfile
from pathlib import Path

from backend import documents


DOC = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>3 Current State</w:t></w:r></w:p>
<w:p><w:r><w:t>Existing </w:t></w:r><w:ins><w:r><w:t>inserted</w:t></w:r></w:ins><w:del><w:r><w:delText>deleted</w:delText></w:r></w:del><w:commentRangeStart w:id="0"/></w:p>
</w:body></w:document>'''
COMMENTS = '''<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0" w:author="Reviewer" w:date="2026-10-04T00:00:00Z"><w:p><w:r><w:t>Check this statement</w:t></w:r></w:p></w:comment></w:comments>'''
CORE = '''<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Assessment</dc:title><cp:revision>7</cp:revision><cp:contentStatus>Draft</cp:contentStatus></cp:coreProperties>'''


def make_project(tmp_path: Path, names: tuple[str, ...] = ("Assessment_v1.5.docx",)) -> tuple[dict[str, str], list[Path]]:
    root = tmp_path / "project"; version = root / "02 Current State Assessment" / "01 Final Version"
    reviews = version / "reviews"; reviews.mkdir(parents=True)
    (reviews / "ChangesCSA_Test_Section3.md").write_text("change")
    work = root / "csa-work"; work.mkdir()
    paths = []
    for name in names:
        path = version / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", DOC); archive.writestr("word/comments.xml", COMMENTS); archive.writestr("docProps/core.xml", CORE)
        paths.append(path)
    return {"key": "iamps-08", "project_root": str(root), "work_dir": str(work)}, paths


def test_one_authoritative_document_returns_metadata(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path); info = documents.metadata(project)
    assert info["state"] == "ready" and info["path"] == str(paths[0].resolve())
    assert info["properties"]["status"] == "Draft"
    assert info["tracked_changes"] == {"insertions": 1, "deletions": 1, "total": 2}
    assert info["comment_count"] == 1 and info["manifest"]["state"] == "missing"


def test_duplicate_candidates_block_without_guessing(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path, ("Assessment_v1.4.docx", "Assessment_v1.5.docx")); result = documents.resolve(project)
    assert result["state"] == "blocked" and result["candidates"] == sorted(str(path.resolve()) for path in paths)


def test_no_candidate_is_a_blocking_state(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path)
    paths[0].unlink()
    result = documents.resolve(project)
    assert result == {"state": "blocked", "path": None, "candidates": [],
                      "reason": "No authoritative working DOCX was found."}


def test_archives_backups_and_owner_files_are_not_candidates(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path); root = Path(project["project_root"])
    backup = root / "backup" / "01 Final Version" / "reviews"; backup.mkdir(parents=True)
    (backup / "ChangesCSA_Test_Section3.md").write_text("change"); (backup.parent / "Old.docx").write_bytes(b"old")
    paths[0].with_name("~$" + paths[0].name[2:]).write_text("lock")
    assert documents.candidates(project) == [paths[0].resolve()]


def test_symlink_outside_project_is_not_a_candidate(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path)
    outside = tmp_path / "outside.docx"; outside.write_bytes(paths[0].read_bytes())
    paths[0].unlink(); paths[0].symlink_to(outside)
    assert documents.candidates(project) == []


def test_word_lock_is_reported(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path); lock = paths[0].with_name("~$" + paths[0].name[2:]); lock.write_text("open")
    info = documents.metadata(project)
    assert info["word_locked"] is True and info["word_lock_file"] == lock.name


def test_hash_cache_invalidates_when_document_changes(tmp_path: Path) -> None:
    project, paths = make_project(tmp_path); calls = []
    def convert(_source: Path, output: Path) -> None:
        calls.append(output); output.write_bytes(b"%PDF-1.4 /Type /Page")
    first, first_hash, pages = documents.render_pdf(project, converter=convert)
    again, again_hash, _ = documents.render_pdf(project, converter=convert)
    assert first == again and first_hash == again_hash and len(calls) == 1 and pages == 1
    with zipfile.ZipFile(paths[0], "a") as archive:
        archive.writestr("changed.txt", "changed")
    changed, changed_hash, _ = documents.render_pdf(project, converter=convert)
    assert changed != first and changed_hash != first_hash and len(calls) == 2


def test_revision_view_and_comments_keep_review_context(tmp_path: Path) -> None:
    project, _ = make_project(tmp_path); revision = documents.revision_view(project)
    assert {token["kind"] for token in revision["paragraphs"][1]["tokens"]} == {"normal", "inserted", "deleted"}
    assert revision["sections"] == [{"index": 0, "title": "3 Current State"}]
    comments = documents.document_comments(project)
    assert comments[0]["text"] == "Check this statement" and "Existing" in comments[0]["anchored_text"]
