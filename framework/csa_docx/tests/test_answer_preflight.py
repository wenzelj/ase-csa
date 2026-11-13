from csa_docx.answer_preflight import findings


def _card():
    return {"obligations": {"contract_version": "answer-contract-v1", "blocks": {"B1": {}}},
            "evidence": {"B1": {"rows": [{"id": "E-1", "claim": "APPHOST1 is outside OT."}]}},
            "questions": [{"id": "B1", "kind": "requirement"}]}


def test_preflight_rejects_wrong_zone_host():
    sheet = {"B1": {"facts": [{"text": "APPHOST2 is in OT.", "ids": ["E-1"]}]}}
    got = findings(sheet, _card())
    assert any(x["code"] == "ZONE_FACT_NOT_BACKED" for x in got)


def test_preflight_rejects_missing_or_unknown_evidence():
    sheet = {"B1": {"facts": [{"text": "The service is present.", "ids": []},
                                {"text": "Another fact.", "ids": ["E-9"]}]}}
    got = findings(sheet, _card())
    assert {x["code"] for x in got} == {"FACT_NO_EVIDENCE", "UNKNOWN_EVIDENCE"}


def test_legacy_card_without_obligations_is_unchanged():
    assert findings({"B1": {"facts": []}}, {"evidence": {}}) == []
