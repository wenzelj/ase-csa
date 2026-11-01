"""Classify a step run's log into a short list of grouped problems.

Pure function: no file or network access. A run can print dozens of identical failures; this turns the raw
output into distinct problems with counts so the page can show them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))
from csa_docx import leads as lead_store

MAX_GROUPS = 25
SAMPLE_CHARS = 300
WITHHELD = "[withheld: looked like a credential]"

_TRACEBACK = "Traceback (most recent call last):"
_CLI_ERROR = re.compile(r"^[\w.\-/ ]+: error: (.+)$")
_CSA_START = ("csa:", "Error:", "ERROR:")
_CSA_WORDS = ("error", "failed", "cannot", "could not", "not found", "refused")
_NO_TERMINAL = "csa: no terminal here, so the agent runs headless (no interactive UI)"
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_ABS_PATH = re.compile(r"(?<![\w.~])/(?:[^\s'\"/:]+/)+([^\s'\"/:]+)")
_DIGITS = re.compile(r"\d+")


def _normalise(text: str) -> str:
    text = _QUOTED.sub("'…'", text.strip())
    text = _ABS_PATH.sub(r"\1", text)
    text = _DIGITS.sub("N", text)
    return re.sub(r"\s+", " ", text)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _sample(text: str) -> str:
    text = text[:SAMPLE_CHARS]
    if lead_store._looks_secret(text):
        return WITHHELD
    return text


def classify_log(text: str) -> list[dict[str, Any]]:
    """Return grouped problems: {kind, signature, count, first_line, last_line, sample}."""
    if not text:
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    partial = len(lines) - 1 if lines and lines[-1] != "" else -1  # last line still being written
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, signature: str, line_no: int, sample: str) -> None:
        group = groups.get((kind, signature))
        if group is None:
            groups[(kind, signature)] = {
                "kind": kind, "signature": signature, "count": 1,
                "first_line": line_no, "last_line": line_no, "sample": _sample(sample),
            }
            return
        group["count"] += 1
        group["first_line"] = min(group["first_line"], line_no)
        group["last_line"] = max(group["last_line"], line_no)

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == _TRACEBACK:
            base = _indent(line)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base):
                j += 1
            if j < len(lines) and j != partial:
                block = "\n".join(lines[i:j + 1])
                add("traceback", _normalise(lines[j]), i + 1, block)
                i = j + 1
            else:
                i = len(lines)  # cut off before its final line: not counted
            continue
        stripped = line.strip()
        number = i + 1
        if _CLI_ERROR.match(line):
            add("cli_error", _normalise(line), number, stripped)
        elif stripped == _NO_TERMINAL:
            pass
        elif line.startswith(_CSA_START) and any(w in line.lower() for w in _CSA_WORDS):
            add("csa_error", _normalise(line), number, stripped)
        elif "hit(s) skipped" in line or "hit(s) withheld" in line:
            add("skipped", _normalise(line), number, stripped)
        i += 1

    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["first_line"]))
    return ordered[:MAX_GROUPS]
