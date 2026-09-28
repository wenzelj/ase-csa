#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx import tools


def main() -> int:
    args = parse_args()

    if args.dump_ids:
        from csa_docx.stable_ids import generate_manifest
        try:
            from csa_docx.engines.docxengine_adapter import DocxEngineEditor
        except ImportError as exc:
            print(f"error: docxengine unavailable: {exc}", file=sys.stderr)
            return 1
        editor = DocxEngineEditor(Path(args.docx), section_heading=args.section)
        paragraphs = editor.paragraphs_with_table_rows()
        manifest = generate_manifest(paragraphs)
        print(json.dumps(manifest, indent=2))
        return 0

    result = tools.apply_next_batch(
        section=args.section,
        limit=args.limit,
        workspace=args.workspace,
        change_file=args.change_file,
        docx=args.docx,
        start_edit_id=args.start_edit_id,
        end_edit_id=args.end_edit_id,
        comment_author=args.comment_author,
        comment_initials=args.comment_initials,
        engine=args.engine,
        track_changes=args.track_changes,
    )
    print(json.dumps(result, indent=2))
    if result.get("status") == "ERROR":
        return 1
    return 2 if result.get("status") == "BLOCKED" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a bounded CSA DOCX change batch.")
    parser.add_argument("--section", required=True)
    parser.add_argument(
        "--dump-ids",
        action="store_true",
        help="Dump the stable ID manifest for the document and exit. "
             "Prints one JSON entry per paragraph/table-row with its ID, "
             "section path, text preview, and DocxEngine anchor.",
    )
    parser.add_argument("--change-file")
    parser.add_argument("--docx", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--limit", type=int, default=2)
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
    track_changes_group = parser.add_mutually_exclusive_group()
    track_changes_group.add_argument(
        "--track-changes",
        dest="track_changes",
        action="store_true",
        help="Apply edits as Word tracked changes (default). Old and new content both stay in the "
        "document until a human accepts/rejects them in Word, or the Phase 3 cleanup agent runs "
        "docx_revision accept_all after Phase 2 review sign-off. See framework-robustness-plan.md §4.",
    )
    track_changes_group.add_argument(
        "--no-track-changes",
        dest="track_changes",
        action="store_false",
        help="Apply edits destructively (old framework behaviour, pre-Direction-B) - old content is "
        "removed immediately, no accept/reject step. Only the docxengine engine supports tracked "
        "changes at all, so this flag has no effect with --engine legacy.",
    )
    parser.set_defaults(track_changes=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
