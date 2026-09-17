#!/usr/bin/env python3
"""Manual OOXML bounded range replacement for E-147 (Section 9), authorised by user
("Do manually repair and update the framework to handle similar future issues").

E-147's anchor 'This indicates:' (exactly, with colon) matches 3 paragraphs across
the document (sections 7, 9, 12). The 9.1 target is the one under 'Time
Synchronization > Design and functionality expected'. Disambiguate deterministically
by choosing the candidate whose enclosing same-level heading region also contains
the unique end anchor 'Consistent time across domains is required for system
operation'. Then replace that bounded range (start through end, inclusive) with
the approved 4 paragraphs (intro sentence + 3 bullets), preserving styles.
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
from csa_docx.models import ApplySummary, EditResult
from csa_docx.run_state import read_completed_ids, state_path, write_state
from csa_docx.report_writer import update_changes_report
from csa_docx.validator import validate_docx

ROOT = Path("/Users/wenzel/Work/ASE/IAMPS/06 IAMPS")
DOCX = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx"
CHANGE_FILE = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section9_E146_E160.md"
SECTION = "9"
EDIT_ID = "E-147"
COMMENT_AUTHOR = "Wenzel Joubert"
COMMENT_INITIALS = "WJ"

START = "This indicates:"
END = "Consistent time across domains is required for system operation"
EXPECTED_REPLACEMENT_PARAGRAPHS = 4


def find_record(records):
    for record in records:
        if record.edit_id == EDIT_ID:
            return record
    raise SystemExit(f"{EDIT_ID} not found in change file")


def enclosure_level(paras, index):
    for j in range(index, -1, -1):
        lvl = _paragraph_heading_level(paras[j])
        if lvl is not None:
            return j, lvl
        if j == 0:
            break
    return index, None


def section_end(paras, heading_index, level):
    for j in range(heading_index + 1, len(paras)):
        lvl = _paragraph_heading_level(paras[j])
        if lvl is not None and level is not None and lvl <= level:
            return j - 1
    return len(paras) - 1


def locate(paras):
    sn = normalise_text(START)
    en = normalise_text(END)
    starts = [i for i, p in enumerate(paras) if normalise_text(paragraph_text(p)) == sn or normalise_text(paragraph_text(p)).startswith(sn)]
    ends = [i for i, p in enumerate(paras) if normalise_text(paragraph_text(p)) == en or normalise_text(paragraph_text(p)).endswith(en)]
    return starts, ends


def choose_start(starts, end_index, paras):
    valid, reasons = [], []
    for s in starts:
        h_idx, level = enclosure_level(paras, s)
        if level is None:
            reasons.append(f"@{s}: no enclosing heading"); continue
        se = section_end(paras, h_idx, level)
        if h_idx < s < end_index <= se:
            valid.append((s, h_idx, se))
        else:
            reasons.append(f"@{s}: region {h_idx}..{se} does not contain end@{end_index}")
    return valid, reasons


def main():
    section_label, records = parse_change_file(CHANGE_FILE)
    record = find_record(records)
    if record.text is None or not str(record.text).strip():
        print("ABORT: E-147 has no approved Text"); return 3

    # ---------- dry run ----------
    pkg0 = extract_docx(DOCX)
    try:
        ed0 = DocumentEditor(pkg0.path("word/document.xml"), section_heading=None)
        paras0 = ed0.paragraphs()
        starts, ends = locate(paras0)
        print(f"dry-run: START candidates={starts}  END matches={ends}")
        if len(ends) != 1:
            print(f"ABORT: end anchor not unique ({len(ends)} matches)"); return 3
        end_index = ends[0]
        valid, reasons = choose_start(starts, end_index, paras0)
        print(f"dry-run: disambiguated={valid if valid else reasons}")
        if len(valid) != 1:
            print(f"ABORT: {len(valid)} candidates (expected 1)"); return 3
        si, hi, se = valid[0]
        if not (hi < si < end_index <= se):
            print("ABORT: boundary containment failed"); return 3
        print(f"dry-run: region starts at {si}, end at {end_index} ({end_index-si+1} paragraphs)")
        for j in range(max(0, si-1), min(len(paras0), end_index+2)):
            print(f"   {j} | {paragraph_text(paras0[j])[:90]!r}")
        old_range = paras0[si : end_index + 1]
        if any(_paragraph_heading_level(p) is not None for p in old_range):
            print("ABORT: heading inside range"); return 3
        texts = markdown_to_paragraph_texts(record.text)
        print(f"dry-run: replacement paragraphs={len(texts)}")
        for t in texts:
            print(f"   > {t[:90]!r}")
        if len(texts) != EXPECTED_REPLACEMENT_PARAGRAPHS:
            print(f"ABORT: expected {EXPECTED_REPLACEMENT_PARAGRAPHS} got {len(texts)}"); return 3
    finally:
        pkg0.cleanup()

    # ---------- real run ----------
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
        si = valid[0][0]
        old_range = paragraphs[si : end_index + 1]
        if any(_paragraph_heading_level(p) is not None for p in old_range):
            raise SystemExit("heading inside range on real run")
        texts = markdown_to_paragraph_texts(record.text)
        add_new_comment = True
        # E-147 mixes a plain intro with bullets: preserve each slot's own pPr
        # (do NOT stamp the intro's pPr onto the bullets). Map old range to the
        # new lines, keep bullet numbering where the replacement line is a bullet.
        parent_map = ed._parent_map()
        comment_id = None
        for offset, text in enumerate(texts):
            paragraph = old_range[offset]
            is_bullet = text.startswith("- ")
            ed._set_paragraph_text(paragraph, text, preserve_list=is_bullet)
            if add_new_comment and offset == 0:
                comment_id = ed.add_comment(paragraph, record, COMMENT_AUTHOR, COMMENT_INITIALS)
        for paragraph in old_range[len(texts):]:
            parent = parent_map[paragraph]
            parent.remove(paragraph)
        ed.save()
        pkg.save(DOCX)
    finally:
        pkg.cleanup()
    print("comment_id:", comment_id)

    validation = validate_docx(DOCX)
    print("validation:", validation)
    failed = (comment_id is None) or any(v != "Pass" for v in validation.values())
    if failed:
        print("FAILED: E-147 not safely applied"); return 1

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
                   "Manual OOXML range replacement (non-standard disambiguation): Section 9.1 'This indicates:' + 4 bullets replaced with approved 'The design documentation indicates that:' + 3 bullets; disambiguated against duplicate 'This indicates:' in Section 7 and Section 12",
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
