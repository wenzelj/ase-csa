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
