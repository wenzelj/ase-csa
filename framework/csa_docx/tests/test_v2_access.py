from csa_docx import answer_sheet, evidence_live, v2_access
from csa_docx.v2repo import Repo


def test_selected_v2_store_supplies_evidence_and_keeps_v1_path(tmp_path, monkeypatch):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.evidence.create(area="dns", question="Resolver?", claim="RMS resolver on HOST1",
                             source_title="capture", excerpt="resolver", actor="test")
    repo.close()
    old = tmp_path / "csa-work" / "evidence-matrix.csv"
    old.parent.mkdir()
    old.write_text("evidence_id,csa_area,question,claim,status,source_title,review_state\n"
                   "E-999,dns,Old?,V1 only,VERIFIED,old,accepted\n", encoding="utf-8")

    monkeypatch.delenv("CSA_WORK_DIR", raising=False)
    assert evidence_live.read(old)[0]["evidence_id"] == "E-999"
    monkeypatch.setenv("CSA_WORK_DIR", str(work))
    rows = evidence_live.read(old)
    assert [r["evidence_id"] for r in rows] == ["E-001"]
    assert list(answer_sheet.load_matrix(work / "evidence-matrix.csv")) == ["E-001"]
    assert v2_access.evidence_rows(work / "csa.sqlite")[0]["claim"] == "RMS resolver on HOST1"


def test_v2_index_uses_single_db(tmp_path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES ('capture.txt', 'x', 10)")
        repo.con.execute("INSERT INTO indexed_chunk(id, rel_path, heading, text) "
                         "VALUES (1, 'capture.txt', 'line 1', 'resolver configured')")
        repo.con.execute("INSERT INTO fts(chunk_id, rel_path, heading, text) "
                         "VALUES (1, 'capture.txt', 'line 1', 'resolver configured')")
    repo.close()
    db = work / "csa.sqlite"
    assert v2_access.index_status(db)["indexed_files"] == 1
    assert v2_access.index_search(db, "resolver")["results"][0]["rel_path"] == "capture.txt"
