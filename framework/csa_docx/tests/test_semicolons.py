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


def test_no_ids_strips_bracketed_evidence_ids_without_leaving_brackets():
    # Evidence IDs are stripped; the brackets/parens that held them go with them,
    # so no [] or [,,] artifacts reach the document.
    assert A.no_ids("events [E-487]") == "events"
    assert A.no_ids("[E-218, E-219, E-220, E-221]") == ""
    assert A.no_ids("hosts [E-043, E-097] use AD") == "hosts use AD"
    assert A.no_ids("all 12 captured hosts, indexed discovery searches [E-468]") == "all 12 captured hosts, indexed discovery searches"
    assert A.no_ids("enterprise NTP (E-063, E-112)") == "enterprise NTP"
    # Brackets that carry real content are left alone.
    assert A.no_ids("keep [Optional note: x]") == "keep [Optional note: x]"
