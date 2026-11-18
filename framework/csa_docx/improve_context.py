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
_QUESTION_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:QUESTION|UNKNOWN|OPEN QUESTION)\s*:\s*(.+?)\s*$", re.I)


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


def extract_gap_questions(answer_text: str, *, limit: int = 8) -> list[str]:
    """Extract explicit unanswered questions from the current subsection only."""
    out: list[str] = []
    seen: set[str] = set()
    for line in str(answer_text or "").splitlines():
        match = _QUESTION_LINE.match(line)
        question = " ".join(match.group(1).split()) if match else ""
        if question and question.casefold() not in seen:
            seen.add(question.casefold())
            out.append(question)
        if len(out) >= limit:
            break
    return out


def extract_improvement_searches(answer_text: str, reader_review: str = "", rating_summary: dict[str, Any] | None = None,
                                 *, limit: int = 8) -> list[str]:
    """Build bounded searches from explicit gaps plus review/rating diagnostics."""
    requests = extract_gap_questions(answer_text)
    seen = {q.casefold() for q in requests}
    active = False
    for line in str(reader_review or "").splitlines():
        if line.startswith("## "):
            active = line.casefold().startswith(("## claims that go beyond", "## does each story"))
            continue
        if active and line.lstrip().startswith("-"):
            text = re.sub(r"^\s*-\s*", "", line).strip()
            if text and text.casefold() not in seen:
                requests.append(f"Verify this answer issue: {text}")
                seen.add(text.casefold())
    for block, tips in ((rating_summary or {}).get("improve") or {}).items():
        for tip in tips:
            text = " ".join(str(tip).split())
            if text and text.casefold() not in seen:
                requests.append(f"Check evidence for {block}: {text}")
                seen.add(text.casefold())
    return requests[:limit]


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
    subsection_data: dict[str, Any] | None = None,
    reader_review: str = "",
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
        # The current answer is not the evidence boundary for Improve.  The
        # live subsection card may contain supported rows that the old answer
        # omitted; retain that pack separately from the document baseline.
        "subsection_data": dict(subsection_data or {}),
        "reader_review": reader_review,
    }


def collect_subsection_data(card: dict[str, Any], verified_rows: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Return the complete live subsection pack for the Improve agent.

    Card evidence is routed per question, while ``available_evidence`` is the
    deduplicated set of verified rows the proposal may cite.  Candidates remain
    visible as unverified leads but are deliberately not added to citeable IDs.
    No normal question rows are truncated here; the card builder owns only its
    explicit register bound.
    """
    evidence = card.get("evidence") or {}
    by_id: dict[str, dict[str, Any]] = {}
    for pack in evidence.values():
        for row in pack.get("rows", []) if isinstance(pack, dict) else []:
            if isinstance(row, dict) and row.get("id"):
                by_id.setdefault(str(row["id"]).upper(), dict(row))
    verified = {str(row.get("evidence_id") or row.get("id") or "").upper(): dict(row)
                for row in verified_rows if isinstance(row, dict)
                and (row.get("evidence_id") or row.get("id"))}
    available = [verified[eid] for eid in sorted(by_id) if eid in verified]
    candidates = []
    for qid, pack in evidence.items():
        for candidate in (pack.get("candidates", []) if isinstance(pack, dict) else []):
            candidates.append({"question": qid, **candidate})
    return {
        "questions": card.get("questions", []),
        "evidence": evidence,
        "available_evidence": available,
        "available_evidence_ids": [str(row.get("evidence_id") or row.get("id")).upper() for row in available],
        "unverified_candidates": candidates,
        "established": card.get("established", {}),
        "keep": card.get("keep", []),
        "correct": card.get("correct", []),
        "frame": card.get("frame"),
        "current_content": card.get("current_content", []),
        "writing_purpose": card.get("writing_purpose", ""),
    }
