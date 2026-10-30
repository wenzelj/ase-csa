"""Evidence, review log, hosts and graph stay in step (investigation 2026-10-27)."""
import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from csa_docx import evidence_digest, evidence_live, evidence_refresh
from csa_docx import hostmodel as hm
from csa_docx.tests.test_hostmodel import _index

AGENTS = Path(__file__).resolve().parents[3]
SCRIPTS = AGENTS / "skills" / "csa-evidence-matrix" / "scripts"
COLS = "evidence_id,csa_area,question,claim,status,source_title,evidence_excerpt,page_or_location,review_state"


def _matrix(wd: Path, rows: list[str]):
    (wd / "evidence-matrix.csv").write_text(COLS + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _review(wd: Path, eid: str, state: str):
    with (wd / "evidence-reviews.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"evidence_id": eid, "state": state, "by": "t", "at": "x"}) + "\n")


def test_live_matrix_applies_latest_review(tmp_path):
    _matrix(tmp_path, ["E-001,a,q,c1,VERIFIED,s,x,,pending", "E-002,a,q,c2,VERIFIED,s,x,,pending"])
    _review(tmp_path, "E-001", "rejected"); _review(tmp_path, "E-002", "rejected"); _review(tmp_path, "E-002", "reviewed")
    rows = {r["evidence_id"]: r["review_state"] for r in evidence_live.read(tmp_path / "evidence-matrix.csv")}
    assert rows == {"E-001": "rejected", "E-002": "reviewed"}
    assert [r["evidence_id"] for r in evidence_live.read(tmp_path / "evidence-matrix.csv", drop_rejected=True)] == ["E-002"]


def test_links_skip_rejected_and_name_peers_the_register_owns():
    rows = [{"evidence_id": "E-1", "status": "VERIFIED", "csa_area": "network_and_connectivity", "review_state": "pending",
             "claim": "APP01 has an established connection from app.exe to 10.0.0.9 (name not captured) on port 443."},
            {"evidence_id": "E-2", "status": "VERIFIED", "csa_area": "network_and_connectivity", "review_state": "rejected",
             "claim": "APP01 has an established connection from app.exe to 10.0.0.8 (name not captured) on port 80."}]
    out = evidence_digest.links(rows, {"MON01": {"ips": "10.0.0.9"}})
    assert len(out) == 1 and out[0]["peer"] == "MON01" and out[0]["peer_ip"] == "10.0.0.9"
    assert evidence_digest.links(rows)[0]["peer"] == "10.0.0.9"


def test_rejected_claim_does_not_register_a_host_and_graph_hosts_do(tmp_path):
    _index(tmp_path)
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "roles.csv").write_text("kind,match,system,role,site,basis,reviewed\n", encoding="utf-8")
    _matrix(tmp_path, ["E-001,a,q,GHOST01 (10.9.9.9) is a server,VERIFIED,s,x,,pending",
                       "E-002,a,q,DOCHOST01 is the gateway,VERIFIED,doc.xlsx,x,,pending",
                       "E-003,a,q,IPR400 gateways,VERIFIED,doc.xlsx,x,,pending"])
    _review(tmp_path, "E-001", "rejected")
    (tmp_path / "graph").mkdir()
    (tmp_path / "graph" / "nodes.csv").write_text(
        "node_id,label,node_type,evidence_ids\nN-001,DOCHOST01 (gateway server; 10.5.5.5),host,E-002\n"
        "N-002,IPR400 Radio Over IP gateways (7 x IPR400),host,E-003\nN-003,GHOST01 (10.9.9.9),host,E-001\n", encoding="utf-8")
    hm.build(tmp_path)
    reg = {r["host"]: r for r in csv.DictReader((tmp_path / "hosts" / "hosts.csv").open())}
    assert "GHOST01" not in reg and "IPR400" not in reg
    assert reg["DOCHOST01"]["in_scope"] == "peer" and "10.5.5.5" in reg["DOCHOST01"]["ips"]
    ev = {r["evidence_id"]: r for r in csv.DictReader((tmp_path / "hosts" / "evidence_hosts.csv").open())}
    assert ev["E-001"]["review_state"] == "rejected" and ev["E-002"]["hosts"] == "DOCHOST01"


def test_refresh_retires_removed_and_superseded_and_lists_changed(tmp_path):
    con = sqlite3.connect(tmp_path / "discovery-index.sqlite")
    con.execute("create table captures(capture_id, folder, host, collector, capture_utc, archived, superseded_by, file_count)")
    con.execute("insert into captures values (1,'d/X_discovery_H1_20260101T000000Z','H1','t','x',0,2,1)")
    con.execute("insert into captures values (2,'d/X_discovery_H1_20260301T000000Z','H1','t','x',0,null,1)")
    con.commit(); con.close()
    _matrix(tmp_path, ["E-001,a,What does H1 run?,H1 runs x.,VERIFIED,X_discovery_H1_20260101T000000Z: 32.txt,x,,pending",
                       "E-002,a,Patch level?,H1 patched.,VERIFIED,X_discovery_H1_20260101T000000Z: 71.txt,x,,pending",
                       "E-003,a,q,Doc says y.,VERIFIED,src/gone.pdf,y,,pending"])
    (tmp_path / "intake").mkdir()
    (tmp_path / "intake" / "latest.json").write_text(json.dumps({"id": "r1", "added": [], "changed": [],
        "removed": ["src/gone.pdf"]}), encoding="utf-8")
    res = evidence_refresh.run(tmp_path)
    assert {r["evidence_id"] for r in res["rejected"]} == {"E-001", "E-003"}
    assert [r["evidence_id"] for r in res["recheck"]] == ["E-002"]
    assert evidence_live.rejected(tmp_path / "evidence-matrix.csv") == {"E-001", "E-003"}
    assert (tmp_path / "intake" / "refresh-latest.json").is_file()


def test_graph_store_refuses_a_second_node_for_a_host():
    sys.path.insert(0, str(SCRIPTS))
    from graph_store import host_key
    assert host_key("ROTPRDRBS101 (RevBroadcast application server, Rockhampton)") == "ROTPRDRBS101"
    assert host_key("MOTPRDLOG101") == "MOTPRDLOG101"
    assert host_key("IPR400 Radio Over IP gateways, Mackay (7 x IPR400)") is None
    assert host_key("10.0.0.1 (name not captured)") is None
