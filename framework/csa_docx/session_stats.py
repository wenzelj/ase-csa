"""What a Codex exec session read: commands, output bytes, tokens and the files read most.

A log block starts with a line `exec`; the command follows, then a status line (` succeeded in 0ms:`,
` exited 1 in 3ms:`), then its output, up to the next `codex`, `exec`, `user` or `thinking` line.

    python3 -m csa_docx.session_stats <log> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import defaultdict
from pathlib import Path

_END = {"codex", "exec", "user", "thinking"}
_STATUS = re.compile(r"\b(succeeded|exited \d+|failed|timed out)\b.* in \d+(\.\d+)?m?s:\s*$")
_TOKENS = re.compile(r"tokens used\D{0,3}([\d,]+)?", re.I)
_READERS = {"cat", "head", "tail", "sed", "nl", "less"}


def _read_files(command: str) -> list[str]:
    """Files named by a cat / sed -n / head / tail / nl command (each command of a `cd x && ...` chain)."""
    try:
        outer = shlex.split(command)
    except ValueError:
        return []
    if len(outer) >= 3 and outer[1] in ("-lc", "-c"):
        command = outer[2]
    files: list[str] = []
    for part in re.split(r"&&|;|\|\|", command):
        try:
            toks = shlex.split(part.split("|")[0])
        except ValueError:
            continue
        if not toks or toks[0] not in _READERS:
            continue
        reader, args, i, script_seen = toks[0], toks[1:], 0, False
        while i < len(args):
            t = args[i]
            if t == "-n" and reader in ("head", "tail"):
                i += 1                                          # the count after -n
            elif t in ("-e", "-f"):
                i += 1
                script_seen = True
            elif t.startswith("-") and len(t) > 1:
                pass
            elif reader == "sed" and not script_seen:
                script_seen = True                              # the sed script, e.g. 1,80p
            elif reader in ("head", "tail") and re.fullmatch(r"\d+", t):
                pass
            else:
                files.append(t)
            i += 1
    return files


def stats(log: Path) -> dict:
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    commands, out_bytes, tokens = 0, 0, None
    reads: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    i = 0
    while i < len(lines):
        m = _TOKENS.search(lines[i])
        if m and lines[i].strip().lower().startswith("tokens used"):
            digits = m.group(1) or (lines[i + 1].strip() if i + 1 < len(lines) else "")
            digits = digits.replace(",", "")
            if digits.isdigit():
                tokens = int(digits)
        if lines[i].strip() != "exec":
            i += 1
            continue
        commands += 1
        j = i + 1
        header: list[str] = []
        while j < len(lines) and not _STATUS.search(lines[j]) and lines[j].strip() not in _END:
            header.append(lines[j])
            j += 1
        if j < len(lines) and _STATUS.search(lines[j]):
            header.append(_STATUS.sub("", lines[j]))               # the status may share the command's last line
            body_start = j + 1
        else:
            body_start = j
        k = body_start
        while k < len(lines) and lines[k].strip() not in _END and not lines[k].lstrip().lower().startswith("tokens used"):
            k += 1
        size = sum(len(x.encode("utf-8")) + 1 for x in lines[body_start:k])
        out_bytes += size
        files = _read_files("\n".join(header))
        for f in files:
            reads[f][0] += 1
            reads[f][1] += size // len(files)
        i = k
    top = sorted(reads.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:10]
    return {"commands": commands, "output_bytes": out_bytes, "tokens_used": tokens,
            "top_files": [{"file": f, "reads": c, "bytes": b} for f, (c, b) in top]}


def timing_fields(stage: str, st: dict) -> dict:
    """The keys `timing.json` and the fleet summary carry for one stage."""
    return {f"{stage}_read_kb": round(st["output_bytes"] / 1024, 1), f"{stage}_commands": st["commands"],
            f"{stage}_tokens": st["tokens_used"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        st = stats(a.log)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        print(f"{st['commands']} commands, {st['output_bytes'] / 1024:.1f} KB read, tokens {st['tokens_used']}")
        for t in st["top_files"]:
            print(f"  {t['reads']}x {t['bytes'] / 1024:.1f} KB  {t['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
