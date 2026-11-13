"""Bounded contract shared by CSA answer prompts and answer-sheet validation.

This is intentionally compact.  It is a model-facing checklist, not a replacement
for the validator or the full authoring rules.  The contract has no project-data
access so it can be safely embedded in every answer prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

VERSION = "answer-contract-v1"
MAX_BYTES = 12000

_RULES = (
    ("SHEET", "Write one ## B/F block per requested card block, using only the fields that block needs."),
    ("FACTS", "Every fact is about the system, application, host or practice and ends with cited evidence IDs plus basis and scope."),
    ("EVIDENCE", "Use only evidence IDs present on the card or explicitly added by this run. Never invent, upgrade or broaden evidence."),
    ("SCOPE", "Every host, address, zone, count and role in a fact or prose sentence must be supported by its cited evidence."),
    ("RETENTION", "Preserve supported facts and capture evidence from the answer being replaced, or explicitly say why a dropped fact no longer applies."),
    ("DIGEST", "Use a card digest when it supplies a fact needed by the question, or leave it out knowingly without inventing a replacement."),
    ("TABLES", "Rows start with the exact card header, use exact column counts, group hosts by role and keep totals consistent."),
    ("REQUIREMENTS", "Rate only the stated practice. Include current-state facts, a valid rating and a one-sentence rating reason."),
    ("STORIES", "A Story explains how the capability operates, adds detail not repeated in Summary, and ends with the evidence gap or unknown."),
    ("QUESTIONS", "Use one QUESTION: line for each unresolved fact. Do not turn an unknown into a fact or put a question in Summary."),
    ("REPAIR", "When ERRORS is supplied, rewrite only the named blocks and change only what the reported findings require."),
    ("OUTPUT", "Write only SHEET. Do not write anchors, edit IDs, change files, Word files or tool output."),
)

_ERRORS = {
    "QUESTION_MISSING": "answer every requested card block",
    "EMPTY_ANSWER": "write a non-empty answer for the block",
    "FACT_NO_EVIDENCE": "add valid evidence IDs or write QUESTION:",
    "UNKNOWN_EVIDENCE": "use only IDs on the card or added by this run",
    "RATING_INVALID": "use one rating offered by the card",
    "RATING_NO_REASON": "add a one-sentence Rating reason:",
    "COLUMNS": "copy the card table header exactly",
    "ROW_WIDTH": "use exactly the card table column count",
    "NO_ROWS": "write at least one table row or a QUESTION:",
    "REQUIREMENT_NO_FACTS": "state at least one evidence-grounded current fact",
    "ZONE_FACT_NOT_BACKED": "cite the evidence row that places the named host in that zone",
    "ZONE_CONTRADICTED": "remove or correct the zone claim to match the evidence",
    "ISOLATION_WRONG_SIDE": "keep the connection direction and isolation side stated by evidence",
    "ATTEMPT_AS_ESTABLISHED": "label an attempted or planned action as such",
    "SUMMARY_STORY_OVERLAP": "make Summary decision-first and Story an evidence-first path",
    "STORY_NO_EVIDENCE_PATH": "write at least two Story sentences: operation, then unknown or gap",
    "STORY_STARTS_WITH_RATING": "start Story with how the capability operates",
    "STORY_RESTATES_RATING": "keep rating language out of Story",
    "STORY_SENTENCE_LONG": "split the long Story sentence",
    "BACKGROUND_AS_EVIDENCE": "do not cite K- background as project evidence",
    "CROSS_PROJECT_ONLY": "do not use another project's evidence as the only support",
    "SEMICOLON": "split the sentence or join it without a semicolon",
}


@dataclass(frozen=True)
class Contract:
    version: str
    text: str
    rules: tuple[tuple[str, str], ...]
    errors: tuple[tuple[str, str], ...]


def build() -> Contract:
    lines = [
        f"ANSWER CONTRACT: {VERSION}",
        "Use this checklist before returning SHEET. The validator remains authoritative.",
        "",
        "RULES:",
    ]
    lines.extend(f"- {name}: {rule}" for name, rule in _RULES)
    lines.extend(["", "BLOCKING FINDINGS:"])
    lines.extend(f"- {code}: {instruction}" for code, instruction in sorted(_ERRORS.items()))
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"answer contract exceeds {MAX_BYTES} bytes")
    return Contract(VERSION, text, _RULES, tuple(sorted(_ERRORS.items())))


def render() -> str:
    return build().text


def metadata() -> dict:
    contract = build()
    return {"version": contract.version, "bytes": len(contract.text.encode("utf-8")),
            "rule_count": len(contract.rules), "blocking_code_count": len(contract.errors)}
