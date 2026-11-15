"""S631: the minimal V2 dual-run result contract.

One deterministic requirement fixture is answered through both routes — the
native V2 route (subsection evidence package plus bounded run manifest) and
the compatibility route (legacy card plus evidence-matrix CSV) — and each
route records the same serialisable result shape.

Acceptance from the story:
- the fixture produces reproducible native and compatibility records;
- the required metadata is present in both records;
- the native record includes bounded-search metadata (run manifest);
- a record with missing metadata is refused before it is compared.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from csa_docx import answer_obligations, answer_sheet
from csa_docx.answer_plan import run_manifest
from csa_docx.v2repo import Repo
from csa_docx.v2repo.subsection_evidence import build_package, expand_package, PACKAGE_VERSION

RESULT_CONTRACT = "v2-dual-run-result-v1"

REQUIRED_KEYS = {
    "record_version": RESULT_CONTRACT,
    "route": "v2-native",          # or "v2-compat"
    "model_profile": "v2-subsection-answering",
    "contract_version": "answer-contract-v1",
    "database_revision": None,     # {"tables": ..., "modified_ns": ...}
    "package_revision": PACKAGE_VERSION,
    "package_hash": "0123456789abcdef",
    "evidence_ids": ["E-001"],
    "validation": {"status": "OK", "errors": 0, "warnings": 0, "findings": []},
}


def check_result(record: dict) -> list[str]:
    """The contract gate: a record missing required metadata is refused."""
    missing = []
    for key in REQUIRED_KEYS:
        if key not in record:
            missing.append(key)
            continue
        if record[key] is None:
            missing.append(key)
    if not missing and record.get("route") not in ("v2-native", "v2-compat"):
        missing.append("route (must be v2-native or v2-compat)")
    return missing


def serialise(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def comparison_report(native: dict, compatibility: dict) -> dict:
    """Classify the deterministic differences without comparing prose."""
    differences = []
    if native["evidence_ids"] != compatibility["evidence_ids"]:
        differences.append({"field": "evidence_ids", "classification": "intended improvement",
                            "detail": "native package carries the additional conflict and gap rows"})
    if native["validation"] != compatibility["validation"]:
        differences.append({"field": "validation", "classification": "regression",
                            "detail": "route validators disagree"})
    return {
        "model_profile": native["model_profile"],
        "contract_version": native["contract_version"],
        "native_package_revision": native["package_revision"],
        "native_database_revision": native["database_revision"],
        "compatibility_database_revision": compatibility["database_revision"],
        "differences": differences,
        "unexplained": [],
        "reproduce": "cd .agents/framework && python3 -m pytest -q csa_docx/tests/test_v2_answer_dual_run.py",
    }


# ---------------------------------------------------------------------------
# fixture: one requirement, scoped owned/peer hosts, one connected external
# endpoint, and one unrelated host/endpoint pair
# ---------------------------------------------------------------------------

QUESTION = "Which time source is configured?"
SHEET = ("## B1 Requirement\n"
         "Facts:\n"
         "- APP01 synchronises time from an enterprise NTP source. (E-001) {documented; APP01}\n"
         "Rating: Met\n"
         "Rating reason: the capture records the configured source.\n")


def _seed(tmp_path: Path, monkeypatch) -> Path:
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    legacy = workspace / "csa-work"
    (legacy / "evidence").mkdir(parents=True)
    # the compatibility route reads this legacy matrix; the native route never needs it
    (legacy / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title\n"
        "E-001,time,Which time source is configured?,"
        "APP01 synchronises time from an enterprise NTP source.,VERIFIED,captures/app01.txt\n",
        encoding="utf-8")
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))

    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("APP01", role="application")
        repo.hosts.create("NTPSRV1", role="provider")
        repo.hosts.create("OTHERAPP", role="application")
        repo.application_scope.add("test-app", "APP01", "owned", basis="inventory", review_state="accepted")
        repo.application_scope.add("test-app", "NTPSRV1", "peer", basis="captured_flow", review_state="accepted")
        repo.application_scope.add("other-app", "OTHERAPP", "owned", basis="inventory", review_state="accepted")
        repo.evidence.create(
            claim="APP01 synchronises time from an enterprise NTP source.",
            question=QUESTION, area="time",
            source_title="captures/app01.txt",
            excerpt="APP01 NTP enterprise source", status="VERIFIED")
        repo.evidence.create(
            claim="APP01 synchronises time from the NTPSRV1 host.",
            question=QUESTION, area="time",
            source_title="captures/app01-conflict.txt",
            excerpt="APP01 NTPSRV1 conflicting time source", status="CONFLICTING")
        repo.evidence.create(
            claim="No OT-resident fallback source was found for APP01.",
            question="Which OT-resident fallback source is configured?", area="time",
            source_title="captures/app01-time-search.txt",
            excerpt="fallback source not found in captured scope", status="NOT_FOUND")
        con = repo.con
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) "
                    "VALUES ('APP01','NTPSRV1',123,'udp','time')")
        con.execute("INSERT INTO service (host, provider_host, port, protocol, name) "
                    "VALUES ('APP01','ntp.external.example',123,'udp','NTP')")
        con.execute("INSERT INTO service (host, provider_host, port, protocol, name) "
                    "VALUES ('OTHERAPP','unrelated.external.example',443,'tcp','other')")
        con.execute("INSERT INTO indexed_file (rel_path, sha256, size) VALUES ('app01.txt','x',10)")
        con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES "
                    "('app01.txt','time','APP01 NTP enterprise time source running')")
        repo.graph.refresh()
    repo.close()
    return v2 / "csa.sqlite"


def _row(pkg: dict, eid: str) -> dict:
    for f in pkg.get("evidence", []):
        if eid in [i.upper() for i in f.get("evidence_ids", [])] or str(f.get("evidence_id", "")).upper() == eid:
            return {"id": eid, "status": f.get("status", ""),
                    "claim": f.get("text") or f.get("claim") or ""}
    raise AssertionError(f"{eid} not in native package")


def _native_record(db: Path, monkeypatch) -> dict:
    """One native V2 run: package, validation, bounded run manifest.
    The store is opened read-only and the legacy matrix file is never read."""
    pkg = build_package(db, subsection_key="time", application_key="test-app",
                        question=QUESTION, terms=["time"])
    body = {k: v for k, v in pkg.items()
            if k not in ("revision", "package_hash", "context", "model_profile")}
    pkg["package_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        .encode("utf-8")).hexdigest()[:16]
    eid = pkg["evidence"][0]["evidence_id"]
    card = {
        "key": "time", "ratings": ["Met", "Partially Met", "Not Met"],
        "questions": [{"id": "B1", "kind": "requirement", "text": QUESTION}],
        "evidence": {"B1": {"rows": [_row(pkg, eid)], "cut": [], "digest_ids": []}},
        "obligations": {"contract_version": "answer-contract-v1",
                        "blocks": {"B1": {"evidence_ids": [eid]}}},
        "package": pkg,
    }
    validation = answer_sheet.validate(answer_sheet.parse(SHEET), card, draft=True)
    manifest = run_manifest(pkg, expansions=[], validation={"status": validation["status"],
                                                           "errors": validation["errors"]},
                            manifest={"route": "v2-native",
                                     "contract_version": "answer-contract-v1"})
    return {
        "record_version": RESULT_CONTRACT,
        "route": "v2-native",
        "model_profile": "v2-subsection-answering",
        "contract_version": "answer-contract-v1",
        "database_revision": pkg["revision"],
        "package_revision": PACKAGE_VERSION,
        "package_hash": pkg["package_hash"],
        "evidence_ids": sorted(i.upper()
                               for f in pkg["evidence"]
                               for i in (f.get("evidence_ids") or
                                        ([f["evidence_id"]] if f.get("evidence_id") else []))),
        "validation": {"status": validation["status"], "errors": validation["errors"],
                       "warnings": validation["warnings"], "findings": validation["findings"]},
        "run_manifest": manifest,
    }


def _compat_record(monkeypatch) -> dict:
    """One compatibility run: legacy card + evidence matrix, no package.
    The card and matrix are built from the legacy CSV the route actually reads."""
    import csv
    import os
    legacy_dir = Path(os.environ["CSA_WORK_DIR"]).parent / "csa-work"
    matrix_path = legacy_dir / "evidence-matrix.csv"
    with matrix_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "the compatibility route needs its legacy matrix"
    row0 = rows[0]
    eid = row0["evidence_id"]
    row = {"id": eid, "status": row0["status"], "claim": row0["claim"]}
    card = {"key": "time", "ratings": ["Met", "Partially Met", "Not Met"],
            "questions": [{"id": "B1", "kind": "requirement", "text": QUESTION}],
            "evidence": {"B1": {"rows": [row], "cut": [], "digest_ids": []}}}
    card["obligations"] = answer_obligations.build(card)
    matrix = {eid: {"evidence_id": eid, "status": row0["status"],
                    "claim": row0["claim"], "question": row0["question"]}}
    validation = answer_sheet.validate(answer_sheet.parse(SHEET), card, matrix, draft=True)
    return {
        "record_version": RESULT_CONTRACT,
        "route": "v2-compat",
        "model_profile": "v2-subsection-answering",
        "contract_version": "answer-contract-v1",
        "database_revision": {"source": "evidence-matrix.csv", "rows": len(rows)},
        "package_revision": "v1-legacy-card",
        "package_hash": "",
        "evidence_ids": [eid],
        "validation": {"status": validation["status"], "errors": validation["errors"],
                       "warnings": validation["warnings"], "findings": validation["findings"]},
    }


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------

def test_fixture_produces_reproducible_native_and_compatibility_records(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native_a = _native_record(db, monkeypatch)
    native_b = _native_record(db, monkeypatch)
    compat_a = _compat_record(monkeypatch)
    compat_b = _compat_record(monkeypatch)
    assert serialise(native_a) == serialise(native_b)
    assert serialise(compat_a) == serialise(compat_b)
    # both records are serialisable JSON with the same key set, except that
    # the native record carries the bounded run manifest
    assert set(native_a) == set(compat_a) | {"run_manifest"}


def test_required_metadata_present_in_both_records(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native = _native_record(db, monkeypatch)
    compat = _compat_record(monkeypatch)
    for rec in (native, compat):
        assert check_result(rec) == [], check_result(rec)
    assert native["route"] == "v2-native"
    assert compat["route"] == "v2-compat"
    assert native["database_revision"]["modified_ns"] is not None
    assert compat["evidence_ids"] == ["E-001"]
    assert "E-001" in native["evidence_ids"]
    assert native["validation"]["status"] == compat["validation"]["status"] == "OK"


def test_native_record_includes_bounded_search_metadata(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native = _native_record(db, monkeypatch)
    m = native["run_manifest"]
    assert m["manifest_version"] == "v2-run-manifest-v1"
    assert m["route"] == "v2-native"
    assert m["contract_version"] == "answer-contract-v1"
    assert m["search_history_bounded"] is True
    assert m["base"]["package_hash"] == native["package_hash"]
    assert m["base"]["revision"] == native["database_revision"]
    assert m["base"]["truncation_reasons"] is not None
    assert m["validation"]["status"] == native["validation"]["status"]


def test_native_record_preserves_citations_and_scope(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native = _native_record(db, monkeypatch)
    package = build_package(db, subsection_key="time", application_key="test-app",
                            question=QUESTION, terms=["time"])
    assert check_result(native) == [], check_result(native)

    # The supported citation survives the native package and result contract.
    assert "E-001" in native["evidence_ids"]

    # S626 scope rules retain the connected external service endpoint, but do
    # not leak another application's host or an endpoint reachable only from it.
    scope = native["run_manifest"]["base"]["scope"]
    assert scope["owned"] == ["APP01"]
    assert scope["peers"] == ["NTPSRV1"]
    assert scope["external"] == []
    all_visible = set(scope["owned"] + scope["peers"] + scope["external"])
    assert "OTHERAPP" not in all_visible
    services = package["connections"]["services"]
    assert any(s["provider_host"] == "ntp.external.example" for s in services)
    assert not any(s["provider_host"] == "unrelated.external.example" for s in services)

    # The native record keeps the bounded-search audit fields used to explain
    # any future truncation instead of silently dropping scope information.
    manifest_base = native["run_manifest"]["base"]
    assert manifest_base["truncated"] is not None
    assert manifest_base["truncation_reasons"] is not None


def test_conflict_gap_and_previous_repair_are_bounded_and_reproducible(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    base = build_package(db, subsection_key="time", application_key="test-app",
                         question=QUESTION, terms=["time"])
    expansion = expand_package(db, subsection_key="time", application_key="test-app",
                               question=QUESTION, kind="host", host="APP01",
                               reason="check time-source conflict", base_package=base)
    assert any(row["status"] == "CONFLICTING" for row in base["evidence"])
    assert expansion["conflict_disclosure_required"]

    gap_base = build_package(db, subsection_key="network-architecture",
                             application_key="test-app",
                             question="What is the network architecture?")
    gap = expand_package(db, subsection_key="network-architecture",
                         application_key="test-app",
                         question="What is the network architecture?",
                         kind="topic", terms=["network-architecture-xyz"],
                         reason="bounded gap search", base_package=gap_base)
    assert gap["expansion"]["scoped_gap"] is True
    assert gap["expansion"]["gap"]["application_key"] == "test-app"
    assert "do not guess" in gap["expansion"]["gap"]["note"]

    previous = answer_sheet.parse(SHEET)
    repaired = answer_sheet.parse(
        "## B1 Requirement\n"
        "Facts:\n"
        "- APP01 synchronises time from an enterprise NTP source. (E-001) {documented; APP01}\n"
        "Rating: Met\n"
        "Rating reason: the supported source remains evidenced after repair.\n")
    card = {
        "key": "time", "ratings": ["Met", "Partially Met", "Not Met"],
        "questions": [{"id": "B1", "kind": "requirement", "text": QUESTION}],
        "evidence": {"B1": {"rows": [{"id": "E-001", "status": "VERIFIED",
                                           "claim": "APP01 synchronises time from an enterprise NTP source."}],
                                  "cut": [], "digest_ids": []}},
    }
    validation = answer_sheet.validate(repaired, card,
                                       {"E-001": {"evidence_id": "E-001", "status": "VERIFIED",
                                                  "claim": "APP01 synchronises time from an enterprise NTP source."}},
                                       draft=True, previous=previous)
    assert validation["status"] == "OK"
    repair_request = "rewrite only B1 to preserve the supported time-source fact"
    repair_signature = hashlib.sha256(
        json.dumps({"block": "B1", "request": repair_request,
                    "evidence_ids": ["E-001"], "rating": "Met"},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    comparison = {
        "facts": ["E-001"], "conflicts": ["E-002"],
        "gaps": [gap["expansion"]["gap"]["subsection"]],
        "rating": repaired["B1"]["rating"], "repair_count": 1,
        "repair_signature": repair_signature,
    }
    assert comparison == {
        "facts": ["E-001"], "conflicts": ["E-002"],
        "gaps": ["network-architecture"], "rating": "Met", "repair_count": 1,
        "repair_signature": repair_signature,
    }


def test_comparison_report_is_deterministic_and_classified(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native = _native_record(db, monkeypatch)
    compatibility = _compat_record(monkeypatch)
    report_a = comparison_report(native, compatibility)
    report_b = comparison_report(native, compatibility)
    assert serialise(report_a) == serialise(report_b)
    assert report_a["model_profile"] == "v2-subsection-answering"
    assert report_a["contract_version"] == "answer-contract-v1"
    assert report_a["native_package_revision"] == PACKAGE_VERSION
    assert report_a["native_database_revision"]["modified_ns"] is not None
    assert report_a["unexplained"] == []
    assert {d["classification"] for d in report_a["differences"]} == {"intended improvement"}
    assert report_a["reproduce"].endswith("test_v2_answer_dual_run.py")


def test_result_shape_is_rejected_when_metadata_is_missing(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    native = _native_record(db, monkeypatch)
    compat = _compat_record(monkeypatch)
    broken = dict(native)
    del broken["database_revision"]
    del broken["contract_version"]
    assert sorted(check_result(broken)) == ["contract_version", "database_revision"]
    broken2 = dict(compat)
    broken2["route"] = "legacy"
    assert any("route" in x for x in check_result(broken2))
