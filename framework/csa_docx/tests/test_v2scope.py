"""`csa v2 scope-rebuild` reads V2 records only (S594, S605, S617)."""
import builtins
import io
import os
import sqlite3
from pathlib import Path

import pytest

from csa_docx.v2repo import Repo
from csa_docx.v2scope import OWNERSHIP_REF, SOURCE, rebuild

OWNED, ACTIVE_PEERS, INACTIVE_PEERS = 26, 14, 130


def _pilot(tmp_path: Path, ownership: bool = True) -> tuple[Path, Path]:
    """A store shaped like the pilot: 26 owned hosts, 14 peers with a current relationship and
    130 peer candidates without one. There is no csa-work folder at all."""
    root = tmp_path / "project"
    v2 = root / "csa-work-v2"
    repo = Repo(v2)
    owned = [f"OWN{i:02d}" for i in range(1, OWNED + 1)]
    active = [f"PEER{i:02d}" for i in range(1, ACTIVE_PEERS + 1)]
    inactive = [f"IDLE{i:03d}" for i in range(1, INACTIVE_PEERS + 1)]
    with repo.tx():
        for host in owned + active + inactive + ["UNCLASSIFIED01"]:
            repo.hosts.create(host)
        for host in owned:
            if ownership:
                repo.application_ownership.add("pilot-app", host, "inventory/asset-register.xlsx",
                                               review_state="accepted", by="test")
            else:                                    # a store migrated before application_ownership existed
                repo.application_scope.add("pilot-app", host, "owned", basis="register:in_scope=yes",
                                           source_ref="v2:host-register; evidence-backed")
        for host in active + inactive:
            repo.application_scope.add("pilot-app", host, "peer", basis="", source_ref="v2:flow-service-evidence",
                                       active=False)
        for i, host in enumerate(active[:10]):
            repo.con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES (?,?,443)", (owned[i], host))
        for host in active[10:12]:
            repo.con.execute("INSERT INTO service (host, provider_host, port, name) VALUES (?,?,53,'dns')",
                             (owned[0], host))
        for host in active[12:]:
            repo.evidence.create(claim=f"OWN01 has an established connection to {host} on port 8443.",
                                 source_title="captures/own01/connections.txt", excerpt="x", status="VERIFIED")
        rejected = repo.evidence.create(claim="OWN01 has an established connection to IDLE001 on port 22.",
                                        source_title="captures/own01/connections.txt", excerpt="x", status="VERIFIED")
        repo.evidence.reject(rejected, by="test", note="rejected relationship")
        repo.con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('IDLE002','IDLE003',80)")   # peer to peer only
    repo.close()
    return root, v2


@pytest.fixture
def no_legacy_reads(monkeypatch):
    """Fail the test if anything below a legacy csa-work folder is opened."""
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def guard(path):
        parts = Path(os.fsdecode(path)).parts if isinstance(path, (str, bytes, os.PathLike)) else ()
        if "csa-work" in parts:
            raise AssertionError(f"the V2 scope rebuild opened a legacy file: {path}")

    def _open(path, *args, **kwargs):
        guard(path)
        return real_open(path, *args, **kwargs)

    def _io_open(path, *args, **kwargs):
        guard(path)
        return real_io_open(path, *args, **kwargs)

    def _os_open(path, *args, **kwargs):
        guard(path)
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _io_open)
    monkeypatch.setattr(os, "open", _os_open)


def _counts(result: dict) -> tuple[int, int, int]:
    return result["owned_count"], result["active_peer_count"], result["excluded_peer_count"]


def test_rebuild_preserves_the_pilot_counts_from_v2_only(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path)
    dry = rebuild(root, v2, "pilot-app", dry_run=True)
    assert dry["status"] == "DRY-RUN" and _counts(dry) == (OWNED, ACTIVE_PEERS, INACTIVE_PEERS)
    result = rebuild(root, v2, "pilot-app")
    assert result["status"] == "OK" and _counts(result) == (OWNED, ACTIVE_PEERS, INACTIVE_PEERS)
    assert result["peer_candidates"] == ACTIVE_PEERS + INACTIVE_PEERS
    assert result["unclassified_hosts"] == ["UNCLASSIFIED01"]          # never guessed into the scope
    assert not (root / "csa-work").exists()                            # nothing legacy was created or required
    repo = Repo(v2)
    rows = repo.application_scope.list_app_hosts("pilot-app")
    assert sum(r["membership"] == "owned" and r["active"] for r in rows) == OWNED
    assert sum(r["membership"] == "peer" and r["active"] for r in rows) == ACTIVE_PEERS
    assert sum(r["membership"] == "peer" and not r["active"] for r in rows) == INACTIVE_PEERS
    assert repo.application_scope.get("pilot-app", "UNCLASSIFIED01") is None
    repo.close()


def test_report_and_active_rows_point_to_v2_records(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path)
    result = rebuild(root, v2, "pilot-app")
    assert result["source"] == SOURCE and "hosts.csv" not in Path(result["report_path"]).read_text(encoding="utf-8")
    assert result["ownership_source"] == "application_ownership"
    repo = Repo(v2)
    active = repo.application_scope.list_app_hosts("pilot-app", active=True)
    assert len(active) == OWNED + ACTIVE_PEERS
    for row in active:
        assert row["source_ref"].startswith("v2:") and "hosts.csv" not in (row["source_ref"] + (row["basis"] or ""))
        if row["membership"] == "owned":
            assert row["source_ref"] == OWNERSHIP_REF and row["basis"] == "ownership:accepted"
            assert row["review_state"] == "accepted"
    by_host = {row["host_name"]: row for row in active}
    assert by_host["PEER01"]["source_ref"] == "v2:flow" and by_host["PEER01"]["basis"] == "flow:OWN01->PEER01"
    assert by_host["PEER11"]["source_ref"] == "v2:service"
    assert by_host["PEER13"]["source_ref"] == "v2:evidence" and by_host["PEER13"]["evidence_ids"] == "E-001"
    # a rejected evidence row and a peer-to-peer flow are not proof
    excluded = {row["host_name"]: row for row in result["excluded_peers"]}
    for host in ("IDLE001", "IDLE002", "IDLE003"):
        assert excluded[host]["reason"] == "no current flow, service or accepted evidence proof"
    repo.close()


def test_dry_run_is_read_only(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path)
    db = v2 / "csa.sqlite"
    before = (db.read_bytes(), sorted(p.name for p in v2.rglob("*")))
    assert rebuild(root, v2, "pilot-app", dry_run=True)["status"] == "DRY-RUN"
    assert (db.read_bytes(), sorted(p.name for p in v2.rglob("*"))) == before
    assert not (v2 / "scope-reports").exists()


def test_apply_backs_up_and_appends_review_events(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path)
    backups = set((v2 / "backups").glob("csa.sqlite.*"))
    result = rebuild(root, v2, "pilot-app")
    assert Path(result["report_path"]).is_file()
    assert set((v2 / "backups").glob("csa.sqlite.*")) - backups, "the applied rebuild backs the database up first"
    repo = Repo(v2)
    events = repo.con.execute("SELECT COUNT(*) FROM review_event WHERE action='scope-rebuild'").fetchone()[0]
    assert events == OWNED + ACTIVE_PEERS + INACTIVE_PEERS
    # the global records are untouched
    assert repo.con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == OWNED + ACTIVE_PEERS + INACTIVE_PEERS + 1
    assert repo.con.execute("SELECT COUNT(*) FROM flow").fetchone()[0] == 11
    repo.close()
    assert _counts(rebuild(root, v2, "pilot-app")) == (OWNED, ACTIVE_PEERS, INACTIVE_PEERS)      # stable when repeated


def test_first_applied_rebuild_imports_ownership_from_v2_scope_rows(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path, ownership=False)
    dry = rebuild(root, v2, "pilot-app", dry_run=True)
    assert _counts(dry) == (OWNED, ACTIVE_PEERS, INACTIVE_PEERS) and "not yet imported" in dry["ownership_source"]
    with sqlite3.connect(v2 / "csa.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM application_ownership").fetchone()[0] == 0     # the dry run imported nothing
    result = rebuild(root, v2, "pilot-app")
    assert _counts(result) == (OWNED, ACTIVE_PEERS, INACTIVE_PEERS)
    repo = Repo(v2)
    owned = repo.application_ownership.list("pilot-app")
    assert len(owned) == OWNED and owned[0]["source_ref"] == "v2:application_scope/pilot-app/OWN01"
    assert owned[0]["review_state"] == "proposed" and owned[0]["recorded_by"] == "csa v2 scope-rebuild"
    assert repo.con.execute("SELECT COUNT(*) FROM review_event WHERE action='ownership.add'").fetchone()[0] == OWNED
    assert {r["source_ref"] for r in repo.application_scope.list_app_hosts("pilot-app", membership="owned")} == {OWNERSHIP_REF}
    repo.close()
    assert rebuild(root, v2, "pilot-app", dry_run=True)["ownership_source"] == "application_ownership"


def test_ownership_is_explicit_and_reviewable(tmp_path, no_legacy_reads):
    root, v2 = _pilot(tmp_path)
    repo = Repo(v2)
    with pytest.raises(ValueError, match="source_ref"):
        with repo.tx():
            repo.application_ownership.add("pilot-app", "UNCLASSIFIED01", "")
    with repo.tx():
        repo.application_ownership.add("pilot-app", "OWN26", "inventory/asset-register.xlsx",
                                       review_state="rejected", by="reviewer")
        repo.hosts.retire("PEER01", note="test")
    repo.close()
    result = rebuild(root, v2, "pilot-app", dry_run=True)
    assert result["owned_count"] == OWNED - 1 and result["rejected_ownership"] == ["OWN26"]
    assert {"host_name": "PEER01", "reason": "host is retired", "proof": ["flow:OWN01->PEER01"]} in result["excluded_peers"]
    assert result["active_peer_count"] == ACTIVE_PEERS - 1


def test_rebuild_needs_recorded_ownership_not_a_name_or_folder(tmp_path, no_legacy_reads):
    root = tmp_path / "pilot-app"                      # the folder is named after the application: not ownership
    v2 = root / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("PILOT-APP-01")
    repo.close()
    for dry_run in (True, False):
        result = rebuild(root, v2, "pilot-app", dry_run=dry_run)
        assert result["status"] == "ERROR" and "no ownership is recorded" in result["error"]
    assert rebuild(root, v2, " ")["error"] == "application_key is required"
    assert rebuild(root, tmp_path / "missing" / "csa-work-v2", "pilot-app", dry_run=True)["status"] == "ERROR"
    assert not (tmp_path / "missing").exists()


def test_scope_rebuild_resolves_address_only_peer_proof(tmp_path, no_legacy_reads):
    root = tmp_path / "project"
    v2 = root / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("APP01")
        repo.hosts.create("PEER01")
        repo.application_ownership.add("pilot-app", "APP01", "inventory", review_state="accepted")
        repo.con.execute("INSERT INTO address (ip, owner_host) VALUES ('10.10.0.2', 'PEER01')")
        repo.evidence.create(
            claim="APP01 has an established connection to 10.10.0.2 on port 443.",
            source_title="captures/address.txt", excerpt="APP01 -> 10.10.0.2", status="VERIFIED")
    repo.close()
    result = rebuild(root, v2, "pilot-app", dry_run=True)
    assert result["active_peer_count"] == 1
    peer = next(row for row in result["active_peer_rows"] if row["host_name"] == "PEER01")
    assert peer["proof"] == ["evidence:E-001 (10.10.0.2)"]
