"""Fixture gate for the bounded answer context and first-pass validation.

These are deterministic framework fixtures, not a live-model benchmark: the
model is never allowed to weaken the validator in order to pass a case.
"""

import json
from pathlib import Path

from csa_docx import answer_obligations, answer_sheet


FIX = Path(__file__).parent / "fixtures"


def _errors(result):
    return [f for f in result["findings"] if f["level"] == "ERROR"]


def _card(key, question, rows, kind="narrative", **extra):
    card = {"key": key, "ratings": ["Met", "Partially Met", "Not Met"],
            "questions": [{"id": "B1", "kind": kind, "text": question}],
            "evidence": {"B1": {"rows": rows, "cut": [], "digest_ids": []}}, **extra}
    card["obligations"] = answer_obligations.build(card)
    return card


def _validate(card, text, matrix):
    return answer_sheet.validate(answer_sheet.parse(text), card, matrix, draft=True)


def test_golden_first_pass_fixtures_cover_required_answer_shapes():
    time_card = json.loads((FIX / "time_card.json").read_text(encoding="utf-8"))
    time_text = (FIX / "time_sheet_good.md").read_text(encoding="utf-8")
    time_matrix = {f"E-{n}": {"evidence_id": f"E-{n}", "status": "VERIFIED",
                                "claim": "time evidence"} for n in ("003", "004", "005", "3173")}

    narrative = _card("NARR", "What was observed?", [{"id": "E-101", "status": "VERIFIED",
                                                         "claim": "APPHOST1 runs the service"}])
    narrative_text = "## B1 Observation\nFacts:\n- APPHOST1 runs the service. (E-101) {observed; APPHOST1}\nText: The service runs on APPHOST1.\n"

    table = _card("TABLE", "Discovery table", [{"id": "E-102", "status": "VERIFIED",
                                                  "claim": "APPHOST1 has the service"}], kind="observation")
    table["questions"][0]["columns"] = ["Aspect", "Finding"]
    table["obligations"] = answer_obligations.build(table)
    table_text = "## B1 Discovery Information\nRows:\n| Aspect | Finding |\n| Service host | APPHOST1 (E-102) |\n"

    network = _card("NET", "Which hosts connect?", [{"id": "E-103", "status": "VERIFIED",
                                                       "claim": "APPHOST1 connects to DBHOST1"}], kind="observation")
    network_text = "## B1 Host network\nFacts:\n- APPHOST1 connects to DBHOST1. (E-103) {observed; APPHOST1}\nText: The captured connection is from APPHOST1 to DBHOST1.\n"

    cases = [
        ("requirement", time_card, time_text, time_matrix),
        ("table", table, table_text, {"E-102": {"evidence_id": "E-102", "status": "VERIFIED", "claim": "x"}}),
        ("narrative", narrative, narrative_text, {"E-101": {"evidence_id": "E-101", "status": "VERIFIED", "claim": "x"}}),
        ("network-zone", network, network_text, {"E-103": {"evidence_id": "E-103", "status": "VERIFIED", "claim": "x"}}),
    ]
    for name, card, text, matrix in cases:
        result = _validate(card, text, matrix)
        assert not _errors(result), f"{name}: {result}"


def test_previous_answer_repair_preserves_valid_untouched_content():
    card = _card("PREV", "What was observed?", [{"id": "E-104", "status": "VERIFIED",
                                                   "claim": "APPHOST1 has the service"}])
    matrix = {"E-104": {"evidence_id": "E-104", "status": "VERIFIED", "claim": "x"}}
    previous = answer_sheet.parse("## B1 Observation\nFacts:\n- APPHOST1 has the service. (E-104) {observed; APPHOST1}\nText: Existing answer.\n")
    repaired = answer_sheet.parse("## B1 Observation\nFacts:\n- APPHOST1 has the service. (E-104) {observed; APPHOST1}\nText: Existing answer.\n")
    result = answer_sheet.validate(repaired, card, matrix, draft=True, previous=previous)
    assert not _errors(result)
