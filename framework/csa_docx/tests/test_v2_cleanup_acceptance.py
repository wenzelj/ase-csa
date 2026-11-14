"""The V2 acceptance gate (S606, S619): a throw-away store, then the live pilot store read-only."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from csa_docx.v2repo import Repo
from csa_docx.v2repo import graph as _graph  # noqa: F401 — adds Repo.graph

AGENTS = Path(__file__).resolve().parents[3]
CSA = AGENTS / "bin" / "csa"
PILOT_KEY = "tetra-reveloc"
PILOT_DB = AGENTS.parent / "TETRA" / "06 REVELOC TETRA" / "csa-work-v2" / "csa.sqlite"
pilot = pytest.mark.skipif(not PILOT_DB.is_file(), reason="the pilot V2 store is not on this machine")


def _gate(key: str, registry: Path | None = None) -> tuple[int, dict]:
    env = {k: v for k, v in os.environ.items() if k != "CSA_PROJECTS_FILE"}
    if registry:
        env["CSA_PROJECTS_FILE"] = str(registry)
    proc = subprocess.run([sys.executable, str(CSA), "-p", key, "v2", "acceptance"], capture_output=True, text=True, env=env)
    return proc.returncode, json.loads(proc.stdout[proc.stdout.index("{"):])


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    work = root / "csa-work-v2"
    repo = Repo(work)
    with repo.tx() as con:
        for host in ("APP1", "APP2", "PEER1", "IDLE1"):
            repo.hosts.create(host)
        for host in ("APP1", "APP2"):
            repo.application_ownership.add("app-a", host, "inventory/assets.xlsx", review_state="accepted", by="test")
        con.execute("INSERT INTO indexed_file(rel_path) VALUES ('captures/app1/connections.txt')")
        con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('APP1','APP2',1433)")
        con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('APP1','PEER1',443)")
        repo.application_scope.add("app-a", "IDLE1", "peer", active=False)
        repo.evidence.create("APP1 has an established connection to 203.0.113.9 on port 443.",
                             "captures/app1/connections.txt", excerpt="x", status="VERIFIED")
        repo.graph.refresh()
    repo.close()
    from csa_docx import v2scope
    assert v2scope.rebuild(root, work, "app-a")["status"] == "OK"
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text("projects:\n  - key: app-a\n    label: \"App A\"\n"
                        f"    project_root: \"{root}\"\n    project_context: \"\"\n"
                        f"    work_dir: \"{work}\"\n    default_source_set: \"\"\n", encoding="utf-8")
    return work, registry


def _contents(db: Path) -> dict:
    """Every row of every table except the rebuilt full-text mirror."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'fts%' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables}


def test_gate_passes_on_a_consistent_store_and_reports_limitations(tmp_path):
    work, registry = _fixture(tmp_path)
    before = _contents(work / "csa.sqlite")
    code, result = _gate("app-a", registry)
    assert code == 0 and result["status"] == "OK", result
    assert result["scope"] == {"owned": 2, "active_peers": 1, "inactive_peers": 1}
    assert all(check["ok"] for check in result["checks"]) and len(result["checks"]) == 11
    assert result["provenance"] == {"checked": 1, "canonical": 1, "ambiguous": 0, "unresolved": 0, "recorded_rows": 0}
    assert any("provenance is recorded for 0 of 1" in item for item in result["limitations"])
    assert _contents(work / "csa.sqlite") == before                # the gate reads; it repairs nothing
    assert not (work.parent / "csa-work").exists()                 # and creates no V1 state


def test_gate_fails_when_a_required_check_is_false(tmp_path):
    work, registry = _fixture(tmp_path)
    repo = Repo(work)
    with repo.tx() as con:
        con.execute("INSERT INTO intake_record(id) VALUES ('R1')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R1', 'captures/new.txt', 'pending')")
        con.execute("INSERT INTO lead(id, question, searched_scope, state) VALUES ('L-000001', 'q', 'DR-OLD-1', 'open')")
        con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('APP2','IDLE1',22)")   # scope is now out of date
    repo.close()
    code, result = _gate("app-a", registry)
    assert code == 2 and result["status"] == "FAILED"
    failed = {check["check"] for check in result["checks"] if not check["ok"]}
    assert failed == {"no pending intake files", "only V2 open leads", "stored scope equals a scope rebuild from V2 records"}


def test_gate_separates_current_and_superseded_intake_failures(tmp_path):
    work, registry = _fixture(tmp_path)
    repo = Repo(work)
    with repo.tx() as con:
        con.execute("INSERT INTO intake_record(id, started_at) VALUES ('R-old', '2026-01-01T00:00:00Z')")
        con.execute("INSERT INTO intake_record(id, started_at) VALUES ('R-new', '2026-01-02T00:00:00Z')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R-old', 'captures/replayed.txt', 'failed')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R-new', 'captures/replayed.txt', 'processed')")
        con.execute("INSERT INTO intake_record(id) VALUES ('R0')")
        con.execute("INSERT INTO intake_record(id) VALUES ('R1')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R0', 'captures/fallback.txt', 'failed')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R1', 'captures/fallback.txt', 'processed')")
        con.execute("INSERT INTO intake_record(id, started_at) VALUES ('R-latest', '2026-01-03T00:00:00Z')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R-latest', 'captures/current.txt', 'failed')")
    repo.close()
    code, result = _gate("app-a", registry)
    assert code == 0 and result["status"] == "OK"
    detail = {check["check"]: check["detail"] for check in result["checks"]}
    assert detail["no pending intake files"] == {"pending": 0, "failed": 1, "failed_superseded": 2}
    assert "1 intake file(s) are recorded as failed" in result["limitations"]


@pilot
def test_tetra_cleanup_acceptance():
    db = sqlite3.connect(f"file:{PILOT_DB}?mode=ro", uri=True)
    try:
        one = lambda sql: db.execute(sql).fetchone()[0]
        assert one("select count(*) from evidence where review_state != 'rejected' and lower(source_title) like '%current_state_assessment%'") == 0
        assert one("select count(*) from lead where state='open' and searched_scope not like 'v2 discovery index:%'") == 0
        assert one("select count(*) from intake_file where status='pending'") == 0
        scope = f"select count(*) from application_scope where application_key='{PILOT_KEY}'"
        assert one(scope + " and membership='owned' and active=1") == 26
        assert one(scope + " and membership='peer' and active=1") == 14
        assert one(scope + " and membership='peer' and active=0") == 130
        assert one(scope + " and active=1 and (source_ref like '%hosts.csv%' or basis like '%hosts.csv%')") == 0
    finally:
        db.close()


@pilot
def test_tetra_live_gate_passes_without_touching_v1_state():
    legacy = PILOT_DB.parent.parent / "csa-work"
    snapshot = lambda: sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in legacy.rglob("*") if p.is_file())
    before = snapshot() if legacy.is_dir() else None
    code, result = _gate(PILOT_KEY)
    assert code == 0 and result["status"] == "OK", [c for c in result["checks"] if not c["ok"]]
    assert result["scope"] == {"owned": 26, "active_peers": 14, "inactive_peers": 130}
    detail = {check["check"]: check["detail"] for check in result["checks"]}
    assert detail["owned view is stable"]["nodes"] == 26
    assert detail["application view holds the owned hosts and only evidence-backed peer hosts"]["hosts"] == 40
    assert detail["global view is the complete graph"]["nodes"] > detail["application view is stable"]["nodes"]
    assert detail["graph verification passes"] == {"global_issues": 0, "application_issues": 0}
    # unfinished work is reported, never hidden
    assert result["provenance"]["checked"] == sum(result["provenance"][k] for k in ("canonical", "ambiguous", "unresolved"))
    if legacy.is_dir():
        assert snapshot() == before
