#!/usr/bin/env python3
"""Manual OOXML bounded range replacement for E-140 (Section 8), authorised by user
("if this is due to non standard disambiguation then just fix the document").

E-140's start anchor 'While the design defines a segmented architecture with
controlled conduits' appears in TWO subsections (8.3.1 Findings and 8.3
Assessment). The end anchor is unique. Disambiguate deterministically: keep the
start candidate whose enclosing same-level heading region actually contains the
unique end anchor (that is the 8.3.1 Findings block), then replace that bounded
range through the end paragraph with the approved two-paragraph text. Reuses the
framework's own primitives, backup, validator, run-state and report writers.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor"))

from csa_docx.ooxml import (
    DocumentEditor,
    _paragraph_heading_level,
    markdown_to_paragraph_texts,
    normalise_text,
    paragraph_text,
)
from csa_docx.docx_package import create_backup, extract_docx
from csa_docx.change_parser import parse_change_file
from csa_docx.models import ApplySummary, ChangeRecord, EditResult
from csa_docx.run_state import read_completed_ids, state_path, write_state
from csa_docx.report_writer import update_changes_report
from csa_docx.validator import validate_docx
from csa_docx.engines.docxengine_adapter import _heading_level

ROOT = Path("/Users/wenzel/Work/ASE/IAMPS/06 IAMPS")
DOCX = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx"
CHANGE_FILE = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section8_E129_E145.md"
SECTION = "8"
EDIT_ID = "E-140"
COMMENT_AUTHOR = "Wenzel Joubert"
COMMENT_INITIALS = "WJ"

START = "While the design defines a segmented architecture with controlled conduits"
END = "Availability of externally hosted services"
EXPECTED_REPLACEMENT_PARAGRAPHS = 2


def find_record(records) -> ChangeRecord:
    for record in records:
        if record.edit_id == EDIT_ID:
            return record
    raise SystemExit(f"{EDIT_ID} not found in change file")


def locate(paras):
    """Return (start_candidates, end_matches) as lists of paragraph objects and their indexes."""
    sn = normalise_text(START)
    en = normalise_text(END)
    starts = [i for i, p in enumerate(paras) if normalise_text(paragraph_text(p)) == sn or normalise_text(paragraph_text(p)).startswith(sn)]
    ends = [i for i, p in enumerate(paras) if normalise_text(paragraph_text(p)) == en or normalise_text(paragraph_text(p)).endswith(en)]
    return starts, ends


def enclosure_level(paras, index):
    """Return (heading_index, level) of nearest preceding heading, or (index, None)."""
    for j in range(index, -1, -1):
        lvl = _paragraph_heading_level(paras[j])
        if lvl is not None:
            return j, lvl
        if j == 0:
            break
    return index, None


def section_end(paras, heading_index, level):
    """Index just before the next same-or-higher level heading."""
    for j in range(heading_index + 1, len(paras)):
        lvl = _paragraph_heading_level(paras[j])
        if lvl is not None and level is not None and lvl <= level:
            return j - 1
    return len(paras) - 1


def choose_start(starts, end_index, paras):
    """Pick the start candidate whose enclosing section region contains the end anchor."""
    valid = []
    reasons = []
    for s in starts:
        h_index, level = enclosure_level(paras, s)
        if level is None:
            reasons.append(f"start@{s}: no enclosing heading")
            continue
        se = section_end(paras, h_index, level)
        # The end anchor must sit strictly inside this section's own body:
        # after the section heading, after the start paragraph, and before
        # the next same-or-higher level heading.
        if h_index < s < end_index <= se:
            valid.append((s, h_index, se))
        else:
            reasons.append(f"start@{s}: region {h_index}..{se} does not contain end@{end_index}")
    return valid, reasons


def main() -> int:
    section_label, records = parse_change_file(CHANGE_FILE)
    record = find_record(records)
    if record.text is None or not str(record.text).strip():
        print("ABORT: E-140 has no approved Text")
        return 3

    # ----------------- dry run -----------------
    pkg0 = extract_docx(DOCX)
    try:
        ed0 = DocumentEditor(pkg0.path("word/document.xml"), section_heading=None)
        paras0 = ed0.paragraphs()
        starts, ends = locate(paras0)
        print(f"dry-run: START candidates={starts}  END matches={ends}")
        if len(ends) != 1:
            print(f"ABORT: end anchor not unique ({len(ends)} matches)")
            return 3
        end_index = ends[0]
        valid, reasons = choose_start(starts, end_index, paras0)
        print("dry-run: start disambiguation:", valid or reasons)
        if len(valid) != 1:
            print(f"ABORT: could not uniquely disambiguate start (valid={valid}; reasons={reasons})")
            return 3
        start_index, h_index, se = valid[0]
        # show enclosing heading text for the record
        print(f"dry-run: enclosing heading[{h_index}] = {paragraph_text(paras0[h_index])!r} -> region ends {se}")
        if not (h_index <= start_index < end_index <= se):
            print("ABORT: boundary order/containment failed")
            return 3
        old_range = paras0[start_index : end_index + 1]
        heading_in = [(j, paragraph_text(p)) for j, p in zip(range(start_index, end_index + 1), old_range) if _paragraph_heading_level(p) is not None]
        print(f"dry-run: range {start_index}..{end_index} ({len(old_range)} paragraphs)")
        for j in range(start_index, end_index + 1):
            print("   ", j, "|", paragraph_text(paras0[j])[:95].replace("\n", " "))
        if heading_in:
            print(f"ABORT: heading inside range: {heading_in}")
            return 3
        texts = markdown_to_paragraph_texts(record.text)
        print("dry-run: replacement paragraphs:", len(texts))
        for t in texts:
            print("   >", t[:95].replace("\n", " "))
        if len(texts) != EXPECTED_REPLACEMENT_PARAGRAPHS:
            print(f"ABORT: expected {EXPECTED_REPLACEMENT_PARAGRAPHS} replacement paragraphs, got {len(texts)}")
            return 3
    finally:
        pkg0.cleanup()

    # ----------------- real run -----------------
    state = state_path(ROOT, SECTION)
    completed_ids = read_completed_ids(state)
    backup = create_backup(DOCX, SECTION)
    print(f"backup: {backup}")

    pkg = extract_docx(DOCX)
    try:
        ed = DocumentEditor(pkg.path("word/document.xml"), section_heading=None)
        paragraphs = ed.paragraphs()
        starts, ends = locate(paragraphs)
        end_index = ends[0] if len(ends) == 1 else None
        if end_index is None:
            raise SystemExit("end anchor not unique on real run")
        valid, _ = choose_start(starts, end_index, paragraphs)
        if len(valid) != 1:
            raise SystemExit(f"start disambiguation not unique on real run: {valid}")
        start_index = valid[0][0]
        old_range = paragraphs[start_index : end_index + 1]
        if any(_paragraph_heading_level(p) is not None for p in old_range):
            raise SystemExit("heading inside range on real run")
        texts = markdown_to_paragraph_texts(record.text)
        comment_id = ed._replace_paragraph_range(old_range, texts, record, COMMENT_AUTHOR, COMMENT_INITIALS, add_new_comment=True)
        ed.save()
        pkg.save(DOCX)
    finally:
        pkg.cleanup()
    print("comment_id:", comment_id)

    validation = validate_docx(DOCX)
    print("validation:", validation)
    failed = (comment_id is None) or any(v != "Pass" for v in validation.values())
    if failed:
        print("FAILED: E-140 not safely applied")
        return 1

    summary = ApplySummary(
        status="PARTIAL_COMPLETE",
        section=SECTION,
        change_file=CHANGE_FILE,
        docx=DOCX,
        backup=backup,
        batch_ids=[EDIT_ID],
        run_state_path=state,
        completed_ids=[r.edit_id for r in records if r.edit_id in completed_ids],
    )
    summary.applied.append(EDIT_ID)
    summary.results.append(
        EditResult(EDIT_ID, "APPLIED",
                   "Manual bounded range replacement (non-standard disambiguation): 8.3.1 Findings paragraph through 'Availability of externally hosted services' replaced with approved two-paragraph conclusion; disambiguated against duplicate sentence in 8.3 Assessment",
                   START, comment_id)
    )
    summary.completed_ids = [r.edit_id for r in records if r.edit_id in (completed_ids | {EDIT_ID})]
    remaining = [r.edit_id for r in records if r.edit_id not in summary.completed_ids]
    summary.next_edit_id = remaining[0] if remaining else None
    summary.validation = validation
    summary.status = "PARTIAL_COMPLETE" if remaining else "SECTION_COMPLETE"
    write_state(state, records, summary)
    update_changes_report(CHANGE_FILE, summary)
    write_state(state, records, summary)
    print("SUMMARY:", summary.status, "| next:", summary.next_edit_id, "| report_updated:", summary.report_updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
