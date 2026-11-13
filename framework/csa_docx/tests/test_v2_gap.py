from csa_docx.v2_gap import run, settle
from csa_docx.v2repo import Repo
import csa_docx.v2repo.intake  # noqa: F401


def test_v2_gap_check_writes_leads_and_gap_checks(tmp_path):
    work = tmp_path / "csa-work-v2"
    (work / "draft").mkdir(parents=True)
    (work / "draft" / "open-questions.md").write_text(
        "## 3.4 Time Synchronisation (TIME)\n\n"
        "- [B1] Which time source is configured?\n", encoding="utf-8")
    repo = Repo(work)
    try:
        with repo.tx():
            repo.con.execute(
                "INSERT INTO indexed_file(rel_path, sha256, size) VALUES (?, ?, ?)",
                ("capture.txt", "sha", 10))
            repo.con.execute(
                "INSERT INTO indexed_chunk(id, rel_path, heading, text) VALUES (?, ?, ?, ?)",
                (1, "capture.txt", "line 1", "configured time source is NTP"))
            repo.con.execute(
                "INSERT INTO fts(chunk_id, rel_path, heading, text) VALUES (?, ?, ?, ?)",
                (1, "capture.txt", "line 1", "configured time source is NTP"))
    finally:
        repo.close()

    result = run(work)
    assert result["summary"]["gaps"] == 1
    assert result["questions"][0]["verdict"] == "CANDIDATES"
    repo = Repo(work)
    try:
        assert repo.leads.list(state="open")
        assert repo.gap_checks.latest()["dr_id"].startswith("DR-TIME-B1")
    finally:
        repo.close()
    assert (work / "intake" / "gap-check-latest.json").is_file()


def test_v2_settlement_resolves_only_saved_question_leads_and_audits(tmp_path):
    work = tmp_path / "csa-work-v2"
    (work / "draft").mkdir(parents=True)
    (work / "draft" / "open-questions.md").write_text(
        "## 3.4 Time Synchronisation (TIME)\n\n- [B1] Which time source is configured?\n", encoding="utf-8")
    repo = Repo(work)
    with repo.tx():
        repo.con.execute("INSERT INTO evidence(id, question, claim, status, review_state) VALUES ('E-001', 'Which time source is configured?', 'NTP', 'VERIFIED', 'accepted')")
        lid = repo.leads.create("Which time source is configured?", "v2 evidence", dr_id="DR-TIME-B1")
    repo.close()
    record = {"questions": [{"dr_id": "DR-TIME-B1", "text": "Which time source is configured?", "lead_ids": [lid]}]}
    result = settle(work, record, [{"lead_id": lid, "state": "resolved", "evidence_ids": ["E-001"]}])
    assert result["status"] == "OK" and result["resolved"][0]["lead_id"] == lid
    repo = Repo(work)
    assert repo.leads.get(lid)["state"] == "resolved"
    assert repo.con.execute("SELECT action FROM review_event WHERE subject_id=? ORDER BY id DESC LIMIT 1", (lid,)).fetchone()[0] == "leads.resolve"
    repo.close()
    assert not (work.parent / "evidence-matrix.csv").exists()


def test_v2_settlement_rejects_stale_or_rejected_evidence_without_mutation(tmp_path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.con.execute("INSERT INTO evidence(id, claim, status, review_state) VALUES ('E-009', 'old', 'VERIFIED', 'rejected')")
        lid = repo.leads.create("Question A", "v2 evidence", dr_id="DR-A")
    repo.close()
    record = {"questions": [{"dr_id": "DR-A", "text": "Question A", "lead_ids": [lid]}]}
    result = settle(work, record, [{"lead_id": lid, "state": "resolved", "evidence_ids": ["E-009"]}])
    assert result["status"] == "ERROR"
    repo = Repo(work)
    assert repo.leads.get(lid)["state"] == "open"
    repo.close()
    stale = settle(work, record, [{"lead_id": "L-999999", "state": "not_an_answer"}])
    assert stale["status"] == "ERROR"
