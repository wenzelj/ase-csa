from __future__ import annotations

from pathlib import Path

from backend import pipeline


def fixture(tmp_path: Path, *, revise: list | None = None, build: list | None = None,
            nodes: list | None = None, next_rows: list | None = None, comments: list | None = None):
    root = tmp_path / "project"
    work = root / "csa-work"
    work.mkdir(parents=True)
    docx = root / "Assessment.docx"
    docx.write_bytes(b"fixture")
    project = {"key": "iamps-08", "label": "IAMPS", "project_root": str(root),
               "work_dir": str(work), "spec_mode": "on", "working_docx": str(docx)}
    outputs = {
        "status": revise or [], "next": next_rows or [], "sections": build or [],
        "spec_status": {"source": str(docx), "template_file": None, "nodes": nodes or []},
        "comments": comments or [],
    }
    return project, lambda operation: outputs[operation]


def node(number: str, key: str, title: str, kind: str = "requirement-block") -> dict:
    return {"number": number, "key": key, "path": f"@H{number}", "title": title, "kind": kind,
            "status": {"state": "open", "open": 1, "total": 1}}


def revise(number: str, **values) -> dict:
    return {"section": number.split(".")[0], "subsection": number if "." in number else None,
            "title": values.pop("title", "Identity"), "change_file": values.pop("change_file", "/tmp/change.md"),
            "authored": True, "edits": ["S3-E1"], "apply_status": "NOT_STARTED", "completed": [],
            "blocked": [], "next_edit": None, "review_result": None, "cleaned": False, **values}


def test_revise_snapshot_keeps_partial_apply(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("3.2", "IAM", "Identity")],
                              revise=[revise("3.2", apply_status="PARTIAL_COMPLETE", completed=["S3-E1"], next_edit="S3-E2")],
                              next_rows=[{"section": "3", "stage": "applying", "next": "csa apply 3.2 --until-done"}])
    result = pipeline.snapshot(tmp_path / ".agents", project, runner=runner)
    assert result.sections[0].lane == "revise"
    assert result.sections[0].applied_state == "partial"
    assert result.next_action["next"].startswith("csa apply")


def test_failed_review_is_not_done(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("3.2", "IAM", "Identity")],
                              revise=[revise("3.2", apply_status="SECTION_COMPLETE", review_result="FAIL")],
                              next_rows=[{"section": "3", "stage": "review FAIL", "next": "csa apply 3 --agent"}])
    section = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).sections[0]
    assert section.review_verdict == "fail"
    assert section.cleanup_state == "not_started"


def test_completed_cleanup_is_complete(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("3.2", "IAM", "Identity")],
                              revise=[revise("3.2", apply_status="SECTION_COMPLETE", review_result="PASS", cleaned=True)])
    section = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).sections[0]
    assert (section.applied_state, section.review_verdict, section.cleanup_state) == ("complete", "pass", "complete")


def test_build_lane_uses_section_authority(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("4", "GOV", "Governance", "narrative")],
                              build=[{"file": "04-governance.md", "heading": "Governance", "status": "built",
                                      "review": "READY", "review_note": None, "problem": None}])
    section = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).sections[0]
    assert section.lane == "build" and section.applied_state == "complete"
    assert section.section_file == "04-governance.md"


def test_missing_record_stays_unknown_with_issue(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("3.2", "IAM", "Identity")])
    section = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).sections[0]
    assert section.applied_state == "unknown"
    assert {issue.code for issue in section.issues} == {"PIPELINE_RECORD_MISSING"}


def test_missing_manifest_returns_issue_instead_of_claiming_completion(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path)
    outputs = {name: runner(name) for name in ("status", "next", "sections", "spec_status", "comments")}
    outputs["spec_status"] = {"source": project["working_docx"]}
    result = pipeline.snapshot(tmp_path / ".agents", project, runner=lambda operation: outputs[operation])
    assert result.sections == []
    assert "MANIFEST_UNAVAILABLE" in {issue.code for issue in result.issues}


def test_word_lock_and_comments_are_exposed(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("3.2", "IAM", "Identity")],
                              revise=[revise("3.2")], comments=[{"heading_path": ["3.2 Identity"]}])
    document = Path(project["working_docx"])
    document.with_name("~$" + document.name[2:]).write_text("open")
    result = pipeline.snapshot(tmp_path / ".agents", project, runner=runner)
    assert result.word_locked is True and result.sections[0].open_comments == 1


def test_etag_changes_when_owning_file_changes(tmp_path: Path) -> None:
    project, runner = fixture(tmp_path, nodes=[node("4", "GOV", "Governance", "narrative")],
                              build=[{"file": "04-governance.md", "heading": "Governance", "status": "draft",
                                      "review": None, "review_note": None, "problem": None}])
    section_file = Path(project["work_dir"]) / "sections" / "04-governance.md"
    section_file.parent.mkdir(); section_file.write_text("first")
    first = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).etag
    section_file.write_text("second version")
    second = pipeline.snapshot(tmp_path / ".agents", project, runner=runner).etag
    assert first != second
