"""S493: a note that repeats prose in the same sheet, and two paragraphs that repeat each other, are warnings."""
from csa_docx import answer_sheet as A
from csa_docx.audit import check_duplicate_prose


# ------------------------------------------------------------------ NOTE_REPEATS_TEXT (answer_sheet)


def _card_with_narrative_and_note():
    """Card: one narrative (B1) and one note (B2), in document order."""
    return {
        "key": "TIME",
        "questions": [
            {"id": "B1", "kind": "narrative", "part": 0,
             "text": "Discovery Information: one paragraph"},
            {"id": "B2", "kind": "note", "part": 1,
             "text": "the optional note under the table",
             "table_rows": ["Time source | ROTPRDSRV122 | all hosts"]},
        ],
        "evidence": {},
        "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"],
    }


def test_note_repeating_narrative_is_warned():
    card = _card_with_narrative_and_note()
    story = "MOTPRDCLU103 takes its time from MOTPRDSRV122 while the other cluster nodes use ROTPRDSRV122."
    sheet = A.parse(
        "## B1 Discovery Information\n"
        f"Story: {story}\n\n"
        "## B2 Optional note\n"
        "Facts:\n"
        f"- {story} (E-001) {{observed; MOTPRDCLU103}}\n"
    )
    res = A.validate(sheet, card, draft=True)
    codes = {f["code"] for f in res["findings"]}
    assert "NOTE_REPEATS_TEXT" in codes, f"NOTE_REPEATS_TEXT not found; codes={codes}"
    note = [f for f in res["findings"] if f["code"] == "NOTE_REPEATS_TEXT"]
    assert note[0]["level"] == "WARN"
    assert note[0]["question"] == "B2"


def test_note_that_does_not_repeat_narrative_is_not_warned():
    card = _card_with_narrative_and_note()
    story = "MOTPRDCLU103 takes its time from MOTPRDSRV122 while the other cluster nodes use ROTPRDSRV122."
    # Note is about a different fact: the fallback peer
    note_fact = "No host has a configured fallback peer for the time source."
    sheet = A.parse(
        "## B1 Discovery Information\n"
        f"Story: {story}\n\n"
        "## B2 Optional note\n"
        f"Facts:\n- {note_fact} (E-002) {{observed; all hosts}}\n"
    )
    res = A.validate(sheet, card, draft=True)
    codes = {f["code"] for f in res["findings"]}
    assert "NOTE_REPEATS_TEXT" not in codes, f"NOTE_REPEATS_TEXT should not fire; codes={codes}"


def test_note_repeating_another_note_is_warned():
    """Two note blocks in the same sheet; the second repeats the first."""
    card = {
        "key": "TIME",
        "questions": [
            {"id": "B1", "kind": "note", "part": 0, "text": "note 1", "table_rows": []},
            {"id": "B2", "kind": "note", "part": 1, "text": "note 2", "table_rows": []},
        ],
        "evidence": {},
        "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"],
    }
    note_text = "The cluster nodes take their time from two different domain controllers."
    sheet = A.parse(
        "## B1 note one\n"
        f"Facts:\n- {note_text} (E-001) {{observed; cluster nodes}}\n\n"
        "## B2 note two\n"
        f"Facts:\n- {note_text} (E-001) {{observed; cluster nodes}}\n"
    )
    res = A.validate(sheet, card, draft=True)
    codes = {f["code"] for f in res["findings"]}
    assert "NOTE_REPEATS_TEXT" in codes, f"NOTE_REPEATS_TEXT not found; codes={codes}"


# ------------------------------------------------------------------ DUPLICATE_PROSE (audit.py)


def P(text, path, **kw):
    u = {"kind": "para", "text": text, "path": path}
    u.update(kw)
    return u


def R(cells, row, path):
    return {"kind": "row", "cells": cells, "row": row, "path": path}


def H(level, text, path):
    return {"kind": "heading", "level": level, "text": text, "path": path}


PATH = ["3.4 Time Synchronisation", "3.4.1 Discovery Information"]


def test_two_paragraphs_sharing_a_sentence_are_reported():
    p1 = "The SQL Server cluster node group does not share one time source. MOTPRDCLU103 follows the Mackay source while the Rockhampton nodes follow the Rockhampton source."
    p2 = "MOTPRDCLU103 follows the Mackay source while the Rockhampton nodes follow the Rockhampton source. The only function with a recorded dependency is Voice and SDS recording."
    units = [H(2, "3.4 Time Synchronisation", ["3.4 Time Synchronisation"]),
             H(3, "3.4.1 Discovery Information", PATH),
             P(p1, PATH), P(p2, PATH)]
    out = check_duplicate_prose(units)
    assert len(out) == 1
    assert out[0]["issue"] == "DUPLICATE_PROSE"
    assert out[0]["severity"] == "warning"
    assert "motprdclu103" in out[0]["detail"]
    assert out[0]["paragraphs"][0] == p1
    assert out[0]["paragraphs"][1] == p2


def test_two_paragraphs_that_share_a_host_name_but_say_different_things_are_not_reported():
    p1 = "MOTPRDCLU103 takes its time from MOTPRDSRV122."
    p2 = "MOTPRDCLU103 runs the SQL Server cluster instance for the OT database."
    units = [H(2, "3.4 Time Synchronisation", ["3.4 Time Synchronisation"]),
             H(3, "3.4.1 Discovery Information", PATH),
             P(p1, PATH), P(p2, PATH)]
    assert check_duplicate_prose(units) == []


def test_a_sentence_that_repeats_a_requirement_is_not_reported():
    req_text = "Time from an OT-resident authoritative source independent of the IT domain hierarchy"
    p1 = req_text
    p2 = "The Windows Time service runs on every captured host; no OT-resident authoritative source was identified."
    units = [H(2, "3.4 Time Synchronisation", ["3.4 Time Synchronisation"]),
             H(3, "3.4.1 Discovery Information", PATH),
             R(["SEP-TIME-01", req_text, "", "Not Met"], 1, PATH),
             P(p1, PATH), P(p2, PATH)]
    assert check_duplicate_prose(units) == []


def test_a_paragraph_repeating_a_table_cell_is_not_flagged_as_paragraph_repeat():
    """A paragraph that restates a table cell is not a DUPLICATE_PROSE: the table is not prose."""
    p = "The time source is ROTPRDSRV122 for all captured hosts."
    units = [H(2, "3.4 Time Synchronisation", ["3.4 Time Synchronisation"]),
             H(3, "3.4.1 Discovery Information", PATH),
             R(["Time source", "ROTPRDSRV122 for all captured hosts", "all hosts"], 1, PATH),
             P(p, PATH)]
    # one paragraph that restates the table cell: no second paragraph, so no DUPLICATE_PROSE
    assert check_duplicate_prose(units) == []
