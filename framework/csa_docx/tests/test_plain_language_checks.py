from csa_docx import answer_sheet as a

CARD = {"questions": [{"id": "B1", "kind": "requirement", "text": "SEP-DNS-01 resolve names"},
                      {"id": "B2", "kind": "requirement", "text": "Which hosts use which DNS servers?"}]}


def codes(sheet):
    return [(f["code"], f["question"]) for f in a.plain_language_checks(sheet, CARD)]


def test_host_name_and_shorthand_are_flagged():
    sheet = {"B1": {"summary": "Servers use ROTPRDSRV122 and MOTPRDSRV122 as a resolver pair.", "story": "", "text": ""}}
    got = codes(sheet)
    assert ("HOST_IN_PROSE", "B1") in got
    assert ("JARGON_SHORTHAND", "B1") in got


def test_plain_prose_passes():
    sheet = {"B1": {"summary": "The Reveloc servers ask two corporate DNS servers for names. No fallback was found.",
                    "story": "", "text": ""}}
    assert not [c for c in codes(sheet) if c[0] in ("HOST_IN_PROSE", "JARGON_SHORTHAND")]


def test_question_asking_for_hosts_may_name_them():
    sheet = {"B2": {"summary": "ROTPRDSRV122 serves the Mackay hosts.", "story": "", "text": ""}}
    assert ("HOST_IN_PROSE", "B2") not in codes(sheet)


def test_codes_are_content_warnings():
    assert {"HOST_IN_PROSE", "JARGON_SHORTHAND"} <= a.CONTENT_CODES
