"""S510 (moved): the framework words the answer must not use are in the prompt digest, once, with the 'Say instead' text.
The card carries evidence only and no longer lists them."""
from csa_docx import rules_digest, section_card

HEAD = "## Words that must not appear in the text"
NODE = {"key": "DEMO", "title": "Demo section", "number": "1.1", "kind": "subsection", "level": 2, "parts": [], "facets": {},
        "text": "", "rules": []}
SPEC = {"nodes": [NODE]}


def test_the_card_no_longer_lists_the_words():
    assert HEAD not in section_card.card(NODE, SPEC, None, evidence=False)["text"]


def test_the_answer_digest_lists_the_framework_terms_once():
    from csa_docx import prompts
    for text in (rules_digest.digest("answer"), prompts.assemble({"requirement"}, None)[0]):
        assert text.count("## Words that must not appear in the text") == 1
        for phrase in ("captured hosts", "not captured", "discovery data"):
            assert "- " + phrase + ": " in text
        assert "- captured hosts: Name the system, the role group or the host" in text
