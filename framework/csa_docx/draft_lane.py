"""Draft lane (pre-V1): write an answered section card straight into the working document as plain text.

Before a CSA reaches V1 the change process (change-file checks, writer pass, tracked changes in batches of
two, review, cleanup) costs more than it gives. The draft lane keeps one model call per subsection: the
answer sheet is rendered into records (``answer_sheet render``), the records of this run are applied
untracked, and the records are taken out of the change file again, so nothing is left to review or clean
up. What changed is logged per day in ``csa-work/draft/changes-<date>.md``; every ``Unknown:`` line of
every answered card is collected in ``csa-work/draft/open-questions.md``.

    python3 -m csa_docx.draft_lane blocker --docx <docx> --heading "<title>"
    python3 -m csa_docx.draft_lane apply --workspace <root> --docx <docx> --change-file <cf> --ids S3-E10,S3-E11
    python3 -m csa_docx.draft_lane log --work-dir <dir> --key <key> --number <n> --title <t> --records <n> --open <n> [--note <text>]
    python3 -m csa_docx.draft_lane open-questions --work-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from . import tools
from .build_apply import _comment_ids, _drop_plain_records, _strip_comments, _strip_edit_bookmarks
from .run_state import state_key


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").split()).strip().lower()


def blocker(docx: Path, heading: str) -> str | None:
    """Why the subsection under ``heading`` cannot be written plain: unaccepted tracked changes in it."""
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    heads = []
    for m in re.finditer(r"<w:p\b(?:(?!</w:p>).)*?</w:p>", xml, re.S):
        lvl = re.search(r'<w:pStyle\s+w:val="Heading\s?(\d)"', m[0])
        if lvl:
            text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>",
                                      re.sub(r"<w:delText.*?</w:delText>", "", m[0], flags=re.S)))
            heads.append((m.start(), int(lvl[1]), text))
    want = _norm(re.sub(r"^\d+(\.\d+)*\s+", "", heading))
    for i, (start, level, text) in enumerate(heads):
        if _norm(text) != want:
            continue
        end = next((h[0] for h in heads[i + 1:] if h[1] <= level), len(xml))
        if re.search(r"<w:(?:ins|del|moveFrom|moveTo)\b", xml[start:end]):
            return f"'{text}' still has tracked changes: accept or reject them in Word first"
    return None


def expand(change_set: str) -> list[str]:
    """'S3-E10 to S3-E12' -> [S3-E10, S3-E11, S3-E12]; 'none' -> []."""
    m = re.fullmatch(r"\s*S(\d+)-E(\d+)\s+to\s+S\1-E(\d+)\s*", change_set or "")
    if not m:
        return []
    return [f"S{m[1]}-E{n}" for n in range(int(m[2]), int(m[3]) + 1)]


def apply(workspace: Path, docx: Path, change_file: Path, ids: list[str], new_file: bool = False) -> dict:
    """Apply only ``ids`` from ``change_file`` as plain text, then remove their records, comments and bookmarks."""
    if not ids:
        return {"status": "OK", "applied": [], "docx": str(docx)}
    section = re.match(r"S(\d+)-E", ids[0])[1]
    before = _comment_ids(docx)
    applied: list[str] = []
    while True:
        res = tools.apply_next_batch(section, 500, workspace=workspace, change_file=change_file, docx=docx,
                                     start_edit_id=ids[0], end_edit_id=ids[-1], track_changes=False)
        st = res.get("status")
        applied += res.get("applied") or []
        docx = Path(res.get("docx") or docx)
        if st == "SECTION_COMPLETE":
            break
        if st != "PARTIAL_COMPLETE":
            edit = (res.get("blocked") or [None])[0] or res.get("next_edit_id") or "?"
            return {"status": "ERROR", "applied": applied, "docx": str(docx),
                    "message": f"{edit}: {st}: {res.get('message') or res.get('reasons') or ''}"}
    _strip_comments(docx, _comment_ids(docx) - before)
    _strip_edit_bookmarks(docx, ids)
    _drop_plain_records(Path(change_file), docx, state_key(section, change_file), ids)
    cf = Path(change_file)
    if new_file and cf.is_file() and not re.search(r"^#{2,4}\s+(?:REJECTED\s+)?S\d+-E\d+\b", cf.read_text(encoding="utf-8"), re.M):
        cf.unlink()                      # made by this run and empty again: leave nothing for csa status to show
        (cf.parent / (cf.stem + ".approval.json")).unlink(missing_ok=True)
    return {"status": "OK", "applied": applied, "docx": str(docx)}


def log(work: Path, key: str, number: str, title: str, records: int, open_q: int, note: str = "") -> Path:
    out = Path(work) / "draft" / f"changes-{datetime.now():%Y-%m-%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        out.write_text(f"# Draft changes {datetime.now():%Y-%m-%d}\n\n| Time | Subsection | Change | Open questions |\n"
                       "| --- | --- | --- | --- |\n", encoding="utf-8")
    change = f"{records} part(s) rewritten" + (f"; {note}" if note else "")
    with out.open("a", encoding="utf-8") as fh:
        fh.write(f"| {datetime.now():%H:%M} | {number} {title} ({key}) | {change} | {open_q} |\n")
    return out


def open_questions(work: Path) -> dict:
    """Every Unknown: line of every answered card, one list per card, in csa-work/draft/open-questions.md."""
    from .answer_sheet import parse
    cards = Path(work) / "cards"
    lines, total = [f"# Open questions (draft lane, {datetime.now():%Y-%m-%d %H:%M})", "",
                    "Built from the `Unknown:` lines of every answered card. These feed Discovery Required.", ""], 0
    for sheet in sorted(cards.glob("*.answer.md")):
        card_json = sheet.with_name(sheet.name[: -len(".answer.md")] + ".json")
        title = sheet.name[: -len(".answer.md")]
        if card_json.is_file():
            c = json.loads(card_json.read_text(encoding="utf-8"))
            title = f"{c.get('number', '')} {c.get('title', '')} ({c.get('key', title)})".strip()
        items = [(qid, u) for qid, b in parse(sheet.read_text(encoding="utf-8")).items() for u in b["unknown"]]
        if items:
            lines += [f"## {title}", ""] + [f"- [{qid}] {u}" for qid, u in items] + [""]
            total += len(items)
    from csa_docx.figures.work import load_gaps
    for key, gaps in load_gaps(Path(work)).items():           # what the CSA figures need but the evidence lacks
        if gaps:
            lines += [f"## Figure for {gaps[0].get('section') or key}", ""] + [f"- [{g['dr_id']}] {g['text']}" for g in gaps] + [""]
            total += len(gaps)
    out = Path(work) / "draft" / "open-questions.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"status": "OK", "file": str(out), "open": total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("blocker"); s.add_argument("--docx", type=Path, required=True); s.add_argument("--heading", required=True)
    s = sub.add_parser("apply"); s.add_argument("--workspace", type=Path, required=True)
    s.add_argument("--docx", type=Path, required=True); s.add_argument("--change-file", type=Path, required=True)
    s.add_argument("--ids", default=""); s.add_argument("--change-set", default="")
    s.add_argument("--new-file", action="store_true", help="the change file was made by this run: delete it when empty")
    s = sub.add_parser("log"); s.add_argument("--work-dir", type=Path, required=True)
    for k in ("key", "number", "title"):
        s.add_argument(f"--{k}", default="")
    s.add_argument("--records", type=int, default=0); s.add_argument("--open", type=int, default=0); s.add_argument("--note", default="")
    s = sub.add_parser("open-questions"); s.add_argument("--work-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "blocker":
            why = blocker(a.docx, a.heading)
            out = {"status": "BLOCKED" if why else "OK", "message": why or ""}
        elif a.cmd == "apply":
            ids = [x for x in a.ids.split(",") if x.strip()] or expand(a.change_set)
            out = apply(a.workspace, a.docx, a.change_file, ids, new_file=a.new_file)
        elif a.cmd == "log":
            out = {"status": "OK", "file": str(log(a.work_dir, a.key, a.number, a.title, a.records, a.open, a.note))}
        else:
            out = open_questions(a.work_dir)
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        out = {"status": "ERROR", "message": str(e)}
    print(json.dumps(out))
    return 0 if out.get("status") in ("OK", "BLOCKED") else 1


if __name__ == "__main__":
    sys.exit(main())
