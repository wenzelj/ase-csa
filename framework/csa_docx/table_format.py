"""Match an existing table to the document's named CSA styles without replacing content."""
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _props(element, name):
    found = element.find(W + name)
    if found is None:
        found = ET.Element(W + name)
        element.insert(0, found)
    return found


def _remove(parent, names):
    for child in list(parent):
        if child.tag in {W + name for name in names}:
            parent.remove(child)


def match_csa_table(table, reference):
    """Keep content and geometry, replace presentation overrides with named styles."""
    if any(next(table.iter(W + tag), None) is not None for tag in ['ins', 'del', 'moveFrom', 'moveTo']):
        raise ValueError('target table has pending tracked changes')
    props = _props(table, 'tblPr')
    _remove(props, ['tblStyle', 'tblBorders', 'tblCellMar', 'shd', 'tblLook'])
    props.insert(0, ET.Element(W + 'tblStyle', {W + 'val': 'CSATable'}))
    look = reference.find(W + 'tblPr/' + W + 'tblLook')
    if look is not None:
        props.append(copy.deepcopy(look))
    else:
        props.append(ET.Element(W + 'tblLook', {W + 'firstRow': '1', W + 'noHBand': '0', W + 'noVBand': '1'}))
    for row_index, row in enumerate(table.findall(W + 'tr')):
        row_props = _props(row, 'trPr')
        _remove(row_props, ['cnfStyle', 'tblHeader', 'cantSplit'])
        row_props.append(ET.Element(W + 'cantSplit'))
        if row_index == 0:
            row_props.append(ET.Element(W + 'tblHeader'))
        for cell in row.findall(W + 'tc'):
            _remove(_props(cell, 'tcPr'), ['tcBorders', 'shd', 'tcMar'])
            for paragraph in cell.iter(W + 'p'):
                paragraph_props = _props(paragraph, 'pPr')
                _remove(paragraph_props, ['pStyle', 'spacing', 'jc', 'ind', 'contextualSpacing', 'textAlignment', 'rPr', 'cnfStyle'])
                paragraph_props.insert(0, ET.Element(W + 'pStyle', {W + 'val': 'TableHeader' if row_index == 0 else 'TableText'}))
            for run_props in cell.iter(W + 'rPr'):
                _remove(run_props, ['rFonts', 'sz', 'szCs', 'color', 'shd', 'highlight'])
    return table
