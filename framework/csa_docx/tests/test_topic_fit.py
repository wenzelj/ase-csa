"""A Fact belongs to the subsection whose topic it states."""
from csa_docx import answer_sheet as A
from csa_docx import scope_map, topic_fit as T

CARD = {"number": "3.4", "title": "Time Synchronisation", "key": "TIME",
        "questions": [{"id": "B1", "kind": "requirement"}, {"id": "B3", "kind": "narrative"}]}
MATRIX = {
    "E-097": {"claim": "Active Directory / Kerberos: domain authentication unavailable; the jump hosts lose administrative access", "csa_area": "identity_authentication"},
    "E-1249": {"claim": "Time source on MOTPRDCLU101: ROTPRDSRV122", "csa_area": "time_synchronisation"},
}


def sheet(*facts):
    return A.parse("## B1 x\nFacts:\n" + "\n".join(f"- {t} ({i}) {{observed}}" for t, i in facts) + "\nRating: Not Met\n")


def run(s):
    return [f for f in T.topic_checks(s, CARD, MATRIX, A._f)]


def test_a_fact_about_another_subsections_topic_is_flagged_with_where_it_belongs():
    out = run(sheet(("During an isolation event the General Purpose Jump Hosts lose their administrative access because their "
                     "remote access depends on enterprise domain authentication through Kerberos.", "E-097")))
    assert len(out) == 1 and out[0]["code"] == "FACT_OFF_TOPIC" and "3.2" in out[0]["message"] and "3.4" in out[0]["message"]


def test_a_time_fact_and_a_fact_filed_for_this_topic_are_not():
    assert run(sheet(("The hosts take their time from ROTPRDSRV122 at stratum 4.", "E-1249"))) == []
    assert run(sheet(("Domain authentication is unavailable.", "E-1249"))) == []          # a row filed for this topic keeps it


def test_one_passing_word_does_not_place_a_fact_elsewhere():
    assert run(sheet(("The hosts hold authentication connections.", "E-1"))) == []


def test_drawbridge_and_cross_cutting_subsections_are_never_judged():
    card = dict(CARD, number="3.12", title='Isolation & Resilience Validation ("Drawbridge")')
    assert T.topic_checks(sheet(("Kerberos authentication is lost during isolation.", "E-097")), card, MATRIX, A._f) == []
    narrative = A.parse("## B3 x\nFacts:\n- Kerberos authentication and domain controller access is lost. (E-097) {observed}\n")
    assert T.topic_checks(narrative, CARD, MATRIX, A._f) == []                              # only requirement blocks are judged


def test_the_warning_is_a_content_warning_that_does_not_block():
    assert A.tier_of({"level": "WARN", "code": "FACT_OFF_TOPIC"}) == "content" and "FACT_OFF_TOPIC" not in A.RELAXED_HARD
