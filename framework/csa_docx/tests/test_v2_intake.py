"""S588: batched intake — build_batch / apply_batch on a v2repo."""
import json

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


def test_build_batch_has_chunks_hosts_and_instructions(repo):
    rid = _start(repo, [SRC_A, SRC_B])
    payload = v2_intake.build_batch(rid, [SRC_A, SRC_B], repo=repo)
    assert payload["record_id"] == rid
    assert [f["rel_path"] for f in payload["files"]] == [SRC_A, SRC_B]
    assert TEXT_B in payload["files"][1]["chunks"]
    assert payload["files"][0]["existing_hosts"] == ["SRV1", "SRV2"]
    assert "Intake mode" in payload["instructions"]
    assert len(v2_intake.build_batch(rid, [SRC_A, SRC_B], max_files=1, repo=repo)["files"]) == 1


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
