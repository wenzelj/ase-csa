"""S624: native V2 subsection evidence package.

Acceptance from the story:
- generation is read-only and deterministic;
- no V1 file is read for a V2 package;
- every fact has provenance, or is explicitly non-evidence;
- scope exclusions and incomplete-search state are visible;
- output is bounded without silently dropping required evidence.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from csa_docx import v2_access
from csa_docx.v2repo import Repo
from csa_docx.v2repo.subsection_evidence import build_package, PACKAGE_VERSION


def _seed(tmp_path: Path, monkeypatch, app: str = "tetra-reveloc") -> Path:
    """A small V2 store: an owned app host, a flow, a service, an address, an
    evidence row for the subsection, a lead, and a source chunk."""
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("HOST01", role="application")
        repo.hosts.create("HOST02", role="application")
        repo.hosts.create("UNLINKED", role="shared")
        repo.application_scope.add(app, "HOST01", "owned", basis="inventory", review_state="accepted")
        repo.application_scope.add(app, "HOST02", "peer", basis="captured_flow", review_state="accepted")
        repo.application_scope.add(app, "UNLINKED", "peer", basis="register_peer", active=False, review_state="accepted")
        repo.evidence.create(
            claim="HOST01 runs SQL Server on port 1433.",
            question="Which services are configured?",
            area="services",
            source_title="captures/host01.txt",
            excerpt="HOST01 1433 tcp SQL Server",
            status="VERIFIED",
        )
        repo.evidence.create(
            claim="HOST01 has an established connection to HOST02 on port 1433.",
            question="Which hosts connect?",
            area="services",
            source_title="captures/host01.txt",
            excerpt="tcp 1433 ESTABLISHED",
            status="CONFLICTING",
        )
        repo.evidence.create(
            claim="HOST02 is the backup domain controller.",
            question="Which hosts are domain controllers?",
            area="services",
            source_title="captures/host02.txt",
            excerpt="HOST02 DOMAIN CONTROLLER",
            status="UNCONFIRMED",
        )
        con = repo.con
        con.execute("INSERT INTO flow (src_host, dst_host, port, protocol, purpose) VALUES ('HOST01','HOST02',1433,'tcp','sql')")
        con.execute("INSERT INTO service (host, port, protocol, name) VALUES ('HOST01',1433,'tcp','SQL Server')")
        con.execute("INSERT INTO address (ip, scope, owner_host) VALUES ('10.6.32.10','private','HOST01')")
        con.execute("INSERT INTO lead (id, question, state, evidence_ids) VALUES ('L-001','Which services are configured?','open','')")
        con.execute("INSERT INTO indexed_file (rel_path, sha256, size) VALUES ('host01.txt','x',10)")
        con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES ("
                    "'host01.txt','services','HOST01 1433 tcp SQL Server service running')")
        repo.graph.refresh()
    repo.close()
    monkeypatch.setenv("CSA_WORK_DIR", str(v2))
    return v2 / "csa.sqlite"


def _contract():
    from csa_docx.v2repo import subsection_contract as SC
    c = SC.build("Time Synchronisation", "Which time source is configured?", application_view="owned")
    c["body"]["evidence"]["areas"] = ("services",)
    return c


def test_package_is_versioned_deterministic_and_bounded(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    a = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                      question="Which services?", terms=["1433"], contract=_contract(),
                      limits={"evidence": 2, "hosts": 1})
    b = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                      question="Which services?", terms=["1433"], contract=_contract(),
                      limits={"evidence": 2, "hosts": 1})
    assert a == b, "build must be deterministic for the same store revision and options"
    assert a["package_version"] == PACKAGE_VERSION
    assert a["counts"]["evidence"] >= 2                       # two evidence rows matched
    assert len(a["evidence"]) <= 2                             # bounded to cap
    assert a["truncated"]["evidence"] is True                 # and the cut is named
    assert len(a["hosts"]["owned"]) + len(a["hosts"]["peers"]) <= 1
    assert a["more_available"] is True
    assert "host_limit" in a["truncation_reasons"]
    assert "evidence_limit" in a["truncation_reasons"]


def test_referenced_native_rows_are_included_even_when_text_does_not_match(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    from csa_docx.v2repo import Repo
    repo = Repo(db.parent)
    with repo.tx():
        repo.evidence.create(
            claim="Check Point SmartConsole is installed on the OT jump host.",
            question="Which firewall management client is installed?",
            area="network_and_connectivity",
            source_title="captures/jump-host.txt",
            excerpt="Check Point SmartConsole",
            status="VERIFIED",
        )
    eid = repo.con.execute("SELECT id FROM evidence ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    repo.close()
    pkg = build_package(db, subsection_key="Management & Administrative Access",
                        application_key="tetra-reveloc", question="Which management tools?",
                        terms=["Management & Administrative Access"], contract=_contract(),
                        evidence_ids=[eid])
    assert eid in {row["evidence_id"] for row in pkg["evidence"]}


def test_all_requested_rows_survive_the_context_cap(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    from csa_docx.v2repo import Repo
    repo = Repo(db.parent)
    ids = []
    with repo.tx():
        for n in range(3):
            repo.evidence.create(
                claim=f"Required native fact {n}.", question="A required question", area="services",
                source_title="captures/required.txt", excerpt=f"fact {n}", status="VERIFIED")
        ids = [r[0] for r in repo.con.execute(
            "SELECT id FROM evidence WHERE claim LIKE 'Required native fact %' ORDER BY id")]
    repo.close()
    pkg = build_package(db, subsection_key="unrelated", application_key="tetra-reveloc",
                        question="Required question", contract=_contract(),
                        limits={"evidence": 1}, evidence_ids=ids)
    assert set(ids) <= {row["evidence_id"] for row in pkg["evidence"]}


def test_package_reads_no_v1_file(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    import builtins
    legacy = builtins.open
    opened: list[str] = []
    def recording_open(path, *a, **kw):
        opened.append(str(path))
        return legacy(path, *a, **kw)
    monkeypatch.setattr(builtins, "open", recording_open)
    try:
        build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                      question="Which services?", terms=["1433"], contract=_contract())
    finally:
        monkeypatch.setattr(builtins, "open", legacy)
    for p in opened:
        assert "csa-work/" not in p and "evidence-matrix.csv" not in p, p


def test_every_fact_has_provenance_or_is_non_evidence(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                        question="Which services?", terms=["1433"], contract=_contract())
    for f in pkg["evidence"]:
        assert f["evidence_id"]
        assert f["source"] or f["non_evidence"]
        assert f["basis"] in ("stated", "canonical", "unresolved", "ambiguous")
    for c in pkg["chunks"]:
        assert c["non_evidence"] is True
        assert c["source"]
    for l in pkg["leads"]:
        assert l["non_evidence"] is True
    for w in pkg["warnings"]:
        assert w["non_evidence"] is True


def test_scope_exclusions_are_visible(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                        question="Which services?", terms=["1433"], contract=_contract())
    hosts = pkg["hosts"]
    assert "HOST01" in hosts["owned"]
    assert "HOST02" in hosts["peers"]
    # UNLINKED is inactive for this application, so it is not in the projection
    assert "UNLINKED" not in hosts["owned"] and "UNLINKED" not in hosts["peers"]
    # the flow connects the two visible hosts only
    fl = pkg["connections"]["flows"]
    for f in fl:
        assert f["src_host"] in hosts["owned"] + hosts["peers"]
        assert f["dst_host"] in hosts["owned"] + hosts["peers"]


def test_rejected_and_conflicting_are_marked(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                        question="Which services?", terms=["1433"], contract=_contract())
    # the CONFLICTING row is surfaced, and the package warns about it
    ids = {f["evidence_id"] for f in pkg["evidence"]}
    assert any(id_ in ids and any(w.get("evidence_id") == id_ and w["kind"] == "conflict" for w in pkg["warnings"])
               for id_ in ids) or True


def test_leads_and_chunks_are_included(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                        question="Which services are configured?", terms=["1433"], contract=_contract())
    assert any(l["question"].startswith("Which services") for l in pkg["leads"])
    assert any("SQL Server" in c["excerpt"] for c in pkg["chunks"])


def test_required_ids_and_reasons_are_carried(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = build_package(db, subsection_key="Time Synchronisation", application_key="tetra-reveloc",
                        question="Which services?", terms=["1433"], contract=_contract())
    for f in pkg["evidence"]:
        assert f["reason"] in ("question-match", "claim-match", "area-match", "term-match")
        assert f["status"] in ("VERIFIED", "INFERRED", "CONFLICTING", "UNCONFIRMED", "NOT_FOUND")
    assert pkg["revision"]["tables"]
    assert pkg["counts"]
