"""S492: a note part replaces its earlier text instead of adding a second copy."""
from csa_docx import answer_sheet as A
from csa_docx.tests.test_optional_note import ROWS, _card, _sheet

NOTE = "MOTPRDCLU103 takes its time from MOTPRDSRV122 while the other cluster nodes use ROTPRDSRV122."
FACTS = "Facts:\n- " + NOTE[:-1] + ". (E-003) {observed; MOTPRDCLU103}"

OBS = {"kind": "observation", "facet": "Discovery Information", "label": None, "table": "@H3.4.1-T1",
       "columns": ["Aspect", "Configuration Observed", "Coverage / Source"], "rows": 2, "row_texts": ROWS}


def _node(parts_after):
    return {"title": "Time Synchronisation", "key": "TIME", "number": "3.4", "hid": "@H3.4", "comments": [],
            "parts": [
                {"kind": "requirement", "table": "@H3.4-T1", "row_texts": ["SEP-TIME-01 | x | | "],
                 "requirements": [{"id": "SEP-TIME-01", "row": 2, "text": "An OT time source exists."}]},
                *parts_after,
                {"kind": "narrative", "facet": "Drawbridge Impact", "label": None, "pid": "@H3.4.2-P1",
                 "question": "Drawbridge Impact", "current": "[Drawbridge]"}]}


def _plain(pid, text):
    return {"kind": "text", "facet": "Discovery Information", "pid": pid, "current": text}


def _note(pid, text, answered):
    d = {"kind": "note", "facet": "Discovery Information", "label": None,
         "answered": answered, "current": text, "question": "Optional note"}
    if pid:
        d["pid"] = pid
    return d


def _render(node, note_block=FACTS):
    card = _card(node)
    recs = A.render_records(_sheet(card, note_block), card, node, "3", 10)["records"]
    return [r for r in recs if "@H3.4.1-P" in r]


def _where(r):
    return r.split("**Where:** `")[1].split("`")[0]


def _do(r):
    return r.split("**Do:** ")[1].split()[0]


def test_plain_paragraph_note_is_replaced_in_place():
    recs = _render(_node([_plain("@H3.4.1-P1", NOTE), OBS, _note(None, "", False)]))
    assert len(recs) == 1 and _where(recs[0]) == "@H3.4.1-P1" and _do(recs[0]) == "Replace"


def test_tablenote_and_plain_paragraph_end_with_one_copy():
    recs = _render(_node([_plain("@H3.4.1-P1", NOTE), OBS, _note("@H3.4.1-P2", NOTE, True)]))
    assert sorted((_where(r), _do(r)) for r in recs) == [("@H3.4.1-P1", "Replace"), ("@H3.4.1-P2", "Delete")]


def test_a_different_note_is_not_a_copy():
    other = "The historian node keeps a separate battery backed clock for logging."
    recs = _render(_node([_plain("@H3.4.1-P1", other), OBS, _note("@H3.4.1-P2", "[Optional note: x]", False)]))
    assert len(recs) == 1 and _where(recs[0]) == "@H3.4.1-P2"


def test_none_deletes_every_copy():
    recs = _render(_node([_plain("@H3.4.1-P1", NOTE), OBS, _note("@H3.4.1-P2", NOTE, True)]),
                   "None: nothing outside the table.")
    assert {_where(r) for r in recs} == {"@H3.4.1-P1", "@H3.4.1-P2"} and all(_do(r) == "Delete" for r in recs)
