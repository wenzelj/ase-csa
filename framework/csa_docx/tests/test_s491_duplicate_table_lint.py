"""S491: the audit names two framework topic tables in one section that repeat each other."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csa_docx import audit, topic_tables as tt  # noqa: E402
from test_topic_tables import DOC, build  # noqa: E402
from test_s489_time_duplicate_table import HEADING, _with_stale_table  # noqa: E402


def _docx(path: Path, xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def _table(cols, rows=1):
    cell = lambda t: f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"
    tr = lambda cells: "<w:tr>" + "".join(cell(c) for c in cells) + "</w:tr>"
    return ('<w:tbl><w:tblPr><w:tblCaption w:val="csa-topic-table"/></w:tblPr>' + tr(cols)
            + "".join(tr(["x"] * len(cols)) for _ in range(rows)) + "</w:tbl>")


def _doc(*tables):
    h = '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>3.4 Time Synchronisation</w:t></w:r></w:p>'
    return f'<w:document xmlns:w="w"><w:body>{h}{"".join(tables)}</w:body></w:document>'


def test_s489_fixture_reports_duplicate(tmp_path):
    once, _ = tt.place_xml(DOC, build(tmp_path), HEADING)
    out = audit.check_duplicate_topic_tables(_docx(tmp_path / "a.docx", _with_stale_table(once)))
    assert [o["issue"] for o in out] == ["DUPLICATE_TOPIC_TABLE"]
    assert "Role" in out[0]["detail"] and "rows" in out[0]["detail"] and "Time Synchronisation" in out[0]["detail"]


def test_role_and_flow_tables_are_not_duplicates(tmp_path):
    d = _docx(tmp_path / "b.docx", _doc(_table(["Role", "Hosts", "Time source", "Poll interval"], 3),
                                        _table(["From", "To", "Protocol", "Port"], 2)))
    assert audit.check_duplicate_topic_tables(d) == []


def test_single_table_is_not_a_duplicate(tmp_path):
    assert audit.check_duplicate_topic_tables(_docx(tmp_path / "c.docx", _doc(_table(["Role", "Hosts"])))) == []


def test_mostly_shared_labels_are_a_duplicate(tmp_path):
    d = _docx(tmp_path / "d.docx", _doc(_table(["Host", "Role", "Time source"]),
                                        _table(["Site", "Time source", "Role", "Host", "Poll"])))
    assert len(audit.check_duplicate_topic_tables(d)) == 1
