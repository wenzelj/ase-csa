#!/usr/bin/env python3
"""Manual OOXML range replacement for E-123 (Section 7), authorised by user.

Replaces the first two paragraphs of Section 7.3.2 (anchor paragraph through
"fallback authentication.") with the two approved replacement paragraphs,
preserving paragraph properties, and attaches the standard approved-change
Word comment. Reuses the framework's editors/validator/report writers so the
result matches framework conventions and run-state/report stay consistent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx.ooxml import (
    DocumentEditor,
    W_NS,
    markdown_to_paragraph_texts,
    normalise_text,
    paragraph_text,
    qn,
)
from csa_docx.docx_package import create_backup, extract_docx
from csa_docx.change_parser import parse_change_file
from csa_docx.models import ApplySummary, ChangeRecord, EditResult
from csa_docx.run_state import read_completed_ids, state_path, write_state
from csa_docx.report_writer import update_changes_report
from csa_docx.validator import validate_docx

ROOT = Path("/Users/wenzel/Work/ASE/IAMPS/06 IAMPS")
DOCX = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx"
CHANGE_FILE = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section7_E112_E128.md"
SECTION = "7"
COMMENT_AUTHOR = "Wenzel Joubert"
COMMENT_INITIALS = "WJ"

ANCHOR_START = "Host-level discovery confirms that all IAMPS servers are domain joined to internal.qr.com.au"
ANCHOR_END = "fallback authentication."


def find_record(records: list[ChangeRecord]) -> ChangeRecord:
    for record in records:
        if record.edit_id == "E-123":
            return record
    raise SystemExit("E-123 not found in change file")


def main() -> int:
    section_label, records = parse_change_file(CHANGE_FILE)
    record = find_record(records)

    # --- dry-run: inspect the target range before touching anything ----------
    pkg0 = extract_docx(DOCX)
    ed0 = DocumentEditor(pkg0.path("word/document.xml"), section_heading="Identity & Authentication")
    paras0 = ed0.paragraphs()
    starts = ed0._matching_paragraphs(ANCHOR_START, "beginning exactly")
    ends = [p for p in paras0 if normalise_text(paragraph_text(p)).endswith(ANCHOR_END.lower())]
    print(f"dry-run: start matches={len(starts)} end matches={len(ends)}")
    if len(starts) != 1 or len(ends) != 1:
        pkg0.cleanup()
        print("ABORT: anchors not unique")
        return 3
    si = paras0.index(starts[0])
    ei = paras0.index(ends[0])
    print(f"dry-run: range {si}..{ei} ({ei - si + 1} paragraphs)")
    for j in range(max(0, si - 2), min(len(paras0), ei + 3)):
        print("  ", j, "|", paragraph_text(paras0[j])[:100].replace("\n", " "))
    if record.text is None:
        pkg0.cleanup()
        print("ABORT: E-123 has no approved Text")
        return 3
    replacement_paragraphs = markdown_to_paragraph_texts(record.text)
    print("dry-run: replacement paragraphs:", len(replacement_paragraphs))
    for r in replacement_paragraphs:
        print("   >", r[:100].replace("\n", " "))
    pkg0.cleanup()
    if len(replacement_paragraphs) != 2:
        print("ABORT: expected exactly 2 approved replacement paragraphs")
        return 3
    if ends[0] is starts[0]:
        print("ABORT: end paragraph is the start paragraph; range ambiguous")
        return 3
    if ei < si:
        print("ABORT: end paragraph precedes start paragraph")
        return 3
    # ensure no heading is in range (this would mean we crossed a subsection)
    from csa_docx.ooxml import _paragraph_heading_level
    for j in range(si, ei + 1):
        lvl = _paragraph_heading_level(paras0[j])
        if lvl is not None:
            print(f"ABORT: heading (level {lvl}) inside range at {j}")
            return 3

    # --- real run ------------------------------------------------------------
    state = state_path(ROOT, SECTION)
    completed_ids = read_completed_ids(state)
    backup = create_backup(DOCX, SECTION)
    print(f"backup: {backup}")

    pkg = extract_docx(DOCX)
    try:
        ed = DocumentEditor(pkg.path("word/document.xml"), section_heading="Identity & Authentication")
        paragraphs = ed.paragraphs()
        starts = ed._matching_paragraphs(ANCHOR_START, "beginning exactly")
        assert len(starts) == 1, "start anchor not unique"
        start = starts[0]
        start_index = paragraphs.index(start)
        end = next(p for p in paragraphs if normalise_text(paragraph_text(p)).endswith(ANCHOR_END.lower()))
        end_index = paragraphs.index(end)
        assert end_index > start_index, "range out of order"
        old_range = paragraphs[start_index : end_index + 1]
        assert all(_paragraph_heading_level(p) is None for p in old_range), "heading inside range"

        texts = markdown_to_paragraph_texts(record.text)
        # use the framework's own range-replacement helper: preserves the first
        # paragraph's pPr as template, preserves bullet markers, removes extras,
        # and attaches the approved-change comment on the first replacement paragraph.
        comment_id = ed._replace_paragraph_range(old_range, texts, record, COMMENT_AUTHOR, COMMENT_INITIALS, add_new_comment=True)
        ed.save()
        pkg.save(DOCX)
    finally:
        pkg.cleanup()
    print("comment_id:", comment_id)

    validation = validate_docx(DOCX)
    print("validation:", validation)
    blocked = comment_id is None
    for key, value in validation.items():
        if value != "Pass":
            blocked = True
    if blocked:
        print("FAILED: E-123 not safely applied")
        return 1

    summary = ApplySummary(
        status="PARTIAL_COMPLETE" if "E-124" not in completed_ids and True else "SECTION_COMPLETE",
        section=SECTION,
        change_file=CHANGE_FILE,
        docx=DOCX,
        backup=backup,
        batch_ids=["E-123"],
        run_state_path=state,
        completed_ids=[r.edit_id for r in records if r.edit_id in completed_ids],
    )
    summary.applied.append("E-123")
    summary.results.append(
        EditResult("E-123", "APPLIED", "Manual OOXML range replacement: first two 7.3.2 paragraphs through 'fallback authentication.' replaced with approved two-paragraph text (framework limitation workaround, user-authorised)", ANCHOR_START, comment_id)
    )
    summary.completed_ids = [r.edit_id for r in records if r.edit_id in (completed_ids | {"E-123"})]
    remaining = [r.edit_id for r in records if r.edit_id not in summary.completed_ids]
    summary.next_edit_id = remaining[0] if remaining else None
    summary.validation = validation
    summary.status = "PARTIAL_COMPLETE" if summary.next_edit_id else "SECTION_COMPLETE"
    write_state(state, records, summary)
    update_changes_report(CHANGE_FILE, summary)
    write_state(state, records, summary)
    print("SUMMARY:", summary.status, "| next:", summary.next_edit_id, "| report_updated:", summary.report_updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
