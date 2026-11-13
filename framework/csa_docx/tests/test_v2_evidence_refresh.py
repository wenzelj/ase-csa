from __future__ import annotations

from pathlib import Path

from csa_docx import evidence_refresh, evidence_stale
from csa_docx.v2repo import Repo


def test_v2_refresh_rejects_removed_source_without_v1_log(tmp_path: Path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        eid = repo.evidence.create("old claim", "Discovery Data/old.txt", excerpt="old", status="VERIFIED")
        repo.evidence.accept(eid, by="test")
    repo.close()
    result = evidence_refresh.run(work)
    assert result["rejected"] == [{"evidence_id": "E-001", "reason": "source unavailable in V2 index: Discovery Data/old.txt"}]
    repo = Repo(work)
    assert repo.evidence.get("E-001")["review_state"] == "rejected"
    assert repo.con.execute("SELECT action FROM review_event WHERE subject_id='E-001' ORDER BY id DESC LIMIT 1").fetchone()[0] == "reject"
    repo.close()
    assert not (work / "evidence-reviews.jsonl").exists()


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
