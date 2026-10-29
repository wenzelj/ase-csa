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


EXPECTED_BODY = (
    "For every requirement block write both `Summary:` and `Story:`. Do not put the SEP label or a title in either field; the framework adds a bold title from the requirement ID and wording.\n"
    "- Summary is the Current State table cell. It is decision-first: state the observed control or practice, then finish with `The requirement is <Rating> because ...` and name the decisive requirement condition. Use one to three sentences and at most 80 words. Do not put discovery questions, host inventories or the detailed evidence trail in Summary.\n"
    "- Story is the paragraph under its requirement title in Discovery Information. It is evidence-first and tells how the assessment reached the rating to a reader who has not seen the evidence:\n"
    "  1. Start with how the capability or practice currently operates. Do not start with the rating.\n"
    "  2. Explain the relevant coverage, behaviour and gaps in a logical order. Name at most three parts in a sentence, by their display names.\n"
    "  3. State any material limitation as a factual unknown. Keep the corresponding `QUESTION:` line separate so the framework sends it to Discovery Required.\n"
    "  4. Finish with `The requirement is <Rating> because ...` and the decisive comparison with the requirement.\n"
    "  At most 90 words. Story must add the evidence path, not paraphrase Summary. Say nothing about another requirement's conditions. Hosts, ports and inventories stay in the tables."
)


def test_the_stor_card_carrying_the_new_story_contract_exactly():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    text = section_card.card(node, spec, None, evidence=False)["text"]
    assert "## Requirement summaries and stories" in text
    assert EXPECTED_BODY in text
    # and the old "fuller" description is gone
    assert "fuller evidence-backed operational narrative" not in text


def test_every_section_3_requirement_block_uses_the_same_summary_story_contract():
    spec = doc_spec.read(_template())
    domains = [n for n in spec["nodes"] if n.get("kind") == "requirement-block"
               and str(n.get("number", "")).startswith("3.")]
    assert len(domains) == 17
    for node in domains:
        made = section_card.card(node, spec, None, evidence=False)
        assert made["requirement_stories"] is True, node["number"]
        assert EXPECTED_BODY in made["text"], node["number"]


def test_the_draft_agent_step_points_to_the_card_shape_and_no_longer_describes_the_fuller_paragraph():
    md = (Path(__file__).resolve().parents[3] / "csa-draft-agent.md").read_text(encoding="utf-8")
    step = next(l for l in md.splitlines() if l.startswith("3. "))
    assert 'write Summary: and Story: exactly in the shape that section gives.' in step
    assert "the fuller paragraph" not in step
    assert "For every other prose block" in step
