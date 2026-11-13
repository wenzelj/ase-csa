"""NO_TOTALS rejects estate totals without mistaking compound nouns for host counts."""

from csa_docx.answer_sheet import totals_in


def test_host_estate_totals_are_rejected():
    assert totals_in("Nine captured hosts use enterprise DNS.") == "Nine captured hosts"
    assert totals_in("Two application servers use the listener.") == "Two application servers"
    assert totals_in("9 of 12 were captured.") == "9 of 12"


def test_configuration_object_counts_are_not_host_totals():
    assert totals_in("The server holds two hosts-file entries for private endpoints.") is None
    assert totals_in("Four enterprise resolver addresses are configured.") is None
    assert totals_in("The path uses ports 25 and 587.") is None


def test_the_host_count_the_card_gives_is_allowed_and_no_other():
    assert totals_in("Group Policy was read for 19 hosts.", frozenset({19})) is None
    assert totals_in("Group Policy was read for 18 hosts.", frozenset({19})) == "18 hosts"
    assert totals_in("Group Policy was read for 19 hosts.") == "19 hosts"
    assert totals_in("Seven hosts, 9 of 12.", frozenset({7, 9, 12})) == "9 of 12"


def _count_errors(text, card):
    from csa_docx import answer_sheet as A
    sheet = A.parse(f"## B1 Group Policy Observations\nFacts:\n- The hosts apply it. (E-001) {{observed; H1}}\nText:\n{text}\n")
    res = A.validate(sheet, dict(card, questions=[{"id": "B1", "kind": "narrative"}],
                                 evidence={"B1": {"rows": [{"id": "E-001", "status": "VERIFIED", "claim": "x"}], "cut": [], "digest_ids": []}}),
                     {"E-001": {"evidence_id": "E-001", "status": "VERIFIED", "source_title": "x", "question": "", "gap_or_action": "", "claim": "x"}},
                     draft=True)
    return [f for f in res["findings"] if f["code"] == "NO_TOTALS"]


def test_the_count_in_a_role_table_is_allowed_in_the_text_and_another_is_not():
    card = {"key": "GPO", "role_table": {"hosts_covered": ["H1", "H2", "H3"]}}
    assert not _count_errors("Group Policy was read on 3 hosts of the system.", card)
    assert _count_errors("Group Policy was read on 4 hosts of the system.", card)
    assert _count_errors("Group Policy was read on 3 hosts of the system.", {"key": "GPO"})


def test_a_year_is_not_a_host_count():
    assert totals_in("MOTPRDLOG103 apply a 2019 baseline with Log Server firewall policies.") is None
    assert totals_in("The Sepura Radio Manager server applies a 2022 baseline set.") is None
    assert totals_in("Nineteen hosts and 19 hosts and 2019 hosts") == "Nineteen hosts" or totals_in("19 hosts apply it.") == "19 hosts"
