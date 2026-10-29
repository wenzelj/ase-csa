"""Repairs the framework makes itself (no model call) and the content / wording tiers of warnings."""
from csa_docx import answer_sheet as A
from csa_docx import sheet_fixes as S

MATRIX = {
    "E-1": {"evidence_id": "E-1", "claim": "c", "source_title": "REVELOC_discovery_ROTPRDLOG102_20260605T014815Z: 23_process_connection_mapping.txt"},
    "E-2": {"evidence_id": "E-2", "claim": "c", "source_title": "Expected flow map workbook"},
    "E-3": {"evidence_id": "E-3", "claim": "c", "source_title": "User confirmation 2026-06-10"},
}


def test_a_line_with_two_self_contained_questions_becomes_two_lines():
    q = "What is the zone of the peer at 10.129.11.10, and which team owns the TETRA log server?"
    out, n = S.split_question_lines("## B3 x\nFacts:\n- f (E-1) {observed}\nQUESTION: " + q + "\nQUESTION: Who owns the host?\n")
    lines = [l for l in out.splitlines() if l.startswith("QUESTION:")]
    assert n == 1 and len(lines) == 3
    assert lines[0].endswith("10.129.11.10?") and lines[1] == "QUESTION: Which team owns the TETRA log server?"
    assert not [x for x in A.parse(out)["B3"]["unknown"] if A.bundled_unsplit(x)]


def test_a_second_question_that_leans_on_the_first_is_not_cut_off_but_reported():
    q = "What is the zone of the peer at 10.129.11.10, and what data does it read from the TETRA log server?"
    assert A.split_questions(q) == [q] and A.bundled_unsplit(q)
    out, n = S.split_question_lines("## B3 x\nQUESTION: " + q + "\n")
    assert n == 0 and out.count("QUESTION:") == 1
    assert A.tier_of({"level": "WARN", "code": "QUESTION_BUNDLED"}) == "content"


def test_relatives_and_single_questions_are_not_split():
    for q in ("Which hosts are in OT and are not patched?",
              "Which side of the OT boundary are the peers at 10.1.1.1 and 10.1.1.2 in?",
              "Is any share used to move files across the IT and OT boundary?"):
        assert A.split_questions(q) == [q]


def test_observed_facts_that_rest_on_documents_take_the_documented_basis():
    text = ("## B1 x\nFacts:\n- The flow map records RB2. (E-2) {observed; the expected flow map}\n"
            "- The owner states no fallback exists. (E-3) {observed}\n"
            "- A capture shows it. (E-1) {observed; ROTPRDLOG102}\n"
            "- Mixed. (E-1, E-2) {observed; ROTPRDLOG102}\n")
    out, changed = S.fix_basis(text, MATRIX)
    assert len(changed) == 2
    assert "{documented; the expected flow map}" in out and "{stated}" in out
    assert "(E-1) {observed; ROTPRDLOG102}" in out and "(E-1, E-2) {observed; ROTPRDLOG102}" in out


def test_a_fact_citing_a_row_the_matrix_lacks_is_left_alone():
    out, changed = S.fix_basis("## B1 x\nFacts:\n- A. (E-2, E-99) {observed}\n", MATRIX)
    assert not changed and "{observed}" in out


def test_normalise_reports_what_it_did_and_does_nothing_twice():
    text = "## B1 x\nFacts:\n- A. (E-2) {observed}\nQUESTION: Who owns the host, and which zone is the host in?\n"
    out, notes = S.normalise(text, {}, MATRIX)
    assert len(notes) == 2
    assert S.normalise(out, {}, MATRIX) == (out, [])


def test_tiers_blocking_content_wording():
    assert A.tier_of({"level": "ERROR", "code": "ANY"}) == "blocking"
    assert A.tier_of({"level": "WARN", "code": "SLOT_NOT_ANSWERED"}) == "content"
    assert A.tier_of({"level": "WARN", "code": "STORY_TOO_LONG"}) == "wording"
    assert A.tier_of({"level": "WARN", "code": "IP_IN_PROSE"}) == "wording"


TABLE_CARD = {"role_tables": [{"common": "All hosts in this table run the Windows Time Service, operate at stratum 5 and follow sources at stratum 4.",
                               "rows": [{"hosts": ["MKYPRDOPS110"], "cells": ["MOTPRDSRV122 (10.45.228.97)", "None", "32,768 s"]},
                                        {"hosts": ["IPTPRDAPP137"], "cells": ["MOTPRDSRV122 (10.45.228.97)", "time.windows.com (pending)", "1,024 s"]}]}]}


def test_a_setting_stated_for_hosts_is_covered_when_the_role_table_states_it():
    assert A.table_covers("Fallback time peer on MKYPRDOPS110: None", TABLE_CARD)
    assert A.table_covers("Fallback time peer on IPTPRDAPP137: time.windows.com (pending)", TABLE_CARD)
    assert A.table_covers("Host stratum on MKYPRDOPS110 and IPTPRDAPP137: 5", TABLE_CARD)
    assert A.table_covers("Time service on MKYPRDOPS110: Windows Time Service", TABLE_CARD)


def test_a_setting_the_table_does_not_state_is_not_covered():
    assert not A.table_covers("Fallback time peer on MKYPRDOPS110: pool.ntp.org", TABLE_CARD)
    assert not A.table_covers("Fallback time peer on MKYPRDOPS110 and ROTPRDLOG102: None", TABLE_CARD)     # a host not in the table
    assert not A.table_covers("Fallback time peer on MKYPRDOPS110: None", {})


def test_moving_a_table_covered_capture_out_of_the_prose_is_not_a_loss():
    claim = "Fallback time peer on MKYPRDOPS110: None"
    matrix = {"E-9": {"evidence_id": "E-9", "claim": claim, "status": "VERIFIED",
                      "source_title": "REVELOC_discovery_MKYPRDOPS110_20260605T020722Z: 03_time_status.txt"}}
    old = A.parse("## B2 x\nFacts:\n- It has none. (E-9) {observed; MKYPRDOPS110}\n")
    new = A.parse("## B2 x\nFacts:\n- Something else. (E-2) {documented}\n")
    codes = {f["code"] for f in A.regression(old, new, matrix, TABLE_CARD)}
    assert "CAPTURE_IN_TABLE" in codes and not codes & {"EVIDENCE_DROPPED", "SOURCE_DOWNGRADE", "CAPTURE_DROPPED"}
    assert A.tier_of({"level": "WARN", "code": "CAPTURE_IN_TABLE"}) == "wording"


def test_a_fact_that_only_says_the_evidence_does_not_answer_is_a_question_not_a_fact():
    card = {"questions": [{"id": "B1", "kind": "requirement", "text": "x", "req_id": "R"}], "evidence": {}}
    sheet = A.parse("## B1 x\nFacts:\n- The discovery captures and the supplied documents do not answer which time connections were observed to which servers. (E-2377) {documented; all captured role groups}\n"
                    "- The hosts run the Windows Time Service. (E-1253) {observed; all captured role groups}\n")
    res = A.validate(sheet, card, {}, draft=True, relaxed=True)
    hits = [f for f in res["findings"] if f["code"] == "GAP_AS_FACT"]
    assert len(hits) == 1 and "E-2377" not in hits[0]["message"] and "time connections" in hits[0]["message"]
    assert A.tier_of(hits[0]) == "content"


def test_a_question_an_earlier_block_already_asks_is_not_asked_again():
    sheet = ("## B3 x\nFacts:\n- f (E-1) {observed}\n"
             "QUESTION: What is the zone of the internal peer at 10.129.11.10, and what data does it read from the TETRA log server?\n"
             "QUESTION: Which security zone contains the Mackay Dell PowerProtect Data Manager MOTPRDPDM101?\n"
             "## B4 y\nFacts:\n- g (E-2) {observed}\n"
             "QUESTION: Which side of the OT boundary is the internal peer at 10.129.11.10 in?\n"
             "QUESTION: What data does the internal peer at 10.129.11.10 read from the TETRA log server?\n"
             "QUESTION: Which side of the OT boundary are the Dell PowerProtect Data Manager hosts MOTPRDPDM101 and ROTPRDPDM101 in?\n"
             "QUESTION: Is any fallback for the storage paths tested or documented?\n")
    out, dropped = S.dedupe_questions(sheet)
    kept = [l for l in out.splitlines() if l.startswith("QUESTION:")]
    assert len(dropped) == 2 and "10.129.11.10 in?" in dropped[0] and "read" in dropped[1]
    assert any("ROTPRDPDM101" in l for l in kept)             # a new endpoint (ROTPRDPDM101) is a new question: kept whole
    assert any("fallback" in l for l in kept) and sum("10.129.11.10" in l for l in kept) == 1


def test_a_question_with_no_endpoint_or_no_recognised_ask_is_never_dropped_and_blocks_go_by_number():
    s = ("## B2 b\nQUESTION: Is any fallback tested?\n## B1 a\nQUESTION: Is any fallback tested?\n"
         "QUESTION: Which side of OT is 10.1.1.1 in?\n## B3 c\nQUESTION: Which side of OT is 10.1.1.1 in?\n")
    out, dropped = S.dedupe_questions(s)
    assert out.count("Is any fallback tested?") == 2 and len(dropped) == 1 and dropped[0].startswith("B3")
    assert S.question_keys("What does the peer at 10.1.1.1 do for SMB?") == {("role", "10.1.1.1")}
    assert S.normalise(out, {}, {}) == (out, [])


def test_the_register_lists_a_repeated_question_once_with_where_else_it_is_raised():
    from csa_docx import draft_lane as DL
    groups = [
        {"label": "3.7 Storage (STOR)", "order": 1, "items": [
            ("B3", "Which security zone contains the Mackay Dell PowerProtect Data Manager MOTPRDPDM101? Same question for: ROTPRDPDM101."),
            ("B4", "whether a fallback backup procedure exists for isolation events")]},
        {"label": "3.11 Backup (BAK)", "order": 2, "items": [
            ("B1", "Which zones contain MOTPRDPDM101 and ROTPRDPDM101?"),
            ("B4", "whether a fallback backup procedure exists for isolation events"),
            ("B4", "whether a fallback restore procedure exists for isolation events"),
            ("B4", "whether a fallback rebuild procedure exists for isolation events"),
            ("F1", "whether a fallback restore procedure exists for isolation events")]},
    ]
    merged = DL.merge_across_sections(groups)
    first, second = groups
    assert merged == 3
    assert [i["qid"] for i in first["kept"]] == ["B3", "B4"]
    assert first["kept"][0]["also"] == ["3.11 Backup (BAK) [B1]"]               # same endpoints, another section
    assert first["kept"][1]["also"] == ["3.11 Backup (BAK) [B4]"]               # the same words, another section
    kept = [i["text"] for i in second["kept"]]
    assert kept == ["whether a fallback restore procedure exists for isolation events",
                    "whether a fallback rebuild procedure exists for isolation events"]    # restore and rebuild are not backup
    assert second["kept"][0]["also"] == ["[F1]"]                                # the same section: by block only
