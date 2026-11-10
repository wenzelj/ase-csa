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
SHARED_LIMIT = 2048
COMMON_LIMIT = 6144
ANSWER_CARD_RULES_LIMIT = 20480   # the card rules (prompts/answer) the V1 answer lane adds to its digest (raised from 16384, 2026-11-05)
COMMON_STAGES = ("answer", "draft")   # the card lanes share one file of cross-lane rules
STAGES = ("answer", "writer", "author", "draft")
DIGESTS = Path(__file__).resolve().parents[2] / "references" / "digests"
STYLE_SKILL = Path(__file__).resolve().parents[2] / "skills" / "csa-writing-style" / "SKILL.md"
_PLAIN_START = "<!-- digest:plain-language:start -->"
_PLAIN_END = "<!-- digest:plain-language:end -->"


def digest_path(stage: str) -> Path:
    if stage not in STAGES:
        raise ValueError(f"unknown digest stage {stage!r}; use one of {', '.join(STAGES)}")
    return DIGESTS / f"{stage}.md"


def plain_language() -> str:
    """The shared plain-language rule, read from csa-writing-style/SKILL.md (its single source) for every stage."""
    text = STYLE_SKILL.read_text(encoding="utf-8")
    a, b = text.find(_PLAIN_START), text.find(_PLAIN_END)
    if a < 0 or b < a:
        raise ValueError(f"{STYLE_SKILL} has no {_PLAIN_START} ... {_PLAIN_END} section")
    body = text[a + len(_PLAIN_START):b].strip()
    if len(body.encode("utf-8")) > SHARED_LIMIT:
        raise ValueError(f"the plain-language section is over {SHARED_LIMIT} bytes")
    return body


def digest(stage: str) -> str:
    path = digest_path(stage)
    data = path.read_bytes()
    if len(data) > LIMIT:
        raise ValueError(f"{path.name} is {len(data)} bytes; a digest must be {LIMIT} bytes or less")
    text = data.decode("utf-8").rstrip("\n")
    if stage in COMMON_STAGES:
        common = (DIGESTS / "_shared.md").read_bytes()
        if len(common) > COMMON_LIMIT:
            raise ValueError(f"_shared.md is {len(common)} bytes; it must be {COMMON_LIMIT} bytes or less")
        text += "\n\n" + common.decode("utf-8").strip("\n")
    if stage == "answer":        # the V1 answer lane: the card holds evidence only, its writing rules are the prompts'
        from csa_docx import prompts
        text += "\n\n" + prompts.card_rules(set(prompts.KIND_FILE)).rstrip()
    return text + "\n\n" + plain_language() + "\n"


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
