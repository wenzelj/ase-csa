from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands
from backend.models import CommandRequest


def test_catalogue_exposes_read_only_operations_and_one_docx_locked_apply() -> None:
    rows = commands.catalogue()
    assert {row["key"] for row in rows} == {
        "status", "next", "report", "sections", "spec_status", "comments",
        "check_change", "check_section", "apply", "review", "cleanup", "author",
        "build_preview", "build", "audit",
    }
    apply = next(row for row in rows if row["key"] == "apply")
    assert apply["mutating"] is True and apply["lock"] == "docx"
    review = next(row for row in rows if row["key"] == "review")
    assert review["mutating"] is True and review["lock"] == "docx"
    cleanup = next(row for row in rows if row["key"] == "cleanup")
    assert cleanup["mutating"] is True and cleanup["lock"] == "docx"
    author = next(row for row in rows if row["key"] == "author")
    assert author["mutating"] is True and author["mutation_class"] == "workspace_write" and author["lock"] == "section"
    assert {"legacy", "fresh", "check_answers", "writer", "no_writer"} <= set(author["options"])
    assert all(row["mutating"] is False and row["lock"] == "none" for row in rows if row["key"] not in ("apply", "review", "cleanup", "build", "author"))


def test_build_argv_uses_fixed_executable_and_typed_arguments(tmp_path: Path) -> None:
    operation, argv = commands.build_argv(
        tmp_path / ".agents", "tetra-reveloc", "check_change",
        CommandRequest(target="3.4", options={"file": "dns", "no_lint": True}),
    )
    assert operation.key == "check_change"
    assert argv == [
        str((tmp_path / ".agents/bin/csa").resolve()), "--project", "tetra-reveloc",
        "check-change", "3.4", "--file", "dns", "--no-lint", "--json",
    ]


@pytest.mark.parametrize("value", ["../3", "/tmp/file", "3;touch x", "$(id)", "a\\b", "--help"])
def test_identifiers_reject_paths_and_shell_syntax(tmp_path: Path, value: str) -> None:
    with pytest.raises(HTTPException) as caught:
        commands.build_argv(tmp_path, "tetra-reveloc", "status", CommandRequest(target=value))
    assert caught.value.status_code == 422


def test_unknown_operation_project_and_option_are_rejected_before_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launched = False

    def fake_run(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("must not launch")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    with pytest.raises(HTTPException):
        commands.build_argv(tmp_path, "hidden-project", "status", CommandRequest())
    with pytest.raises(HTTPException):
        commands.build_argv(tmp_path, "tetra-reveloc", "destroy", CommandRequest(target="3"))
    with pytest.raises(HTTPException):
        commands.build_argv(tmp_path, "tetra-reveloc", "next", CommandRequest(options={"force": True}))
    assert launched is False


def test_parse_json_output_tolerates_project_banner() -> None:
    parsed, ok = commands.parse_json_output('[Project label]\n[{"section":"3.4"}]\n')
    assert ok is True
    assert parsed == [{"section": "3.4"}]
    assert commands.parse_json_output("Nothing pending.") == (None, False)


def test_execute_uses_shell_false_minimal_env_and_redacted_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agents = tmp_path / ".agents"
    (agents / "bin").mkdir(parents=True)
    (agents / "bin" / "csa").write_text("#!/bin/sh\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    project = {"key": "iamps-08", "work_dir": str(work)}
    monkeypatch.setenv("SECRET_TOKEN", "must-not-be-inherited")
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed.update({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout='[{"section":"4"}]\n', stderr="")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    result = commands.execute(agents, project, "status", CommandRequest())
    assert observed["shell"] is False
    assert "SECRET_TOKEN" not in observed["env"]
    assert result.exit_code == 0 and result.parsed_json is True
    assert result.parsed == [{"section": "4"}]
    event = json.loads((work / "evidence-browser-audit.jsonl").read_text(encoding="utf-8"))
    assert event["operation"] == "status" and event["classification"] == "read_only"
    assert "stdout" not in event and "stderr" not in event and "target" not in event
