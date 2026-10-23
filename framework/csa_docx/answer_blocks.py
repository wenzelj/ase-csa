"""Block-level work on an answer sheet, so a failed check costs only the blocks that failed.

An answer sheet is a run of blocks (`## B1 ...`, `## C1 ...`, `## F1 Analysis frame`). The framework's checks name
the block each error belongs to, so a sheet that fails is not thrown away:

* ``failing``  the blocks an error names (``*`` when an error belongs to no block: the whole sheet must be redone)
* ``focus``    a smaller card for a fix round: the evidence pack keeps only the blocks being rewritten
* ``merge``    the agent writes only the requested blocks to a patch sheet; the framework copies them into the
               sheet, so a block that already passed can never change in a fix round
* ``wip``      a sheet that has not passed yet is kept as work in progress (``cards/<KEY>.wip.json``: what it was
               built from and which blocks failed), so the next run resumes it instead of starting again

    python3 -m csa_docx.answer_blocks merge <sheet> --patch <patch.md> --only B1,B3 [--json]
    python3 -m csa_docx.answer_blocks focus <card.md> --only B1,B3 --out <focus.md>
    python3 -m csa_docx.answer_blocks wip-check <sheet> --card <card.json> --matrix <csv> [--hosts <csv>]
    python3 -m csa_docx.answer_blocks wip-write <sheet> --card <card.json> --matrix <csv> [--hosts <csv>] --failed B1,B3 --codes X,Y
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HEAD = re.compile(r"^##\s+([BCF]\d+)\b[^\n]*$", re.M)
WHOLE = "*"


# ---------------------------------------------------------------- split / merge

def split(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(text before the first block, [(block id, block text including its heading)]), in sheet order."""
    marks = list(_HEAD.finditer(text))
    if not marks:
        return text, []
    head = text[: marks[0].start()]
    blocks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        blocks.append((m.group(1).upper(), text[m.start(): end].rstrip() + "\n"))
    return head, blocks


def merge_text(base: str, patch: str, only: set[str]) -> dict:
    """Blocks in ``only`` come from the patch, every other block stays as in the base. A requested block the patch
    does not have keeps its base text (reported as missing); a patch block that was not requested is ignored."""
    only = {x.upper() for x in only}
    head, base_blocks = split(base)
    _, patch_blocks = split(patch)
    new = {}
    for bid, body in patch_blocks:
        if bid in only and bid not in new:
            new[bid] = body
    out, merged, seen = [], [], set()
    for bid, body in base_blocks:
        if bid in seen:
            continue
        seen.add(bid)
        if bid in new:
            out.append(new[bid])
            merged.append(bid)
        else:
            out.append(body)
    added = [bid for bid in sorted(new, key=_order) if bid not in seen]      # a block the base lacked
    frame = [b for b in added if b.startswith("F")]
    for bid in [b for b in added if not b.startswith("F")]:
        # before the analysis frame when the base has one: F1 stays last
        fpos = next((i for i, b in enumerate(out) if _HEAD.match(b) and _HEAD.match(b).group(1).upper().startswith("F")), None)
        if fpos is None:
            out.append(new[bid])
        else:
            out.insert(fpos, new[bid])
    for bid in frame:
        out.append(new[bid])
    text = (head.rstrip() + "\n\n" if head.strip() else "") + "\n".join(b.rstrip() + "\n" for b in out)
    return {"text": text, "merged": merged, "added": added,
            "missing": sorted(only - set(new), key=_order),
            "ignored": sorted({b for b, _ in patch_blocks} - only, key=_order)}


def _order(bid: str) -> tuple[int, int]:
    return ("BCF".index(bid[0]) if bid[:1] in "BCF" else 9, int(re.sub(r"\D", "", bid) or 0))


# ---------------------------------------------------------------- which blocks failed

def failing(findings: list[dict], level: str = "ERROR") -> set[str]:
    """Blocks named by the errors. An error that names no block (other than a missing analysis frame) means the
    sheet as a whole is wrong: ``{"*"}``."""
    out: set[str] = set()
    for f in findings:
        if f.get("level") != level:
            continue
        q = (f.get("question") or "").strip().upper()
        if not q:
            if f.get("code") == "FRAME_UNCOVERED":
                out.add("F1")
            else:
                out.add(WHOLE)
            continue
        out.add(q if re.fullmatch(r"[BCF]\d+", q) else WHOLE)
    return out


# ---------------------------------------------------------------- focused card for a fix round

def focus(card_md: str, only: set[str]) -> str:
    """The card with the evidence pack cut to the blocks being rewritten. Everything else (questions, host register,
    analysis frame, rules, examples) stays: the agent needs it to write a block that fits the rest of the sheet."""
    only = {x.upper() for x in only}
    lines = card_md.splitlines(keepends=True)
    out, in_pack, skip = [], False, False
    for line in lines:
        if line.startswith("## "):
            in_pack = line.strip().lower().startswith("## evidence pack")
            skip = False
        elif in_pack and line.startswith("### "):
            m = re.match(r"###\s+([BCF]\d+)\b", line)
            skip = bool(m) and m.group(1).upper() not in only
        if not skip:
            out.append(line)
    note = ("> Fix round: rewrite only " + ", ".join(sorted(only, key=_order)) +
            ". The evidence pack below holds only those blocks; the other blocks already pass and are not shown.\n\n")
    text = "".join(out)
    first = text.find("\n## ")
    return text[: first + 1] + note + text[first + 1:] if first >= 0 else note + text


# ---------------------------------------------------------------- work in progress

def wip_path(sheet: Path) -> Path:
    sheet = Path(sheet)
    name = sheet.name[: -len(".answer.md")] if sheet.name.endswith(".answer.md") else sheet.stem
    return sheet.with_name(f"{name}.wip.json")


def wip_write(sheet: Path, fp: dict, failed: list[str], codes: list[str]) -> Path:
    from csa_docx import answer_cache
    path = wip_path(sheet)
    data = {"fingerprint": fp, "sheet_sha256": answer_cache._file_sha(Path(sheet)),
            "failed": sorted(set(failed), key=_order), "codes": sorted(set(codes)),
            "written": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def wip_check(sheet: Path, fp: dict) -> dict:
    """RESUME (with "changed": blocks whose evidence changed since the sheet was kept, and "failed"), STALE (the card's
    questions or the host register changed: answer from scratch) or NONE (nothing to resume)."""
    sheet, path = Path(sheet), wip_path(sheet)
    if not sheet.is_file() or not path.is_file():
        return {"status": "NONE", "changed": [], "failed": []}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        old = saved["fingerprint"]
    except (OSError, ValueError, KeyError):
        return {"status": "NONE", "changed": [], "failed": []}
    old_q, new_q = old.get("questions", {}), fp.get("questions", {})
    if set(old_q) != set(new_q):
        return {"status": "STALE", "changed": [], "failed": [], "reason": "the card's questions changed"}
    if old.get("hosts", "") != fp.get("hosts", ""):
        return {"status": "STALE", "changed": [], "failed": [], "reason": "hosts.csv changed"}
    changed = [q for q in new_q if old_q[q] != new_q[q]]
    return {"status": "RESUME", "changed": changed, "failed": saved.get("failed", []), "codes": saved.get("codes", []),
            "written": saved.get("written", "")}


def wip_clear(sheet: Path) -> None:
    wip_path(sheet).unlink(missing_ok=True)


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("sheet", type=Path)
    m.add_argument("--patch", type=Path, required=True)
    m.add_argument("--only", required=True)
    m.add_argument("--json", action="store_true")
    f = sub.add_parser("focus")
    f.add_argument("card", type=Path)
    f.add_argument("--only", required=True)
    f.add_argument("--out", type=Path, required=True)
    for name in ("wip-check", "wip-write", "wip-clear"):
        s = sub.add_parser(name)
        s.add_argument("sheet", type=Path)
        s.add_argument("--card", type=Path)
        s.add_argument("--matrix", type=Path)
        s.add_argument("--hosts", type=Path)
        s.add_argument("--failed", default="")
        s.add_argument("--codes", default="")
    a = ap.parse_args(argv)
    only = {x.strip().upper() for x in getattr(a, "only", "").split(",") if x.strip()}
    if a.cmd == "merge":
        base = a.sheet.read_text(encoding="utf-8") if a.sheet.is_file() else ""
        if not a.patch.is_file():
            print(json.dumps({"status": "NO_PATCH", "merged": [], "missing": sorted(only, key=_order)}))
            return 1
        res = merge_text(base, a.patch.read_text(encoding="utf-8"), only)
        a.sheet.write_text(res.pop("text"), encoding="utf-8")
        print(json.dumps({"status": "OK", **res}))
        return 0
    if a.cmd == "focus":
        a.out.write_text(focus(a.card.read_text(encoding="utf-8"), only), encoding="utf-8")
        print(json.dumps({"status": "OK", "out": str(a.out)}))
        return 0
    if a.cmd == "wip-clear":
        wip_clear(a.sheet)
        print(json.dumps({"status": "OK"}))
        return 0
    from csa_docx import answer_cache
    fp = answer_cache.fingerprint(a.card, a.matrix, a.hosts)
    if a.cmd == "wip-write":
        p = wip_write(a.sheet, fp, [x for x in a.failed.split(",") if x], [x for x in a.codes.split(",") if x])
        print(json.dumps({"status": "OK", "wip": str(p)}))
        return 0
    print(json.dumps(wip_check(a.sheet, fp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
