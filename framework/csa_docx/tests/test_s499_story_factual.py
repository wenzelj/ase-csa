"""S499: a Story or note states observations, not conclusions or rating talk."""
from csa_docx import answer_sheet as A

BAD = [
    "Their time comes from the Windows Time client, so their time comes from it rather than a local source.",
    "The nodes sit behind the controllers, placing them one step behind the domain controllers.",
    "The missing fallback is the gap that decided this rating.",
]


def _codes(kind, **b):
    return [f["code"] for f in A.story_factual("R1", kind, b)]


def test_three_34_sentences_are_reported():
    assert "STORY_INFERS" in _codes("requirement", story=BAD[0])
    assert "STORY_INFERS" in _codes("requirement", story=BAD[1])
    assert "STORY_STATES_RATING" in _codes("requirement", story=BAD[2])
    assert all(f["level"] == "WARN" for f in A.story_factual("R1", "requirement", {"story": " ".join(BAD)}))


def test_note_is_checked_too():
    assert "STORY_INFERS" in _codes("note", facts=[], text=BAD[0])
    assert "STORY_STATES_RATING" in _codes("note", facts=[], text="The host is Not Met.")


def test_plain_observation_is_not_reported():
    plain = "HOSTCLU03 follows TIMESRV224 and HOSTCLU01 follows TIMESRV122. No local time source appears in the captures."
    assert _codes("requirement", story=plain) == []
    assert _codes("note", facts=[], text=plain) == []
