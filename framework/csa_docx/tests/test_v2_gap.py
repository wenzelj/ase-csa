from csa_docx.v2_gap import run
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
