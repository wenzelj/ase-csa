from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import app as workspace
from backend import word_review
from backend.models import PipelineDocument, PipelineIssue, PipelineSection, PipelineSnapshot


def make_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    agents = tmp_path / ".agents"
    context = agents / "csa-context"
    skills = agents / "skills"
    context.mkdir(parents=True)
    skills.mkdir()
    project = tmp_path / "IAMPS"
    sources = project / "source"
    work = project / "csa-work"
    sources.mkdir(parents=True)
    work.mkdir()
    context.joinpath("PROJECTS.yaml").write_text(
        "projects:\n"
        "  - key: iamps-08\n"
        "    label: \"IAMPS\"\n"
        f"    project_root: \"{project}\"\n"
        f"    work_dir: \"{work}\"\n"
        f"    default_source_set: \"{sources}\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_AGENTS_DIR", str(agents))
    db = sqlite3.connect(work / "discovery-index.sqlite")
    db.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);"
        "CREATE TABLE captures(capture_id INTEGER PRIMARY KEY,folder TEXT,host TEXT,collector TEXT,capture_utc TEXT,archived INTEGER,superseded_by INTEGER,file_count INTEGER);"
        "CREATE TABLE files(file_id INTEGER PRIMARY KEY,rel_path TEXT,capture_id INTEGER,host TEXT,ext TEXT,size INTEGER,mtime REAL,sha1 TEXT,status TEXT,reason TEXT,dup_of INTEGER,source_class TEXT,archived INTEGER);"
        "CREATE TABLE rows(file_id INTEGER,table_name TEXT,fmt TEXT,block_no INTEGER,line_no INTEGER,data TEXT);"
        "CREATE TABLE chunks(content TEXT);"
        "CREATE TABLE chunk_map(chunk_id INTEGER,file_id INTEGER,line_start INTEGER,line_end INTEGER);"
    )
    db.executemany("INSERT INTO meta VALUES(?,?)", [("complete", "1"), ("built_at_utc", "2026-10-03T00:00:00Z")])
    db.execute("INSERT INTO captures VALUES(1,'capture','HOST01','collector','2026-10-01T00:00:00Z',0,NULL,1)")
    db.commit()
    db.close()
    return project, sources


def add_file(project: Path, rel_path: str, content: str = "first\nneedle\nlast\n") -> int:
    path = project / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (rel_path, 1, "HOST01", path.suffix, path.stat().st_size, path.stat().st_mtime, "indexed", "text", "capture", 0),
    )
    db.commit()
    file_id = cursor.lastrowid
    db.close()
    return int(file_id)


def test_summary_and_current_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    add_file(project, "source/03_time_status.txt")
    result = workspace.get_summary("iamps")
    assert result["current_captures"] == 1
    assert result["files_by_status"] == {"indexed": 1}
    assert result["coverage"][0]["families"]["Time"] == 1


def test_application_portrait_explains_claims_and_decisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    add_file(project, "source/03_time_status.txt")
    fields = ["evidence_id", "csa_area", "question", "claim", "status", "source_title",
              "source_version", "section", "page_or_location", "evidence_excerpt",
              "inference_reason", "confidence", "gap_or_action", "review_state"]
    with (project / "csa-work" / "evidence-matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"evidence_id": "E-001", "csa_area": "network_and_connectivity",
                         "question": "Which time source is used?", "claim": "HOST01 uses DC01.",
                         "status": "VERIFIED", "source_title": "03_time_status.txt",
                         "confidence": "high", "review_state": "pending"})
        writer.writerow({"evidence_id": "E-002", "csa_area": "network_and_connectivity",
                         "question": "Is the secondary peer intentional?", "claim": "A peer may be stale.",
                         "status": "INFERRED", "confidence": "medium",
                         "gap_or_action": "Confirm with the application owner.", "review_state": "pending"})
    result = workspace.application_portrait("iamps")
    assert result["application"]["name"] == "IAMPS"
    assert result["assessment"]["status_counts"]["VERIFIED"] == 1
    assert result["areas"][0]["label"] == "Network and connectivity"
    assert result["areas"][0]["claims"][0]["claim"] == "HOST01 uses DC01."
    assert result["areas"][0]["decisions"][0]["gap_or_action"] == "Confirm with the application owner."
    assert result["observed_hosts"][0]["host"] == "HOST01"


def test_safe_file_rejects_indexed_path_outside_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("../outside.txt", None, None, ".txt", 7, 0, "indexed", "text", "other", 0),
    )
    db.commit(); file_id = cursor.lastrowid; db.close()
    with pytest.raises(HTTPException) as caught:
        workspace.safe_file(workspace.system_project("iamps"), file_id)
    assert caught.value.status_code == 403


def test_safe_file_rebases_index_copied_from_older_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, sources = make_workspace(tmp_path, monkeypatch)
    path = sources / "PROD" / "capture" / "03_time_status.txt"
    path.parent.mkdir(parents=True)
    path.write_text("Source: Local CMOS Clock", encoding="utf-8")
    legacy_relative = f"01 Current State AS Built/{sources.name}/PROD/capture/03_time_status.txt"
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (legacy_relative, 1, "HOST01", ".txt", path.stat().st_size, path.stat().st_mtime, "indexed", "text", "capture", 0),
    )
    db.commit(); file_id = cursor.lastrowid; db.close()
    _, resolved = workspace.safe_file(workspace.system_project("iamps"), file_id)
    assert resolved == path.resolve()


def test_safe_file_recovers_renamed_folder_by_capture_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, sources = make_workspace(tmp_path, monkeypatch)
    capture = "REVELOC_discovery_HOST01_20261003T010203Z"
    path = sources / "renamed-source" / "Script_Results" / capture / "03_time_status.txt"
    path.parent.mkdir(parents=True)
    path.write_text("Source: domain controller", encoding="utf-8")
    stale_relative = f"source/OldName/Script_Results/{capture}/03_time_status.txt"
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (stale_relative, 1, "HOST01", ".txt", path.stat().st_size, path.stat().st_mtime, "indexed", "text", "capture", 0),
    )
    db.commit(); file_id = cursor.lastrowid; db.close()
    _, resolved = workspace.safe_file(workspace.system_project("iamps"), file_id)
    assert resolved == path.resolve()


def test_text_preview_keeps_citation_line(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 301)), encoding="utf-8")
    result = workspace.text_preview(path, "evidence.txt lines 140-142")
    assert result["highlight"] == [140, 142]
    assert any(line["number"] == 141 for line in result["lines"])


def test_search_stops_when_matrix_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_workspace(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def fake(command: list[str], **_: object):
        calls.append(command)
        return {"status": "OK", "verdict": "LIKELY_ANSWERED", "matches": []}

    monkeypatch.setattr(workspace, "run_json", fake)
    result = workspace.search("iamps", workspace.SearchRequest(query="NTP source"))
    assert [stage["kind"] for stage in result["stages"]] == ["matrix"]
    assert len(calls) == 1


def test_search_continues_to_index_and_resolves_file_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    file_id = add_file(project, "source/03_time_status.txt")
    responses = iter([
        {"status": "OK", "verdict": "NO_MATCH", "matches": []},
        {"status": "OK", "count": 1, "results": [{"rel_path": "source/03_time_status.txt"}]},
    ])
    monkeypatch.setattr(workspace, "run_json", lambda *_args, **_kwargs: next(responses))
    result = workspace.search("iamps", workspace.SearchRequest(query="NTP source"))
    assert [stage["kind"] for stage in result["stages"]] == ["matrix", "index"]
    assert result["stages"][1]["results"][0]["file_id"] == file_id


def test_evidence_source_choices_are_limited_to_cited_captures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    first = add_file(project, "source/REVELOC_discovery_HOST01_20261001T010101Z/03_time_status.txt")
    add_file(project, "source/REVELOC_discovery_HOST02_20261001T020202Z/03_time_status.txt")
    fields = ["evidence_id", "csa_area", "question", "claim", "status", "source_title",
              "source_version", "section", "page_or_location", "evidence_excerpt",
              "inference_reason", "confidence", "gap_or_action", "review_state"]
    with (project / "csa-work" / "evidence-matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"evidence_id": "E-001", "csa_area": "network_and_connectivity",
                         "question": "Which source?", "claim": "HOST01 uses DC01.", "status": "VERIFIED",
                         "source_title": "REVELOC_discovery_HOST01_20261001T010101Z: 03_time_status.txt",
                         "page_or_location": "03_time_status.txt lines 1-2", "review_state": "pending"})
    result = workspace.evidence_sources("iamps", "E-001")
    assert result["state"] == "found"
    assert [row["file_id"] for row in result["sources"]] == [first]


def test_commit_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_workspace(tmp_path, monkeypatch)
    draft = workspace.EvidenceDraft(csa_area="network_and_connectivity", question="q", claim="c", status="VERIFIED")
    with pytest.raises(HTTPException) as caught:
        workspace.commit_evidence("iamps", workspace.CommitRequest(draft=draft, confirmed=False))
    assert caught.value.status_code == 409


def _make_doc(path: Path) -> None:
    """Create a minimal valid DOCX at the given path."""
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>")
        zf.writestr("word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        zf.writestr("word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Test document</w:t></w:r></w:p></w:body></w:document>')
        zf.writestr("word/comments.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')


def test_word_review_returns_document_and_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)

    # Create a real DOCX + change file where documents.candidates() will find it
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    _make_doc(version_dir / "Assessment.docx")

    # Build a fake pipeline snapsho...[truncated]
    fake_snap = PipelineSnapshot(
        project_key="iamps",
        project_label="IA MPS",
        spec_mode="spec",
        word_locked=False,
        document=PipelineDocument(path="doc.docx", size=1024,
                                  modified_at="2026-10-01T00:00:00Z"),
        etag='"test-etag"',
        sections=[
            PipelineSection(visible_number="1.", stable_key="1", heading="Introduction",
                            lane="revise", change_file="1-intro.md",
                            applied_state="complete", validation_result="valid",
                            open_comments=0, last_activity="2026-10-03T00:00:00Z"),
            PipelineSection(visible_number="2.", stable_key="2", heading="Security",
                            lane="build", change_file=None,
                            applied_state="unknown", validation_result="unknown",
                            open_comments=2, last_activity="2026-10-02T00:00:00Z"),
        ],
        issues=[],
    )

    def fake_snapshot(agents_dir, proj, *, runner=None):
        return fake_snap

    monkeypatch.setattr("backend.pipeline.snapshot", fake_snapshot)
    review = word_review.build_review(
        tmp_path / ".agents", workspace.system_project("iamps"),
        snapshot_runner=lambda _: "ok",
    )
    assert review["gate"] == "awaiting_word_save"
    assert review["authoritative_path"]
    assert review["sha256"]
    assert review["size"] > 0
    assert review["generated_at"]
    for sec in review["sections"]:
        assert sec["number"]
        assert sec["status"] in ("pending", "has_comments")
        assert sec["comment_count"] >= 0


def test_word_review_pending_counts_when_no_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)

    # Create a real DOCX + change file
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    _make_doc(version_dir / "Assessment.docx")

    # No sections in the snapshot → all pending
    fake_snap = PipelineSnapshot(
        project_key="iamps",
        project_label="IA MPS",
        spec_mode="spec",
        word_locked=False,
        document=PipelineDocument(path="doc.docx", size=512,
                                  modified_at="2026-10-01T00:00:00Z"),
        etag='"test-etag"',
        sections=[],
        issues=[],
    )

    def fake_snapshot(agents_dir, proj, *, runner=None):
        return fake_snap

    monkeypatch.setattr("backend.pipeline.snapshot", fake_snapshot)
    review = word_review.build_review(
        tmp_path / ".agents", workspace.system_project("iamps"),
        snapshot_runner=lambda _: "ok",
    )
    assert review["section_count"] == 0
    assert review["pending_count"] == 0
    assert review["gate"] == "awaiting_word_save"


def test_word_review_requires_hash_change_after_save_and_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    document = version_dir / "Assessment.docx"
    _make_doc(document)
    monkeypatch.setattr("backend.pipeline.snapshot", lambda *_args, **_kwargs: PipelineSnapshot(
        project_key="iamps", project_label="IAMPS", spec_mode="spec", word_locked=False,
        document=PipelineDocument(path=str(document)), sections=[], issues=[], etag='"x"'))
    project_row = workspace.system_project("iamps")
    first = word_review.build_review(tmp_path / ".agents", project_row)
    assert first["review_enabled"] is False
    import time
    time.sleep(0.002)
    with document.open("ab") as handle:
        handle.write(b"saved")
    refreshed = word_review.refresh_gate(tmp_path / ".agents", project_row)
    assert refreshed["gate"] == "ready_for_review"
    assert refreshed["review_enabled"] is True


def test_word_review_blocked_when_no_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set up project registry WITHOUT a document
    agents = tmp_path / ".agents"
    context = agents / "csa-context"
    context.mkdir(parents=True)
    project = tmp_path / "IAMPS"
    work = project / "csa-work"
    work.mkdir(parents=True)
    context.joinpath("PROJECTS.yaml").write_text(
        "projects:\n"
        "  - key: iamps-08\n"
        "    label: \"IAMPS\"\n"
        f"    project_root: \"{project}\"\n"
        f"    work_dir: \"{work}\"\n"
        f"    default_source_set: \"{tmp_path / 'sources'}\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_AGENTS_DIR", str(agents))
    review = word_review.build_review(
        agents, workspace.system_project("iamps")
    )
    assert review["gate"] == "blocked"
    assert "reason" in review


def test_word_review_open_uses_registered_path_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)

    # Create a real DOCX where documents.resolve() can find it
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    _make_doc(version_dir / "Assessment.docx")
    expected_path = (version_dir / "Assessment.docx").resolve()

    captured = {}

    def fake_open(path):
        captured["path"] = str(path)
        return {"state": "opened"}

    result = word_review.open_authoritative(
        workspace.system_project("iamps"), document_opener=fake_open
    )
    assert result["state"] == "opened"
    assert result["authoritative_path"] == str(expected_path)
    assert captured["path"] == str(expected_path)


def test_word_review_operator_note_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)

    # Create a real DOCX where documents.resolve() can find it
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    _make_doc(version_dir / "Assessment.docx")

    work_dir = project / "csa-work"
    result = word_review.record_operator_note(
        tmp_path / ".agents", workspace.system_project("iamps"), "Approved by reviewer"
    )
    assert result["state"] == "recorded"
    audit_path = work_dir / "operator-decisions.jsonl"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert "Approved by reviewer" in content
    assert "operator_record" in content


def test_word_review_refresh_recomputes_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)

    # Create a real DOCX where documents.resolve() can find it
    version_dir = project / "versions" / "v1"
    version_dir.joinpath("reviews").mkdir(parents=True)
    version_dir.joinpath("reviews", "ChangesCSA_01.md").write_text("# Change\n", encoding="utf-8")
    _make_doc(version_dir / "Assessment.docx")

    def fake_lock_check(proj):
        return {"owner": "jdoe", "since": "2026-10-04T00:00:00Z"}

    review = word_review.build_review(
        tmp_path / ".agents", workspace.system_project("iamps"),
        word_lock_check=fake_lock_check,
    )
    assert review["gate"] == "word_locked"
    assert review["word_lock"]["owner"] == "jdoe"
