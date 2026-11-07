"""S459: the Story contract - the card gives the Story a shape, and the draft agent points to it."""
from pathlib import Path

try:
    import pytest
except ImportError:          # the story checks run these tests without pytest
    pytest = None

from csa_docx import doc_spec, section_card, spec_cli


def _skip(msg: str):
    if pytest:
        pytest.skip(msg)
    raise RuntimeError(msg)


def _template() -> Path:
    p = Path(__file__).resolve().parents[3] / "CSA Template" / "CSA_Template_v1.6.dotx"
    if not p.is_file():
        p = spec_cli.find_template(None)
    if not p or not p.is_file():
        _skip("no CSA template available")
    return p


def test_the_stor_card_carries_no_writing_rules_and_the_digest_carries_the_story_contract():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    made = section_card.card(node, spec, None, evidence=False)
    assert made["requirement_stories"] is True
    assert "## Requirement summaries and stories" not in made["text"]
    assert "## Rules from the template" not in made["text"]
    from csa_docx import prompts
    rules = prompts.assemble({"requirement"}, None)[0]
    assert "## Summary and Story" in rules
    assert "**Summary** is the Current State table cell" in rules
    assert "fuller evidence-backed operational narrative" not in made["text"] + rules


def test_every_section_3_requirement_block_uses_the_same_summary_story_contract():
    spec = doc_spec.read(_template())
    domains = [n for n in spec["nodes"] if n.get("kind") == "requirement-block"
               and str(n.get("number", "")).startswith("3.")]
    assert len(domains) == 17
    for node in domains:
        made = section_card.card(node, spec, None, evidence=False)
        assert made["requirement_stories"] is True, node["number"]
        assert "## Requirement summaries and stories" not in made["text"], node["number"]


def test_the_draft_agent_holds_no_writing_rules_and_the_requirement_prompt_holds_the_story_contract():
    md = (Path(__file__).resolve().parents[3] / "csa-draft-agent.md").read_text(encoding="utf-8")
    assert "Story" not in md and "Summary" not in md and "the fuller paragraph" not in md
    from csa_docx import prompts
    rules = prompts.assemble({"requirement"}, None)[0]
    assert "Write both `Summary:` and `Story:`" in rules
