"""CSA table formatting changes presentation only and runs through the document engine."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from csa_docx.table_format import W, match_csa_table


def _table():
    return ET.fromstring(f'''<w:tbl xmlns:w="{W[1:-1]}"><w:tblPr><w:tblBorders/><w:tblCellMar/></w:tblPr>
    <w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="2000"/><w:shd w:fill="FF0000"/></w:tcPr>
    <w:p><w:pPr><w:spacing w:after="200"/></w:pPr><w:bookmarkStart w:id="22" w:name="keep"/>
    <w:r><w:rPr><w:rFonts w:ascii="Times New Roman"/><w:sz w:val="24"/></w:rPr><w:t>Heading</w:t></w:r><w:bookmarkEnd w:id="22"/></w:p>
    </w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Account &amp; membership</w:t></w:r></w:p></w:tc></w:tr></w:tbl>''')


def test_formatting_preserves_text_geometry_and_bookmarks_and_is_idempotent():
    table = _table()
    original = copy.deepcopy(table)
    match_csa_table(table, _table())
    for tag in ['t', 'tblGrid', 'tcW', 'bookmarkStart', 'bookmarkEnd']:
        assert [ET.tostring(x) for x in table.iter(W + tag)] == [ET.tostring(x) for x in original.iter(W + tag)]
    assert table.find(W + 'tblPr/' + W + 'tblStyle').get(W + 'val') == 'CSATable'
    assert [p.find(W + 'pPr/' + W + 'pStyle').get(W + 'val') for p in table.iter(W + 'p')] == ['TableHeader', 'TableText']
    assert not list(table.iter(W + 'shd')) and not list(table.iter(W + 'rFonts'))
    assert table.find(W + 'tr/' + W + 'trPr/' + W + 'tblHeader') is not None
    first = ET.tostring(table)
    match_csa_table(table, _table())
    assert ET.tostring(table) == first


def test_pending_revisions_are_refused_without_changes():
    table = _table()
    table.find('.//' + W + 'p').append(ET.Element(W + 'ins'))
    original = ET.tostring(table)
    with pytest.raises(ValueError, match='tracked changes'):
        match_csa_table(table, _table())
    assert ET.tostring(table) == original


def test_engine_format_record_saves_and_keeps_all_table_text(tmp_path):
    from csa_docx import spec_cli
    from csa_docx.engines.docxengine_adapter import DocxEngineEditor, _serialize_part_preserving
    from csa_docx.models import ChangeRecord
    from csa_docx.stable_ids import generate_manifest
    template = spec_cli.find_template(None)
    if not template:
        pytest.skip('CSA template unavailable')
    path = tmp_path / 'style-test.dotx'
    path.write_bytes(Path(template).read_bytes())
    engine = DocxEngineEditor(path, track_changes=False)
    package = engine.doc._doc.package
    part = package.main_document_part()
    original = package.part(part)
    root = ET.fromstring(original)
    tables = root.find(W + 'body').findall(W + 'tbl')
    index = next(i for i, t in enumerate(tables) if t.find(W + 'tblPr/' + W + 'tblStyle') is not None
                 and t.find(W + 'tblPr/' + W + 'tblStyle').get(W + 'val') == 'CSATable')
    props = tables[index].find(W + 'tblPr')
    props.remove(props.find(W + 'tblStyle'))
    package.set_part(part, _serialize_part_preserving(root, original))
    engine.doc._doc.mark_dirty()
    entries = generate_manifest(engine.paragraphs_with_table_rows())
    entry = next(e for e in entries if e.get('anchor') == f'T{index + 1}-R1')
    record = ChangeRecord('S4-E1', 'Match table formatting', entry['id'], 'Apply CSA table formatting', None, 'Owner request', '')
    texts = [x.text for x in root.iter(W + 't')]
    result = engine.apply_change(record, 'Wenzel Joubert', 'WJ')
    assert result.status == 'APPLIED', result
    engine.save()
    from zipfile import ZipFile
    with ZipFile(path) as z:
        after = ET.fromstring(z.read(part))
    assert [x.text for x in after.iter(W + 't')] == texts
    assert after.find(W + 'body').findall(W + 'tbl')[index].find(W + 'tblPr/' + W + 'tblStyle').get(W + 'val') == 'CSATable'
