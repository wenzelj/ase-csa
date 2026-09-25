from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChangeRecord:
    edit_id: str
    title: str
    where: str
    action: str
    text: str | None
    why: str
    raw: str
    questions: list[str] = field(default_factory=list)
    note: str = ""  # plain-language summary for the Word comment (**Note:** field)


@dataclass(slots=True)
class EditResult:
    edit_id: str
    status: str
    message: str
    anchor: str | None = None
    comment_id: str | None = None


@dataclass(slots=True)
class ApplySummary:
    status: str
    section: str
    change_file: Path
    docx: Path
    backup: Path | None
    batch_ids: list[str]
    applied: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)
    completed_ids: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    results: list[EditResult] = field(default_factory=list)
    next_edit_id: str | None = None
    validation: dict[str, str] = field(default_factory=dict)
    run_state_path: Path | None = None
    report_updated: bool = False

    @property
    def comment_count(self) -> int:
        return sum(1 for result in self.results if result.comment_id)
