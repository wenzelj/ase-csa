from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .docx_package import extract_docx, test_zip
from .ooxml import W_NS, qn


def validate_docx(docx: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    ok, message = test_zip(docx)
    results["archive_integrity"] = "Pass" if ok else f"Fail: {message}"
    if not ok:
        return results

    package = extract_docx(docx)
    try:
        for member in ["[Content_Types].xml", "word/document.xml", "word/_rels/document.xml.rels"]:
            results[f"xml_parse:{member}"] = _parse_member(package.path(member))

        comments_path = package.path("word/comments.xml")
        if comments_path.exists():
            results["xml_parse:word/comments.xml"] = _parse_member(comments_path)
            results["comment_id_consistency"] = _check_comment_ids(package.path("word/document.xml"), comments_path)
            results["table_row_comment_safety"] = _check_table_row_comment_safety(package.path("word/document.xml"))
        else:
            results["xml_parse:word/comments.xml"] = "Not applicable"
    finally:
        package.cleanup()
    return results


def _parse_member(path: Path) -> str:
    if not path.exists():
        return "Fail: missing"
    try:
        ET.parse(path)
        return "Pass"
    except Exception as exc:
        return f"Fail: {exc}"


def _check_comment_ids(document_xml: Path, comments_xml: Path) -> str:
    doc_root = ET.parse(document_xml).getroot()
    comments_root = ET.parse(comments_xml).getroot()
    declared = {node.get(qn(W_NS, "id")) for node in comments_root.findall(qn(W_NS, "comment"))}
    starts = {node.get(qn(W_NS, "id")) for node in doc_root.iter(qn(W_NS, "commentRangeStart"))}
    ends = {node.get(qn(W_NS, "id")) for node in doc_root.iter(qn(W_NS, "commentRangeEnd"))}
    refs = {node.get(qn(W_NS, "id")) for node in doc_root.iter(qn(W_NS, "commentReference"))}
    missing = (starts | ends | refs) - declared
    incomplete = declared & ((starts ^ ends) | (starts ^ refs) | (ends ^ refs))
    if missing:
        return f"Fail: document references undeclared comment IDs {sorted(missing)}"
    if incomplete:
        return f"Fail: incomplete comment markers for IDs {sorted(incomplete)}"
    return "Pass"


def _check_table_row_comment_safety(document_xml: Path) -> str:
    root = ET.parse(document_xml).getroot()
    unsafe_tags = {
        qn(W_NS, "commentRangeStart"),
        qn(W_NS, "commentRangeEnd"),
        qn(W_NS, "commentReference"),
        qn(W_NS, "r"),
    }
    unsafe = []
    for tr in root.iter(qn(W_NS, "tr")):
        for child in list(tr):
            if child.tag in unsafe_tags:
                unsafe.append(child.tag)
    if unsafe:
        return f"Fail: unsafe direct w:tr children found: {len(unsafe)}"
    return "Pass"
