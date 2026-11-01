import importlib.util
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[3] / "skills" / "australian-it-ot-terminology"
SCRIPT = SKILL / "scripts" / "term_lint.py"
TERMS = SKILL / "references" / "terminology.md"


def _load():
    spec = importlib.util.spec_from_file_location("term_lint_s507", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["term_lint_s507"] = mod
    spec.loader.exec_module(mod)
    return mod


def _codes(tl, text):
    Para = sys.modules["prose_lint"].Para
    paras = [Para("heading", "Section", 1), Para("text", text)]
    sec = tl.Section(1, "Section", paras)
    review, abbreviations, evidence, spelling = tl.load_terms()
    items = tl.lint_section(sec, review, abbreviations, evidence, spelling, tl.load_framework_terms())
    return [i for i in items if i["code"] == "FRAMEWORK_TERM"]


def test_captured_hosts_reported():
    hits = _codes(_load(), "The captured hosts follow one source.")
    assert len(hits) == 1 and hits[0]["found"] == "captured hosts" and hits[0]["ask"]


def test_not_captured_reported_case_insensitive():
    hits = _codes(_load(), "Time is Not captured.")
    assert [h["found"] for h in hits] == ["Not captured"]


def test_packet_capture_not_reported():
    assert _codes(_load(), "A packet capture was taken.") == []


def test_clean_text_not_reported():
    assert _codes(_load(), "The TETRA/Reveloc hosts follow one source.") == []


def test_every_section_16_phrase_reported():
    tl = _load()
    md = TERMS.read_text(encoding="utf-8")
    phrases = [r[0] for r in tl._table(md, r"16\. Framework terms")]
    assert len(phrases) == 8
    for phrase in phrases:
        assert _codes(tl, f"The text uses {phrase} here."), phrase


def test_load_terms_return_shape_unchanged():
    assert len(_load().load_terms()) == 4


def test_section_13_free_of_framework_wording():
    md = TERMS.read_text(encoding="utf-8")
    m = re.search(r"^##\s+13\..*?$(.*?)(?=^##\s)", md, re.M | re.S)
    body = m.group(1).lower()
    assert "captured hosts" not in body
    assert "discovery captures" not in body
