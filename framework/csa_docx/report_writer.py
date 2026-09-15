from __future__ import annotations

from pathlib import Path

from .models import ApplySummary

REPORT_HEADING = "## Changes Report"


def update_changes_report(change_file: Path, summary: ApplySummary) -> None:
    original = change_file.read_text(encoding="utf-8")
    report = build_changes_report(summary)
    if REPORT_HEADING in original:
        before = original.split(REPORT_HEADING, 1)[0].rstrip()
        updated = f"{before}\n\n{REPORT_HEADING}\n\n{report}\n"
    else:
        updated = f"{original.rstrip()}\n\n{REPORT_HEADING}\n\n{report}\n"
    change_file.write_text(updated, encoding="utf-8")
    summary.report_updated = True


def build_changes_report(summary: ApplySummary) -> str:
    lines = [
        f"Status: {summary.status}",
        "",
        f"Section: {summary.section}",
        "",
        "Working document",
        str(summary.docx),
        "",
        "Change file",
        str(summary.change_file),
        "",
        "Current iteration edit IDs",
        ", ".join(summary.batch_ids) or "None",
        "",
        "Edits",
        f"Applied: {', '.join(summary.completed_ids or summary.applied) or 'None'}",
        f"Already applied: {', '.join(summary.already_applied) or 'None'}",
        f"Unresolved: {', '.join(summary.unresolved) or 'None'}",
        f"Blocked: {', '.join(summary.blocked) or 'None'}",
        f"Skipped: {', '.join(summary.skipped) or 'None'}",
        f"Next edit ID: {summary.next_edit_id or 'None'}",
        "",
        "Comments",
        f"Number of Word comments added: {summary.comment_count}",
        "",
        "Validation",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(summary.validation.items())) if summary.validation else lines.append("- Not run")
    lines.extend([
        "",
        "Saved",
        str(summary.docx),
        "",
        "Backup",
        str(summary.backup or "None"),
        "",
        "Run state",
        str(summary.run_state_path or "None"),
        "",
        "Detailed edit results",
    ])
    for result in summary.results:
        comment = f"; comment ID {result.comment_id}" if result.comment_id else ""
        lines.append(f"- {result.edit_id}: {result.status} - {result.message}{comment}")
    return "\n".join(lines)
