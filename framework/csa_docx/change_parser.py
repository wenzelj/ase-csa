from __future__ import annotations

import re
from pathlib import Path

from .models import ChangeRecord

EDIT_HEADING_RE = re.compile(r"^###\s+(S\d+-[EA]\d+|[EA]-\d+)\s+-\s+(.+?)\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^\*\*Section:\*\*\s*(.+?)\s*$", re.MULTILINE)


def parse_change_file(path: Path) -> tuple[str | None, list[ChangeRecord]]:
    markdown = path.read_text(encoding="utf-8")
    section_match = SECTION_RE.search(markdown)
    section = section_match.group(1).strip() if section_match else None
    return section, parse_change_records(markdown)


def parse_change_records(markdown: str) -> list[ChangeRecord]:
    matches = list(EDIT_HEADING_RE.finditer(markdown))
    records: list[ChangeRecord] = []

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        block = markdown[start:end].strip()
        records.append(_parse_block(match.group(1), match.group(2).strip(), block))

    return records


def _parse_block(edit_id: str, title: str, block: str) -> ChangeRecord:
    return ChangeRecord(
        edit_id=edit_id,
        title=title,
        where=_extract_label(block, "Where"),
        action=_extract_label(block, "Do"),
        text=_extract_text_block(block),
        why=_extract_label(block, "Why"),
        raw=block,
        questions=_extract_questions(block),
        note=_extract_label(block, "Note"),
    )


def _extract_label(block: str, label: str) -> str:
    pattern = re.compile(
        rf"^\*\*{re.escape(label)}:\*\*\s*(.*?)(?=^\*\*(?:Where|Do|Text|Why|Note):\*\*|\n---[ \t]*(?:\n|\Z)|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(block)
    if not match:
        return ""
    return _clean_markdown_value(match.group(1).strip())


def _extract_text_block(block: str) -> str | None:
    raw = _extract_label(block, "Text")
    if not raw or raw.lower() in {"none", "none."}:
        return None

    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.rstrip()
        if stripped.startswith(">"):
            stripped = stripped[1:]
            if stripped.startswith(" "):
                stripped = stripped[1:]
        lines.append(stripped)

    text = "\n".join(lines).strip()
    return text or None


def _extract_questions(block: str) -> list[str]:
    questions: list[str] = []
    in_open_questions = False

    for line in block.splitlines():
        stripped = line.strip()
        if re.match(r"^##+\s+Open questions", stripped, re.IGNORECASE):
            in_open_questions = True
            continue
        if stripped.startswith("##") and in_open_questions:
            in_open_questions = False
        if in_open_questions or "?" in stripped:
            cleaned = stripped.lstrip("-*0123456789. ").strip()
            if cleaned and not re.match(r"(?:none\.?$|no (?:new |open )?questions|there are no (?:new |open )?questions)", cleaned, re.IGNORECASE):
                questions.append(cleaned)

    return questions


def _clean_markdown_value(value: str) -> str:
    value = re.sub(r"```(?:text)?\n(.*?)\n```", r"\1", value, flags=re.DOTALL)
    value = value.replace("`", "")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def select_batch(
    records: list[ChangeRecord],
    completed_ids: set[str],
    limit: int,
    start_edit_id: str | None = None,
    end_edit_id: str | None = None,
) -> list[ChangeRecord]:
    eligible = records
    if start_edit_id:
        try:
            start_index = next(i for i, rec in enumerate(eligible) if rec.edit_id == start_edit_id)
            eligible = eligible[start_index:]
        except StopIteration:
            return []
    if end_edit_id:
        try:
            end_index = next(i for i, rec in enumerate(eligible) if rec.edit_id == end_edit_id)
            eligible = eligible[: end_index + 1]
        except StopIteration:
            return []

    pending = [record for record in eligible if record.edit_id not in completed_ids]
    return pending[:limit]
