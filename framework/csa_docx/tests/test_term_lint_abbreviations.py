from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "australian-it-ot-terminology" / "scripts" / "term_lint.py"
SPEC = importlib.util.spec_from_file_location("csa_term_lint", SCRIPT)
assert SPEC and SPEC.loader
TERM_LINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TERM_LINT)


def _items(markdown: str, tmp_path: Path) -> list[dict]:
    path = tmp_path / "draft.md"
    path.write_text(markdown, encoding="utf-8")
    review, abbreviations, evidence, spelling = TERM_LINT.load_terms()
    section = TERM_LINT.split_sections(TERM_LINT.read_markdown(path))[0]
    return TERM_LINT.lint_section(section, review, abbreviations, evidence, spelling)


def test_flags_unexpanded_abbreviation_in_heading(tmp_path):
    items = _items("# Storage and Data Transfer\n## SMB connections to unnamed peers\n", tmp_path)
    assert any(item["code"] == "UNEXPANDED_ABBREVIATION" and item["found"] == "SMB" for item in items)


def test_accepts_full_term_in_heading(tmp_path):
    items = _items("# Storage and Data Transfer\n## Server Message Block connections to unnamed peers\n", tmp_path)
    assert not any(item["code"] == "UNEXPANDED_ABBREVIATION" for item in items)


def test_heading_uses_full_term_without_parenthetical_abbreviation(tmp_path):
    items = _items("# Storage and Data Transfer\n## Server Message Block (SMB) connections\n", tmp_path)
    assert any(item["code"] == "UNEXPANDED_ABBREVIATION" and item["found"] == "SMB" for item in items)


def test_accepts_full_term_before_reused_abbreviation(tmp_path):
    items = _items(
        "# Storage and Data Transfer\n"
        "Server Message Block (SMB) connections were observed. SMB was used by two application servers.\n",
        tmp_path,
    )
    assert not any(item["code"] == "UNEXPANDED_ABBREVIATION" for item in items)
