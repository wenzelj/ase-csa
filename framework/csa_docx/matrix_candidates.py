"""Evidence already in the matrix that may answer a question, found with the topic's own words.

A question is usually worded differently from the evidence that answers it: "which time connections were observed to
which servers" against "Time source on HOST: SERVER". Matching the question's words alone misses the row, and the
framework's own earlier "no evidence answers: ..." rows, which repeat the question word for word, outrank the real
evidence. This ranks the matrix's VERIFIED rows by the question's words and by the topic vocabulary (``look_for``: the
phrases the evidence for this topic uses), never offers a row the framework wrote about a gap, and returns the best few
for a person or the answer agent to read. It decides nothing: a candidate is a row to read, not an answer.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")
_STOP = set("""which what where when whether does have this that with from into each every other their there about
observed seen shown connections connection hosts host servers server whole sits above any some than then them they
these those also could would should will been being were over under between across and the for are was not who how why
confirm confirmed owner owners network""".split())
#: rows that are the framework's own record of a gap, or a pointer to a question: never evidence
_SKIP_AREAS = {"discovery_required", "gap_lookup"}
#: the statuses the evidence matrix itself treats as able to answer a question (evidence_matrix.py ANSWER_STATUSES)
ANSWER_STATUSES = ("VERIFIED", "INFERRED")


def words(text: str) -> set[str]:
    """Content words of a question, cut to their first five letters so "synchronise" meets "synchronises"."""
    return {w.lower()[:5] for w in _WORD.findall(text or "") if w.lower() not in _STOP}


_CAPTURE_TERM = re.compile(r"[\\$:/]|^[A-Z][a-z]+-[A-Z]|[a-z][A-Z]|_")


def natural_terms(terms: list[str] | None) -> list[str]:
    """The phrases of a slot's ``search`` list that evidence claims can contain. Capture-file terms (a cmdlet such as
    Get-LocalUser, a path, a setting name such as NtpServer) never appear in a claim and are dropped."""
    return [t for t in (terms or []) if t.strip() and not _CAPTURE_TERM.search(t)]


def eligible(row: dict) -> bool:
    return (row.get("status") == "VERIFIED" and row.get("csa_area") not in _SKIP_AREAS
            and not str(row.get("evidence_id", "")).count(":")                      # another project's row
            and not (row.get("gap_or_action") or "").startswith("legacy L-")
            and not (row.get("claim") or "").lower().startswith(("possible answer to", "no evidence in the matrix", "searched for this and nothing matched")))


def candidates(rows: list[dict], question: str, look_for: list[str] | None = None, area: str = "",
               limit: int = 5, skip: set[str] | None = None) -> list[dict]:
    """[{id, claim, score}] best first. With ``look_for`` a row must hold one of its phrases and one word of the
    question; without it, three words of the question."""
    qwords, phrases = words(question), [p.lower() for p in natural_terms(look_for)]
    skip = {s.upper() for s in (skip or set())}
    scored = []
    for r in rows:
        if not eligible(r) or str(r.get("evidence_id", "")).upper() in skip:
            continue
        low = (r.get("claim") or "").lower()
        # a multi-word phrase is specific evidence of the topic; a single word ("manual", "backup") is weak, so one alone
        # does not qualify a row
        phrase_hits = sum(3 if " " in p else 1.5 for p in phrases if p in low)
        word_hits = len(qwords & words(low))
        in_area = bool(area) and r.get("csa_area") == area
        # a topic phrase (or two weak words) and a word of the question; or, failing that, three words of the question
        if phrases and not (phrase_hits >= 1.5 and word_hits >= (1 if phrase_hits >= 3 else 2)) and word_hits < 3:
            continue
        if not phrases and word_hits < (2 if in_area else 3):
            continue
        scored.append((phrase_hits + word_hits + (0.5 if area and r.get("csa_area") == area else 0), r))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("evidence_id"))))
    return [{"id": r["evidence_id"], "claim": r.get("claim", ""), "score": s} for s, r in scored[:limit]]
