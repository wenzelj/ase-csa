"""S505/S508: prose that says "the captured hosts" is reported as FRAMEWORK_TERM (error)."""
import pytest

from csa_docx import answer_sheet as A

CARD = {"questions": [{"id": "B1", "kind": "requirement", "text": "y"}]}


def run(text):
    sheet = {"B1": {"summary": "", "text": text, "facts": [], "bullets": [], "rows": []}}
    return [f for f in A.framework_term_checks(sheet, CARD) if f["code"] == "FRAMEWORK_TERM"]


@pytest.mark.parametrize("text", [
    "The captured hosts derive time from the enterprise time servers.",
    "The captured OT hosts follow ROTPRDSRV122, and captured hosts also use it.",
    "Time is recorded for 3 of 5 captured hosts.",
])
def test_errors(text):
    got = run(text)
    assert len(got) == 1 and got[0]["level"] == "ERROR"


@pytest.mark.parametrize("text", [
    "The hosts take their time from ROTPRDSRV122.",
    "QUESTION: Which captured hosts have no fallback peer?",
])
def test_does_not_error(text):
    assert not run(text)
