"""S456: the section card shows what decides each requirement's rating (its conditions and logic)."""
import os
from pathlib import Path

try:
    import pytest
except ImportError:          # the story checks run these tests without pytest
    pytest = None

from csa_docx import conditions, doc_spec, section_card, spec_cli


def _skip(msg: str):
    if pytest:
        pytest.skip(msg)
    raise RuntimeError(msg)


def _template() -> Path:
    p = Path(os.environ.get("CSA_TEST_TEMPLATE") or "")
    if not p.is_file():
        p = spec_cli.find_template(None)
    if not p or not p.is_file():
        _skip("no CSA template available")
    return p


def test_the_stor_card_shows_the_conditions_and_logic_under_sep_stor_01():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    text = section_card.card(node, spec, None, evidence=False)["text"]
    assert "  What decides this rating (conditions):" in text
    b1 = text.split("- B1 SEP-STOR-01")[1].split("\n- B2")[0]
    assert "  - C1: The vital OT systems hold their operational and application data on storage inside OT" in b1
    assert "  - C2: That storage does not depend on IT-hosted file shares" in b1
    assert "  - C3: A documented fallback keeps the data available during isolation" in b1
    assert ("  - Logic: C1 and (C2 or C3)   (Met only when the logic holds; an unknown condition "
            "caps the rating at Partially Met)") in b1
    # reviewed: true in the reference file, so no not-reviewed note under SEP-STOR-01
    assert "conditions not reviewed yet" not in b1


def test_a_requirement_with_no_entry_shows_its_own_text_and_no_logic_line():
    cond = conditions.load("SEP-NONE-99", "Some requirement text.")
    lines = section_card.condition_lines("SEP-NONE-99", "Some requirement text.")
    assert lines[:2] == ["  What decides this rating (conditions):", "  - C1: Some requirement text."]
    assert not any(l.startswith("  - Logic:") for l in lines)
    assert cond["reviewed"] is False and cond["default"] is True


def test_the_not_reviewed_note_appears_only_when_the_entry_is_not_reviewed():
    reviewed = {"conditions": [{"id": "C1", "text": "a"}, {"id": "C2", "text": "b"}],
                "logic": "C1 and C2", "reviewed": True, "default": False, "basis": ""}
    monkey = None
    orig = conditions.load
    try:
        conditions.load = lambda req_id, text="": dict(reviewed)
        lines = section_card.condition_lines("SEP-REV-01", "a and b")
        assert "conditions not reviewed yet" not in "\n".join(lines)
        assert "  - Logic: C1 and C2   (Met only when the logic holds; an unknown condition caps the rating at Partially Met)" in lines
        conditions.load = lambda req_id, text="": dict(reviewed, reviewed=False)
        lines = section_card.condition_lines("SEP-REV-01", "a and b")
        assert lines[-1] == "  (conditions not reviewed yet: use them, and say nothing that depends on their wording)"
    finally:
        conditions.load = orig
