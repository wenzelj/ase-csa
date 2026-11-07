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
import hashlib
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
    m = re.fullmatch(r"\s*S(\d+(?:\.\d+)?)-E(\d+)\s+to\s+S\1-E(\d+)\s*", change_set or "")
    if not m:
        return []
    return [f"S{m[1]}-E{n}" for n in range(int(m[2]), int(m[3]) + 1)]


def apply(workspace: Path, docx: Path, change_file: Path, ids: list[str], new_file: bool = False) -> dict:
    """Apply only ``ids`` from ``change_file`` as plain text, then remove their records, comments and bookmarks."""
    if not ids:
        return {"status": "OK", "applied": [], "docx": str(docx)}
    section = re.match(r"S(\d+(?:\.\d+)?)-E", ids[0])[1]
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
    if new_file and cf.is_file() and not re.search(r"^#{2,4}\s+(?:REJECTED\s+)?S\d+(?:\.\d+)?-E\d+\b", cf.read_text(encoding="utf-8"), re.M):
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


_SUBJECT = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")


def _group_unknowns(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One open item per subject: the Unknown: lines of one block that are about the same address or host (its name, its
    role, its zone) are one question for one owner, so they are listed together."""
    out: list[tuple[str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    for qid, u in items:
        subj = _SUBJECT.search(u)
        if not subj:
            out.append((qid, u))
            continue
        k = (qid, subj.group(0).upper())
        if k in seen:
            first = out[seen[k]]
            out[seen[k]] = (qid, first[1] + " Also: " + u)
        else:
            seen[k] = len(out)
            out.append((qid, u))
    # the same question about different addresses, hosts or sites ("What share is accessed at A?" / "... at B?") is one item
    shaped: dict[tuple[str, str], int] = {}
    merged: list[tuple[str, str]] = []
    for qid, u in out:
        shape = re.sub(r"\s+", " ", _SUBJECT.sub("#", re.sub(r"\b(?:Mackay|Rockhampton)\b", "#", u))).lower()
        k = (qid, shape)
        subj = ", ".join(dict.fromkeys(m.group(0) for m in _SUBJECT.finditer(u)))
        if "#" in shape and k in shaped:
            q0, u0 = merged[shaped[k]]
            merged[shaped[k]] = (q0, u0 + (f" Same question for: {subj}." if subj else " Same question for another site."))
        else:
            shaped[k] = len(merged)
            merged.append((qid, u))
    return merged


def _section_order(number: str, title: str) -> tuple:
    """Section number as numbers (3.4 before 3.11); a card with none sorts last, by title."""
    nums = [int(x) for x in re.findall(r"\d+", number or "")]
    return (0, nums) if nums else (1, [], title)


def merge_across_sections(groups: list[dict]) -> int:
    """Merge a question that is already asked. ``groups`` is [{"label", "items": [(qid, text)]}] in section order. A question whose
    every (what is asked, endpoint) pair was raised before, or whose content words are exactly those of an earlier question
    (a fallback *backup* procedure is not a fallback *restore* procedure), is taken out of its list and noted under the first
    one ("also raised in ..."): by block when it is the same section, by section and block otherwise. Returns how many were
    merged. The sections' own sheets and documents are untouched: each reads in its own topic."""
    from .matrix_candidates import words
    from .sheet_fixes import question_keys
    seen: list[dict] = []                      # {"keys", "words", "item", "group"}
    merged = 0
    for gi, g in enumerate(groups):
        keep = []
        for qid, text in g["items"]:
            keys, ws = question_keys(text), words(text)
            first = next((s for s in seen if (keys and keys <= s["keys"]) or (len(ws) >= 4 and ws == s["words"])), None)
            if first is None and keys:         # covered by several earlier questions together
                hit = [s for s in seen if keys & s["keys"]]
                if hit and keys <= set().union(*(s["keys"] for s in hit)):
                    first = hit[0]
            if first is not None:
                where = f"[{qid}]" if first["group"] == gi else f"{g['label']} [{qid}]"
                if where not in first["item"]["also"]:
                    first["item"]["also"].append(where)
                merged += 1
                continue
            item = {"qid": qid, "text": text, "also": []}
            keep.append(item)
            seen.append({"keys": keys, "words": ws, "item": item, "group": gi})
        g["kept"] = keep
    return merged


def open_questions(work: Path) -> dict:
    """Every QUESTION: line of every answered card in csa-work/draft/open-questions.md, one list per card in section order. A question
    that an earlier section already asks is listed once, under that section, with where else it is raised."""
    from .answer_sheet import parse
    cards = Path(work) / "cards"
    groups = []
    for sheet in sorted(cards.glob("*.answer.md")):
        card_json = sheet.with_name(sheet.name[: -len(".answer.md")] + ".json")
        title, order = sheet.name[: -len(".answer.md")], _section_order("", sheet.name)
        if card_json.is_file():
            c = json.loads(card_json.read_text(encoding="utf-8"))
            title = f"{c.get('number', '')} {c.get('title', '')} ({c.get('key', title)})".strip()
            order = _section_order(c.get("number", ""), c.get("title", ""))
        items = [(qid, u) for qid, b in parse(sheet.read_text(encoding="utf-8")).items() for u in b["unknown"]]
        if items:
            groups.append({"label": title, "order": order, "items": _group_unknowns(items)})
    groups.sort(key=lambda g: g["order"])
    merged = merge_across_sections(groups)
    lines, total = [f"# Open questions (draft lane, {datetime.now():%Y-%m-%d %H:%M})", "",
                    "Built from the `QUESTION:` lines of every answered card. A question another section also asks is listed once, "
                    "under the first section, with where else it is raised. These feed Discovery Required.", ""], 0
    for g in groups:
        if not g["kept"]:
            continue
        lines += [f"## {g['label']}", ""]
        for it in g["kept"]:
            lines.append(f"- [{it['qid']}] {it['text']}")
            if it["also"]:
                lines.append(f"  also raised in: {'; '.join(it['also'])}")
            total += 1
        lines.append("")
    from csa_docx.figures.work import load_gaps
    for key, gaps in load_gaps(Path(work)).items():           # what the CSA figures need but the evidence lacks
        if gaps:
            lines += [f"## Figure for {gaps[0].get('section') or key}", ""] + [f"- [{g['dr_id']}] {g['text']}" for g in gaps] + [""]
            total += len(gaps)
    from csa_docx.topic_tables import load_gaps as topic_gaps
    for key, gaps in topic_gaps(Path(work)).items():         # hosts the role tables could not show from a capture
        if gaps:
            lines += [f"## Role table for {gaps[0].get('section') or key}", ""] + [f"- [{g['dr_id']}] {g['text']}" for g in gaps] + [""]
            total += len(gaps)
    out = Path(work) / "draft" / "open-questions.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"status": "OK", "file": str(out), "open": total, "merged_across_sections": merged}


_TR = re.compile(r"<w:tr[ >].*?</w:tr>", re.S)


def _cell_texts(row: str) -> list[str]:
    from .figures.place import _text
    return [_text(c.encode("utf-8")).strip() for c in re.findall(r"<w:tc>.*?</w:tc>", row, re.S)]


def tidy(docx: Path, card: dict, sheet_text: str) -> dict:
    """After the answer is written: (1) a table the answer gives fewer rows than the document had loses the rows
    after the answer's last one (the draft lane rewrites the table, so an old row left below the new ones is
    stale); (2) the reviewer comments the answer answered (an Answer: line in its C block) are removed. Plain
    edits, no tracked changes. Returns {"status", "rows": removed rows, "comments": removed comment ids}."""
    from .answer_sheet import parse
    from .build_apply import _strip_comments
    from .figures import place as P
    sheet = parse(sheet_text)
    docx = Path(docx)
    with zipfile.ZipFile(docx) as z:
        parts = {n: z.read(n) for n in z.namelist()}
        infos = {i.filename: i for i in z.infolist()}
    xb = parts["word/document.xml"]
    kids = P._body_children(xb)
    title = card.get("title", "")
    hi = next((i for i, (s, e, t) in enumerate(kids) if t == b"w:p" and P._heading_level(P._style(xb[s:e]))
               and P._text(xb[s:e]).strip() == title), None)
    removed = 0
    if hi is not None:
        lvl = P._heading_level(P._style(xb[kids[hi][0]:kids[hi][1]]))
        end = next((i for i in range(hi + 1, len(kids)) if kids[i][2] == b"w:p"
                    and (P._heading_level(P._style(xb[kids[i][0]:kids[i][1]])) or 99) <= lvl), len(kids))
        want = {}                                       # table header -> data rows the answer gives
        for q in card.get("questions", []):
            b = sheet.get(q["id"])
            if q.get("kind") in ("observation", "register") and q.get("columns") and b and b["rows"]:
                want[tuple(c.strip().lower() for c in q["columns"])] = len(b["rows"]) - 1
        out, last = [], 0
        for s, e, t in kids[hi:end]:
            if t != b"w:tbl":
                continue
            tbl = xb[s:e].decode("utf-8")
            if "csa-topic-table" in tbl:
                continue                                # the framework's own tables are placed whole
            rows = _TR.findall(tbl)
            keep = want.get(tuple(c.lower() for c in _cell_texts(rows[0]))) if rows else None
            if keep is None or len(rows) - 1 <= keep:
                continue
            new = tbl
            for r in rows[1 + keep:]:
                new = new.replace(r, "", 1)
                removed += 1
            out.append((s, e, new.encode("utf-8")))
        if out:
            buf, pos = [], 0
            for s, e, new in out:
                buf += [xb[pos:s], new]
                pos = e
            parts["word/document.xml"] = b"".join(buf) + xb[pos:]
            tmp = docx.with_name(docx.name + ".tidy")
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for n, data in parts.items():
                    z.writestr(infos[n], data, compress_type=zipfile.ZIP_DEFLATED)
            tmp.replace(docx)
    # reviewer comments the answer answered: matched on author and text, as the card asked them
    answered = []
    for q in card.get("questions", []):
        if q.get("kind") == "comment" and (sheet.get(q["id"]) or {}).get("answer"):
            m = re.match(r'Reviewer comment \((.*?)\): "(.*)"$', q.get("text", ""), re.S)
            if m:
                answered.append((m[1], " ".join(m[2].split())[:120]))
    ids = set()
    if answered and "word/comments.xml" in parts:
        from .figures.place import _text
        for c in re.finditer(r'<w:comment\b([^>]*)>(.*?)</w:comment>', parts["word/comments.xml"].decode("utf-8"), re.S):
            cid = re.search(r'w:id="(\d+)"', c[1])
            who = re.search(r'w:author="([^"]*)"', c[1])
            text = " ".join(_text(c[2].encode("utf-8")).split())
            if cid and any((who[1] if who else "") == a and text.startswith(t) for a, t in answered):
                ids.add(cid[1])
    if ids:
        _strip_comments(docx, ids)
    return {"status": "OK", "rows": removed, "comments": sorted(ids)}


_RUN = re.compile(r"<w:r(?P<ra>\s[^>]*)?>(?P<rpr><w:rPr>.*?</w:rPr>)?<w:t(?P<ta>\s[^>]*)?>(?P<t>[^<]*)</w:t></w:r>", re.S)
_AFTER_COLOR = ("w:spacing", "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr",
                "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish")
QUESTION_RED = "FF0000"


def _red(rpr: str) -> str:
    """A run's properties with a red colour (replacing any other colour), in schema order."""
    rpr = re.sub(r"<w:color\b[^>]*/>", "", rpr or "<w:rPr></w:rPr>")
    tag = f'<w:color w:val="{QUESTION_RED}"/>'
    m = re.search(r"<(?:" + "|".join(re.escape(t) for t in _AFTER_COLOR) + r")\b", rpr)
    return rpr[:m.start()] + tag + rpr[m.start():] if m else rpr.replace("</w:rPr>", tag + "</w:rPr>")


def colour_questions(docx: Path) -> dict:
    """Show every 'QUESTION: ...?' the draft lane wrote in red, so a gap stands out in the document. The sentence
    is split out of its run (same properties, red colour); a run already red is left alone, so this can run again."""
    docx = Path(docx)
    with zipfile.ZipFile(docx) as z:
        parts = {n: z.read(n) for n in z.namelist()}
        infos = {i.filename: i for i in z.infolist()}
    xml = parts["word/document.xml"].decode("utf-8")
    count = 0

    def split(m):
        nonlocal count
        text = m["t"]
        if "QUESTION:" not in text or (m["rpr"] and QUESTION_RED in m["rpr"]):
            return m[0]
        ra, rpr = m["ra"] or "", m["rpr"] or ""

        def run(t, props):
            return f'<w:r{ra}>{props}<w:t xml:space="preserve">{t}</w:t></w:r>' if t else ""
        out, pos = [], 0
        for q in re.finditer(r"QUESTION:[^?]*\??", text):
            out += [run(text[pos:q.start()], rpr), run(q[0], _red(rpr))]
            pos = q.end()
            count += 1
        return "".join(out) + run(text[pos:], rpr)

    new = _RUN.sub(split, xml)
    if count:
        parts["word/document.xml"] = new.encode("utf-8")
        tmp = docx.with_suffix(".tmp.docx")
        with zipfile.ZipFile(tmp, "w") as z:
            for n, data in parts.items():
                z.writestr(infos[n], data)
        tmp.replace(docx)
    return {"status": "OK", "questions": count}


def record_run(work: Path, key: str, number: str, title: str, status: str, detail: str = "", phase: str = "",
               blocks: str = "", elapsed_s: float | None = None, model: str = "", sheet_hash: str = "") -> dict:
    """Keep the latest draft-lane attempt in ``runs.json``.

    RUNNING/READY describe an in-flight or deliberately unapplied answer. OK is the only state that means the
    current sheet reached the document. FAILED, NO_SHEET, INTERRUPTED, TIMED_OUT and STALLED are terminal failures and keep
    ``last_ok`` so status can distinguish the latest attempt from the text still present in Word.
    """
    f = Path(work) / "draft" / "runs.json"
    try:
        runs = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        runs = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    r = runs.setdefault(key, {})
    terminal = status in {"OK", "READY", "FAILED", "NO_SHEET", "INTERRUPTED", "TIMED_OUT", "STALLED"}
    if terminal:
        model = model or str(r.get("model", ""))
        blocks = blocks or str(r.get("blocks", ""))
    r.update({"number": number, "title": title, "status": status, "detail": detail[:500], "at": now})
    r.update({"phase": phase, "blocks": blocks, "model": model, "candidate_sha256": sheet_hash})
    if elapsed_s is not None:
        r["elapsed_s"] = round(float(elapsed_s), 1)
    if status == "OK":
        r["last_ok"] = now
        sheet = Path(work) / "cards" / f"{key}.answer.md"      # bind the run to the sheet that passed
        r["sheet_sha256"] = hashlib.sha256(sheet.read_bytes()).hexdigest()[:16] if sheet.is_file() else ""
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return {"status": "OK", "file": str(f)}


def failed_runs(work: Path) -> list[str]:
    """One line per subsection whose latest draft-lane run failed: the document still holds an older answer."""
    try:
        runs = json.loads((Path(work) / "draft" / "runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for key, r in sorted(runs.items(), key=lambda kv: kv[1].get("number", "")):
        if r.get("status") in ("FAILED", "NO_SHEET", "INTERRUPTED", "TIMED_OUT", "STALLED"):
            since = f"text is from the run of {r['last_ok']}" if r.get("last_ok") else "no run has been applied yet"
            elapsed = f", {r['elapsed_s'] / 60:.1f} min" if r.get("elapsed_s") is not None else ""
            phase = f", phase {r['phase']}" if r.get("phase") else ""
            blocks = f", blocks {r['blocks']}" if r.get("blocks") else ""
            out.append(f"{r.get('number', '')} {r.get('title', key)}: last run {r.get('status')} at {r.get('at')}"
                       f"{elapsed}{phase}{blocks} ({since}){': ' + r['detail'] if r.get('detail') else ''}")
    return out


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
    s = sub.add_parser("run"); s.add_argument("--work-dir", type=Path, required=True)
    for k in ("key", "number", "title", "status", "detail", "phase", "blocks", "model", "sheet-hash"):
        s.add_argument(f"--{k}", default="")
    s.add_argument("--elapsed-s", type=float)
    s = sub.add_parser("failed-runs"); s.add_argument("--work-dir", type=Path, required=True)
    s = sub.add_parser("colour-questions"); s.add_argument("--docx", type=Path, required=True)
    s = sub.add_parser("tidy"); s.add_argument("--docx", type=Path, required=True)
    s.add_argument("--card", type=Path, required=True); s.add_argument("--sheet", type=Path, required=True)
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
        elif a.cmd == "run":
            out = record_run(a.work_dir, a.key, a.number, a.title, a.status, a.detail, a.phase, a.blocks,
                             a.elapsed_s, a.model, a.sheet_hash)
        elif a.cmd == "failed-runs":
            out = {"status": "OK", "failed": failed_runs(a.work_dir)}
        elif a.cmd == "colour-questions":
            out = colour_questions(a.docx)
        elif a.cmd == "tidy":
            out = tidy(a.docx, json.loads(a.card.read_text(encoding="utf-8")), a.sheet.read_text(encoding="utf-8"))
        else:
            out = open_questions(a.work_dir)
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        out = {"status": "ERROR", "message": str(e)}
    print(json.dumps(out))
    return 0 if out.get("status") in ("OK", "BLOCKED") else 1


if __name__ == "__main__":
    sys.exit(main())
