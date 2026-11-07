"""UNKNOWN_BUNDLED counts questions, not every 'which': an owner clause or 'to which' is not a separate question."""

from csa_docx.answer_sheet import _QRELATIVE, _QWORD


def n(u):
    return len(_QWORD.findall(_QRELATIVE.sub(" ", u)))


def test_owner_clause_and_relative_are_not_questions():
    assert n("which time connections were observed to which servers, which the network owner could confirm.") == 1
    assert n("whether any part of the hierarchy is OT-resident, which the Active Directory owners could confirm.") == 1


def test_real_bundle_still_counts():
    assert n("which functions keep working, whether the clock holds and how long the fallback lasts") == 3
