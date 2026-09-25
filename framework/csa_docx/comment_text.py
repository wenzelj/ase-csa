"""Build the Word comment attached to an applied change.

A comment is read by the document's reviewers and approvers, not by the agents. It says,
in plain language and in one or two sentences, what changed and why. The traceability
(edit ID and evidence IDs) goes in a short reference at the end. The full reasoning, file
names and host lists stay in the change record's ``Why``, which is the audit trail.

Source of the sentence, in order:
  1. the record's ``**Note:**`` field (written by the authoring agent to csa-writing-style);
  2. otherwise the first sentence of ``Why``, if it is short and plain;
  3. otherwise the record title.
"""
from __future__ import annotations

import re

from .models import ChangeRecord

MAX_NOTE_WORDS = 40

_EVIDENCE_ID_RE = re.compile(r"\bE-\d{2,}\b")
_EVIDENCE_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*\bE-\d{2,}\b[^\)\]]*[\)\]]")
_FILE_RE = re.compile(r"\b[\w.-]+\.(?:txt|csv|log|json|xml|ps1|evtx|docx|md)\b", re.IGNORECASE)
_HOST_RE = re.compile(r"\b[A-Z]{3,}[A-Z0-9]*\d{2,}[A-Z0-9]*\b")
_EDITORIAL_RE = re.compile(r"^editorial\s*[-–—:]+\s*", re.IGNORECASE)
_NO_QUESTION_RE = re.compile(r"^(?:none\.?|n/?a|no (?:new |open )?questions?\b|there are no (?:new |open )?questions?\b)", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<![.])(?<!\be\.g)(?<!\bi\.e)(?<=[.!?])\s+(?=[A-Z])")
_STATUS_RE = re.compile(r"\s*\((?:VERIFIED|INFERRED|UNCONFIRMED|CONFLICTING|NOT_FOUND)\)")
_QUOTED_DETAIL_RE = re.compile(r"\bpara(?:graph)?s? \d|:\s*[\"“]|@H\d")
MAX_QUESTION_WORDS = 30


def evidence_ids(record: ChangeRecord) -> list[str]:
    seen: list[str] = []
    for eid in _EVIDENCE_ID_RE.findall(f"{record.note}\n{record.why}"):
        if eid not in seen:
            seen.append(eid)
    return seen


def _own_text(record: ChangeRecord) -> str:
    """The record's own lines: stop at the first level-2 heading (the file's Open questions,
    Changes Report, ...), which the parser otherwise leaves attached to the last record."""
    return re.split(r"^##\s", record.raw or "", maxsplit=1, flags=re.MULTILINE)[0]


def real_questions(record: ChangeRecord) -> list[str]:
    own = _own_text(record)
    return [q for q in record.questions
            if q.strip() and not _NO_QUESTION_RE.search(q.strip())
            and q.strip()[:40] in own and len(q.split()) <= MAX_QUESTION_WORDS]


def _plain(text: str) -> str:
    text = _STATUS_RE.sub("", text)
    text = _EVIDENCE_PAREN_RE.sub("", text)
    text = _EVIDENCE_ID_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:])", r"\1", text)


def _is_plain_enough(sentence: str) -> bool:
    return (
        len(sentence.split()) <= MAX_NOTE_WORDS
        and not _FILE_RE.search(sentence)
        and len(_HOST_RE.findall(sentence)) <= 1
        and not _QUOTED_DETAIL_RE.search(sentence)
    )


def note_sentence(record: ChangeRecord) -> tuple[str, str]:
    """(sentence, source) where source is 'note', 'why' or 'title'."""
    if record.note.strip():
        return _plain(record.note), "note"
    why = _plain(_EDITORIAL_RE.sub("", record.why or ""))
    editorial = bool(_EDITORIAL_RE.match(record.why or ""))
    first = _SENTENCE_RE.split(why, maxsplit=1)[0].strip() if why else ""
    if first and _is_plain_enough(first):
        return (f"Wording tightened, no facts changed: {first[0].lower()}{first[1:]}" if editorial else first), "why"
    title = record.title.strip().rstrip(".")
    return (f"{title}." if title else ""), "title"


def build_comment_text(record: ChangeRecord) -> str:
    """One paragraph: the plain-language note, then '(Ref S9-E3; evidence E-082)'."""
    sentence, _ = note_sentence(record)
    ids = evidence_ids(record)
    ref = f"Ref {record.edit_id}" + (f"; evidence {', '.join(ids)}" if ids else "")
    parts = [sentence.rstrip() if sentence.rstrip().endswith((".", "?", "!")) else sentence.rstrip() + "."]
    for question in real_questions(record)[:2]:
        parts.append(f"Question: {question.rstrip()}")
    return " ".join(p for p in parts if p.strip(".")) + f" ({ref})"


def comment_warnings(record: ChangeRecord) -> list[str]:
    """Reasons the comment may read badly; surfaced in apply results for the reviewer."""
    warnings: list[str] = []
    sentence, source = note_sentence(record)
    if source != "note":
        warnings.append(f"no **Note:** in the change record; comment built from the {source}")
    if len(sentence.split()) > MAX_NOTE_WORDS:
        warnings.append(f"note is {len(sentence.split())} words (limit {MAX_NOTE_WORDS})")
    if _FILE_RE.search(sentence):
        warnings.append("note names an evidence file")
    return warnings


def main(argv: list[str] | None = None) -> int:
    """Preview the Word comment each record in a change file will produce.

    python3 -m csa_docx.comment_text <ChangesCSA_*.md>
    """
    import argparse
    import json
    from pathlib import Path

    from .change_parser import parse_change_file

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("change_file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    _, records = parse_change_file(Path(a.change_file))
    rows = [{"edit_id": r.edit_id, "comment": build_comment_text(r), "words": len(note_sentence(r)[0].split()),
             "warnings": comment_warnings(r)} for r in records]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['edit_id']}  ({row['words']} words)")
            print(f"  {row['comment']}")
            for w in row["warnings"]:
                print(f"  ! {w}")
    return 1 if any(r["warnings"] for r in rows) else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
