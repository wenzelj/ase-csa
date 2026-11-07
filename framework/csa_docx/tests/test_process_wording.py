"""Wording about the framework's own search must never reach the CSA document."""
from csa_docx import answer_sheet as A

CARD = {"questions": [{"id": "B1", "kind": "requirement"}], "evidence": {}}


def _sheet(fact: str, text: str) -> dict:
    return A.parse(f"## B1 Isolation\nFacts:\n- {fact} (E-001) {{observed; all in-scope systems}}\n"
                   f"Text:\n{text}\nRating: Not Met\nRating reason: No isolation test record was identified.\n")


def test_draft_lane_refuses_a_fact_about_the_matrix_and_index_search():
    bad = _sheet("The search of the matrix and index rows for this domain identified no isolation test record.",
                 "No isolation test record was identified.")
    res = A.validate(bad, CARD, draft=True)
    assert res["status"] == "ERROR"
    assert any(f["code"] == "PROCESS_AS_SUBJECT" for f in res["findings"])


def test_draft_lane_refuses_the_same_wording_in_text():
    bad = _sheet("No isolation test record appears in the discovery captures.",
                 "The matrix and index rows searched for this domain hold no isolation test record.")
    assert any(f["code"] == "PROCESS_AS_SUBJECT" for f in A.validate(bad, CARD, draft=True)["findings"])


def test_a_statement_about_the_system_and_its_real_sources_passes():
    ok = _sheet("No isolation test record appears in the twelve discovery captures or the supplied documents.",
                "No isolation test record appears in the twelve discovery captures or the supplied documents.")
    assert not any(f["code"] == "PROCESS_AS_SUBJECT" for f in A.validate(ok, CARD, draft=True)["findings"])
