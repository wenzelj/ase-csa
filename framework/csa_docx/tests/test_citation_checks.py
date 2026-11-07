"""Citation relevance, basis, capture preference, unused evidence and regression checks on an answer sheet."""
from csa_docx import answer_sheet as A

CAPTURE = "REVELOC_discovery_ROTPRDCLU101_20260709T042915Z: 03_time_status.txt"
PREV = "NetSeg_Current_State_Assessment_X.docx | Time Synchronization"

MATRIX = {
    "E-001": {"evidence_id": "E-001", "status": "VERIFIED", "source_title": CAPTURE, "question": "", "gap_or_action": ""},
    "E-002": {"evidence_id": "E-002", "status": "VERIFIED", "source_title": PREV, "question": "", "gap_or_action": ""},
    "E-463": {"evidence_id": "E-463", "status": "NOT_FOUND", "source_title": "searched files", "gap_or_action": "",
              "question": "Is a documented fallback recorded for the S01 operational storage (SEP-STOR-01)?"},
}
CARD = {"key": "TIME", "questions": [{"id": "B1", "kind": "requirement"}],
        "evidence": {"B1": {"rows": [{"id": "E-001", "status": "VERIFIED", "claim": "ROTPRDCLU101 takes time from ROTPRDSRV122"},
                                     {"id": "E-002", "status": "VERIFIED", "claim": "old"}], "cut": [], "digest_ids": []}}}


def _sheet(fact):
    return A.parse(f"## B1 Time\nFacts:\n- {fact}\nText:\nThe hosts take their time from enterprise servers.\n"
                   "Rating: Not Met\nRating reason: No OT source was identified.\n")


def _codes(res):
    return {f["code"]: f for f in res["findings"]}


def test_absence_row_for_another_subsection_is_refused():
    sh = _sheet("No fallback test record was identified for time synchronisation. (E-463) {observed; all hosts}")
    res = A.validate(sh, CARD, MATRIX, draft=True)
    assert res["status"] == "ERROR" and _codes(res)["CITATION_OFF_TOPIC"]["level"] == "ERROR"


def test_absence_row_for_this_subsection_is_accepted():
    m = {**MATRIX, "E-463": {**MATRIX["E-463"], "question": "Is an OT time source recorded (SEP-TIME-01)?"}}
    res = A.validate(_sheet("No OT time source was identified. (E-463) {observed; all hosts}"), CARD, m, draft=True)
    assert "CITATION_OFF_TOPIC" not in _codes(res)


def test_observed_basis_needs_a_capture_row():
    res = A.validate(_sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-002) {observed; ROTPRDCLU101}"), CARD, MATRIX, draft=True)
    assert "BASIS_NOT_OBSERVED" in _codes(res)
    ok = A.validate(_sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-001) {observed; ROTPRDCLU101}"), CARD, MATRIX, draft=True)
    assert "BASIS_NOT_OBSERVED" not in _codes(ok)


def test_prefers_the_capture_row_over_the_previous_assessment():
    res = A.validate(_sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-002) {documented; ROTPRDCLU101}"), CARD, MATRIX, draft=True)
    assert "PREFER_CAPTURE" in _codes(res) and "E-001" in _codes(res)["PREFER_CAPTURE"]["message"]


def test_unused_verified_rows_are_listed():
    res = A.validate(_sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-001) {observed; ROTPRDCLU101}"), CARD, MATRIX, draft=True)
    assert "E-002" in _codes(res)["EVIDENCE_UNUSED"]["message"]


def test_regression_reports_dropped_evidence_and_downgrade():
    old = _sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-001) {observed; ROTPRDCLU101}")
    new = _sheet("ROTPRDCLU101 takes time from ROTPRDSRV122. (E-002) {documented; ROTPRDCLU101}")
    codes = {f["code"] for f in A.regression(old, new, MATRIX)}
    assert {"EVIDENCE_DROPPED", "SOURCE_DOWNGRADE"} <= codes
