"""Visible document numbers must not be confused with structural stable IDs."""

from __future__ import annotations

import json
import runpy
from pathlib import Path


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
