"""User-added inventory tables can grow without restyling or deleting content."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

import pytest

AGENTS = Path(__file__).resolve().parents[3]
SCRIPT = AGENTS / 'skills/csa-document-template/scripts/scaffold_csa.py'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def _document(path, title='Remote Desktop Users Inventory', style=None, merged=False):
    def p(text):
        return '<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>'
    def row(cells):
        return '<w:tr>' + ''.join('<w:tc>' + p(c) + '</w:tc>' for c in cells) + '</w:tr>'
    props = '<w:tblPr><w:tblStyle w:val="' + style + '"/></w:tblPr>' if style else ''
    table = '<w:tbl>' + props + row(['Host(s)', 'Member Name', 'Member Type', 'Notes'])
    table += row(['HOST1', 'GROUP1', 'Group', 'Keep this note']) + row(['HOST2', 'USER1', 'User', '']) + '</w:tbl>'
    if merged:
        table = table.replace('<w:tc>', '<w:tc><w:tcPr><w:vMerge/></w:tcPr>', 1)
    xml = '<w:document xmlns:w="' + NS['w'] + '"><w:body>'
    xml += '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>' + escape(title) + '</w:t></w:r></w:p>'
    xml += table + '</w:body></w:document>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)
        z.writestr('untouched.bin', b'preserve this part')
    return path


def _run(path, count=6, title='Remote Desktop Users Inventory'):
    result = subprocess.run([sys.executable, str(SCRIPT), 'rows', '--docx', str(path),
                             '--heading', title, '--set-count', str(count)], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize('style,title', [(None, 'Remote Desktop Users Inventory'),
    ('TableGrid', 'Local Administrators Inventory'), (None, 'Security Group & Membership Inventory')])
def test_grow_inventory_preserves_rows_style_other_parts_and_backup(tmp_path, style, title):
    path = _document(tmp_path / 'inventory.docx', title, style)
    before = path.read_bytes()
    rc, result = _run(path, title=title)
    assert rc == 0 and result['status'] == 'UPDATED'
    assert Path(result['backup']).read_bytes() == before
    with zipfile.ZipFile(path) as z:
        assert z.read('untouched.bin') == b'preserve this part'
        table = ET.fromstring(z.read('word/document.xml')).find('.//w:tbl', NS)
    rows = table.findall('w:tr', NS)
    assert len(rows) == 7
    assert 'Keep this note' in ''.join(rows[1].itertext())
    assert 'HOST2' in ''.join(rows[2].itertext())
    table_style = table.find('w:tblPr/w:tblStyle', NS)
    assert (table_style.get('{' + NS['w'] + '}val') if table_style is not None else None) == style
    assert '[Host(s)]' in ''.join(rows[3].itertext())
    rc, result = _run(path, title=title)
    assert rc == 0 and result['status'] == 'UNCHANGED'


@pytest.mark.parametrize('title,merged,count', [('Reference', False, 6),
    ('Remote Desktop Users Inventory', True, 6), ('Remote Desktop Users Inventory', False, 1)])
def test_refusal_does_not_change_document(tmp_path, title, merged, count):
    path = _document(tmp_path / 'reference.docx', title, merged=merged)
    before = path.read_bytes()
    rc, result = _run(path, count=count, title=title)
    assert rc != 0 and result['status'] == 'ERROR'
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))


def test_result_outcome_preserves_review_and_only_marks_applied_after_write(tmp_path):
    csa = runpy.run_path(str(AGENTS / 'bin/csa'))
    file = tmp_path / 'RESULT.md'
    csa['_write_answer_result'](file, '4.8', 'VALIDATED - NOT APPLIED', {'findings': []}, 0,
                                tmp_path / 'answer.md', 'Validation passed; write pending.')
    with file.open('a') as stream:
        stream.write('\n## Reader review (advisory)\nKeep this review.\n')
    assert file.read_text().startswith('# csa answer 4.8: VALIDATED - NOT APPLIED')
    csa['_set_answer_outcome'](file, '4.8', 'APPLICATION FAILED', 'Scaffold refused: not rectangular.')
    assert 'APPLICATION FAILED' in file.read_text().splitlines()[0]
    assert 'Keep this review.' in file.read_text()
    csa['_set_answer_outcome'](file, '4.8', 'APPLIED', 'Document write completed.')
    assert file.read_text().startswith('# csa answer 4.8: APPLIED\n')
    assert 'Scaffold refused' not in file.read_text()
    assert 'Keep this review.' in file.read_text()


def test_scaffold_failure_records_failed_phase_and_preserves_diagnostics(tmp_path):
    import ast
    source = AGENTS / 'bin/csa'
    tree = ast.parse(source.read_text())
    failure = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'application_failure')
    calls = []

    def die(message):
        raise SystemExit(message)

    env = {'cards': tmp_path, 'key': 'RDP', 'number': '4.8', 'die': die,
           '_set_answer_outcome': lambda *args: calls.append(('report', args[2], args[3])),
           'draft_run': lambda *args, **kwargs: calls.append(('run', args, kwargs))}
    exec(compile(ast.Module(body=[failure], type_ignores=[]), str(source), 'exec'), env)
    with pytest.raises(SystemExit):
        env['application_failure']('scaffold refused: detailed reason', 'SCAFFOLDING')
    assert calls[0] == ('report', 'APPLICATION FAILED', 'scaffold refused: detailed reason')
    assert calls[1][1][0] == 'FAILED' and calls[1][1][2] == 'SCAFFOLDING'
    assert calls[1][2]['terminal'] is True
