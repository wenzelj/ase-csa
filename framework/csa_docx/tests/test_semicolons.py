"""No semicolons in text that lands in the CSA document."""
from csa_docx import answer_sheet as A
from csa_docx.check_change import semicolon_text


def test_check_change_finds_a_semicolon_in_prose_and_in_a_current_state():
    assert semicolon_text("The hosts take time from IT; no OT source exists.")
    assert semicolon_text("All hosts use enterprise DNS; there is no fallback. | Not Met")
    assert semicolon_text("Plain sentence. | Met") is None


def test_check_change_leaves_data_tables_alone():
    assert semicolon_text("Resolvers | 10.1.1.1; 10.1.1.2 | all captured hosts") is None


def test_draft_lane_refuses_a_semicolon_in_text():
    card = {"questions": [{"id": "B1", "kind": "requirement"}], "evidence": {}}
    sheet = A.parse("## B1 Time\nFacts:\n- The log server takes time from ROTPRDSRV122. (E-001) {observed; ROTPRDLOG102}\n"
                    "Text:\nThe log server takes time from an enterprise domain controller; no OT source exists.\n"
                    "Rating: Not Met\nRating reason: No OT source was identified.\n")
    res = A.validate(sheet, card, draft=True)
    assert res["status"] == "ERROR" and any(f["code"] == "SEMICOLON" for f in res["findings"])
    ok = A.parse("## B1 Time\nFacts:\n- The log server takes time from ROTPRDSRV122. (E-001) {observed; ROTPRDLOG102}\n"
                 "Text:\nThe log server takes time from an enterprise domain controller. No OT source was identified.\n"
                 "Rating: Not Met\nRating reason: No OT source was identified.\n")
    assert not any(f["code"] == "SEMICOLON" for f in A.validate(ok, card, draft=True)["findings"])
