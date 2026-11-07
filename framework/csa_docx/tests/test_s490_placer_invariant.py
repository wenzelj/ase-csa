"""S490: place_xml ends with exactly the framework tables it was asked to place."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csa_docx import topic_tables as tt  # noqa: E402
from test_topic_tables import DOC, build  # noqa: E402

HEADING = "Time Synchronisation"
MARK = f'w:tblCaption w:val="{tt.CAPTION}"'
EMPTY_P = '<w:p w14:paraId="00216FFB" w14:textId="77777777" />'


def _marked(xml: str) -> int:
    return sum(MARK in m.group(0) for m in re.finditer(r"<w:tbl>.*?</w:tbl>", xml, re.S))


def _ours(once: str) -> str:
    """Our caption, table and note as one string."""
    s = once.rindex("<w:p>", 0, once.index("SEQ Table"))
    e = once.index("</w:p>", once.index("All hosts in this table")) + len("</w:p>")
    return once[s:e]


def _after_agent_note(once: str) -> int:
    return once.index("</w:p>", once.index("Agent note")) + len("</w:p>")


def test_placing_twice_gives_the_same_document(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    twice, _ = tt.place_xml(once, t, HEADING)
    assert twice == once and _marked(twice) == 1


def test_stray_marked_table_above_is_removed_with_caption_note_and_empty_paragraph(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    at = once.index(_ours(once))
    messy = once[:at] + _ours(once) + EMPTY_P + _ours(once) + once[at + len(_ours(once)):]
    assert _marked(messy) == 2
    fixed, _ = tt.place_xml(messy, t, HEADING)
    assert fixed == once


def test_stray_marked_table_below_the_real_one_is_removed(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    end = _after_agent_note(once)
    messy = once[:end] + EMPTY_P + _ours(once) + once[end:]
    assert _marked(messy) == 2
    fixed, _ = tt.place_xml(messy, t, HEADING)
    assert fixed == once


def test_table_without_the_marker_is_kept(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    plain = re.search(r"<w:tbl>(?:(?!</w:tbl>).)*?CSATable.*?</w:tbl>", DOC, re.S).group(0).replace("OT source", "Human table")
    end = _after_agent_note(once)
    messy = once[:end] + plain + once[end:]
    fixed, _ = tt.place_xml(messy, t, HEADING)
    assert fixed == messy and "Human table" in fixed


def test_section_with_no_profile_is_left_alone(tmp_path):
    r = tt.place(tmp_path, tmp_path / "missing.docx", "No Such Topic Anywhere")
    assert r["status"] == "SKIPPED"
