from __future__ import annotations

from pathlib import Path

from csa_docx import evidence_refresh, evidence_stale
from csa_docx.v2repo import Repo


def test_v2_refresh_rejects_removed_source_without_v1_log(tmp_path: Path):
    from csa_docx.v2_cleanup import repair_provenance
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx() as con:
        con.execute("INSERT INTO indexed_file(rel_path) VALUES ('Discovery Data/old.txt')")
        eid = repo.evidence.create("old claim", "Discovery Data/old.txt", excerpt="old", status="VERIFIED")
        repo.evidence.accept(eid, by="test")
    repo.close()
    assert repair_provenance(work, dry_run=False)["canonical"] == 1
    assert evidence_refresh.run(work)["rejected"] == []                    # the source is still indexed
    repo = Repo(work)
    with repo.tx() as con:
        con.execute("DELETE FROM indexed_file WHERE rel_path='Discovery Data/old.txt'")
    repo.close()
    result = evidence_refresh.run(work)
    assert result["rejected"] == [{"evidence_id": "E-001", "reason": "source unavailable in V2 index: Discovery Data/old.txt"}]
    repo = Repo(work)
    assert repo.evidence.get("E-001")["review_state"] == "rejected"
    assert repo.con.execute("SELECT action FROM review_event WHERE subject_id='E-001' ORDER BY id DESC LIMIT 1").fetchone()[0] == "reject"
    repo.close()
    assert not (work / "evidence-reviews.jsonl").exists()


def test_v2_refresh_reports_unresolved_and_ambiguous_rows_without_rejecting_them(tmp_path: Path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx() as con:
        for path in ("captures/HOSTA/20_listening_ports.txt", "captures/HOSTB/20_listening_ports.txt"):
            con.execute("INSERT INTO indexed_file(rel_path) VALUES (?)", (path,))
        for claim, source in (("ports", "20_listening_ports.txt"), ("legacy", "legacy/never-indexed.txt"),
                              ("nothing found", "searched: evidence matrix; discovery index")):
            repo.evidence.accept(repo.evidence.create(claim, source, excerpt="x", status="VERIFIED"), by="test")
    repo.close()
    events = _events(work)
    result = evidence_refresh.run(work)
    assert result["rejected"] == [] and result["checked"] == 3
    assert [(r["evidence_id"], r["state"]) for r in result["review"]] == [
        ("E-001", "ambiguous"), ("E-002", "unresolved"), ("E-003", "unresolved")]
    repo = Repo(work)
    assert {row["review_state"] for row in repo.evidence.list()} == {"accepted"}        # nothing rejected or deleted
    repo.close()
    assert _events(work) == events
    assert not (work.parent / "csa-work").exists() and not (work / "evidence-reviews.jsonl").exists()


def _events(work: Path) -> int:
    repo = Repo(work)
    try:
        return repo.con.execute("SELECT COUNT(*) FROM review_event").fetchone()[0]
    finally:
        repo.close()


def test_v2_stale_answers_read_sqlite_and_report_missing_ids(tmp_path: Path):
    work = tmp_path / "csa-work-v2"
    (work / "cards").mkdir(parents=True)
    (work / "cards" / "TIME.answer.md").write_text("Time was [E-099].\n", encoding="utf-8")
    repo = Repo(work)
    repo.close()
    stale = evidence_stale.stale_rows(work)
    assert stale["TIME"][0]["why"] == "not available in csa.sqlite"
    text = evidence_stale.report(work)
    assert "E-099" in text
