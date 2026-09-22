from __future__ import annotations

from pathlib import Path

from .models import ApplySummary, ChangeRecord


def state_path(base_dir: Path, section: str) -> Path:
    # The run-state lives in a ``run-state`` directory beside the working
    # DOCX (decision DECISION-002, 2026-09-21). ``base_dir`` must be the folder that
    # contains the working DOCX (``01 Current State AS Built/01 Final
    # Version``), NOT the workspace root - callers pass ``docx.parent``.
    return base_dir / "run-state" / f"current-state-assessment-document-section-{section}.md"


def read_completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- Completed edit IDs:"):
            value = line.split(":", 1)[1].strip()
            completed.update(part.strip() for part in value.split(",") if part.strip() and part.strip() != "None")
    return completed


def write_state(path: Path, records: list[ChangeRecord], summary: ApplySummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inventory = ", ".join(record.edit_id for record in records) or "None"
    completed_ids = summary.completed_ids or _ordered_unique(summary.applied + summary.already_applied)
    content = f"""# Current State Assessment Document Run State

- Section: {summary.section}
- Status: {summary.status}
- Change file: {summary.change_file}
- Working DOCX: {summary.docx}
- Backup: {summary.backup or "None"}
- Full edit inventory: {inventory}
- Current iteration edit IDs: {", ".join(summary.batch_ids) or "None"}
- Completed edit IDs: {", ".join(completed_ids) or "None"}
- Already applied edit IDs: {", ".join(summary.already_applied) or "None"}
- Blocked edit IDs: {", ".join(summary.blocked) or "None"}
- Unresolved edit IDs: {", ".join(summary.unresolved) or "None"}
- Skipped edit IDs: {", ".join(summary.skipped) or "None"}
- Next edit ID: {summary.next_edit_id or "None"}
- Report updated: {"Yes" if summary.report_updated else "No"}

## Validation Evidence

"""
    for key, value in sorted(summary.validation.items()):
        content += f"- {key}: {value}\n"

    content += "\n## Edit Results\n\n"
    for result in summary.results:
        content += f"- {result.edit_id}: {result.status} - {result.message}"
        if result.comment_id:
            content += f" (comment ID {result.comment_id})"
        content += "\n"

    path.write_text(content, encoding="utf-8")


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
