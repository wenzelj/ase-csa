"""S498: a rating reason must rest on an observation, not on absence."""
from csa_docx import answer_sheet as A


def _block(reason, unknown=("Which side of OT are the sources on?",)):
    return {"R1": {"rating": "Not Met", "rating_reason": reason, "unknown": list(unknown)}}


def _codes(sheet):
    return [f["code"] for f in A.rating_from_absence(sheet)]


def test_absence_reason_with_open_question_warns():
    out = A.rating_from_absence(_block("No OT-resident time source was identified."))
    assert [f["code"] for f in out] == ["RATING_FROM_ABSENCE"] and out[0]["level"] == "WARN"
    assert "undetermined" in out[0]["message"]


def test_observed_reason_with_evidence_ids_does_not_warn():
    reason = "The sources are domain controllers of the enterprise domain (E-003, E-004), not OT-resident."
    assert _codes(_block(reason)) == []


def test_absence_reason_without_open_question_does_not_warn():
    assert _codes(_block("No OT-resident time source was identified.", unknown=())) == []
