"""The optional note under a Discovery Information table: asked, checked and written (or removed)."""
import csv

from csa_docx import answer_sheet as A
from csa_docx import section_card

ROWS = ["Time source | ROTPRDSRV122 for the Rockhampton hosts | nine captured hosts",
        "Time service | Windows Time Service | all 12 captured hosts"]
PLACEHOLDER = "[Optional note: a finding that does not fit the table, in one or two sentences. Delete if not needed.]"


def _node(note_answered=False, note_text=PLACEHOLDER):
    return {"title": "Time Synchronisation", "key": "TIME", "number": "3.4", "hid": "@H3.4", "comments": [],
            "parts": [
                {"kind": "requirement", "table": "@H3.4-T1", "row_texts": ["SEP-TIME-01 | x | | "],
                 "requirements": [{"id": "SEP-TIME-01", "row": 2, "text": "An OT time source exists."}]},
                {"kind": "observation", "facet": "Discovery Information", "label": None, "table": "@H3.4.1-T1",
                 "columns": ["Aspect", "Configuration Observed", "Coverage / Source"], "rows": 2, "row_texts": ROWS},
                {"kind": "note", "facet": "Discovery Information", "label": None, "pid": "@H3.4.1-P1",
                 "answered": note_answered, "current": note_text, "question": "Optional note"},
                {"kind": "narrative", "facet": "Drawbridge Impact", "label": None, "pid": "@H3.4.2-P1",
                 "question": "Drawbridge Impact", "current": "[Drawbridge]"},
            ]}


def _card(node):
    qs = section_card.questions(node)
    return {"key": node["key"], "questions": qs, "evidence": {}, "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"]}


def _note_qid(card):
    return next(q["id"] for q in card["questions"] if q["kind"] == "note")


def _sheet(card, note_block):
    qid = _note_qid(card)
    return A.parse(
        "## B1 SEP-TIME-01\nFacts:\n- Every captured host takes its time from an enterprise server. (E-001) {observed; all 12 hosts}\n"
        "Rating: Not Met\nRating reason: no OT source was identified.\n\n"
        "## B2 Discovery Information\nRows:\n| Aspect | Configuration Observed | Coverage / Source |\n"
        "| Time source | ROTPRDSRV122 for the Rockhampton hosts | the RevServer and RevBroadcast nodes (E-001) |\n\n"
        "## B3 Drawbridge Impact\nFacts:\n- The hosts run on their own clocks during isolation. (E-002) {observed; all 12 hosts}\n\n"
        f"## {qid} Discovery Information note\n{note_block}\n")


def _codes(res, level="ERROR"):
    return {f["code"] for f in res["findings"] if f["level"] == level}


def test_the_note_is_asked_after_the_other_questions_so_their_numbers_do_not_move():
    qs = section_card.questions(_node())
    assert [(q["id"], q["kind"]) for q in qs] == [("B1", "requirement"), ("B2", "observation"),
                                                   ("B4", "note"), ("B3", "narrative")]
    note = qs[2]
    assert "cannot show" in note["text"] and "None:" in note["text"]
    assert note["table_rows"] == ROWS


def test_none_removes_the_placeholder():
    node = _node()
    card = _card(node)
    sheet = _sheet(card, "None: every captured host fits a row of the table.")
    assert A.validate(sheet, card)["status"] == "OK"
    recs = A.render_records(sheet, card, node, "3", 10)["records"]
    note = [r for r in recs if "@H3.4.1-P1" in r]
    assert len(note) == 1 and "**Do:** Delete" in note[0] and "**Text:**" not in note[0]
    assert "every captured host fits a row" in note[0]


def test_a_note_replaces_the_placeholder():
    node = _node()
    card = _card(node)
    sheet = _sheet(card, "Facts:\n- MOTPRDCLU103 takes its time from MOTPRDSRV122 while the other cluster nodes use "
                         "ROTPRDSRV122. (E-003) {observed; MOTPRDCLU103}")
    assert A.validate(sheet, card)["status"] == "OK"
    out = A.render_records(sheet, card, node, "3", 10)
    note = [r for r in out["records"] if "@H3.4.1-P1" in r][0]
    assert "**Do:** Replace" in note and "> MOTPRDCLU103 takes its time from MOTPRDSRV122" in note
    assert "E-003" not in note.split("**Text:**")[1].split("**Why:**")[0]
    assert any("E-003" in a for a in out["audit"])


def test_records_follow_document_order():
    node = _node()
    card = _card(node)
    sheet = _sheet(card, "None: nothing outside the table.")
    recs = A.render_records(sheet, card, node, "3", 10)["records"]
    where = [r.split("**Where:** `")[1].split("`")[0] for r in recs]
    assert where.index("@H3.4.1-P1") < where.index("@H3.4.2-P1")


def test_a_long_note_is_refused_even_in_the_draft_lane():
    card = _card(_node())
    sheet = _sheet(card, "Facts:\n- One host differs. (E-003) {observed; MOTPRDCLU103}\n- A second fact. (E-003) {observed; MOTPRDCLU103}\n"
                         "- A third fact. (E-003) {observed; MOTPRDCLU103}")
    res = A.validate(sheet, card, draft=True)
    assert "NOTE_TOO_LONG" in _codes(res)


def test_a_note_that_repeats_a_row_is_refused():
    card = _card(_node())
    sheet = _sheet(card, "Facts:\n- Windows Time Service runs on all 12 captured hosts. (E-004) {observed; all 12 captured hosts}")
    assert "NOTE_REPEATS_ROW" in _codes(A.validate(sheet, card))


def test_a_note_that_judges_is_refused():
    card = _card(_node())
    sheet = _sheet(card, "Facts:\n- MOTPRDCLU103 should use the same time server as its peers. (E-003) {observed; MOTPRDCLU103}")
    assert "NOTE_NOT_A_FACT" in _codes(A.validate(sheet, card))


def test_none_with_a_note_is_refused():
    card = _card(_node())
    sheet = _sheet(card, "None: nothing.\nFacts:\n- MOTPRDCLU103 differs. (E-003) {observed; MOTPRDCLU103}")
    assert "NOTE_NONE_AND_TEXT" in _codes(A.validate(sheet, card, draft=True))


def test_note_text_without_facts_is_refused():
    card = _card(_node())
    sheet = _sheet(card, "Text:\nMOTPRDCLU103 takes its time from another server.")
    assert "NOTE_NO_FACTS" in _codes(A.validate(sheet, card, draft=True))


def test_a_note_question_left_empty_is_refused():
    card = _card(_node())
    res = A.validate(_sheet(card, ""), card)
    assert "EMPTY_ANSWER" in _codes(res)


def test_an_unknown_only_removes_the_placeholder_and_becomes_an_open_question():
    node = _node()
    card = _card(node)
    sheet = _sheet(card, "Unknown: whether MOTPRDCLU103 was moved to another time server on purpose, the OT team could confirm.")
    out = A.render_records(sheet, card, node, "3", 10)
    assert any("@H3.4.1-P1" in r and "**Do:** Delete" in r for r in out["records"])
    assert any("MOTPRDCLU103" in q for q in out["open"])


def test_a_pending_search_leaves_the_placeholder_alone():
    node = _node()
    card = _card(node)
    sheet = _sheet(card, "Search: MOTPRDCLU103 w32tm peers")
    out = A.render_records(sheet, card, node, "3", 10)
    assert not any("@H3.4.1-P1" in r for r in out["records"])


def test_an_existing_note_is_kept_unless_none_is_written():
    node = _node(note_answered=True, note_text="MOTPRDCLU103 uses another time server.")
    card = _card(node)
    out = A.render_records(_sheet(card, "Unknown: why it differs, the OT team could confirm."), card, node, "3", 10)
    assert not any("@H3.4.1-P1" in r for r in out["records"])
    out = A.render_records(_sheet(card, "None: no longer true."), card, node, "3", 10)
    assert any("@H3.4.1-P1" in r and "**Do:** Delete" in r for r in out["records"])


def test_none_on_another_question_is_only_a_warning():
    card = _card(_node())
    sheet = _sheet(card, "None: nothing outside the table.")
    sheet["B3"]["none"] = "yes"
    assert "NONE_IGNORED" in _codes(A.validate(sheet, card), "WARN")


def _write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def test_note_candidates_find_a_role_group_member_that_differs(tmp_path):
    ws = tmp_path / "workspace"
    hosts = ws / "csa-work" / "hosts"
    _write(hosts / "hosts.csv", ["host", "in_scope", "system", "role", "site", "capture"],
           [["ROTPRDCLU101", "", "Reveloc", "SQL Server cluster node", "", "cap"],
            ["MOTPRDCLU101", "", "Reveloc", "SQL Server cluster node", "", "cap"],
            ["MOTPRDCLU103", "", "Reveloc", "SQL Server cluster node", "", "cap"],
            ["ROKPRDOPS110", "", "Reveloc", "RevViewer Jump Host", "", "cap"]])
    _write(hosts / "host_facts.csv", ["host", "attribute", "value"],
           [["ROTPRDCLU101", "time_status: Source", "ROTPRDSRV122.internal.qr.com.au"],
            ["MOTPRDCLU101", "time_status: Source", "ROTPRDSRV122.internal.qr.com.au"],
            ["MOTPRDCLU103", "time_status: Source", "MOTPRDSRV122.internal.qr.com.au"],
            ["ROTPRDCLU101", "host_summary: Caption", "Windows Server 2019"],
            ["MOTPRDCLU103", "host_summary: Caption", "Windows Server 2016"]])
    _write(ws / "csa-work" / "evidence-matrix.csv",
           ["evidence_id", "csa_area", "section", "status", "claim", "source_title", "evidence_excerpt"],
           [["E-010", "time", "time synchronisation", "VERIFIED", "MOTPRDCLU103 time source",
             "REVELOC_discovery_MOTPRDCLU103_20260709T052659Z: 03_time_status.txt", "Source: MOTPRDSRV122.internal.qr.com.au"],
            ["E-011", "time", "time synchronisation", "VERIFIED", "ROTPRDCLU101 time source",
             "REVELOC_discovery_ROTPRDCLU101_20260709T042915Z: 03_time_status.txt", "Source: ROTPRDSRV122.internal.qr.com.au"],
            ["E-012", "time", "time synchronisation", "CONFLICTING", "The documents and captures give different time servers",
             "System matrix", ""]])
    reg = section_card.host_register(ws)
    cands = section_card.note_candidates(_node(), ws, reg)
    texts = [c["text"] for c in cands]
    differ = next(c for c in cands if "MOTPRDCLU103" in c["text"] and "SQL Server cluster node" in c["text"])
    assert "MOTPRDSRV122.internal.qr.com.au on MOTPRDCLU103" in differ["text"]
    assert set(differ["ids"]) == {"E-010", "E-011"}
    assert any("recorded for 3 of 4 captured hosts" in t and "ROKPRDOPS110" in t for t in texts)
    assert any(t.startswith("sources disagree") for t in texts)
    assert not any("caption" in t for t in texts)          # not about time


def test_a_kept_fact_that_counts_hosts_is_marked_for_restating():
    hint = section_card.count_hint("Nine captured hosts synchronise from ROTPRDSRV122.")
    assert 'restate without "Nine captured hosts"' in hint and "role group" in hint
    assert section_card.count_hint("The RevServer nodes synchronise from ROTPRDSRV122.") == ""


def test_a_restated_kept_fact_passes_when_it_cites_the_same_capture():
    node = _node()
    card = _card(node)
    card["keep"] = [{"question": "B1", "fact": "Nine captured hosts synchronise from ROTPRDSRV122.",
                     "evidence_ids": ["E-001"], "capture_ids": ["E-001"]}]
    sheet = _sheet(card, "None: every captured host fits a row of the table.")
    res = A.validate(sheet, card)
    assert "CAPTURE_DROPPED" not in _codes(res) and "NO_TOTALS" not in _codes(res)
