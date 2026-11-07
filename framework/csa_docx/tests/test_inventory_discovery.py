"""New, populated inventory subsections stay discoverable without a template entry."""
import zipfile
from xml.sax.saxutils import escape

import pytest

from csa_docx import doc_spec as D, section_card as SC


INVENTORIES = [
    ("User and Service Account Inventory", ["Account Name", "Type", "Hosts(s)", "Purpose", "Privileged", "Notes"]),
    ("Security Group & Membership Inventory", ["Group Name", "Type", "Hosts(s)", "Purpose", "Privileged", "Members", "Notes"]),
    ("Local Administrators Inventory", ["Host(s)", "Member Name", "Member Type", "Notes"]),
    ("Remote Desktop Users Inventory", ["Host(s)", "Member Name", "Member Type", "Notes"]),
]


@pytest.mark.parametrize('title,columns', INVENTORIES)
@pytest.mark.parametrize('data', ['populated', 'blank', 'header_only'])
def test_inventory_tables_are_registers_with_or_without_existing_rows(title, columns, data):
    rows = [columns]
    if data != 'header_only':
        rows.append(['existing name'] + [''] * (len(columns) - 1) if data == 'populated' else [''] * len(columns))
    part = D._table_part(rows, None, None, [], heading=title + '\u00a0')
    assert part['kind'] == 'register'
    assert part['filled'] == (1 if data == 'populated' else 0)
    assert part['columns'] == columns
    assert len(part['row_texts']) == len(rows) - 1


@pytest.mark.parametrize('title,rows', [
    ('Document Information', [['Name', 'Value'], ['Version', '1.0']]),
    ('Glossary and Acronyms', [['Term', 'Meaning'], ['AD', 'Active Directory']]),
    ('Account Information', [['Account Name', 'Notes'], ['Service A', 'Runs service']]),
    ('Inventory', [['Description', 'Comment'], ['Scope', 'Reference text']]),
])
def test_reference_tables_are_not_reclassified_from_content_alone(title, rows):
    assert D._table_part(rows, None, None, [], heading=title)['kind'] == 'reference'


def test_live_read_to_card_detects_inserted_inventory_and_keeps_following_numbers(tmp_path):
    def para(text, style):
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{escape(text)}</w:t></w:r></w:p>'

    def table(rows):
        return '<w:tbl>' + ''.join('<w:tr>' + ''.join(
            f'<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>' for cell in row
        ) + '</w:tr>' for row in rows) + '</w:tbl>'

    title, columns = INVENTORIES[0]
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    xml += para('4 Migration Discovery', 'Heading1') + para('4.5 ' + title, 'Heading2')
    xml += table([columns, ['Example service'] + [''] * (len(columns) - 1)])
    xml += para('4.6 Next Topic', 'Heading2') + '</w:body></w:document>'
    file = tmp_path / 'new-inventory.docx'
    with zipfile.ZipFile(file, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    spec = D.join(D.read(file), {'nodes': []})
    node = D.resolve(spec, title)
    assert node['number'] == '4.5' and node['kind'] == 'register'
    assert D.resolve(spec, 'Next Topic')['number'] == '4.6'
    card = SC.card(node, spec, workspace=tmp_path)
    assert card['questions'][0]['kind'] == 'register'
    assert card['questions'][0]['columns'] == columns
    assert card['frame']['origin'] == 'document_questions'
