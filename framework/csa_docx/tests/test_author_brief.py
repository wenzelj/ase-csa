"""The author's section brief comes from the document: its requirement rows, tables, placeholders and comments."""
try:
    import pytest
except ImportError:          # the story checks run these tests without pytest
    pytest = None


def _skip(msg: str):
    if pytest:
        pytest.skip(msg)
    raise RuntimeError(msg)

from csa_docx import author_brief as ab
from csa_docx import doc_spec, spec_cli


def _spec():
    t = spec_cli.find_template(None)
    if not t:
        _skip("no CSA template available")
    return spec_cli.load(None, t)


def test_a_subsection_belongs_to_its_topic():
    assert ab.domain_key("3.1") == "3.1" and ab.domain_key("3.1.2") == "3.1" and ab.domain_key("3") == "3"


def test_requirements_split_into_id_and_wording():
    got = ab.requirement_items("SEP-GEN-01 classified inventory (type, role); SEP-GEN-03 dependencies, documented.")
    assert got == [("SEP-GEN-01", "classified inventory (type, role)"), ("SEP-GEN-03", "dependencies, documented")]


def test_the_brief_asks_what_the_document_asks():
    res = ab.build("3.1", spec=_spec())
    assert res["status"] == "OK" and res["questions"] == 5 and res["comments"] == 0 and res["key"] == "GEN"
    t = res["text"]
    assert t.startswith("## Section brief")
    for s in ("**Purpose:**", "**Requirements:** SEP-GEN-01, SEP-GEN-03", "- **Questions:**", "B1 SEP-GEN-01",
              "B2 SEP-GEN-03", "B3 Discovery Information", "B4 Hosts and roles found", "B5 Drawbridge Impact", "**Not here:**"):
        assert s in t, s


def test_the_same_brief_by_number_heading_or_family():
    spec = _spec()
    texts = {ab.build(x, spec=spec)["text"] for x in ("3.1", "General / Asset Inventory", "GEN")}
    assert len(texts) == 1


def test_every_reviewer_comment_becomes_a_c_question():
    spec = _spec()
    doc_spec.resolve(spec, "GEN")["comments"].append({"author": "Reviewer", "text": "Where is the second site?", "facet": None})
    res = ab.build("3.1", spec=spec)
    assert res["comments"] == 1 and 'C1 Reviewer comment (Reviewer): "Where is the second site?"' in res["text"]


def test_an_unknown_section_says_to_write_the_brief_by_hand():
    res = ab.build("9.9", spec=_spec())
    assert res["status"] == "UNKNOWN_SECTION" and "by hand" in res["message"]
