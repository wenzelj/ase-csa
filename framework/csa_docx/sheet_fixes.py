"""Repairs the framework makes to an answer sheet itself, before it is checked: what the card and the evidence matrix
settle without asking the model again. Each one removes a reason to spend a repair call, and each is reported
("fixed without the model: ...") so a reader can see what changed.

split_question_lines   a QUESTION: line that holds two questions becomes two lines
dedupe_questions       a question another block of the same section already asks (the same thing about the same endpoint) is dropped
fix_basis              a fact whose basis is "observed" but whose cited rows are all documents, a previous assessment
                       or a user statement takes the basis the rows support ("documented" or "stated")
"""
from __future__ import annotations

import re

from csa_docx import answer_sheet as A

_Q_LINE = re.compile(r"^(?P<lead>\s*)(?P<key>QUESTION|Question|Unknown):\s*(?P<q>\S.*?)\s*$")
_META = re.compile(r"\{(?P<meta>[^{}]*)\}\s*$")


def split_question_lines(text: str) -> tuple[str, int]:
    """(text, lines added): each block-level QUESTION: line holding several questions becomes one line per question."""
    out: list[str] = []
    added = 0
    for line in text.split("\n"):
        m = _Q_LINE.match(line)
        qs = A.split_questions(m["q"]) if m else []
        if len(qs) > 1:
            out += [f"{m['lead']}QUESTION: {A.as_question(q)}" for q in qs]
            added += len(qs) - 1
        else:
            out.append(line)
    return "\n".join(out), added


_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOSTNAME = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
#: what a question asks about an endpoint, in the words the answer agent uses
_ASKS = {
    "zone": re.compile(r"\bzones?\b|\bside of (?:the )?OT\b|\bwhich side\b|\bhosted on\b|\b(?:in|inside|outside) OT\b|\bOT or (?:in )?IT\b", re.I),
    "data": re.compile(r"\bwhat data\b|\bdata (?:does|do|is|moves?)\b|\breads?\b|\bcop(?:y|ies)\b", re.I),
    "role": re.compile(r"\broles?\b|\bpurpose\b|\bwhat does\b[^?]*\bdo\b", re.I),
}
_BLOCK_NO = re.compile(r"^##\s+([A-Z]+)(\d+)\b")


def question_keys(q: str) -> set[tuple[str, str]]:
    """The (what is asked, endpoint) pairs a question raises: "Which side of OT is 10.129.11.10 in, and what data does it read?"
    is {(zone, 10.129.11.10), (data, 10.129.11.10)}. Empty when it names no address or host, or asks nothing recognised, so
    such a question is never judged a repeat of another."""
    ends = set(_IPV4.findall(q)) | {h.upper() for h in _HOSTNAME.findall(q)}
    asks = [a for a, rx in _ASKS.items() if rx.search(q)]
    return {(a, e) for a in asks for e in ends}


def dedupe_questions(text: str) -> tuple[str, list[str]]:
    """(text, the questions dropped): in block order (B1, B2, ... by number), a QUESTION: line whose every pair was already asked
    by an earlier line of the section is dropped; the first block that asks keeps it. A line that asks something new stays whole."""
    lines = text.split("\n")
    blocks: list[tuple[int, str, int]] = []                     # (order, block id, line index of its heading)
    for i, l in enumerate(lines):
        m = _BLOCK_NO.match(l)
        if m and m.group(1) in ("B", "C"):
            blocks.append((int(m.group(2)), m.group(1) + m.group(2), i))
    spans = {}
    ordered = sorted(blocks, key=lambda b: b[2])
    for n, (_, bid, start) in enumerate(ordered):
        spans[bid] = (start, ordered[n + 1][2] if n + 1 < len(ordered) else len(lines))
    seen: set[tuple[str, str]] = set()
    drop: set[int] = set()
    dropped: list[str] = []
    for _, bid, _ in sorted(blocks):
        start, end = spans[bid]
        for i in range(start, end):
            m = _Q_LINE.match(lines[i])
            if not m:
                continue
            keys = question_keys(m["q"])
            if keys and keys <= seen:
                drop.add(i)
                dropped.append(f"{bid}: {m['q'][:80]}")
            else:
                seen |= keys
    return "\n".join(l for i, l in enumerate(lines) if i not in drop), dropped


def _basis_for(rows: list[dict]) -> str:
    """The basis cited rows support when none of them is a capture: a user's statement is "stated", anything else
    ("documented")."""
    classes = {A.source_class(r) for r in rows}
    return "stated" if classes == {"user"} else "documented"


def fix_basis(text: str, matrix: dict[str, dict]) -> tuple[str, list[str]]:
    """(text, [fact starts changed]): "observed" facts that cite only rows from documents, the previous assessment or a
    user are re-based. A fact citing a capture row, a row the matrix lacks, or no row is left alone."""
    changed: list[str] = []
    out: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        fm = A._FACT.match(s) if s.startswith(("-", "*")) else None
        meta = fm.group("meta") if fm else None
        if fm and meta and meta.split(";")[0].strip().lower() == "observed" and fm.group("ids"):
            ids = [i.upper() for i in A._ANYID.findall(fm.group("ids"))]
            rows = [matrix[i] for i in ids if i in matrix]
            if rows and len(rows) == len(ids) and all(A.source_class(r) != "capture" for r in rows):
                new = _basis_for(rows)                  # the framework's own BASIS_NOT_OBSERVED rule: documented or stated
                head, _, rest = meta.partition(";")
                line = _META.sub("{" + new + (";" + rest if rest else "") + "}", line)
                changed.append(f"{ids[0]} observed -> {new}: {fm.group('text')[:50]}")
        out.append(line)
    return "\n".join(out), changed


def normalise(text: str, card: dict, matrix: dict[str, dict]) -> tuple[str, list[str]]:
    """The sheet text with every deterministic repair made, and one note per kind of repair."""
    notes: list[str] = []
    text, n = split_question_lines(text)
    if n:
        notes.append(f"{n} QUESTION: line(s) held more than one question: split so each is its own line")
    text, dropped = dedupe_questions(text)
    if dropped:
        notes.append(f"{len(dropped)} QUESTION: line(s) repeated a question an earlier block of the section already asks: "
                     + "; ".join(dropped[:4]))
    if matrix:
        text, changed = fix_basis(text, matrix)
        if changed:
            notes.append(f"{len(changed)} fact(s) cited only documents or statements but were marked observed: "
                         + "; ".join(changed[:4]))
    return text, notes
