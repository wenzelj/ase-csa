"""Stable structural identifiers for DOCX paragraphs and table rows.

Every paragraph and table row in the document is assigned a deterministic ID
derived from its position in the heading hierarchy:

    @H2.1.4-P2       second body paragraph under the 4th H3 under the 2nd H1
    @H2.1.4-T1-R2    second row of the first table under that heading

Section numbers are assigned by ordinal position within the heading hierarchy:
the 1st H1 is "1", the 2nd H1 is "2", etc. Under each H1, the 1st H2 is
"1.1", the 2nd H2 is "1.2", etc. This works regardless of whether the
heading text contains explicit numbers.

The ID is structural, not text-based, so it is immune to the document drift
that causes "Anchor match count was 0/N" blocks. Prior edits that change
paragraph text do not change the structural layout, so IDs remain valid
across runs as long as the heading hierarchy is intact.

Usage in change files:
    **Where:** `@H2.1.4-P1`
    **Where:** `@H2.1.4-T1-R2`

The framework resolves ``@``-prefixed IDs before falling back to text
matching, so existing change files that use text anchors continue to work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StableId:
    kind: str            # "P" (paragraph) | "T" (table row)
    section_path: str    # e.g. "2.1.4"
    ordinal: int = 1     # 1-based ordinal

    def __str__(self) -> str:
        return f"@H{self.section_path}-{self.kind}{self.ordinal}"


_ID_RE = re.compile(r"@(H(\d+(?:\.\d+)*)(?:-(P|T)(\d+))?)")


def extract_stable_id(where: str) -> StableId | None:
    match = _ID_RE.search(where)
    if not match or not match.group(2) or not match.group(3):
        return None
    return StableId(
        kind=match.group(3),
        section_path=match.group(2),
        ordinal=int(match.group(4) or 1),
    )


def _heading_level(paragraph) -> int | None:
    style = getattr(paragraph, "style", "") or ""
    m = re.match(r"Heading([1-9])", style)
    return int(m.group(1)) if m else None


def build_id_map(paragraphs: list) -> dict[str, int]:
    """Map stable ID string -> paragraph index.

    Assigns section numbers by ordinal position within the heading hierarchy.
    The 1st H1 = "1", the 2nd H1 = "2". Under H1 "2", the 1st H2 = "2.1",
    the 2nd H2 = "2.2". Body paragraphs under a heading get P1, P2, ...
    Table rows get T1-R1, T1-R2, ...
    """
    id_map: dict[str, int] = {}
    # ordinal counter per heading level: {1: 0, 2: 0, 3: 0}
    ordinals: dict[int, int] = {}
    # path components: ["2", "1", "4"]
    path: list[str] = []
    body_counter = 0
    current_table_anchor: str | None = None
    table_row_counter = 0
    table_ordinal = 0

    for index, paragraph in enumerate(paragraphs):
        level = _heading_level(paragraph)

        if level is not None:
            # Increment the ordinal for this level
            ordinals[level] = ordinals.get(level, 0) + 1
            # Reset deeper levels
            for deeper in list(ordinals):
                if deeper > level:
                    del ordinals[deeper]
            # Build the path. Headings may skip levels (e.g. an H2 that
            # directly follows an H1 with no H2 in between is still "1.1");
            # any missing intermediate level takes the next ordinal so the
            # path stays unique and deterministic for the whole document.
            path = [str(ordinals.get(lvl, 0) + (1 if lvl == level else 1)) for lvl in range(1, level + 1)]
            section_path = ".".join(path)
            id_map[f"@H{section_path}"] = index

            # Reset body/table counters for this section
            body_counter = 0
            current_table_anchor = None
            table_row_counter = 0
            table_ordinal = 0
            continue

        # Body paragraph or table row
        table_anchor = getattr(paragraph, "table_anchor", None)
        section_path = ".".join(path) if path else "0"

        if table_anchor:
            if table_anchor != current_table_anchor:
                current_table_anchor = table_anchor
                table_ordinal += 1
                table_row_counter = 0
            else:
                table_row_counter += 1
            id_map[f"@H{section_path}-T{table_ordinal}-R{table_row_counter + 1}"] = index
        else:
            body_counter += 1
            id_map[f"@H{section_path}-P{body_counter}"] = index

    return id_map


def generate_manifest(paragraphs: list) -> list[dict]:
    """Generate a human-readable ID manifest for the document."""
    entries: list[dict] = []
    ordinals: dict[int, int] = {}
    path: list[str] = []
    body_counter = 0
    current_table_anchor: str | None = None
    table_row_counter = 0
    table_ordinal = 0

    for paragraph in paragraphs:
        level = _heading_level(paragraph)
        text_preview = (getattr(paragraph, "text", "") or "").replace("\n", " ")[:120]
        anchor = getattr(paragraph, "anchor", None)

        if level is not None:
            ordinals[level] = ordinals.get(level, 0) + 1
            for deeper in list(ordinals):
                if deeper > level:
                    del ordinals[deeper]
            path = [str(ordinals.get(lvl, 0) + (1 if lvl == level else 1)) for lvl in range(1, level + 1)]
            section_path = ".".join(path)
            entries.append({
                "id": f"@H{section_path}",
                "kind": "heading",
                "level": level,
                "section_path": section_path,
                "text": text_preview,
                "anchor": anchor,
            })
            body_counter = 0
            current_table_anchor = None
            table_row_counter = 0
            table_ordinal = 0
            continue

        section_path = ".".join(path) if path else "0"
        table_anchor = getattr(paragraph, "table_anchor", None)

        if table_anchor:
            if table_anchor != current_table_anchor:
                current_table_anchor = table_anchor
                table_ordinal += 1
                table_row_counter = 0
            else:
                table_row_counter += 1
            entries.append({
                "id": f"@H{section_path}-T{table_ordinal}-R{table_row_counter + 1}",
                "kind": "table_row",
                "section_path": section_path,
                "text": text_preview,
                "anchor": anchor,
            })
        else:
            body_counter += 1
            entries.append({
                "id": f"@H{section_path}-P{body_counter}",
                "kind": "paragraph",
                "section_path": section_path,
                "text": text_preview,
                "anchor": anchor,
            })

    return entries
