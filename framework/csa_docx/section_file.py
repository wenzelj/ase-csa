"""Parser for build-lane section files.

A section file is the build lane's unit of authoring (see
``.agents/docs/build-lane-spec.md``, section 3, and the single definition in
``.agents/references/section-file-format.md``). It is a flat front matter
(block / heading / status, parsed without PyYAML like ``PROJECTS.yaml``)
followed by fixed ``##`` sections of plain prose, Markdown pipe tables or
``-`` bullets. The ``## Evidence`` table is the traceability record and is
never rendered into the document.

This module is standard-library only. It parses one file into structured
data (``parse_section_file``) and lists the rendered statements in document
order (``rendered_statements``); it does not read the template, the evidence
matrix or the DOCX, and it never writes anything.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Headings whose content is a pipe table but which are not rendered as plain
#: table rows: ``Requirements`` is rendered row-by-row as requirement
#: statements, ``Evidence`` is the traceability record and never rendered.
_NON_TABLE_HEADINGS = ("Requirements", "Evidence")


def _split_front_matter(text: str) -> tuple[dict, list[str]]:
    """Split off the leading ``---`` front matter.

    Returns the parsed front-matter mapping (flat ``key: value`` lines) and
    the list of lines that follow the closing ``---``. Raises ``ValueError``
    when the front matter is missing.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("section file is missing its front matter (it must start with '---')")
    meta: dict[str, str] = {}
    closed = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closed = i
            break
        line = lines[i].strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    if closed is None:
        raise ValueError("section file front matter is not closed by a second '---' line")
    return meta, lines[closed + 1:]


def _sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group the body into ``(heading, content_lines)`` in file order.

    Lines before the first ``##`` heading (blank or prose) are ignored; they
    carry no rendered content in the section-file format.
    """
    sections: list[tuple[str, list[str]]] = []
    current: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                sections.append((current, buf))
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections.append((current, buf))
    return sections


def _content_kind(content: list[str]) -> str:
    """Classify a section's non-blank content as ``table``, ``bullets`` or ``prose``."""
    kinds = set()
    for line in content:
        s = line.strip()
        if not s:
            continue
        if s.startswith("|"):
            kinds.add("table")
        elif s.startswith("- "):
            kinds.add("bullets")
        else:
            kinds.add("prose")
    if "table" in kinds:
        return "table"
    if "bullets" in kinds:
        return "bullets"
    return "prose"


def _split_row(line: str) -> list[str]:
    """Cells of a pipe table row, with the leading/trailing pipes removed."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c)


def parse_section_file(path) -> dict:
    """Parse a build-lane section file into structured data.

    See the module docstring for the format. ``ValueError`` is raised when
    the front matter is missing, or when ``block:`` or ``heading:`` is empty.
    """
    text = Path(path).read_text(encoding="utf-8")
    meta, body = _split_front_matter(text)

    block = meta.get("block", "")
    heading = meta.get("heading", "")
    if not block:
        raise ValueError("section file front matter has an empty or missing 'block:'")
    if not heading:
        raise ValueError("section file front matter has an empty or missing 'heading:'")

    result: dict = {
        "block": block,
        "heading": heading,
        "status": meta.get("status") or "draft",
        "meta": meta,
        "requirements": [],
        "bullets": {},
        "paragraphs": {},
        "tables": {},
        "evidence": {},
        "order": [],
    }

    for name, content in _sections(body):
        result["order"].append(name)
        kind = _content_kind(content)

        if name == "Requirements" and kind == "table":
            seen_header = False
            for line in content:
                s = line.strip()
                if not s.startswith("|"):
                    continue
                cells = _split_row(s)
                if len(cells) < 3:
                    continue
                if _is_separator_row(cells):
                    continue
                if not seen_header:
                    seen_header = True
                    continue
                result["requirements"].append({
                    "req_id": cells[0],
                    "current_state": cells[1],
                    "rating": cells[2],
                })
            continue

        if name == "Evidence" and kind == "table":
            seen_header = False
            for line in content:
                s = line.strip()
                if not s.startswith("|"):
                    continue
                cells = _split_row(s)
                if len(cells) < 2:
                    continue
                if _is_separator_row(cells):
                    continue
                if not seen_header:
                    seen_header = True
                    continue
                statement = cells[0].strip()
                ids = [part.strip() for part in cells[1].split(",") if part.strip()]
                if statement:
                    result["evidence"][statement] = ids
            continue

        if name in _NON_TABLE_HEADINGS:
            # A Requirements/Evidence section that is not a table is not
            # rendered; record nothing for it.
            continue

        if kind == "bullets":
            result["bullets"][name] = [
                line.strip()[2:].strip() for line in content if line.strip().startswith("- ")
            ]
        elif kind == "table":
            rows = []
            seen_header = False
            for line in content:
                s = line.strip()
                if not s.startswith("|"):
                    continue
                cells = _split_row(s)
                if _is_separator_row(cells):
                    continue
                if not seen_header:
                    seen_header = True
                    continue
                rows.append(cells)
            result["tables"][name] = rows
        else:
            paragraphs: list[str] = []
            current: list[str] = []
            for line in content:
                if line.strip():
                    current.append(line.strip())
                else:
                    if current:
                        paragraphs.append(" ".join(current))
                        current = []
            if current:
                paragraphs.append(" ".join(current))
            result["paragraphs"][name] = paragraphs

    return result


def rendered_statements(parsed: dict) -> list[tuple[str, str]]:
    """Return every rendered ``(key, text)`` pair in file order, never the Evidence table.

    The keys are exactly the first column the ``## Evidence`` table must
    contain: requirement rows use the Req ID, bullets and table rows are
    numbered ``<heading> <n>`` from 1, and a prose section uses its heading
    when it holds one paragraph, otherwise ``<heading> <n>``.
    """
    out: list[tuple[str, str]] = []
    for name in parsed["order"]:
        if name == "Requirements":
            for req in parsed["requirements"]:
                out.append((req["req_id"], req["current_state"]))
        elif name in parsed.get("bullets", {}):
            for n, text in enumerate(parsed["bullets"][name], start=1):
                out.append((f"{name} {n}", text))
        elif name in parsed.get("paragraphs", {}):
            paras = parsed["paragraphs"][name]
            if len(paras) == 1:
                out.append((name, paras[0]))
            else:
                for n, text in enumerate(paras, start=1):
                    out.append((f"{name} {n}", text))
        elif name in parsed.get("tables", {}):
            for n, cells in enumerate(parsed["tables"][name], start=1):
                out.append((f"{name} {n}", " | ".join(cells)))
        # 'Evidence' (and any unknown heading) is never rendered.
    return out
