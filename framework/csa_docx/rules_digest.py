"""Short rules digests for the agent stages (answer, writer, author).

A digest holds only the rules one stage acts on, with one line per full reference saying when to open it.
`digest(stage)` returns it and refuses one over 8,192 bytes, so a prompt never grows back into full required reading.

    python3 -m csa_docx.rules_digest <stage> [--bytes]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LIMIT = 8192
STAGES = ("answer", "writer", "author")
DIGESTS = Path(__file__).resolve().parents[2] / "references" / "digests"


def digest_path(stage: str) -> Path:
    if stage not in STAGES:
        raise ValueError(f"unknown digest stage {stage!r}; use one of {', '.join(STAGES)}")
    return DIGESTS / f"{stage}.md"


def digest(stage: str) -> str:
    path = digest_path(stage)
    data = path.read_bytes()
    if len(data) > LIMIT:
        raise ValueError(f"{path.name} is {len(data)} bytes; a digest must be {LIMIT} bytes or less")
    return data.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("--bytes", action="store_true", help="print the size in bytes instead of the text")
    a = ap.parse_args(argv)
    try:
        text = digest(a.stage)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(len(text.encode("utf-8")) if a.bytes else text, end="" if not a.bytes else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
