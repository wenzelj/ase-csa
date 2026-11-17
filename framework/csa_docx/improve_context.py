"""Read-only assembly of the current document answer for CSA Improve."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


class ContextError(ValueError):
    """The selected subsection cannot safely be used as an Improve baseline."""


_HEADING = re.compile(r"^(?P<key>\d+(?:\.\d+)*)(?:\s+|$)")
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _heading_level(style_name: str) -> int | None:
    match = re.search(r"heading\s*(\d+)", style_name or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def _hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _section_key(text: str) -> str | None:
    match = _HEADING.match(text.strip())
    return match.group("key") if match else None


def _docx_blocks(path: Path) -> list[dict[str, Any]]:
    try:
        with ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (OSError, BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ContextError(f"cannot read working document: {path}") from exc
    blocks: list[dict[str, Any]] = []
    body = root.find("w:body", _NS)
    if body is None:
        return blocks
    for element in body:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = "".join(node.text or "" for node in element.findall(".//w:t", _NS)).strip()
            style = element.find("w:pPr/w:pStyle", _NS)
            style_name = style.get(f"{{{_NS['w']}}}val", "") if style is not None else ""
            if text:
                block = {"kind": "heading" if style_name.lower().startswith("heading") else "paragraph", "text": text}
                if block["kind"] == "heading":
                    block["level"] = _heading_level(style_name)
                blocks.append(block)
        elif tag == "tbl":
            rows = []
            for row in element.findall("w:tr", _NS):
                cells = []
                for cell in row.findall("w:tc", _NS):
                    cells.append(" ".join(
                        "".join(node.text or "" for node in paragraph.findall(".//w:t", _NS)).strip()
                        for paragraph in cell.findall("w:p", _NS)
                    ).strip())
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows, "text": " | ".join(" | ".join(row) for row in rows)})
    return blocks


def _text_blocks(path: Path) -> list[dict[str, Any]]:
    blocks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        level = None
        if text.startswith("#"):
            level = len(text) - len(text.lstrip("#"))
            text = text.lstrip("#").strip()
        block = {"kind": "heading" if level or _section_key(text) else "paragraph", "text": text}
        if block["kind"] == "heading":
            block["level"] = level or len(_section_key(text).split(".")) if _section_key(text) else None
        blocks.append(block)
    return blocks


def extract_section(path: Path | str, section_key: str, section_title: str | None = None) -> dict[str, Any]:
    """Extract one section from a DOCX or text fixture, stopping at the next heading."""
    source = Path(path)
    if not source.is_file():
        raise ContextError(f"working document is missing: {source}")
    blocks = _docx_blocks(source) if source.suffix.lower() == ".docx" else _text_blocks(source)
    start = None
    for index, block in enumerate(blocks):
        text = block.get("text", "").strip()
        if (_section_key(text) == section_key or
                (section_title and text.casefold() == section_title.strip().casefold())):
            start = index
            break
    if start is None:
        raise ContextError(f"subsection {section_key} is not present in {source.name}")
    start_level = blocks[start].get("level")
    selected = []
    for block in blocks[start + 1:]:
        text = block.get("text", "").strip()
        key = _section_key(text) if block.get("kind") == "heading" else None
        if block.get("kind") == "heading":
            level = block.get("level")
            # Keep nested headings such as “Discovery Information” and
            # “Drawbridge Impact” in the subsection. Stop only at the next
            # heading at the selected subsection's level (or an explicit
            # numbered sibling when a fixture has no style levels).
            if start_level is not None and level is not None:
                if level <= start_level:
                    break
            elif key and key != section_key:
                break
            elif not key and section_title and text.casefold() != section_title.strip().casefold():
                break
        selected.append(block)
    if not selected:
        raise ContextError(f"subsection {section_key} has no current answer in {source.name}")
    return {"section_key": section_key, "heading": blocks[start]["text"], "blocks": selected}


def _ids(values: Iterable[str] | None) -> list[str]:
    return sorted({value.strip() for value in (values or ()) if isinstance(value, str) and value.strip()})


def build_context(
    section_key: str,
    document_path: Path | str,
    *,
    section_title: str | None = None,
    rating: str | None = None,
    answer_run_id: str | None = None,
    findings: Iterable[str] | None = None,
    open_questions: Iterable[str] | None = None,
    supporting_evidence: Iterable[str] | None = None,
    new_evidence: Iterable[dict[str, Any]] | None = None,
    related_evidence: Iterable[dict[str, Any]] | None = None,
    rating_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build bounded, provenance-aware context without performing model or index work."""
    source = Path(document_path)
    section = extract_section(source, section_key, section_title)
    return {
        "version": "improve-context-v1",
        "section_key": section_key,
        "working_document": str(source),
        "document_hash": _hash(source),
        # The Improve contract calls this the baseline hash. Keep the
        # original document_hash field for existing readers while exposing
        # the contract name to the model and validator.
        "base_document_hash": _hash(source),
        "answer_run_id": answer_run_id,
        "provenance": "recorded" if answer_run_id else "legacy/unknown",
        "heading": section["heading"],
        "blocks": section["blocks"],
        "answer_text": "\n".join(block["text"] for block in section["blocks"]),
        "rating": rating,
        "rating_summary": rating_summary or {},
        "findings": list(findings or ()),
        "open_questions": list(open_questions or ()),
        "supporting_evidence_ids": _ids(supporting_evidence),
        "new_evidence": list(new_evidence or ()),
        "related_evidence": list(related_evidence or ()),
    }
