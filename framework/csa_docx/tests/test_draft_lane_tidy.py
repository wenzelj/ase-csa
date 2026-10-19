"""Draft lane after-write tidy: several Text: lines are paragraphs, stale table rows go, answered comments go."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import draft_lane  # noqa: E402
from csa_docx.answer_sheet import parse  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text, style=None):
    ps = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ps}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _tbl(rows):
    return "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in r) + "</w:tr>" for r in rows) + "</w:tbl>"


def _docx(tmp, body, comments):
    d = tmp / "d.docx"
    with zipfile.ZipFile(d, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/comments.xml", f"<w:comments {W}>{comments}</w:comments>")
    return d


def _comment(cid, author, text):
    return f'<w:comment w:id="{cid}" w:author="{author}">{_p(text)}</w:comment>'


SHEET = """## B1 SEP-X-01
Text: First paragraph.
Text: Second paragraph.
Rating: Not Met

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed |
| --- | --- |
| A | one |

## C1 Reviewer
Answer: Done.

## C2 Reviewer
Keep: not answered.
"""

CARD = {"title": "Storage", "questions": [
    {"id": "B1", "kind": "requirement", "text": "x"},
    {"id": "B2", "kind": "observation", "columns": ["Aspect", "Configuration Observed"], "text": "y"},
    {"id": "C1", "kind": "comment", "text": 'Reviewer comment (Rev): "Fix the aspect table please"'},
    {"id": "C2", "kind": "comment", "text": 'Reviewer comment (Rev): "Something else"'}]}


def test_several_text_lines_are_paragraphs():
    assert parse(SHEET)["B1"]["text"] == "First paragraph.\n\nSecond paragraph."


def test_tidy_trims_stale_rows_and_answered_comments(tmp_path):
    body = (_p("Storage", "Heading2") + _tbl([["Aspect", "Configuration Observed"], ["A", "one"], ["Old", "stale"],
                                               ["Older", "stale"]])
            + _p("Next", "Heading2") + _tbl([["Aspect", "Configuration Observed"], ["X", "1"], ["Y", "2"]]))
    d = _docx(tmp_path, body, _comment(7, "Rev", "Fix the aspect table please") + _comment(8, "Rev", "Something else"))
    out = draft_lane.tidy(d, CARD, SHEET)
    assert out["rows"] == 2 and out["comments"] == ["7"]
    with zipfile.ZipFile(d) as z:
        doc = z.read("word/document.xml").decode()
        com = z.read("word/comments.xml").decode()
    assert "Old" not in doc and "Older" not in doc
    assert ">Y<" in doc                                  # a table in another section is left alone
    assert 'w:id="7"' not in com and 'w:id="8"' in com


def test_tidy_no_section_no_change(tmp_path):
    d = _docx(tmp_path, _p("Other", "Heading2") + _tbl([["Aspect", "Configuration Observed"], ["A", "1"], ["B", "2"]]), "")
    assert draft_lane.tidy(d, CARD, SHEET)["rows"] == 0
