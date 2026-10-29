import csv
import json
import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from csa_docx import leads


def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    (ws / "csa-work" / "intake").mkdir(parents=True)
    matrix = ws / "csa-work" / "evidence-matrix.csv"
    with matrix.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["evidence_id", "status"])
        writer.writerow(["E-1", "VERIFIED"])
    return ws


def hit(**changes):
    value = {
        "source_title": "capture_HOST_20260605T001739Z: 41_dns_query_tests.txt",
        "source_ref": "capture_HOST_20260605T001739Z: 41_dns_query_tests.txt",
        "rel_path": "discovery/capture_HOST_20260605T001739Z/41_dns_query_tests.txt",
        "source_version": "capture 2026-06-05T00:17:39Z",
        "source_class": "capture",
        "page_or_location": "41_dns_query_tests.txt lines 10-18",
        "evidence_excerpt": "DNS server 10.0.0.1 answered the resolver query.",
        "terms": ["resolver", "DNS"],
    }
    value.update(changes)
    return value


def test_first_id_dedup_and_monotonic_allocation(tmp_path):
    ws = workspace(tmp_path)
    assert leads.add_leads(ws, "DR-DNS-B3", "B3", "Which resolver?", [hit()]) == ["L-000001"]
    assert leads.add_leads(ws, "DR-DNS-B3", "B3", "Which resolver?", [hit()]) == ["L-000001"]
    assert leads.add_leads(ws, "DR-DNS-B3", "B3", "Which resolver?", [hit(source_version="capture v2")]) == ["L-000002"]
    assert leads.add_leads(ws, "DR-DNS-B3", "B3", "Which DNS server?", [hit()]) == ["L-000003"]
    assert [r["lead_id"] for r in leads.open_leads(ws)] == ["L-000001", "L-000002", "L-000003"]


def test_review_overlay_transitions_and_evidence_validation(tmp_path):
    ws = workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-DNS-B3", "B3", "Which resolver?", [hit()])[0]
    with pytest.raises(ValueError, match="evidence_ids"):
        leads.review(ws, [lead_id], "resolved", "tester", "done")
    with pytest.raises(ValueError, match="unknown evidence"):
        leads.review(ws, [lead_id], "resolved", "tester", "done", ["E-99"])
    assert leads.review(ws, [lead_id], "resolved", "tester", "done", ["E-1"])["reviewed"] == [lead_id]
    assert leads.open_leads(ws) == []
    assert leads.add_leads(ws, "DR-DNS-B3", "B3", "Which resolver?", [hit()]) == [lead_id]
    assert leads.open_leads(ws) == []
    with pytest.raises(ValueError, match="explicit note"):
        leads.review(ws, [lead_id], "open", "tester", "")
    leads.review(ws, [lead_id], "open", "tester", "recheck after source update")
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [lead_id]
    leads.review(ws, [lead_id], "retired", "tester", "question removed")
    assert leads.open_leads(ws) == []


def test_invalid_review_and_unresolved_migrated_source(tmp_path):
    ws = workspace(tmp_path)
    with pytest.raises(ValueError, match="rel_path"):
        leads.add_leads(ws, "DR-X-B1", "B1", "Question", [hit(rel_path=None)])
    lead_id = leads.add_leads(
        ws, "DR-X-B1", "B1", "Question",
        [hit(rel_path=None, legacy_evidence_ids=["E-44"], source_ref="durable historical ref")],
        migration=True,
    )[0]
    assert leads.open_leads(ws)[0]["source_ref"] == "durable historical ref"
    with pytest.raises(ValueError, match="unknown lead"):
        leads.review(ws, ["L-999999"], "not_an_answer", "tester", "read")


def test_truncated_tail_is_reported_and_recovered_on_append(tmp_path):
    ws = workspace(tmp_path)
    leads.add_leads(ws, "DR-X-B1", "B1", "Question", [hit()])
    path = ws / "csa-work" / "intake" / "leads.jsonl"
    with path.open("ab") as fh:
        fh.write(b'{"lead_id":"L-000002"')
    checked = leads.verify(ws)
    assert checked["status"] == "ERROR" and checked["truncated_lines"] == [2]
    assert leads.add_leads(ws, "DR-X-B2", "B2", "Another", [hit(page_or_location="line 30")]) == ["L-000002"]
    assert leads.verify(ws)["status"] == "OK"


def _write_one(args):
    ws, n = args
    return leads.add_leads(Path(ws), f"DR-X-B{n}", f"B{n}", f"Question {n}", [hit(page_or_location=f"line {n}")])[0]


def test_concurrent_writers_allocate_unique_ids(tmp_path):
    ws = workspace(tmp_path)
    with multiprocessing.Pool(4) as pool:
        ids = pool.map(_write_one, [(str(ws), n) for n in range(1, 9)])
    assert sorted(ids) == [f"L-{n:06d}" for n in range(1, 9)]
    assert leads.verify(ws)["status"] == "OK"


def test_verify_reports_duplicate_unknown_review_and_bad_evidence_link(tmp_path):
    ws = workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-X-B1", "B1", "Question", [hit()])[0]
    lead_path = ws / "csa-work" / "intake" / "leads.jsonl"
    record = json.loads(lead_path.read_text(encoding="utf-8").splitlines()[0])
    with lead_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    reviews = ws / "csa-work" / "intake" / "leads-reviews.jsonl"
    with reviews.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"lead_id": "L-999999", "state": "open", "evidence_ids": [], "by": "x", "at": "2026-01-01T00:00:00Z", "note": ""}) + "\n")
        fh.write(json.dumps({"lead_id": lead_id, "state": "resolved", "evidence_ids": ["E-404"], "by": "x", "at": "2026-01-01T00:00:00Z", "note": ""}) + "\n")
    checked = leads.verify(ws)
    assert checked["status"] == "ERROR"
    assert checked["duplicate_ids"] == [lead_id]
    assert checked["unknown_review_leads"] == ["L-999999"]
    assert checked["bad_evidence_links"] == [{"lead_id": lead_id, "evidence_ids": ["E-404"]}]


def _migration_workspace(tmp_path: Path) -> Path:
    ws = workspace(tmp_path)
    matrix = ws / "csa-work" / "evidence-matrix.csv"
    fields = ["evidence_id", "csa_area", "question", "claim", "status", "source_title", "source_version", "section",
              "page_or_location", "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state"]
    with matrix.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"evidence_id": "E-1", "csa_area": "network_and_connectivity", "question": "q", "claim": "fact",
                         "status": "VERIFIED", "source_title": "src/a.txt", "page_or_location": "line 1", "evidence_excerpt": "fact", "review_state": "pending"})
        for eid, question, location in (("E-2", "DR-DNS-B1: Which resolver?", "line 2"),
                                        ("E-3", "DR-DNS-B1: Which resolver?", "line 2"),
                                        ("E-4", "DR-DNS-B2: Which fallback?", "line 3")):
            writer.writerow({"evidence_id": eid, "csa_area": "gap_lookup", "question": question,
                             "claim": f"Possible answer to {question.split(':', 1)[0]}: the source reads: candidate",
                             "status": "UNCONFIRMED", "source_title": "src/a.txt", "source_version": "v1",
                             "page_or_location": location, "evidence_excerpt": f"candidate {location}", "review_state": "pending"})
    (ws / "csa-work" / "evidence-reviews.jsonl").write_text(
        json.dumps({"evidence_id": "E-1", "state": "reviewed", "by": "source check", "at": "2026-01-01T00:00:00Z", "note": "ok"}) + "\n" +
        json.dumps({"evidence_id": "E-2", "state": "rejected", "by": "old", "at": "2026-01-01T00:00:00Z", "note": "not answer"}) + "\n" +
        json.dumps({"evidence_id": "E-3", "state": "rejected", "by": "old", "at": "2026-01-01T00:00:00Z", "note": "not answer"}) + "\n" +
        json.dumps({"evidence_id": "E-4", "state": "reviewed", "by": "old", "at": "2026-01-01T00:00:00Z", "note": "settled by E-1"}) + "\n",
        encoding="utf-8")
    con = sqlite3.connect(ws / "csa-work" / "discovery-index.sqlite")
    con.execute("CREATE TABLE files(file_id INTEGER PRIMARY KEY, rel_path TEXT, archived INTEGER, dup_of INTEGER)")
    con.execute("INSERT INTO files(rel_path,archived,dup_of) VALUES('src/a.txt',0,NULL)")
    con.commit(); con.close()
    return ws


def test_guarded_migration_dry_run_apply_and_rollback_preview(tmp_path):
    ws = _migration_workspace(tmp_path)
    matrix = ws / "csa-work" / "evidence-matrix.csv"
    before = matrix.read_bytes()
    dry = leads.migrate(ws, apply=False)
    assert dry["status"] == "DRY_RUN" and dry["counts"]["candidate_rows"] == 3
    assert dry["counts"]["leads"] == 2 and dry["counts"]["duplicates_collapsed"] == 1
    assert dry["counts"]["states"] == {"not_an_answer": 1, "resolved": 1}
    assert len(dry["mapping"]) == 3 and not (ws / "csa-work" / "intake" / "leads.jsonl").exists()
    applied = leads.migrate(ws, apply=True)
    assert applied["status"] == "OK" and Path(applied["manifest"]).is_file()
    assert matrix.read_bytes() == before
    assert leads.verify(ws)["status"] == "OK"
    assert [r["state"] for r in leads._list(ws, None, None)["leads"]] == ["not_an_answer", "resolved"]
    review_log = (ws / "csa-work" / "evidence-reviews.jsonl").read_text(encoding="utf-8")
    assert review_log.count("migrated to lead L-") == 3
    preview = leads.rollback(ws, Path(applied["manifest"]), apply=False)
    assert preview["status"] == "DRY_RUN" and preview["restore_evidence_reviews"] == 3 and preview["retire_leads"] == 2
    assert matrix.read_bytes() == before


def test_migration_stops_on_ambiguous_review(tmp_path):
    ws = _migration_workspace(tmp_path)
    with (ws / "csa-work" / "evidence-reviews.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"evidence_id": "E-4", "state": "reviewed", "by": "old", "at": "2026-01-02T00:00:00Z", "note": "looked at it"}) + "\n")
    result = leads.migrate(ws, apply=False)
    assert result["status"] == "ERROR"
    assert result["needs_manual_classification"] == ["E-4"]
