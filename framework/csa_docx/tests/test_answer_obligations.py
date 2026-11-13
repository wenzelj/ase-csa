from csa_docx.answer_obligations import build


def test_obligations_are_scoped_and_include_retention_digest_and_findings():
    card = {
        "ratings": ["Met", "Not Met"], "requirement_stories": True,
        "questions": [{"id": "B1", "kind": "requirement", "text": "Can it operate?"},
                      {"id": "B2", "kind": "observation", "text": "What is present?", "columns": ["Aspect", "Observed"]}],
        "evidence": {"B1": {"rows": [{"id": "E-2"}], "digest_ids": ["E-3"]}},
        "keep": [{"question": "B1", "fact": "Keep this", "evidence_ids": ["E-1"]}],
        "frame": {"must_address": {"B1": [{"slot": "S1", "text": "state the fallback", "ids": ["E-4"], "must_state": True}]}}
    }
    result = build(card, only=["B1"])
    assert set(result["blocks"]) == {"B1"}
    b1 = result["blocks"]["B1"]
    assert b1["evidence_ids"] == ["E-2"]
    assert b1["digest_ids"] == ["E-3"]
    assert b1["must_preserve"][0]["evidence_ids"] == ["E-1"]
    assert b1["findings"][0]["must_state"] is True


def test_obligations_do_not_invent_rows_or_scope():
    result = build({"questions": [{"id": "B1", "kind": "observation", "text": "x"}], "evidence": {}})
    assert result["blocks"]["B1"]["evidence_ids"] == []
    assert result["blocks"]["B1"]["must_preserve"] == []
