"""One-page author report: each brief question, what answers it, and the sentence that says it.

Read a change file the author wrote and set its section brief against its records. For every question
(`B1`, `C1`, ...): the facts tagged with it, their evidence IDs, and the first sentence of the record's Text.
A question no fact answers is OPEN when the file mentions it elsewhere (an open question, an `Unknown:` line,
an unchanged note) and UNANSWERED when it does not. No model is involved: the report only lays out what the
file already says, so a person can read the answer against the questions before the change reaches Word.

    python3 -m csa_docx.author_report <change file> [--out report.md]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from csa_docx.change_parser import parse_change_records
from csa_docx.check_change import BRIEF_RE, FACT_TAG_RE, _is_table_text

_ITEM = re.compile(r"^\s*[-*]?\s*([BC]\d+)\b[:.)]?\s*(.*)$")
_EVID = re.compile(r"\bE-\d+\b")


def brief_items(text: str) -> list[tuple[str, str]]:
    m = BRIEF_RE.search(text)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        mm = _ITEM.match(line)
        if mm:
            out.append((mm.group(1), mm.group(2).strip()))
    return list(dict.fromkeys(out))


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def _sentence_for(text: str, fact: str) -> str:
    """The sentence of the record's Text that shares the most words with the fact (the first one on a tie)."""
    t = " ".join((text or "").replace("|", ". ").split())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    if not sentences:
        return ""
    fw = _words(FACT_TAG_RE.sub("", fact))
    best = max(sentences, key=lambda s: len(_words(s) & fw))
    return best[:220]


def build(text: str, name: str = "") -> dict:
    records = parse_change_records(text)
    items = brief_items(text)
    m = BRIEF_RE.search(text)
    rest = text[:m.start()] + text[m.end():] if m else text
    answers: dict[str, list[dict]] = {k: [] for k, _ in items}
    untagged = 0
    no_facts = []
    for r in records:
        prose = (r.text or "").strip() and not _is_table_text(r.text)
        if prose and not (r.facts or "").strip():
            no_facts.append(r.edit_id)
        for line in (r.facts or "").splitlines():
            ln = line.strip()
            if not ln.startswith(("-", "*")) or re.match(r"^[-*]\s*(Table detail|Unknown)\s*:", ln, re.I):
                continue
            tag = FACT_TAG_RE.match(ln)
            if not tag:
                untagged += 1
                continue
            for it in re.split(r"\s*,\s*", tag.group(1)):
                answers.setdefault(it, []).append({"record": r.edit_id, "fact": ln, "sentence": _sentence_for(r.text or "", ln)})
    status = {}
    for k, _ in items:
        if answers.get(k):
            status[k] = "ANSWERED"
        elif re.search(rf"\b{k}\b", rest):
            status[k] = "OPEN"
        else:
            status[k] = "UNANSWERED"
    counts = {s: sum(1 for v in status.values() if v == s) for s in ("ANSWERED", "OPEN", "UNANSWERED")}
    lines = [f"# Author report{' - ' + name if name else ''}", "",
             f"Records: {len(records)}. Questions: {len(items)} "
             f"({counts['ANSWERED']} answered, {counts['OPEN']} open, {counts['UNANSWERED']} unanswered). "
             f"Untagged facts: {untagged}. Prose records without Facts: {len(no_facts)}.", ""]
    if not items:
        lines += ["The change file has no section brief questions (B1, C1, ...).", ""]
    for k, q in items:
        lines += [f"## {k} {status[k]}", "", q, ""]
        for a in answers.get(k, []):
            ids = ", ".join(dict.fromkeys(_EVID.findall(a["fact"]))) or "no evidence ID"
            lines += [f"- {a['record']}: {a['fact'].lstrip('-* ').strip()}", f"  Evidence: {ids}. Says: \"{a['sentence']}\""]
        if status[k] == "OPEN":
            lines.append("- Noted in the file as an open question or unchanged; no fact answers it.")
        if status[k] == "UNANSWERED":
            lines.append("- Nothing in the file answers or mentions it.")
        lines.append("")
    if no_facts:
        lines += ["## Prose records with no Facts", "", ", ".join(no_facts), ""]
    return {"status": "OK", "text": "\n".join(lines), "counts": counts, "questions": len(items),
            "untagged": untagged, "no_facts": no_facts, "records": len(records)}


def summary(res: dict) -> str:
    c = res["counts"]
    return (f"{res['questions']} question(s): {c['ANSWERED']} answered, {c['OPEN']} open, {c['UNANSWERED']} unanswered; "
            f"{res['untagged']} untagged fact(s)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--summary", action="store_true", help="print one line instead of the report")
    ap.add_argument("--json", action="store_true", help="print the counts as JSON")
    a = ap.parse_args(argv)
    res = build(a.path.read_text(encoding="utf-8"), a.path.name)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(res["text"] + "\n", encoding="utf-8")
    if a.json:
        import json
        print(json.dumps({k: res[k] for k in ("counts", "questions", "untagged", "no_facts", "records")}))
        return 0
    print(summary(res) if a.summary else res["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
