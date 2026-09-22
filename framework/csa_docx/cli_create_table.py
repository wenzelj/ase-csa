#!/usr/bin/env python3
"""CLI wrapper for :func:`csa_docx.tables.create_table`.

Insert a new table (matching the document's own table style) immediately
after a given paragraph anchor.

Examples
--------

Two-column table with header + 3 data rows after the "Glossary" heading
(``@H16``):

    /opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_create_table.py \
        --docx "01 Current State AS Built/01 Final Version/Current State Assessment - IAMPS.docx" \
        --after @H16 \
        --cols 2 \
        --rows 4 \
        --header "Term,Definition" \
        --row "IAMPS,Integrated Airport Management and Planning System" \
        --row "CSA,Current State Assessment" \
        --row "OT,Operational Technology"

Or pass all rows as a single ``--data`` argument (JSON):

    /opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_create_table.py \
        --docx "..." \
        --after @H16 \
        --cols 2 \
        --data '[["Term","Definition"],["IAMPS","Integrated Airport Management and Planning System"]]'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx import tools  # noqa: E402  (needs sys.path bootstrap above)


def _parse_header(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [cell.strip() for cell in raw.split(",")]


def _parse_row(raw: str) -> list[str]:
    return [cell.strip() for cell in raw.split(",")]


def main() -> int:
    args = parse_args()

    data: list[list[str]] | None = None
    if args.data:
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as exc:
            print(f"error: --data is not valid JSON: {exc}", file=sys.stderr)
            return 1
        if not isinstance(data, list) or any(
            not isinstance(row, list) or any(not isinstance(c, str) for c in row)
            for row in data
        ):
            print(
                "error: --data must be a JSON list of lists of strings",
                file=sys.stderr,
            )
            return 1
    else:
        rows: list[list[str]] = []
        header = _parse_header(args.header)
        if header:
            rows.append(header)
        for raw in args.row or []:
            rows.append(_parse_row(raw))
        if rows:
            data = rows

    result = tools.create_table(
        args.docx,
        after=args.after,
        rows=args.rows,
        cols=args.cols,
        data=data,
        header=args.header is not None or bool(args.row) or bool(args.data),
        backup=not args.no_backup,
    )
    print(json.dumps(result, indent=2))

    if result.get("status") == "ERROR":
        return 1
    if result.get("status") == "BLOCKED":
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert a new table (matching the document's own table style) "
        "immediately after a paragraph anchor.",
    )
    parser.add_argument("--docx", required=True, help="Path to the working .docx.")
    parser.add_argument(
        "--after",
        required=True,
        help="Paragraph anchor to insert the table after. Either a stable-ID "
        "(e.g. @H16) or a live anchor (e.g. P2139#2dbe).",
    )
    parser.add_argument("--cols", type=int, default=2, help="Number of columns (default 2).")
    parser.add_argument(
        "--rows",
        type=int,
        default=None,
        help="Number of rows (including header when --header is given). "
        "Ignored when --data is supplied.",
    )
    parser.add_argument(
        "--header",
        default=None,
        help="Comma-separated header row cells, e.g. 'Term,Definition'. "
        "When supplied, the first row of the table is treated as a header.",
    )
    parser.add_argument(
        "--row",
        action="append",
        default=None,
        help="Comma-separated data row cells. Repeatable. e.g. "
        "--row 'IAMPS,Integrated Airport Management and Planning System'.",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Full table data as a JSON list of lists of strings. "
        "Takes precedence over --header/--row/--rows.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a .bak backup next to the working .docx. "
        "Only use when you have already taken a backup you intend to keep.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
