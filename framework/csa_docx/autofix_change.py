"""Fix the mechanical `check-change` errors in a change file, and nothing else.

    python3 -m csa_docx.autofix_change <change-file> [--workspace <project root>] [--write] [--json]

Fixes (each is reported; without --write the file is only read):

    MARKDOWN_IN_TEXT     `**`, backticks, a leading `#` or a second `>` in **Text:**: the marker goes, the words stay
    EID_IN_TEXT          evidence IDs in **Text:** move to **Why:** (if not already there)
    STABLE_ID_IN_TEXT    stable IDs (@H...) in **Text:** move to **Why:** (if not already there)
    DUPLICATE_ID         an edit ID used twice in the file, or already used by another change file of the section,
                         is renumbered after the highest S<sec>-E<n> (or -A<n>) in use
    NO_CURRENTLY         a Replace/Delete whose stable ID resolves in the document gets `currently: "<60 characters>"`

A file with nothing to fix is left byte for byte unchanged. Judgement is never applied: Facts, Why wording, anchors
and Text wording are not touched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^###\s+(?!REJECTED\b)(?P<id>S\d+-[EA]\d+)(?P<rest>\s+-\s+.*)$", re.M)
LABEL_RE = re.compile(r"^\*\*(Where|Do|Facts|Text|Why|Note):\*\*", re.M)
FILENAME_RE = re.compile(r"^ChangesCSA_.+?_Section(?P<section>\d+)(?:_[^.]+)?\.md$")
EID = re.compile(r"\bE-\d{2,}\b")
STABLE = re.compile(r"@H[0-9][\w.\-]*")
EID_GROUP = re.compile(r"\s*[\[(]\s*E-\d{2,}(?:\s*[,;]\s*E-\d{2,})*\s*[\])]")
SET_RE = re.compile(r"(\*\*Suggested change set:\*\*\s*)(S\d+-E\d+)\s+to\s+(S\d+-E\d+)")


def _fix(code: str, edit_id: str | None, message: str) -> dict:
    return {"code": code, "edit_id": edit_id, "message": message}


def _split(text: str) -> list[tuple[str | None, str]]:
    """[(edit id or None, block text)] in file order; the first block is everything before the first record."""
    marks = list(HEADING_RE.finditer(text))
    if not marks:
        return [(None, text)]
    out = [(None, text[: marks[0].start()])]
    for i, m in enumerate(marks):
        out.append((m["id"], text[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]))
    return out


def _label_span(block: str, label: str) -> tuple[int, int] | None:
    marks = list(LABEL_RE.finditer(block))
    for i, m in enumerate(marks):
        if m.group(1) == label:
            end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
            sep = re.search(r"^---[ \t]*$", block[m.end():end], re.M)
            if sep:
                end = m.end() + sep.start()
            return m.start(), end
    return None


def _clean_text_line(line: str) -> str:
    inner = line[1:]
    lead = " " if inner.startswith(" ") else ""
    inner = inner[1:] if lead else inner
    inner = re.sub(r"^\s*(?:>\s*|#+\s+)+", "", inner)
    inner = re.sub(r"\*\*(.+?)\*\*", r"\1", inner)
    inner = inner.replace("**", "").replace("`", "")
    return ">" + lead + inner


def _strip_ids(line: str, eids: list[str], sids: list[str]) -> str:
    def take_group(m):
        eids.extend(EID.findall(m.group(0)))
        return ""
    line = EID_GROUP.sub(take_group, line)

    def take_e(m):
        eids.append(m.group(0))
        return ""
    line = re.sub(r"\s*\b(?:E-\d{2,})\b", take_e, line)

    def take_s(m):
        sid = m.group(0)
        tail = ""
        while sid and sid[-1] in ".-":
            tail, sid = sid[-1] + tail, sid[:-1]
        sids.append(sid)
        return tail
    line = re.sub(r"\s*\(?" + STABLE.pattern + r"\)?", take_s, line)
    return re.sub(r"\s+([.,;:])", r"\1", line)


def _fix_text(block: str, eid: str, fixes: list[dict]) -> str:
    span = _label_span(block, "Text")
    if not span:
        return block
    head, body = block[: span[0]], block[span[0]: span[1]]
    lines, out, eids, sids, md = body.split("\n"), [], [], [], False
    for i, line in enumerate(lines):
        if i and line.startswith(">"):
            new = _clean_text_line(line)
            md = md or new != line
            line = new
            line = _strip_ids(line, eids, sids)
        out.append(line)
    new_body = "\n".join(out)
    if md:
        fixes.append(_fix("MARKDOWN_IN_TEXT", eid, "removed Markdown markers from Text"))
    new_block = head + new_body + block[span[1]:]
    if eids or sids:
        moved = list(dict.fromkeys(eids + sids))
        why = _label_span(new_block, "Why")
        have = new_block[why[0]: why[1]] if why else ""
        add = [x for x in moved if x not in have]
        if add and why:
            body_end = why[1]
            piece = new_block[why[0]: why[1]].rstrip("\n")
            new_block = new_block[: why[0]] + piece + f" Moved from Text: {', '.join(add)}.\n\n" + new_block[body_end:].lstrip("\n")
        elif add:
            new_block = new_block.rstrip("\n") + f"\n\n**Why:** Moved from Text: {', '.join(add)}.\n"
        if eids:
            fixes.append(_fix("EID_IN_TEXT", eid, f"moved {', '.join(dict.fromkeys(eids))} from Text to Why"))
        if sids:
            fixes.append(_fix("STABLE_ID_IN_TEXT", eid, f"moved {', '.join(dict.fromkeys(sids))} from Text to Why"))
    return new_block


def _other_ids(path: Path, sec: str) -> set[str]:
    ids: set[str] = set()
    for f in path.parent.glob(f"ChangesCSA_*_Section{sec}*.md"):
        if f.resolve() == path.resolve() or not FILENAME_RE.match(f.name) or FILENAME_RE.match(f.name)["section"] != sec:
            continue
        ids.update(m["id"] for m in HEADING_RE.finditer(f.read_text(encoding="utf-8")))
    return ids


def _renumber(parts: list[tuple[str | None, str]], others: set[str], sec: str, fixes: list[dict]) -> list[tuple[str | None, str]]:
    seen: set[str] = set()
    colliding: list[int] = []
    for i, (eid, _) in enumerate(parts):
        if eid is None:
            continue
        if eid in seen or eid in others:
            colliding.append(i)
        else:
            seen.add(eid)
    if not colliding:
        return parts
    top = {"E": 0, "A": 0}
    for eid in seen | others:
        m = re.fullmatch(rf"S{sec}-([EA])(\d+)", eid)
        if m:
            top[m[1]] = max(top[m[1]], int(m[2]))
    out = list(parts)
    for i in colliding:
        old, block = out[i]
        letter = re.fullmatch(r"S\d+-([EA])\d+", old)[1]
        top[letter] += 1
        new = f"S{sec}-{letter}{top[letter]}"
        out[i] = (new, re.sub(rf"\b{re.escape(old)}\b", new, block))
        fixes.append(_fix("DUPLICATE_ID", new, f"{old} was already used; renumbered to {new}"))
    return out


def _fix_currently(block: str, eid: str, workspace: str | None, fixes: list[dict]) -> str:
    where = re.search(r"^\*\*Where:\*\*[^\n]*$", block, re.M)
    do = re.search(r"^\*\*Do:\*\*\s*(\S[^\n]*)", block, re.M)
    if not where or not do or not do.group(1).lower().startswith(("replace", "delete")):
        return block
    line = where.group(0)
    if re.search(r"currently:\s*[\"“]", line) or "-T" in line:
        return block
    sid = STABLE.search(line)
    if not sid or not workspace:
        return block
    from csa_docx import tools

    res = tools.lookupStableId(sid.group(0).rstrip(".-"), workspace=workspace)
    if res.get("status") == "ERROR" or not res.get("unique_id"):
        return block
    cur = " ".join((res["matches"][0].get("text") or "").split()).replace('"', "'")[:60]
    if not cur:
        return block
    fixes.append(_fix("NO_CURRENTLY", eid, f"added the current text of {res['unique_id']} to Where"))
    return block.replace(line, f'{line.rstrip()} -- currently: "{cur}"', 1)


def autofix(path: Path, workspace: str | None = None, write: bool = False) -> dict:
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    m = FILENAME_RE.match(path.name)
    parts = _split(original)
    fixes: list[dict] = []
    if m:
        parts = _renumber(parts, _other_ids(path, m["section"]), m["section"], fixes)
    parts = [(e, _fix_currently(_fix_text(b, e, fixes), e, workspace, fixes) if e else b) for e, b in parts]
    text = "".join(b for _, b in parts)
    if any(f["code"] == "DUPLICATE_ID" for f in fixes):
        sec_ids = [e for e, _ in parts if e and re.fullmatch(r"S\d+-E\d+", e)]
        if sec_ids:
            lo = min(sec_ids, key=lambda s: int(s.split("-E")[1]))
            hi = max(sec_ids, key=lambda s: int(s.split("-E")[1]))
            text = SET_RE.sub(lambda mm: f"{mm.group(1)}{lo} to {hi}", text, count=1)
    changed = text != original
    if changed and write:
        path.write_text(text, encoding="utf-8")
    return {"status": "FIXED" if changed and write else ("WOULD_FIX" if changed else "CLEAN"),
            "fixes": fixes, "changed": changed, "file": str(path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("change_file", type=Path)
    ap.add_argument("--workspace")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = autofix(a.change_file, a.workspace, a.write)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for f in res["fixes"]:
            print(f"{res['status'].lower()}: {f['code']} {f['edit_id'] or ''} {f['message']}")
        if not res["fixes"]:
            print("nothing to fix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
