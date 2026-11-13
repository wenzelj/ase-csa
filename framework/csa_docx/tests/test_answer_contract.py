from csa_docx import answer_contract, rules_digest


def test_contract_is_bounded_deterministic_and_versioned():
    first = answer_contract.build()
    second = answer_contract.build()
    assert first.version == "answer-contract-v1"
    assert first.text == second.text == answer_contract.render()
    assert len(first.text.encode("utf-8")) <= answer_contract.MAX_BYTES
    assert "ZONE_FACT_NOT_BACKED" in first.text
    assert "RETENTION" in first.text


def test_rules_digest_exposes_contract():
    text = rules_digest.answer_contract()
    assert text.startswith("ANSWER CONTRACT: answer-contract-v1")
    assert rules_digest.answer_contract() == text
