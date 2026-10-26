"""Visible document numbers must not be confused with structural stable IDs."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest


CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def _project(tmp_path: Path) -> dict:
    state = tmp_path / "01 Current State AS Built" / "01 Final Version" / "run-state"
    state.mkdir(parents=True)
    entries = [
        {"id": "@H4.2", "kind": "heading", "level": 2,
         "section_path": "4.2", "text": "General / Asset Inventory"},
        {"id": "@H4.4", "kind": "heading", "level": 2,
         "section_path": "4.4", "text": "PKI / Certificates"},
        {"id": "@H4.18", "kind": "heading", "level": 2,
         "section_path": "4.18", "text": "Internet Access & Communications (Proxy / SMTP)"},
        {"id": "@H6.2", "kind": "heading", "level": 2,
         "section_path": "6.2", "text": "Discovery Coverage"},
        {"id": "@H6.7", "kind": "heading", "level": 2,
         "section_path": "6.7", "text": "File Transfer and Local Storage"},
        {"id": "@H8", "kind": "heading", "level": 1,
         "section_path": "8", "text": "Discovery Required"},
    ]
    (state / "stable-ids-test.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return {"project_root": str(tmp_path)}


def test_visible_domain_numbers_resolve_to_live_structural_paths(tmp_path):
    p = _project(tmp_path)
    assert CSA["resolve_visible_section"](p, "3.1")["stable_path"] == "4.2"
    assert CSA["resolve_visible_section"](p, "3.3")["stable_path"] == "4.4"
    assert CSA["resolve_visible_section"](p, "3.17")["stable_path"] == "4.18"


def test_visible_migration_numbers_resolve_to_live_structural_paths(tmp_path):
    p = _project(tmp_path)
    assert CSA["resolve_visible_section"](p, "5.1")["stable_path"] == "6.2"
    assert CSA["resolve_visible_section"](p, "5.6")["stable_path"] == "6.7"


def test_appendix_e_framework_section_resolves_to_live_structural_path(tmp_path):
    result = CSA["resolve_visible_section"](_project(tmp_path), "8")
    assert result["heading"] == "Discovery Required"
    assert result["stable_path"] == "8"


def test_unknown_visible_number_is_not_guessed(tmp_path):
    result = CSA["resolve_visible_section"](_project(tmp_path), "3.99")
    assert result["stable_path"] is None
    assert result["heading"] is None


def test_model_commands_reject_removed_window_flag():
    with pytest.raises(SystemExit):
        CSA["main"](["answer", "--window", "3.9"])


def test_local_prompt_names_the_supported_codex_cli_shell_tool(tmp_path):
    project = {
        "key": "test",
        "label": "Test",
        "project_context": str(tmp_path / "context.yaml"),
        "work_dir": str(tmp_path / "work"),
        "project_root": str(tmp_path),
    }
    route = {"file": "agent.md", "title": "Test Agent", "verb": "test", "instruction": "Do the task."}
    prompt = CSA["build_prompt"](project, route, [], local=True)
    assert "use `exec_command` for shell commands" in prompt
    assert "Never call `exec`" in prompt


def test_fleet_model_argv_stays_in_the_invoking_process():
    command = CSA["_fleet_argv"]({}, {"prompt": "prompt", "last": Path("last.md"), "verb": "author"},
                                 "evo-x3-qwen", "codex")
    assert command[0] == "codex"
    assert not any("csa-window" in part for part in command)


def test_fleet_rejects_removed_no_window_flag():
    with pytest.raises(SystemExit):
        CSA["main"](["fleet", "--no-window"])


def test_legacy_window_wrapper_is_an_in_place_compatibility_shim():
    source = (Path(__file__).parents[3] / "bin" / "csa-window").read_text(encoding="utf-8")
    assert "osascript" not in source
    assert source.rstrip().endswith('exec "$@"')


def test_focused_answer_written_to_base_is_recovered_before_exit_handling(tmp_path):
    sheet = tmp_path / "DNS.answer.md"
    patch = tmp_path / "DNS.patch.md"
    original = b"## B1 DNS\nFacts:\n- old.\n"
    changed = b"## B1 DNS\nFacts:\n- repaired.\n"
    sheet.write_bytes(original)
    sheet.write_bytes(changed)  # the agent ignored SHEET=patch and edited ANSWER=sheet
    assert CSA["capture_focused_answer"](patch, sheet, original)
    assert patch.read_bytes() == changed
    assert sheet.read_bytes() == original


def test_latest_draft_attempt_is_read_independently_of_change_file_state(tmp_path):
    draft = tmp_path / "csa-work" / "draft"
    draft.mkdir(parents=True)
    state = {"DNS": {"number": "3.5", "status": "FAILED", "detail": "NO_TOTALS", "last_ok": "earlier"}}
    (draft / "runs.json").write_text(json.dumps(state), encoding="utf-8")
    assert CSA["draft_run_state"]({"work_dir": str(tmp_path / "csa-work")}, "3.5") == state["DNS"]


def test_repeated_repair_switches_model_once_then_stops():
    decide = CSA["repeated_repair_action"]
    signature = (("NO_TOTALS", "B1", "same sentence"),)
    assert decide(signature, None, "evo", "codex", False) == (None, False)
    assert decide(signature, signature, "evo", "codex", False) == ("codex", False)
    assert decide(signature, signature, "codex", "codex", True) == (None, True)
