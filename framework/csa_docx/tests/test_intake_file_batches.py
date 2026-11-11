"""Intake saves each source before moving to a fresh model session."""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path


CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def _fixture(tmp_path: Path):
    work = tmp_path / "csa-work"
    intake = work / "intake"
    intake.mkdir(parents=True)
    files = ["source/one.txt", "source/two.txt"]
    for name in files:
        source = tmp_path / name
        source.parent.mkdir(exist_ok=True)
        source.write_text(name, encoding="utf-8")
    record = {"id": "test-record", "added": [
        {"rel_path": name, "status": "indexed", "source_class": "other"} for name in files],
        "changed": [], "unreadable": []}
    (intake / "latest.json").write_text(json.dumps(record), encoding="utf-8")
    return {"key": "test", "project_root": str(tmp_path), "work_dir": str(work)}, files


def test_intake_checkpoints_each_file_and_resumes_after_failure(tmp_path, monkeypatch):
    project, files = _fixture(tmp_path)
    previous_report = tmp_path / "csa-work" / "intake" / "test-record.evidence.md"
    previous_report.write_text("# Previous intake report\n" + "\n".join(files), encoding="utf-8")
    calls = []
    fail_second = True

    def launch(_project, _agent, args, worker):
        nonlocal fail_second
        values = dict(arg.split("=", 1) for arg in args)
        calls.append((values["FILE"], worker.headless))
        if values["FILE"] == files[1] and fail_second:
            return 1
        Path(values["FILE_REPORT"]).write_text(
            f"# {values['FILE']}\n\nNo new evidence.\n", encoding="utf-8")
        return 0

    monkeypatch.setitem(CSA["cmd_intake_files"].__globals__, "launch", launch)
    args = argparse.Namespace(print=False, headless=False)
    assert CSA["cmd_intake_files"](project, args) == 1
    assert calls == [(files[0], True), (files[1], True)]
    assert CSA["intake_pending"](project) == [files[1]]
    assert (previous_report.parent / "test-record.evidence.before-file-batches.md").read_text(
        encoding="utf-8") == "# Previous intake report\n" + "\n".join(files)
    checkpoint_dir = tmp_path / "csa-work" / "intake" / "test-record.files"
    assert len(list(checkpoint_dir.glob("*.json"))) == 1

    fail_second = False
    assert CSA["cmd_intake_files"](project, args) == 0
    assert calls[-1] == (files[1], True)
    assert len(calls) == 3  # the successful first file was not rerun
    assert len(list(checkpoint_dir.glob("*.json"))) == 2
    assert CSA["intake_pending"](project) == []


def test_changed_source_invalidates_its_checkpoint(tmp_path, monkeypatch):
    project, files = _fixture(tmp_path)
    calls = []

    def launch(_project, _agent, args, _worker):
        values = dict(arg.split("=", 1) for arg in args)
        calls.append(values["FILE"])
        Path(values["FILE_REPORT"]).write_text(values["FILE"], encoding="utf-8")
        return 0

    monkeypatch.setitem(CSA["cmd_intake_files"].__globals__, "launch", launch)
    args = argparse.Namespace(print=False, headless=False)
    assert CSA["cmd_intake_files"](project, args) == 0
    (tmp_path / files[0]).write_text("changed", encoding="utf-8")
    assert CSA["cmd_intake_files"](project, args) == 0
    assert calls == [files[0], files[1], files[0]]
