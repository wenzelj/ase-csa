from csa_docx import answer_sheet as A

CARD = {"questions": [{"id": "B1", "kind": "findings"}],
        "frame": {"scope_terms": ["share", "file transfer", "proxy"]}}


def _codes(*bullets, card=CARD):
    return [f["code"] for f in A.findings_scope_checks({"B1": {"bullets": list(bullets)}}, card)]


def test_identical_bullets_are_duplicates():
    b = "MOTPRDCLU103 and ROTPRDCLU104 each open a file share connection to the peer at 10.89.163.66. (E-1)"
    assert _codes(b, b) == ["DUPLICATE_BULLET"]


def test_same_hosts_and_evidence_in_other_words_are_duplicates():
    a = "ROTPRDCLU101 and ROTPRDCLU102 receive web proxy connections from OTPROXY. (E-5, E-6)"
    b = "OTPROXY gets web proxy connections from ROTPRDCLU101 and ROTPRDCLU102. (E-6, E-5)"
    assert _codes(a, b) == ["DUPLICATE_BULLET"]


def test_different_findings_pass():
    assert _codes("ROKPRDOPS110 offers a Music share. (E-1)", "ROKPRDOPS110 offers a Temp share. (E-2)") == []


def test_bullet_without_a_topic_word_is_out_of_scope():
    assert _codes("ROKPRDAMP101 opens database connections to ROTPRDCLU101. (E-9)") == ["OUT_OF_SCOPE"]


def test_no_scope_terms_means_no_scope_check():
    assert _codes("ROKPRDAMP101 opens database connections. (E-9)", card={"questions": CARD["questions"]}) == []


FRAME = {"questions": CARD["questions"],
         "frame": {"scope_terms": ["share", "file transfer", "putty"],
                   "table_patterns": [r"putty|filezilla|winscp"],
                   "bullet_max": [{"match": r"sysvol", "max": 1}]}}


def test_tool_bullet_repeats_the_table():
    assert _codes("The jump host has PuTTY and WinSCP installed for file transfer. (E-1)", card=FRAME) == ["REPEATS_TABLE"]


def test_second_sysvol_bullet_is_one_too_many():
    assert _codes("ROTPRDREV101 keeps the SysVol share open. (E-1)", "ROKPRDOPS110 keeps the sysvol share open. (E-2)", card=FRAME) == ["REPEATS_TABLE"]


def test_wrong_acronym_expansion_is_an_error():
    card = {"questions": CARD["questions"], "acronyms": {"TGOIP": "Tetra Gateway over IP"}}
    bad = {"B1": {"bullets": ["The Reveloc application and TGOIP (telephony gateway over IP) servers offer a share. (E-1)"]}}
    ok = {"B1": {"bullets": ["The TGOIP (Tetra Gateway over IP) servers offer a share. (E-1)", "The TGOIP servers offer a share. (E-2)"]}}
    isdef = {"B1": {"bullets": ["TGOIP is a technology that carries radio over IP. (E-1)"]}}
    assert [f["code"] for f in A.acronym_checks(bad, card)] == ["ACRONYM_EXPANSION"]
    assert A.acronym_checks(ok, card) == []
    assert [f["code"] for f in A.acronym_checks(isdef, card)] == ["ACRONYM_EXPANSION"]


def test_register_must_have_a_row_for_every_name():
    card = {"questions": [{"id": "B2", "kind": "register"}], "frame": {"register_names": ["Baseline GPO", "Default Trust Store"]}}
    sheet = {"B2": {"rows": [["GPO Name", "Category"], ["Baseline GPO", "baseline"]]}}
    got = A.register_completeness_checks(sheet, card)
    assert [f["code"] for f in got] == ["REGISTER_ROW_MISSING"] and "Default Trust Store" in got[0]["message"]
    sheet["B2"]["rows"].append(["default trust store", "trust"])
    assert A.register_completeness_checks(sheet, card) == []


def test_register_row_may_not_name_a_host_the_captures_do_not_show():
    card = {"questions": [{"id": "B2", "kind": "register"}],
            "frame": {"register_hosts": {"Applied on": {"Baseline GPO": ["ROTPRDLOG102"]}},
                      "hosts_covered": ["ROTPRDLOG102", "ROTPRDREV101"]}}
    good = {"B2": {"rows": [["GPO Name", "Applied on"], ["Baseline GPO", "OT TETRA Log Servers (ROTPRDLOG102) (E-1)"]]}}
    bad = {"B2": {"rows": [["GPO Name", "Applied on"], ["Baseline GPO", "ROTPRDLOG102 and ROTPRDREV101 (E-1)"]]}}
    assert A.register_host_checks(good, card) == []
    got = A.register_host_checks(bad, card)
    assert [f["code"] for f in got] == ["REGISTER_HOST_WRONG"] and "ROTPRDREV101" in got[0]["message"]


def test_register_row_that_names_hosts_must_name_every_host():
    card = {"questions": [{"id": "B2", "kind": "register"}],
            "frame": {"register_hosts": {"Applied on": {"Baseline GPO": ["ROTPRDLOG102", "ROTPRDREV101"]}},
                      "hosts_covered": ["ROTPRDLOG102", "ROTPRDREV101"]}}
    short = {"B2": {"rows": [["GPO Name", "Applied on"], ["Baseline GPO", "OT TETRA Log Server (ROTPRDLOG102)"]]}}
    roles_only = {"B2": {"rows": [["GPO Name", "Applied on"], ["Baseline GPO", "OT TETRA Log Servers and Reveloc servers"]]}}
    full = {"B2": {"rows": [["GPO Name", "Applied on"], ["Baseline GPO", "ROTPRDLOG102, ROTPRDREV101"]]}}
    got = A.register_host_checks(short, card)
    assert [f["code"] for f in got] == ["REGISTER_HOST_MISSING"] and "ROTPRDREV101" in got[0]["message"]
    assert A.register_host_checks(roles_only, card) == [] and A.register_host_checks(full, card) == []


def test_text_longer_than_the_frame_allows_is_an_error():
    card = {"questions": [{"id": "B1", "kind": "narrative"}], "frame": {"max_text_sentences": 2}}
    ok = {"B1": {"text": "One. Two."}}
    long = {"B1": {"text": "One. Two. Three."}}
    assert A.text_length_checks(ok, card) == []
    assert [f["code"] for f in A.text_length_checks(long, card)] == ["TEXT_TOO_LONG"]
    assert A.text_length_checks(long, {"questions": card["questions"], "frame": {}}) == []
