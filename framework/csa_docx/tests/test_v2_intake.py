"""S588: batched intake — build_batch / apply_batch on a v2repo."""
import json
import csv

import pytest

from csa_docx import v2_intake
from csa_docx.v2repo import Repo

SRC_A = "docs/a.txt"
SRC_B = "docs/b.txt"
TEXT_A = "SRV1 is the primary application server.\nSRV1 has an established connection to SRV2 on port 1433 (sql)."
TEXT_B = "SRV2 is the database server at Site A."


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "csa.sqlite")
    with r.tx():
        r.hosts.create("SRV1", role="app", site="A")
        r.hosts.create("SRV2", role="db", site="A")
        for rel, text in ((SRC_A, TEXT_A), (SRC_B, TEXT_B)):
            r.con.execute("INSERT INTO indexed_file (rel_path, sha256, size) VALUES (?, 'x', 1)", (rel,))
            r.con.execute("INSERT INTO indexed_chunk (rel_path, heading, text) VALUES (?, 'h', ?)", (rel, text))
    yield r
    r.close()


def _row(claim, src=SRC_A, excerpt="SRV1 is the primary application server.", loc="line 1"):
    return {"claim": claim, "source_title": src, "page_or_location": loc,
            "excerpt": excerpt, "area": "infrastructure_and_hosting", "status": "VERIFIED"}


def _start(r, paths):
    with r.tx():
        return r.intake.start([{"rel_path": p} for p in paths])


def test_batches_split_12_files_into_5_5_2():
    parts = v2_intake.batches([f"f{i}.txt" for i in range(12)], max_files=5)
    assert [len(p) for p in parts] == [5, 5, 2]


def test_batches_default_to_one_file_per_model_session():
    parts = v2_intake.batches(["a.txt", "b.txt", "c.txt"])
    assert parts == [["a.txt"], ["b.txt"], ["c.txt"]]


def test_adaptive_batches_group_compatible_tiny_files(repo):
    parts = v2_intake.batches([SRC_A, SRC_B], repo=repo, adaptive=True)
    assert parts == [[SRC_A, SRC_B]]


def test_deterministic_batch_accepts_generated_path_sidecar(repo):
    with repo.tx():
        repo.con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES ('docs/result_path.txt','x',1)")
        repo.con.execute("INSERT INTO indexed_chunk(rel_path,text) VALUES ('docs/result_path.txt',?)",
                         ('Generated: C:\\\\Temp\\\\result.xml',))
    result = v2_intake.deterministic_batch(["docs/result_path.txt"], repo=repo)
    assert result == [{"rel_path": "docs/result_path.txt", "rows": [], "graph_items": []}]


def test_build_batch_has_chunks_hosts_and_instructions(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    payload = v2_intake.build_batch(rid, [SRC_A, SRC_B], max_files=2, repo=repo)
    assert payload["record_id"] == rid
    assert [f["rel_path"] for f in payload["files"]] == [SRC_A, SRC_B]
    assert TEXT_B in payload["files"][1]["chunks"]
    assert payload["files"][0]["existing_hosts"] == ["SRV1", "SRV2"]
    assert "Intake mode" in payload["instructions"]
    assert len(v2_intake.build_batch(rid, [SRC_A, SRC_B], max_files=1, repo=repo)["files"]) == 1


def test_build_batch_bounds_large_source_payload(repo):
    with repo.tx() as con:
        con.execute("INSERT INTO indexed_file(rel_path, sha256) VALUES ('large.csv','x')")
        con.executemany("INSERT INTO indexed_chunk(rel_path,text) VALUES ('large.csv',?)",
                        [("x" * 20000,), ("y" * 20000,), ("z" * 20000,), ("q" * 20000,)])
    item = v2_intake.build_batch("I-1", ["large.csv"], repo=repo)["files"][0]
    assert item["truncated"] is True
    assert item["source_chars"] == 80000
    assert item["payload_chars"] == v2_intake.MAX_FILE_CHARS


def test_apply_batch_inserts_rows_refreshes_graph_and_marks_files(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    out = [
        {"rel_path": SRC_A, "rows": [_row("SRV1 is the primary application server.")], "graph_items": []},
        {"rel_path": SRC_B, "rows": [], "graph_items": []},
    ]
    s = v2_intake.apply_batch(rid, json.dumps(out), repo=repo)
    assert (s["files_total"], s["files_ok"], s["files_failed"], s["rows_added"], s["rows_rejected"]) == (2, 2, 0, 1, 0)
    assert s["graph_nodes"] >= 2
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert repo.con.execute("SELECT COUNT(*) FROM evidence_source").fetchone()[0] == 2
    assert repo.intake.pending() == []


def test_apply_batch_rejects_row_whose_quote_is_not_in_source(repo):
    rid = _start(repo, [SRC_A])
    out = [{"rel_path": SRC_A, "rows": [_row("SRV1 runs Linux.", excerpt="SRV1 runs Linux")], "graph_items": []}]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert s["rows_rejected"] == 1 and s["rows_added"] == 0
    assert "SOURCE_MISMATCH" in s["rejected"][0]["reason"]
    assert repo.con.execute("SELECT COUNT(*) FROM evidence WHERE claim='SRV1 runs Linux.'").fetchone()[0] == 0
    assert s["files_ok"] == 1


def test_apply_batch_deduplicates_existing_row(repo):
    with repo.tx():
        repo.evidence.create(claim="SRV1 is the primary application server.", source_title=SRC_A,
                             page_or_location="line 1", excerpt="x")
    rid = _start(repo, [SRC_A])
    out = [{"rel_path": SRC_A, "rows": [_row("SRV1 is the primary application server.")], "graph_items": []}]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert s["rows_added"] == 0
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1


def test_apply_batch_marks_malformed_file_failed_and_keeps_others(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    out = [
        {"rel_path": SRC_A, "rows": "not a list", "graph_items": []},
        {"rel_path": SRC_B, "rows": [_row("SRV2 is the database server at Site A.", SRC_B,
                                          "SRV2 is the database server at Site A.")], "graph_items": []},
    ]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert (s["files_ok"], s["files_failed"], s["rows_added"]) == (1, 1, 1)
    status = dict(repo.con.execute("SELECT rel_path, status FROM intake_file").fetchall())
    assert status == {SRC_A: "failed", SRC_B: "processed"}


def test_apply_batch_unparseable_output_fails_every_file(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    s = v2_intake.apply_batch(rid, "{not json", repo=repo)
    assert s["files_failed"] == 2 and s["files_ok"] == 0


def test_round_trip_grows_evidence_graph_and_clears_pending(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    assert repo.con.execute("SELECT COUNT(*) FROM graph_node").fetchone()[0] == 0
    claim = "SRV1 has an established connection to SRV2 on port 1433 (sql)."
    payload = v2_intake.build_batch(rid, [p["rel_path"] for p in repo.intake.pending(rid)], repo=repo)
    out = [{"rel_path": f["rel_path"],
            "rows": [_row(claim, SRC_A, claim, "line 2")] if f["rel_path"] == SRC_A else [],
            "graph_items": []} for f in payload["files"]]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert s["rows_added"] == 1
    assert repo.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert repo.con.execute("SELECT COUNT(*) FROM graph_node").fetchone()[0] > 0
    assert repo.con.execute("SELECT COUNT(*) FROM graph_edge").fetchone()[0] > 0
    assert repo.intake.pending() == []


def test_apply_batch_persists_structured_network_items_and_provenance(repo):
    rid = _start(repo, [SRC_A])
    claim = "SRV1 has an established connection to SRV2 on port 1433 (sql)."
    out = [{"rel_path": SRC_A, "rows": [_row(claim, SRC_A, claim, "line 2")],
           "graph_items": [
               {"kind": "address", "ip": "10.0.0.1", "owner_host": "SRV1", "scope": "test",
                "evidence_row_indexes": [0]},
               {"kind": "flow", "src_host": "SRV1", "dst_host": "10.0.0.9", "port": 1433,
                "protocol": "tcp", "purpose": "sql", "evidence_row_indexes": [0]},
               {"kind": "service", "host": "SRV2", "port": 1433, "protocol": "tcp",
                "name": "sql", "configured": True, "evidence_row_indexes": [0]},
           ]}]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert (s["address_items"], s["flow_items"], s["service_items"]) == (1, 1, 1)
    assert repo.con.execute("SELECT owner_host FROM address WHERE ip='10.0.0.1'").fetchone()[0] == "SRV1"
    purpose = repo.con.execute("SELECT purpose FROM flow WHERE src_host='SRV1' AND dst_host='10.0.0.9'").fetchone()[0]
    assert "evidence=E-001" in purpose
    edge = repo.con.execute("SELECT evidence_ids FROM graph_edge WHERE src='host/SRV1' AND dst='host/10.0.0.9'").fetchone()
    assert edge and edge[0] == "E-001"
    assert repo.con.execute("SELECT role FROM host WHERE name='10.0.0.9'").fetchone()[0] == "Observed network endpoint"


def test_apply_batch_rejects_unknown_structured_item_without_writing(repo):
    rid = _start(repo, [SRC_A])
    out = [{"rel_path": SRC_A, "rows": [], "graph_items": [{"kind": "router", "name": "R1"}]}]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert s["files_failed"] == 1
    assert "unsupported kind" in s["errors"][SRC_A]
    assert repo.con.execute("SELECT COUNT(*) FROM host WHERE name='R1'").fetchone()[0] == 0


def test_apply_batch_persists_host_it_ot_classification_and_preserves_review(repo):
    rid = _start(repo, [SRC_A])
    out = [{"rel_path": SRC_A, "rows": [], "graph_items": [
        {"kind": "host", "name": "SRV1", "role": "SCADA server", "site": "A",
         "classification": "ot", "zone": "OT Site A",
         "classification_basis": "The source identifies SRV1 as an OT SCADA server."}
    ]}]
    s = v2_intake.apply_batch(rid, out, repo=repo)
    assert s["zone_items"] == 1
    zone_file = repo.path.parent / "hosts" / "zones.csv"
    rows = list(csv.DictReader(zone_file.open(encoding="utf-8")))
    assert {r["match"]: r for r in rows}["host:SRV1"]["kind"] == "ot"
    assert {r["match"]: r for r in rows}["host:SRV1"]["reviewed"] == "no"

    from csa_docx import zones
    zones.upsert_host_rules(repo.path.parent, [{"match": "host:SRV1", "kind": "ot",
                                                "zone": "OT Site A", "basis": "reviewed correction",
                                                "reviewed": "yes"}])
    with repo.tx():
        rid2 = repo.intake.start([{"rel_path": SRC_A}])
    v2_intake.apply_batch(rid2, out, repo=repo)
    rows = list(csv.DictReader(zone_file.open(encoding="utf-8")))
    assert {r["match"]: r for r in rows}["host:SRV1"]["reviewed"] == "yes"
