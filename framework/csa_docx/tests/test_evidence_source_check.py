"""The evidence matrix approves a VERIFIED row only when its excerpt is found in the source it cites."""
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3]
SCRIPT = AGENTS / "skills" / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
spec = importlib.util.spec_from_file_location("evidence_matrix", SCRIPT)
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)

CAP = "cap/REVELOC_discovery_HOSTA01_20260605T010203Z/03_time_status.txt"
TEXT = "ReferenceId: 0x0A28E461 (source IP:  10.40.228.97)\nSource: ROTPRDSRV122.internal.qr.com.au \n"


def _index(path: Path):
    con = sqlite3.connect(path)
    con.executescript("""create table files(file_id integer, rel_path text, dup_of integer, archived integer default 0);
        create table chunk_map(chunk_id integer, file_id integer, line_start integer);
        create table chunks_content(id integer, c0 text);""")
    con.execute("insert into files values (1, ?, null, 0)", (CAP,))
    con.execute("insert into files values (2, ?, 1, 0)", (CAP.replace("HOSTA01", "HOSTB02").replace("010203", "040506"),))
    con.execute("insert into chunk_map values (1, 1, 1)")
    con.execute("insert into chunks_content values (1, ?)", (TEXT,))
    con.commit()
    return con


def _row(**kw):
    row = {"status": "VERIFIED", "source_title": "REVELOC_discovery_HOSTA01_20260605T010203Z: 03_time_status.txt",
           "evidence_excerpt": "ReferenceId: 0x0A28E461 (source IP: 10.40.228.97) | Source: ROTPRDSRV122.internal.qr.com.au"}
    row.update(kw)
    return row


def test_source_check_verdicts(tmp_path):
    con = _index(tmp_path / "i.sqlite")
    assert em.source_check(_row(), con)["verdict"] == "SOURCE_OK"                       # spacing and case do not matter
    assert em.source_check(_row(evidence_excerpt="Source: OTHERSRV.internal.qr.com.au"), con)["verdict"] == "SOURCE_MISMATCH"
    assert em.source_check(_row(source_title="REVELOC_discovery_NOPE01_20260101T000000Z: 03_time_status.txt"), con)["verdict"] == "SOURCE_NOT_FOUND"
    assert em.source_check(_row(status="INFERRED"), con)["verdict"] == "NOT_CHECKABLE"
    assert em.source_check(_row(status="NOT_FOUND"), con)["verdict"] == "NOT_CHECKABLE"
    assert em.source_check(_row(source_title="the design document"), con)["verdict"] == "NOT_CHECKABLE"


def test_source_check_reads_a_duplicate_file_from_the_file_it_duplicates(tmp_path):
    con = _index(tmp_path / "i.sqlite")
    dup = _row(source_title="REVELOC_discovery_HOSTB02_20260605T040506Z: 03_time_status.txt")
    assert em.source_check(dup, con)["verdict"] == "SOURCE_OK"


def test_source_check_rejects_a_cited_file_that_holds_none_of_the_excerpt(tmp_path):
    con = _index(tmp_path / "i.sqlite")
    con.execute("insert into files values (3, 'cap/REVELOC_discovery_HOSTA01_20260605T010203Z/11_ip_route.txt', null, 0)")
    con.execute("insert into chunk_map values (3, 3, 1)")
    con.execute("insert into chunks_content values (3, 'unrelated routes')")
    both = _row(source_title="REVELOC_discovery_HOSTA01_20260605T010203Z: 03_time_status.txt, 11_ip_route.txt")
    res = em.source_check(both, con)
    assert res["verdict"] == "SOURCE_MISMATCH" and res["files_without_excerpt"] == ["HOSTA01_20260605T010203Z/11_ip_route.txt"]


def _append(tmp_path, excerpt):
    work = tmp_path / "workspace" / "csa-work"
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "discovery-index.sqlite").exists():
        _index(work / "discovery-index.sqlite").close()
    row = {"csa_area": "network_and_connectivity", "question": "q", "claim": "HOSTA01 syncs from ROTPRDSRV122",
           "status": "VERIFIED", "source_title": "REVELOC_discovery_HOSTA01_20260605T010203Z: 03_time_status.txt",
           "page_or_location": "03_time_status.txt", "evidence_excerpt": excerpt}
    r = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(tmp_path / "workspace"), "append", "--agent", "t",
                        "--row-json", json.dumps(row)], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout), work


def test_append_refuses_an_excerpt_that_is_not_in_the_cited_source(tmp_path):
    code, out, work = _append(tmp_path, "Source: NOTHERE.internal.qr.com.au")
    assert code == 2 and out["status"] == "ERROR" and "SOURCE_MISMATCH" in json.dumps(out["rejected"])
    assert not (work / "evidence-matrix.csv").exists() or "E-001" not in (work / "evidence-matrix.csv").read_text()


def test_append_approves_a_row_the_source_proves_and_stats_counts_it(tmp_path):
    code, out, work = _append(tmp_path, "Source: ROTPRDSRV122.internal.qr.com.au")
    assert code == 0 and out["written"][0]["review"] == "reviewed (source check)"
    log = [json.loads(l) for l in (work / "evidence-reviews.jsonl").read_text().splitlines()]
    assert log[0]["evidence_id"] == "E-001" and log[0]["by"] == em.AUTO_REVIEWER and "03_time_status.txt" in log[0]["note"]
    stats = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(tmp_path / "workspace"), "stats"],
                           capture_output=True, text=True)
    assert json.loads(stats.stdout)["by_review_state"] == {"reviewed": 1}
