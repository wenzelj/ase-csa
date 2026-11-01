"""S510: every card lists the framework words the answer must not use, once, with the 'Say instead' text."""
from csa_docx import section_card

HEAD = "## Words that must not appear in the text"
NODE = {"key": "DEMO", "title": "Demo section", "number": "1.1", "kind": "subsection", "level": 2, "parts": [], "facets": {},
        "text": "", "rules": []}
SPEC = {"nodes": [NODE]}


def build():
    return section_card.card(NODE, SPEC, None, evidence=False)["text"]


def test_section_appears_once_with_the_framework_terms():
    text = build()
    assert text.count(HEAD) == 1
    body = text.split(HEAD)[1].split("\n## ")[0]
    for phrase in ("captured hosts", "not captured", "discovery data"):
        assert "- " + phrase + ": " in body
    assert "- captured hosts: Name the system, the role group or the host" in body


def test_section_absent_when_the_loader_fails(monkeypatch):
    monkeypatch.setattr(section_card, "_load_framework_terms", lambda: [])
    assert HEAD not in build()
