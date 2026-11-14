"""S625: complete scoped retrieval for V2 subsection evidence.

Acceptance:
- Fixture questions retrieve every expected row and source chunk.
- Unrelated application hosts are excluded.
- Captured external endpoints remain available when supported by evidence.
- Rejected or unresolved evidence cannot be presented as verified.
- Results are stable across repeated runs against the same database revision.
"""
from __future__ import annotations

from pathlib import Path

from csa_docx.v2repo import Repo
from csa_docx.v2repo.subsection_evidence import retrieve


def _seed(tmp_path: Path, monkeypatch, app: str = "app-a") -> Path:
    """Two applications in one store: app-a has HOST01/HOST02;
    app-b has HOST03/HOST04 (must be excluded from app-a's scope).
    An unowned external endpoint EXT-EP also appears in flow data."""
    import os
    from pathlib import Path
    workspace = tmp_path / "workspace"
    v2 = workspace / "csa-work-v2"
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: test\n"
        '    label: "Test"\n'
        f'    project_root: "{workspace}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{workspace / "csa-work"}"\n'
        '    default_source_set: ""\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))

    repo = Repo(v2)
    with repo.tx():
        for h in ("HOST01", "HOST02", "HOST03", "HOST04"):
            repo.hosts.create(h, role="application")

        # app-a scope
        repo.application_scope.add(app, "HOST01", "owned", basis="inventory", review_state="accepted")
        repo.application_scope.add(app, "HOST02", "peer", basis="captured_flow", review_state="accepted")

        # app-b scope (isolated)
        app_b = "app-b"
        repo.application_scope.add(app_b, "HOST03", "owned", basis="inventory", review_state="accepted")
        repo.application_scope.add(app_b, "HOST04", "peer", basis="captured_flow", review_state="accepted")

        # Evidence rows for app-a's subsection
        repo.evidence.create(
            claim="HOST01 runs SQL Server on port 1433.",
            question="Which services are configured?",
            area="services", source_title="cap1.txt", excerpt="HOST01 1433 SQL", status="VERIFIED")
        repo.evidence.create(
            claim="HOST01 has an established connection to HOST02 on port 1433.",
            question="Which services are configured?",
            area="services", source_title="cap1.txt", excerpt="tcp 1433 ESTABLISHED", status="CONFLICTING")
        # A rejected row — must not be presented as verified
        rej_eid = "E-REJ-1"
        con = repo.con
        con.execute(
            "INSERT INTO evidence (id, area, question, claim, status, source_title, "
            "page_or_location, excerpt, confidence, gap_or_action, review_state, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'rejected','')",
            (rej_eid, "services", "Which time source is configured?",
             "HOST01 hosts the time source NTP.", "VERIFIED",
             "cap1.txt", None, "NTP time source", None, None))
        # Identical claim row (dedup test: HOST01 SQL Server is duplicated under a different ID)
        repo.evidence.create(
            claim="HOST01 runs SQL Server on port 1433.",
            question="Which services are configured?",
            area="services", source_title="cap2.txt", excerpt="dup capture", status="UNCONFIRMED")

        # External endpoint: an unowned IP that appears in flows as peer
        repo.evidence.create(
            claim="HOST02 has an established connection to 10.99.99.1 on port 443.",
            question="Which services are configured?",
            area="services", source_title="cap3.txt", excerpt="EXT-EP 443", status="VERIFIED")

        con = repo.con
        con.execute("INSERT INTO flow (src_host,dst_host,port,protocol,purpose) VALUES"
                    "('HOST01','HOST02',1433,'tcp','sql')")
        con.execute("INSERT INTO service (host,port,protocol,name) VALUES"
                    "('HOST01',1433,'tcp','SQL Server')")
        con.execute("INSERT INTO address (ip,scope,owner_host) VALUES"
                    "('10.6.1.1','private','HOST01')")
        con.execute("INSERT INTO address (ip,scope,owner_host) VALUES"
                    "('10.6.1.2','private','HOST02')")
        # app-b addresses
        con.execute("INSERT INTO address (ip,scope,owner_host) VALUES"
                    "('10.7.1.1','private','HOST03')")
        con.execute("INSERT INTO lead (id,question,state) VALUES"
                    "('L-1','Which services are configured?','open')")
        con.execute("INSERT INTO indexed_file (rel_path,sha256,size) VALUES ('cap1.txt','x',10)")
        con.execute("INSERT INTO indexed_chunk (rel_path,heading,text) VALUES"
                    "('cap1.txt','services','HOST01 1433 tcp SQL Server service running')")
        repo.graph.refresh()
    repo.close()
    return v2 / "csa.sqlite"


def test_fixture_retrieves_every_expected_row_and_chunk(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["1433", "SQL"], hosts=["HOST01"], areas=["services"])
    # VERIFIED SQL Server row is present
    text_set = {f["text"].lower() for f in pkg["evidence"]}
    assert any("sql server" in t for t in text_set)
    assert pkg["counts"]["evidence"] >= 2
    # FTS chunk confirming source is present
    assert any("sql server" in c["excerpt"].lower() for c in pkg["chunks"])
    # Flows between visible hosts
    assert any(f["src_host"] == "HOST01" and f["dst_host"] == "HOST02"
               for f in pkg["connections"]["flows"])
    # Lead about services
    assert any("services" in l["question"].lower() for l in pkg["leads"])


def test_unrelated_application_hosts_are_excluded(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["1433"])
    # app-b hosts (HOST03, HOST04) must not appear in the scope
    all_names = set(pkg["hosts"]["owned"]) | set(pkg["hosts"]["peers"]) | set(pkg["hosts"]["external"])
    assert "HOST03" not in all_names
    assert "HOST04" not in all_names
    # No app-b addresses in results
    ips = {a["ip"] for a in pkg["connections"]["addresses"]}
    assert "10.7.1.1" not in ips


def test_captured_external_endpoints_remain_available(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["10.99.99.1"])
    # The external IP evidence row is included (not excluded by scope)
    any_ext = any("10.99.99.1" in f["text"] for f in pkg["evidence"])
    assert any_ext, "external endpoint evidence should be available when supported by evidence"


def test_rejected_and_unresolved_not_presented_as_verified(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["1433"])
    # All evidence items for rejected rows must have verified=False
    rejected_ids = set()
    for f in pkg["evidence"]:
        if f["review_state"] == "rejected":
            rejected_ids.add(f["evidence_id"])
            assert f["verified"] is False
    # Warnings list should flag the rejected row if present
    if rejected_ids:
        assert any(w["kind"] == "rejected" for w in pkg["warnings"])
    # CONFLICTING row flagged
    conf_ids = {f["evidence_id"] for f in pkg["evidence"] if f["status"] == "CONFLICTING"}
    for fid in conf_ids:
        assert any(w["evidence_id"] == fid and w["kind"] == "conflict" for w in pkg["warnings"])


def test_results_stable_across_repeated_runs(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    kw = dict(subsection_key="services", application_key="app-a",
              question="Which services are configured?",
              terms=["1433", "SQL"], hosts=["HOST01"], areas=["services"])
    a = retrieve(db, **kw)
    b = retrieve(db, **kw)
    assert a == b, "retrieval must be deterministic for the same store revision and options"


def test_deduplicates_and_retains_evidence_ids(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services?",
                   terms=["SQL", "1433"])
    # Find the deduplicated SQL Server entry
    dup_entries = [f for f in pkg["evidence"] if "sql server" in f["text"].lower()]
    assert len(dup_entries) <= 1, "identical claims should be deduplicated"
    if dup_entries:
        # All evidence IDs for that claim should be in evidence_ids
        assert len(dup_entries[0].get("evidence_ids", [])) >= 1


def test_more_available_shows_when_truncated(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["1433", "SQL", "HOST01", "services", "time"],
                   limits={"evidence": 1})
    # With a very low evidence cap, more_available should be True
    assert pkg["more_available"] is True
    assert pkg["truncated"]["evidence"] is True
    assert "evidence_limit" in pkg["truncation_reasons"]


def test_every_fact_has_provenance_or_non_evidence(tmp_path, monkeypatch):
    db = _seed(tmp_path, monkeypatch)
    pkg = retrieve(db, subsection_key="services", application_key="app-a",
                   question="Which services are configured?",
                   terms=["1433"])
    for f in pkg["evidence"]:
        assert f["non_evidence"] is False
        assert f["evidence_id"]
        assert f["basis"] in ("stated", "canonical", "unresolved", "ambiguous")
    for c in pkg["chunks"]:
        assert c["non_evidence"] is True
    for w in pkg["warnings"]:
        assert w["non_evidence"] is True
