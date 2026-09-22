#!/usr/bin/env python3
"""Permanent regression harness for the CSA DOCX framework.

Replays every edit in every approved change file against the real
DocxEngineEditor.apply_change() code path, on a disposable scratch copy of
the working DOCX. Unlike a normal cli_apply_section.py run, this does NOT
stop at the first BLOCKED edit within a section - it keeps going, so every
blocker in a section is visible in one pass, not just the first.

Nothing here ever touches the real working DOCX or the real change files:
every write goes to a throwaway directory that is safe to delete.

Usage:
    python3 tools/dry_run_all_sections.py [--sections 1,2,3] [--json OUT.json]

With no --sections, every section that is not already SECTION_COMPLETE in
its run-state file is replayed. Sections already complete are reported from
their run-state instead of being re-replayed (replaying against the
*current*, already-edited working DOCX would misleadingly "block" on their
own already-applied text).

This is meant to be run after every framework change, as the primary
regression gate: did total blocked count go down, and did any
already-passing section regress?
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc  # noqa: E402 (Python <3.11 shim)

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]  # .../framework/csa_docx
VENDOR_DIR = FRAMEWORK_DIR.parent / "vendor"
sys.path.insert(0, str(FRAMEWORK_DIR.parent))
sys.path.insert(0, str(VENDOR_DIR))

from csa_docx.change_parser import parse_change_file  # noqa: E402
from csa_docx.engines.docxengine_adapter import DocxEngineEditor  # noqa: E402
from csa_docx.models import EditResult  # noqa: E402
from csa_docx.run_state import read_completed_ids, state_path  # noqa: E402

# WORKSPACE_ROOT is the connected-folder root ("06 IAMPS"), three levels up
# from this file (.agents/framework/csa_docx/tools/this_file.py).
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
REVIEWS_DIR = (
    WORKSPACE_ROOT
    / "01 Current State AS Built"
    / "7 IAMPS"
    / "01 Final Version"
    / "reviews"
)
WORKING_DOCX = (
    WORKSPACE_ROOT
    / "01 Current State AS Built"
    / "7 IAMPS"
    / "01 Final Version"
    / "Current State Assessment - IAMPS - v1.docx"
)

SECTION_FILES = {
    1: "ChangesCSA_IAMPS_Section1.md",
    2: "ChangesCSA_IAMPS_Section2.md",
    3: "ChangesCSA_IAMPS_Section3.md",
    4: "ChangesCSA_IAMPS_Section4.md",
    5: "ChangesCSA_IAMPS_Section5.md",
    6: "ChangesCSA_IAMPS_Section6.md",
    7: "ChangesCSA_IAMPS_Section7.md",
    8: "ChangesCSA_IAMPS_Section8.md",
    9: "ChangesCSA_IAMPS_Section9.md",
    10: "ChangesCSA_IAMPS_Section10.md",
    11: "ChangesCSA_IAMPS_Section11.md",
    12: "ChangesCSA_IAMPS_Section12.md",
    13: "ChangesCSA_IAMPS_Section13.md",
    14: "ChangesCSA_IAMPS_Section14.md",
    15: "ChangesCSA_IAMPS_Section15.md",
    16: "ChangesCSA_IAMPS_Section16.md",
}


def _section_is_complete(section: int) -> bool:
    state = state_path(WORKSPACE_ROOT, section)
    if not state.exists():
        return False
    text = state.read_text(encoding="utf-8")
    return "- Status: SECTION_COMPLETE" in text


def replay_section(section: int, scratch_dir: Path) -> dict:
    """Replay one section's not-yet-completed edits.

    A section can be *partially* complete (its run-state file has Status
    other than SECTION_COMPLETE but a non-empty "Completed edit IDs" list -
    real work was done and recorded, just not the whole section yet). Those
    already-completed edit IDs are skipped here, exactly like a fully
    SECTION_COMPLETE section is skipped by main(): replaying an
    already-applied edit against the current (already-edited) document
    always "blocks" on its now-superseded anchor text, which is a false
    signal, not a real regression. This was found the hard way on Section 10:
    its run-state showed E-161 through E-165 genuinely APPLIED (comment IDs
    C158-C162 present in the document), but a naive from-scratch replay of
    the whole file reported all five as newly blocked.
    """
    cf = REVIEWS_DIR / SECTION_FILES[section]
    section_label, records = parse_change_file(cf)
    heading = None
    if section_label and " - " in section_label:
        heading = section_label.split(" - ", 1)[1].strip()
    elif section_label:
        heading = section_label.strip()

    already_done = read_completed_ids(state_path(WORKSPACE_ROOT, section))
    records_to_replay = [r for r in records if r.edit_id not in already_done]
    skipped = [r.edit_id for r in records if r.edit_id in already_done]

    scratch_docx = scratch_dir / f"section_{section}.docx"
    shutil.copy(WORKING_DOCX, scratch_docx)
    editor = DocxEngineEditor(scratch_docx, section_heading=heading)

    results = []
    for record in records_to_replay:
        try:
            result = editor.apply_change(record, "Wenzel Joubert", "WJ")
        except Exception as exc:  # noqa: BLE001 - want every failure captured, not raised
            result = EditResult(record.edit_id, "BLOCKED", f"EXCEPTION: {type(exc).__name__}: {exc}")
        results.append({"edit_id": record.edit_id, "status": result.status, "message": result.message})
    scratch_docx.unlink(missing_ok=True)
    return {
        "total": len(records),
        "skipped_already_completed": skipped,
        "applied": sum(1 for r in results if r["status"] == "APPLIED"),
        "blocked": [r for r in results if r["status"] == "BLOCKED"],
        "other": [r for r in results if r["status"] not in ("APPLIED", "BLOCKED")],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", help="Comma-separated section numbers. Default: all not-yet-complete sections.")
    parser.add_argument("--json", help="Also write full per-edit results to this JSON path.")
    parser.add_argument(
        "--include-complete",
        action="store_true",
        help="Also replay sections already marked SECTION_COMPLETE (against the CURRENT working DOCX - "
        "expect false blocks there, since their target text is already gone).",
    )
    args = parser.parse_args()

    if args.sections:
        sections = [int(s) for s in args.sections.split(",")]
    else:
        sections = [s for s in SECTION_FILES if args.include_complete or not _section_is_complete(s)]

    scratch_dir = Path("/tmp/csa_dry_run_scratch")
    scratch_dir.mkdir(parents=True, exist_ok=True)

    section_reports = {}
    reason_counter: Counter[str] = Counter()
    reason_examples: dict[str, list[str]] = defaultdict(list)
    total_edits = total_applied = total_blocked = total_skipped = 0

    for sec in sections:
        report = replay_section(sec, scratch_dir)
        section_reports[sec] = report
        total_edits += report["total"]
        total_applied += report["applied"]
        total_blocked += len(report["blocked"])
        total_skipped += len(report.get("skipped_already_completed", []))
        for r in report["blocked"]:
            norm = re.sub(r"\d+", "N", r["message"])
            reason_counter[norm] += 1
            if len(reason_examples[norm]) < 3:
                reason_examples[norm].append(f"Section {sec} {r['edit_id']}: {r['message']}")
        skipped_note = (
            f", {len(report['skipped_already_completed'])} already-completed (skipped)"
            if report.get("skipped_already_completed")
            else ""
        )
        print(
            f"Section {sec}: {report['total']} edits, {report['applied']} applied, "
            f"{len(report['blocked'])} blocked, {len(report['other'])} other{skipped_note}"
        )

    shutil.rmtree(scratch_dir, ignore_errors=True)

    print()
    if total_edits:
        replayed = total_edits - total_skipped
        if replayed:
            print(
                f"TOTAL: {total_edits} edits ({total_skipped} already completed, skipped; {replayed} replayed), "
                f"{total_applied} applied ({100 * total_applied / replayed:.0f}% of replayed), "
                f"{total_blocked} blocked ({100 * total_blocked / replayed:.0f}% of replayed)"
            )
        else:
            print(f"TOTAL: {total_edits} edits, all already completed and skipped - nothing replayed.")
    print()
    print("Blocker reasons (normalised), most common first:")
    for reason, count in reason_counter.most_common():
        print(f"  {count:4d}  {reason}")
        for ex in reason_examples[reason]:
            print(f"         e.g. {ex}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(section_reports, f, indent=2, default=str)
        print(f"\nFull per-edit results written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
