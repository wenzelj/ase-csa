from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import build_workflow, commands


def project(tmp_path: Path, lane="build"):
    root = tmp_path / "project"; work = root / "csa-work"; root.mkdir(); work.mkdir()
    template = root / "template.docx"; template.write_bytes(b"template")
    return {"key": "iamps-08", "label": "Test", "project_root": str(root), "work_dir": str(work),
            "assessment_lane": lane, "template_docx": str(template),
            "build_output_docx": str(root / "Assessment.docx")}


def runner(operation: str):
    if operation == "status": return []
    if operation == "next": return []
    if operation == "sections": return [{"heading": "Overview", "file": "01-overview.md", "review": "valid", "status": "ready"}]
    if operation == "spec_status": return {"source": None, "template_file": "template.docx", "nodes": [{"number": "1", "key": "overview", "title": "Overview", "kind": "build"}]}
    if operation == "comments": return []
    raise AssertionError(operation)


def test_build_lane_requires_explicit_registry_setting(tmp_path):
    with pytest.raises(HTTPException): build_workflow.setup(Path(".agents"), project(tmp_path, "revise"), runner=runner)


def test_build_setup_reports_template_sections_and_output(tmp_path):
    result = build_workflow.setup(Path(".agents"), project(tmp_path), runner=runner)
    assert result["lane"] == "build"
    assert result["ready_for_preview"] is True
    assert result["ready_for_build"] is True
    assert result["sections"][0]["stable_key"] == "overview"


def test_build_refuses_existing_output(tmp_path):
    row = project(tmp_path); Path(row["build_output_docx"]).write_bytes(b"existing")
    result = build_workflow.setup(Path(".agents"), row, runner=runner)
    assert result["ready_for_build"] is False


def test_preview_is_read_only_and_real_build_requires_confirmation(tmp_path):
    row = project(tmp_path); calls = []
    class Manager:
        def submit(self, _project, operation, _request):
            calls.append(operation); return SimpleNamespace(model_dump=lambda: {"id": "j1", "state": "queued"})
    result = build_workflow.submit(Path(".agents"), Manager(), row, preview=True, confirmed=True, setup_runner=runner)
    assert result["preview"] is True and calls == ["build_preview"]
    with pytest.raises(HTTPException): build_workflow.submit(Path(".agents"), Manager(), row, preview=False, confirmed=False, setup_runner=runner)
    assert commands.OPERATIONS["build_preview"].mutating is False
    assert commands.OPERATIONS["build"].mutating is True


def test_build_outcome_reports_generated_hash(tmp_path):
    output = tmp_path / "candidate.docx"; output.write_bytes(b"candidate")
    result = build_workflow.outcome({"state": "succeeded", "stdout_tail": '{"output":"%s","sections":[{"key":"overview"}]}' % output}, preview=True)
    assert result["document_hash"] and result["section_map"][0]["key"] == "overview"
