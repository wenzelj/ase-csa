#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx.change_parser import parse_change_file, select_batch
from csa_docx.docx_package import create_backup, extract_docx
from csa_docx.models import ApplySummary
from csa_docx.ooxml import DocumentEditor
from csa_docx.report_writer import update_changes_report
from csa_docx.run_state import read_completed_ids, state_path, write_state
from csa_docx.validator import validate_docx


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    change_file = Path(args.change_file).resolve()
    docx = Path(args.docx).resolve()
    state = state_path(workspace, args.section)

    section_label, records = parse_change_file(change_file)
    section = args.section or (section_label or "unknown")
    completed_ids = read_completed_ids(state)
    scoped_records = _scope_records(records, args.start_edit_id, args.end_edit_id)
    batch = select_batch(records, completed_ids, args.limit, args.start_edit_id, args.end_edit_id)
    batch_ids = [record.edit_id for record in batch]

    summary = ApplySummary(
        status="PLANNED",
        section=section,
        change_file=change_file,
        docx=docx,
        backup=None,
        batch_ids=batch_ids,
        run_state_path=state,
        completed_ids=[record.edit_id for record in records if record.edit_id in completed_ids],
    )

    if not batch:
        summary.status = "SECTION_COMPLETE"
        summary.validation = validate_docx(docx)
        summary.completed_ids = [record.edit_id for record in records if record.edit_id in completed_ids]
        write_state(state, records, summary)
        update_changes_report(change_file, summary)
        write_state(state, records, summary)
        print_summary(summary)
        return 0

    summary.backup = create_backup(docx, section)
    editor = None
    package = None
    try:
        if args.engine == "docxengine":
            from csa_docx.engines.docxengine_adapter import DocxEngineEditor

            editor = DocxEngineEditor(docx, section_heading=_section_heading(section_label))
        else:
            package = extract_docx(docx)
            editor = DocumentEditor(package.path("word/document.xml"), section_heading=_section_heading(section_label))

        summary.status = "IN_PROGRESS"
        write_state(state, records, summary)
        _apply_batch(editor, batch, summary, args.comment_author, args.comment_initials)
        editor.save()
        if package is not None:
            package.save(docx)
    finally:
        if package is not None:
            package.cleanup()

    done_ids = set(summary.applied + summary.already_applied)
    remaining = [record.edit_id for record in scoped_records if record.edit_id not in (completed_ids | done_ids)]
    if summary.blocked:
        remaining = summary.blocked + [edit_id for edit_id in remaining if edit_id not in summary.blocked]
    summary.completed_ids = [
        record.edit_id for record in records if record.edit_id in (completed_ids | done_ids)
    ]
    summary.next_edit_id = remaining[0] if remaining else None
    summary.validation = validate_docx(docx)
    summary.status = "BLOCKED" if summary.blocked else ("PARTIAL_COMPLETE" if summary.next_edit_id else "SECTION_COMPLETE")

    write_state(state, records, summary)
    update_changes_report(change_file, summary)
    write_state(state, records, summary)
    print_summary(summary)
    return 2 if summary.status == "BLOCKED" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a bounded CSA DOCX change batch.")
    parser.add_argument("--section", required=True)
    parser.add_argument("--change-file", required=True)
    parser.add_argument("--docx", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--start-edit-id")
    parser.add_argument("--end-edit-id")
    parser.add_argument("--comment-author", default="Wenzel Joubert")
    parser.add_argument("--comment-initials", default="WJ")
    parser.add_argument(
        "--engine",
        choices=("legacy", "docxengine"),
        default=os.environ.get("CSA_DOCX_ENGINE", "docxengine"),
        help="DOCX edit engine. Defaults to docxengine; legacy is retained only for explicit fallback.",
    )
    return parser.parse_args()


def _scope_records(records, start_edit_id: str | None, end_edit_id: str | None):
    scoped = records
    if start_edit_id:
        try:
            start_index = next(i for i, rec in enumerate(scoped) if rec.edit_id == start_edit_id)
            scoped = scoped[start_index:]
        except StopIteration:
            return []
    if end_edit_id:
        try:
            end_index = next(i for i, rec in enumerate(scoped) if rec.edit_id == end_edit_id)
            scoped = scoped[: end_index + 1]
        except StopIteration:
            return []
    return scoped


def _section_heading(section_label: str | None) -> str | None:
    if not section_label:
        return None
    if " - " in section_label:
        return section_label.split(" - ", 1)[1].strip()
    return section_label.strip()


def _apply_batch(editor, batch, summary: ApplySummary, author: str, initials: str) -> None:
    for record in batch:
        result = editor.apply_change(record, author, initials)
        summary.results.append(result)
        if result.status == "APPLIED":
            summary.applied.append(record.edit_id)
        elif result.status == "ALREADY_APPLIED":
            summary.already_applied.append(record.edit_id)
        elif result.status == "BLOCKED":
            summary.blocked.append(record.edit_id)
            break
        else:
            summary.unresolved.append(record.edit_id)


def print_summary(summary: ApplySummary) -> None:
    payload = {
        "status": summary.status,
        "section": summary.section,
        "docx": str(summary.docx),
        "backup": str(summary.backup) if summary.backup else None,
        "change_file": str(summary.change_file),
        "batch_ids": summary.batch_ids,
        "applied": summary.applied,
        "already_applied": summary.already_applied,
        "completed_ids": summary.completed_ids,
        "blocked": summary.blocked,
        "unresolved": summary.unresolved,
        "next_edit_id": summary.next_edit_id,
        "validation": summary.validation,
        "run_state": str(summary.run_state_path) if summary.run_state_path else None,
        "report_updated": summary.report_updated,
        "results": [asdict(result) for result in summary.results],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
