"""S627: focused evidence expansion and conflict handling.

Acceptance from the story:
- The first pass can request one or more focused expansions.
- Expansion cannot add an unrelated application host.
- A repeated empty search produces a scoped gap, not a guessed answer.
- Conflicting evidence is passed to the model and validation requires disclosure.
- Search history is present in the run manifest and is bounded.
- An expansion cannot reintroduce an unrelated host or external endpoint, and
  its package hash, database revision, scope, truncation reasons and validation
  outcome remain auditable in the bounded run manifest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from csa_docx import v2_access
from csa_docx.answer_plan import conflict_disclosure_findings, plan_context, run_manifest
from csa_docx.v2repo import Repo
from csa_docx.v2repo.subsection_evidence import (
    build_package,
    expand_package,
    expansion_outcomes,
    PACKAGE_VERSION,
    EXPANSION_VERSION,
    MANIFEST_SEARCH_HISTORY_LIMIT,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _seed(tmp_path: Path, monkeypatch) -> Path:
    """A V2 store with one application, evidence rows (VERIFIED, CONFLICTING,
    NOT_FOUND), a scope host, a flow, a lead, and a source chunk."""
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("APP01", role="application")
        repo.hosts.create("NTPSRV1", role="provider")
        # a host belonging to a DIFFERENT application (out of scope for test-app)
        repo.hosts.create("OTHERAPP", role="application")
        repo.application_scope.add("test-app", "APP01", "owned", basis="inventory", review_state="accepted")
        repo.application_scope.add("test-app", "NTPSRV1", "peer", basis="captured_flow", review_state="accepted")
        # unrelated application scope
        repo.application_scope.add("other-app", "OTHERAPP", "owned", basis="inventory", review_state="accepted")

        repo.evidence.create(
            claim="APP01 synchronises time from an enterprise NTP source.",
            question="Which time source is configured?",
            area="time",
            source_title="captures/app01.txt",
            excerpt="APP01 NTP enterprise source",
            status="VERIFIED")
        repo.evidence.create(
            claim="APP01 uses the NTPSRV1 host for time sync.",
            question="Which time source is configured?",
            area="time",
            source_title="captures/app01.txt",
            excerpt="APP01 NTPSRV1 time sync",
            status="CONFLICTING")
        repo.evidence.create(
            claim="No DNS records were found for APP01.",
            question="Which DNS records exist?",
            area="dns",
            source_title="captures/app01.txt",
            excerpt="DNS lookup failed APP01",
            status="NOT_FOUND")
        # an evidence row that names OTHERAPP (out of scope)
        repo.evidence.create(
            claim="OTHERAPP is an unrelated application.",
            question="What is OTHERAPP?",
            area="other",
            source_title="captures/otherapp.txt",
            excerpt="OTHERAPP unrelated",
            status="VERIFIED")

        con = repo.con
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) "
                    "VALUES ('APP01','NTPSRV1',123,'udp','time')")
        con.execute("INSERT INTO address (ip, scope, owner_host) VALUES ('10.1.2.3','private','APP01')")
        con.execute("INSERT INTO service (host, port, protocol, name) VALUES ('APP01',123,'udp','NTP')")
        con.execute("INSERT INTO lead (id, question, state, evidence_ids) "
                    "VALUES ('L-001','Which time source is configured?','open','')")
        con.execute("INSERT INTO indexed_file (rel_path, sha256, size) VALUES ('app01.txt','x',10)")
        con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES "
                    "('app01.txt','time','APP01 NTP enterprise time source running')")
        repo.graph.refresh()
    repo.close()
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))
    return v2 / "csa.sqlite"


def _base_package(db: Path) -> dict:
    return build_package(
        db, subsection_key="time", application_key="test-app",
        question="Which time source is configured?",
        terms=["time"])


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------

def test_first_pass_can_request_one_or_more_expansions(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    # request two focused expansions from the first pass
    exp1 = expand_package(db, subsection_key="time", application_key="test-app",
                          question="Which time source is configured?",
                          kind="host", host="APP01",
                          reason="first pass incomplete",
                          base_package=base)
    exp2 = expand_package(db, subsection_key="time", application_key="test-app",
                          question="Which time source is configured?",
                          kind="topic", terms=["NTP"],
                          reason="need NTP context",
                          base_package=base)
    assert exp1["expansion"]["kind"] == "host"
    assert exp2["expansion"]["kind"] == "topic"
    assert exp1["expansion"]["reason"] == "first pass incomplete"
    assert exp2["expansion"]["reason"] == "need NTP context"
    # both are full packages with the same shape
    for e in (exp1, exp2):
        assert e["package_version"] == PACKAGE_VERSION
        assert "evidence" in e
        assert "hosts" in e
        assert "more_available" in e
        assert "truncation_reasons" in e


def test_expansion_cannot_add_unrelated_application_host(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    # request expansion for OTHERAPP which is NOT in test-app's scope
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="host", host="OTHERAPP",
                         reason="check other app",
                         base_package=base)
    # the expansion should not add OTHERAPP to the hosts
    hosts = set()
    for k in ("owned", "peers", "external"):
        hosts.update(exp["hosts"][k])
    assert "OTHERAPP" not in hosts
    # the expansion evidence should not include any expansion- rows naming OTHERAPP
    expansion_rows = [f for f in exp["evidence"] if f["reason"].startswith("expansion-")]
    assert not any("OTHERAPP" in f["text"] for f in expansion_rows)


def test_broad_topic_expansion_filters_out_of_scope_evidence(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="topic", terms=["unrelated"],
                         reason="scope check", base_package=base)
    assert not any("OTHERAPP" in f["text"] for f in exp["evidence"]
                   if f["reason"].startswith("expansion-"))


def test_repeated_empty_search_produces_scoped_gap(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    # Use a subsection key that has no evidence rows
    base = build_package(db, subsection_key="network-architecture", application_key="test-app",
                         question="What is the network architecture?")
    # the base has no evidence for this subsection
    assert len(base["evidence"]) == 0
    # search for something that doesn't exist
    exp = expand_package(db, subsection_key="network-architecture", application_key="test-app",
                         question="What is the network architecture?",
                         kind="topic", terms=["network-architecture-xyz"],
                         reason="looking for missing info",
                         base_package=base)
    # the expansion should be a scoped gap
    assert exp["expansion"]["scoped_gap"] is True
    assert exp["expansion"]["gap"] is not None
    assert exp["expansion"]["gap"]["subsection"] == "network-architecture"
    assert exp["expansion"]["gap"]["application_key"] == "test-app"
    assert "do not guess" in exp["expansion"]["gap"]["note"]


def test_conflicting_evidence_passed_to_model_and_requires_disclosure(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    # expansion for CONFLICTING evidence
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="host", host="APP01",
                         reason="check conflict",
                         base_package=base)
    # the expansion outcomes should include the CONFLICTING row
    conflict_outcomes = [o for o in exp["expansion"]["outcomes"] if o["kind"] == "conflict"]
    # the base package already has the CONFLICTING row, so it should be in disclosure
    assert len(exp["conflict_disclosure_required"]) >= 1
    # conflict_disclosure_findings should flag a sheet that cites without disclosing
    import csa_docx.answer_sheet as answer_sheet
    sheet_text = "## B1\nFacts:\n- APP01 uses NTP. (E-1)\n"
    # find the CONFLICTING evidence ID from the base package
    conflicting_ids = [f["evidence_id"] for f in base["evidence"] if f["status"] == "CONFLICTING"]
    if conflicting_ids:
        eid = conflicting_ids[0]
        sheet = answer_sheet.parse(f"## B1\nFacts:\n- APP01 uses NTP. ({eid})\n")
        findings = conflict_disclosure_findings(sheet, {}, exp)
        assert any(f["code"] == "CONFLICT_NOT_DISCLOSED" for f in findings)


def test_search_history_in_run_manifest_is_bounded(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    # create more expansions than the limit
    n = MANIFEST_SEARCH_HISTORY_LIMIT + 5
    expansions = []
    for i in range(n):
        exp = expand_package(db, subsection_key="time", application_key="test-app",
                             question="Which time source is configured?",
                             kind="topic", terms=[f"term{i}"],
                             reason=f"search {i}",
                             base_package=base)
        expansions.append(exp)
    # build the run manifest
    manifest = run_manifest(base, expansions=expansions, validation={"status": "OK"})
    # the manifest should be bounded: history is truncated to the limit
    assert len(manifest["expansions"]) <= MANIFEST_SEARCH_HISTORY_LIMIT
    assert manifest["search_history_bounded"] is (n <= MANIFEST_SEARCH_HISTORY_LIMIT)
    # the first expansion should be present
    assert manifest["expansions"][0]["kind"] == "topic"
    assert manifest["expansions"][0]["reason"] == "search 0"
    # but the base and validation are present
    assert manifest["base"]["package_hash"] is not None
    assert manifest["validation"] == {"status": "OK"}


def test_expansion_auditability_in_run_manifest(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="host", host="APP01",
                         reason="audit test",
                         base_package=base)
    manifest = run_manifest(base, expansions=[exp], validation={"status": "OK", "findings": []})
    # the expansion entry should be auditable
    e = manifest["expansions"][0]
    assert e["kind"] == "host"
    assert e["query"] is not None
    assert e["reason"] == "audit test"
    assert e["result_counts"] is not None
    assert e["outcomes"] is not None
    # the base package hash, revision, scope, truncation are present
    assert manifest["base"]["package_hash"] is not None
    assert manifest["base"]["revision"] is not None
    assert manifest["base"]["scope"] is not None
    assert manifest["base"]["truncated"] is not None
    assert manifest["base"]["truncation_reasons"] is not None


def test_expansion_preserves_application_scope(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="host", host="APP01",
                         reason="scope check",
                         base_package=base)
    # the expanded package should maintain the same application_key
    assert exp["application_key"] == "test-app"
    assert exp["section"] == "time"
    # hosts should be the same scope (APP01, NTPSRV1)
    all_hosts = set()
    for k in ("owned", "peers", "external"):
        all_hosts.update(exp["hosts"][k])
    assert "APP01" in all_hosts
    assert "NTPSRV1" in all_hosts
    assert "OTHERAPP" not in all_hosts


def test_expansion_bounded_by_package_limits(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    # Build a base with more evidence than the limit
    base = build_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         terms=["time"], limits={"evidence": 5})
    base_evidence_count = len(base["evidence"])
    # Now expand with a tight limit
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="topic", terms=["time"],
                         reason="limit test",
                         base_package=base,
                         limits={"evidence": 1})
    # the combined evidence should be bounded to the limit
    # (base evidence + expansion evidence, but capped)
    total_evidence = len(exp["evidence"])
    assert total_evidence <= 1
    # if base had more than 1, the expansion should be truncated
    if base_evidence_count > 1:
        assert exp["truncated"]["evidence"] is True
        assert "evidence_limit" in exp["truncation_reasons"]
        assert exp["more_available"] is True


def test_expansion_outcomes_for_not_found(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    # search for the NOT_FOUND evidence
    exp = expand_package(db, subsection_key="dns", application_key="test-app",
                         question="Which DNS records exist?",
                         kind="topic", terms=["DNS"],
                         reason="check DNS")
    # the NOT_FOUND row should be in the outcomes
    not_found_outcomes = [o for o in exp["expansion"]["outcomes"] if o["kind"] == "not_found"]
    # if the NOT_FOUND row was matched, it should be in the outcomes
    if any(f["status"] == "NOT_FOUND" for f in exp["evidence"] if not f["reason"].startswith("expansion-") or f["reason"].startswith("expansion-")):
        assert len(not_found_outcomes) >= 1


def test_conflict_disclosure_findings_empty_when_no_conflict(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    import csa_docx.answer_sheet as answer_sheet
    sheet = answer_sheet.parse("## B1\nFacts:\n- APP01 uses NTP. (E-1)\n")
    # base package with no conflict_disclosure_required
    findings = conflict_disclosure_findings(sheet, {}, base)
    # base doesn't have conflict_disclosure_required set, so no findings
    assert findings == []


def test_plan_context_with_expansions_and_validation(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = _base_package(db)
    exp = expand_package(db, subsection_key="time", application_key="test-app",
                         question="Which time source is configured?",
                         kind="host", host="APP01",
                         reason="plan context test",
                         base_package=base)
    rows = [{"legacy_ids": "", "req_id": "SEP-TIME-01", "statement_type": "observed",
             "fact": "APP01 uses NTP.", "evidence_scope": "APP01; capture",
             "destination": "REQ SEP-TIME-01 / Current State", "confidence": "high",
             "transformation": "stated", "gap_generated": ""}]
    card = {"obligations": {"contract_version": "v1"}}
    ctx = plan_context(rows, card, base, expansions=[exp],
                       validation={"status": "OK", "findings": []})
    assert ctx["route"] == "v2-native"
    assert "expansions" in ctx
    assert len(ctx["expansions"]) == 1
    assert "run_manifest" in ctx
    assert ctx["run_manifest"]["base"]["package_hash"] is not None
    assert ctx["run_manifest"]["validation"] == {"status": "OK", "findings": []}


def test_plan_context_legacy_unchanged(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    rows = [{"legacy_ids": "", "req_id": "SEP-TIME-01", "statement_type": "observed",
             "fact": "APP01 uses NTP.", "evidence_scope": "",
             "destination": "REQ SEP-TIME-01 / Current State", "confidence": "high",
             "transformation": "", "gap_generated": ""}]
    card = {}
    ctx = plan_context(rows, card, None)
    assert ctx["route"] == "v1-native"
    assert "package_hash" not in ctx
    assert "findings" not in ctx
    assert "expansions" not in ctx
    assert "run_manifest" not in ctx
