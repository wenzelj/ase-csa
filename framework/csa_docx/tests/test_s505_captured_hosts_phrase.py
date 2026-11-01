"""S505: CAPTURED_HOSTS_PHRASE warns when prose says "the captured hosts" instead of naming the system."""
import pytest

from csa_docx import answer_sheet as A

CARD = {"questions": [{"id": "B1", "kind": "requirement", "text": "y"}]}


def run(text):
    sheet = {"B1": {"summary": "", "text": text, "facts": [], "bullets": [], "rows": []}}
    return [f for f in A.captured_hosts_checks(sheet, CARD) if f["code"] == "CAPTURED_HOSTS_PHRASE"]


@pytest.mark.parametrize("text", [
    "The captured hosts derive time from the enterprise time servers.",
    "The captured OT hosts follow ROTPRDSRV122.",
])
def test_warns(text):
    got = run(text)
    assert len(got) == 1 and got[0]["level"] == "WARN"


@pytest.mark.parametrize("text", [
    "The hosts take their time from ROTPRDSRV122.",
    "QUESTION: Which captured hosts have no fallback peer?",
    "Time is recorded for 3 of 5 captured hosts.",
])
def test_does_not_warn(text):
    assert not run(text)
