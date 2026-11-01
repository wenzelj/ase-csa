"""S489: a stale framework table that follows an empty self-closing paragraph survives place_xml.

Fixture shaped like the 3.4 block of the TETRA document (1 November 2026): our role table and its note, then an
empty paragraph written as `<w:p .../>` and a second marked table. Findings: improvements/FINDINGS-s489.md.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csa_docx import topic_tables as tt  # noqa: E402
from test_topic_tables import DOC, build  # noqa: E402

HEADING = "Time Synchronisation"
MARK = f'w:tblCaption w:val="{tt.CAPTION}"'
EMPTY_P = '<w:p w14:paraId="00216FFB" w14:textId="77777777" w:rsidR="0064431F" w:rsidRDefault="0064431F" />'


def _marked(xml: str) -> int:
    return sum(MARK in m.group(0) for m in re.finditer(r"<w:tbl>.*?</w:tbl>", xml, re.S))


def _with_stale_table(once: str) -> str:
    """``once`` plus, straight after our note, an empty self-closing paragraph and a stale marked table."""
    table = re.search(r"<w:tbl>(?:(?!</w:tbl>).)*?" + re.escape(MARK) + r".*?</w:tbl>", once, re.S).group(0)
    stale = table
    at = once.index("</w:p>", once.index("All hosts in this table")) + len("</w:p>")
    return once[:at] + EMPTY_P + stale + once[at:]


@pytest.mark.xfail(strict=True, reason="S489: _blocks swallows a table's first cell after a self-closing <w:p/>")
def test_blocks_reads_the_table_after_a_self_closing_paragraph(tmp_path):
    once, _ = tt.place_xml(DOC, build(tmp_path), HEADING)
    messy = _with_stale_table(once)
    ins, fend, _ = tt._locate(messy, HEADING)
    kinds = [k for k, *_ in tt._blocks(messy, ins, fend)]
    assert kinds.count("tbl") == 3          # our table, the stale one, the Aspect table


@pytest.mark.xfail(strict=True, reason="S489: _blocks swallows a table's first cell after a self-closing <w:p/>")
def test_place_leaves_exactly_the_built_tables_and_no_empty_paragraph(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    messy = _with_stale_table(once)
    assert _marked(messy) == 2
    fixed, _ = tt.place_xml(messy, t, HEADING)
    assert _marked(fixed) == 1                      # as many marked tables as were built
    assert EMPTY_P not in fixed                     # and no empty paragraph left behind
