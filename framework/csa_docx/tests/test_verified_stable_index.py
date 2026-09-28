"""Stable IDs are positional; the apply step must check the record's 'currently' quote."""
from types import SimpleNamespace as P

from csa_docx.engines.docxengine_adapter import verified_stable_index

WHERE = '`@H5.9.2-P5` -- currently: "Both IAMPS production servers keep a connection open ..."'


def paras(*texts):
    return [P(text=t) for t in texts]


def test_id_still_right():
    ps = paras("Heading", "Both IAMPS production servers keep a connection open into TCSI.")
    assert verified_stable_index(WHERE, ps, "@H5.9.2-P5", {"@H5.9.2-P5": 1}) == (1, None)


def test_shifted_id_is_relocated_to_the_quoted_paragraph():
    # an earlier edit inserted a paragraph, so P5 now points at the empty paragraph before the target
    ps = paras("Heading", "new text", "", "Both IAMPS production servers keep a connection open into TCSI.")
    assert verified_stable_index(WHERE, ps, "@H5.9.2-P5", {"@H5.9.2-P5": 2}) == (3, None)


def test_ambiguous_or_missing_quote_blocks():
    ps = paras("", "something else")
    idx, why = verified_stable_index(WHERE, ps, "@H5.9.2-P5", {"@H5.9.2-P5": 0})
    assert idx is None and "does not match" in why


def test_no_quote_keeps_id_only_behaviour():
    assert verified_stable_index("`@H5.9.2-P5`", paras("", "x"), "@H5.9.2-P5", {"@H5.9.2-P5": 0}) == (0, None)
