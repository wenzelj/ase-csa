"""S623 acceptance: versioned, deterministic V2 subsection evidence contracts.

Covers every acceptance criterion in the story:
- contracts are serialisable, versioned and deterministic;
- every requested block receives an explicit contract or a documented fallback;
- the contract distinguishes required, optional and prohibited content;
- a contract cannot widen application scope implicitly;
- existing legacy cards remain readable.
"""
from __future__ import annotations

import json

import pytest

from csa_docx import section_card
from csa_docx.v2repo import subsection_contract as SC


def _contract(**kw):
    return SC.build("DNS", "Which DNS servers are configured?", **kw)


def test_contract_is_versioned_serialisable_and_deterministic():
    a = _contract()
    b = _contract()
    assert a["contract_version"] == SC.VERSION
    assert a == b
    assert a["fingerprint"] == b["fingerprint"]
    # Round-trips through JSON without losing structure.
    rt = SC.build(**(_roundtrip(a)))
    assert rt == a
    assert len(SC.render(a).encode("utf-8")) <= SC.MAX_BYTES
    # metadata() is a view over the same body.
    m = SC.metadata(a)
    assert m["contract_version"] == SC.VERSION
    assert m["fingerprint"] == a["fingerprint"]
    assert m["application_view"] == "owned"


def _roundtrip(contract: dict) -> dict:
    # Re-derive the build() options from a serialised contract body.
    body = contract["body"]
    return {
        "subsection_key": contract["section"],
        "question_text": contract["question"],
        "application_view": body["view"]["application_view"],
        "scope_rule": body["view"]["scope_rule"],
        "relationship_kinds": list(body["graph"]["allowed_relationship_kinds"]),
        "evidence_areas": list(body["evidence"]["areas"]),
        "source_fields": list(body["evidence"]["source_fields"]),
        "required_facts": list(body["answer"]["required_facts"]),
        "answer_obligations": list(body["answer"]["obligations"]),
        "rating_rule": body["answer"]["rating_rule"],
        "freshness": body["handling"]["freshness"],
        "not_found_handling": body["handling"]["not_found"],
        "conflict_handling": body["handling"]["conflict"],
        "citation_rule": body["handling"]["citations"],
        "context_limit": body["handling"]["context_limit"],
    }


def test_every_block_gets_an_explicit_contract_or_documented_fallback():
    # A key with no specialised contract still returns a valid contract.
    c = SC.build("Name Resolution and Discovery")
    assert c["classification"] == "fallback"
    assert c["body"]["answer"]["required_facts"]
    assert c["body"]["answer"]["obligations"]
    assert c["body"]["evidence"]["classes"]
    # A documented fallback means the fallback content is named and non-empty,
    # and the lookup is explicit: the framework infers no specialised contract
    # from a key.
    assert SC.specialisation_for("Name Resolution and Discovery") is None


def test_specialised_contract_when_opted_in():
    # The framework never infers a specialised contract from a key alone; a
    # caller can still opt one in explicitly. With SPECIALISED_KEYS empty the
    # lookup returns None for any key.
    assert SC.specialisation_for("DNS") is None
    assert SC.build("DNS")["classification"] == "fallback"
    # But a caller may supply a specialised body and it is applied.
    c = SC.build("DNS", "q", specialised=True,
                 specialised_body={"view": {"scope_rule": "owned_hosts_only"}})
    assert c["classification"] == "specialised"
    assert c["body"]["view"]["scope_rule"] == "owned_hosts_only"


def test_contract_distinguishes_required_optional_prohibited():
    c = _contract()
    content = c["body"]["content"]
    assert set(content) == {"required", "optional", "prohibited"}
    assert content["required"]
    assert content["optional"]
    # prohibited content must be an explicit, non-trivial list.
    assert content["prohibited"]
    # the three lists are disjoint so a fact is never required and prohibited
    assert not (set(content["required"]) & set(content["prohibited"]))
    assert not (set(content["optional"]) & set(content["prohibited"]))


def test_contract_cannot_widen_application_scope_implicitly():
    owned = SC.build("DNS", "q", application_view="owned")
    app = SC.build("DNS", "q", application_view="application")
    glob = SC.build("DNS", "q", application_view="global")
    assert owned["body"]["view"]["application_view"] == "owned"
    assert app["body"]["view"]["application_view"] == "application"
    assert glob["body"]["view"]["application_view"] == "global"
    # A default build never widens scope: it stays at the narrowest view.
    assert SC.build("DNS", "q")["body"]["view"]["application_view"] == "owned"
    # widening is only detected when a caller explicitly moves up a view.
    assert not SC.check_widening(owned, owned)
    assert SC.check_widening(owned, app)
    assert SC.check_widening(app, glob)
    assert not SC.check_widening(glob, app)
    # Every contract declares it does not widen scope implicitly.
    for c in (owned, app, glob):
        assert c["widens_scope"] is False


def test_contract_covers_required_fields():
    c = _contract()
    b = c["body"]
    # visible key and question text
    assert c["section"] == "DNS"
    assert c["question"]
    # required facts and answer obligations
    assert b["answer"]["required_facts"]
    assert b["answer"]["obligations"]
    # evidence areas and source fields
    assert b["evidence"]["areas"]
    assert b["evidence"]["source_fields"]
    # allowed application view
    assert b["view"]["application_view"] in SC.VALID_VIEWS
    # host, service, provider and endpoint scope rules
    assert set(b["scope"]) == {"hosts", "services", "providers", "endpoints"}
    # required evidence classes and rating rules
    assert b["evidence"]["classes"]
    assert b["answer"]["rating_rule"]
    # conflict, freshness and NOT_FOUND handling
    assert b["handling"]["conflict"]
    assert b["handling"]["freshness"]
    assert b["handling"]["not_found"]
    # allowed graph relationship kinds
    assert b["graph"]["allowed_relationship_kinds"]
    # citation requirements and bounded context limits
    assert b["handling"]["citations"]
    assert b["handling"]["context_limit"]


def test_invalid_view_is_rejected():
    with pytest.raises(ValueError):
        SC.build("DNS", "q", application_view="tenants")


def test_invalid_freshness_is_rejected():
    with pytest.raises(ValueError):
        SC.build("DNS", "q", freshness="stale")


def test_missing_key_is_rejected():
    with pytest.raises(ValueError):
        SC.build("", "q")


def test_relationship_kinds_are_a_subset_of_allowed():
    c = SC.build("DNS", "q", relationship_kinds=("runs", "service"))
    assert c["body"]["graph"]["allowed_relationship_kinds"] == ("runs", "service")
    # an unknown kind is filtered out, never admitted.
    d = SC.build("DNS", "q", relationship_kinds=("runs", "tenant_link"))
    assert "tenant_link" not in d["body"]["graph"]["allowed_relationship_kinds"]
    assert d["body"]["graph"]["allowed_relationship_kinds"] == ("runs",)


def test_section_card_card_includes_subsection_contract():
    # The card exposes the contract, so every requested block receives one.
    node = {"key": "DNS01", "title": "DNS", "number": "3.1", "kind": "requirement",
            "parent": None, "path": "DNS", "parts": [], "facets": {}}
    spec = {"nodes": [node], "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"]}
    card = section_card.card(node, spec, None, evidence=False)
    assert "subsection_contract" in card
    sub = card["subsection_contract"]
    assert sub["contract_version"] == SC.VERSION
    assert sub["section"] == "DNS01"
    assert sub["classification"] in ("specialised", "fallback")
    # legacy card shape is preserved: the existing keys a reader expects survive.
    for k in ("status", "key", "number", "title", "text", "questions", "obligations"):
        assert k in card
    assert card["status"] == "OK"
    assert card["key"] == "DNS01"


def test_section_card_adds_v2_writing_purpose_and_current_content():
    node = {"key": "GROUP_POLICY_OBSERVATIONS", "title": "Group Policy Observations", "number": "4.9",
            "kind": "narrative", "parent": None, "path": "Group Policy Observations", "facets": {},
            "parts": [{"kind": "narrative", "facet": "Group Policy Observations",
                       "text": "Existing Group Policy observations."}]}
    spec = {"nodes": [node], "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"]}
    card = section_card.card(node, spec, None, evidence=False)
    assert "Group Policy observations" in card["writing_purpose"]
    assert card["current_content"][0]["text"] == "Existing Group Policy observations."
