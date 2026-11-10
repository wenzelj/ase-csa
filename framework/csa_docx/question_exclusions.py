"""Questions the owner removed from the open-questions list, with the reason.

csa-work/draft/question-exclusions.json:  {"excluded": [{"dr_id", "text", "category", "reason", "duplicate_of"}]}

A DR id for a QUESTION: line is content-addressed (section, block and the wording), so a reworded question is a new question and comes back.
A removed question is left out of open-questions.md, gap-check and Discovery Required. Nothing else is changed: the answer sheets, the
evidence matrix and the lead store keep what they hold. Delete the entry to restore the question.
"""

from __future__ import annotations

import json
from pathlib import Path


def path(work: Path) -> Path:
    return Path(work) / "draft" / "question-exclusions.json"


def load(work: Path) -> dict[str, dict]:
    """{dr_id: entry}. A missing file means nothing is removed; a malformed one is an error, never a silent restore."""
    p = path(work)
    if not p.is_file():
        return {}
    try:
        rows = json.loads(p.read_text(encoding="utf-8")).get("excluded", [])
    except (ValueError, AttributeError) as error:
        raise ValueError(f"malformed question exclusions at {p}: {error}") from error
    return {str(r["dr_id"]): r for r in rows if isinstance(r, dict) and r.get("dr_id")}
