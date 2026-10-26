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
    "For every requirement block write both `Summary:` and `Story:`. Do not put the SEP label in either field; the framework adds it.\n"
    "- Summary is the Current State table cell: one to three sentences, at most 80 words, stating the control or practice and its main qualification.\n"
    "- Story is the paragraph under Discovery Information. It explains the rating to a reader who has not seen the evidence:\n"
    '  1. First sentence: the rating and the condition that decides it (see "What decides this rating").\n'
    "  2. Then one sentence for each condition that is not met or is unknown, saying what the system does and which parts cause it. "
    "Name at most three parts in a sentence, by their display names.\n"
    "  3. End with what is still unknown, in one sentence, if anything is.\n"
    "  At most 90 words. Say nothing about another requirement's conditions. Hosts, ports and inventories stay in the tables."
)


def test_the_stor_card_carrying_the_new_story_contract_exactly():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    text = section_card.card(node, spec, None, evidence=False)["text"]
    assert "## Requirement summaries and stories" in text
    assert EXPECTED_BODY in text
    # and the old "fuller" description is gone
    assert "fuller evidence-backed operational narrative" not in text


def test_the_draft_agent_step_points_to_the_card_shape_and_no_longer_describes_the_fuller_paragraph():
    md = (Path(__file__).resolve().parents[3] / "csa-draft-agent.md").read_text(encoding="utf-8")
    step = next(l for l in md.splitlines() if l.startswith("3. "))
    assert 'write Summary: and Story: exactly in the shape that section gives.' in step
    assert "the fuller paragraph" not in step
    assert "For every other prose block" in step
