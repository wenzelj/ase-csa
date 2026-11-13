from __future__ import annotations

from pathlib import Path

from csa_docx.convert_brief import build_brief
from csa_docx.v2repo import Repo
import csa_docx.v2repo.intake  # noqa: F401


def test_v2_brief_uses_scoped_sqlite_data_only(tmp_path: Path):
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.hosts.create("APP1", role="Application server", site="Site A")
        repo.hosts.create("PEER1", role="Database", site="Site A")
        repo.application_scope.add("app-a", "APP1", "owned", review_state="accepted")
        repo.application_scope.add("app-a", "PEER1", "peer", review_state="accepted")
        repo.con.execute("INSERT INTO indexed_file(rel_path,sha256,size) VALUES ('Discovery Data/a.txt','sha',1)")
        repo.evidence.create("APP1 uses PEER1", "Discovery Data/a.txt", status="VERIFIED")
        repo.leads.create("Which database is used?", "V2 index", dr_id="DR-1")
    repo.close()
    (work / "hosts").mkdir()
    (work / "hosts" / "hosts.csv").write_text("host,role\nLEGACY,Wrong\n", encoding="utf-8")
    result = build_brief(work, "3.4", application_key="app-a")
    assert result["status"] == "OK" and result["mode"] == "v2"
    text = Path(result["files"][0]).read_text(encoding="utf-8")
    assert "APP1" in text and "PEER1" in text and "Discovery Data/a.txt" in text
    assert "LEGACY" not in text and not (work / "evidence-matrix.csv").exists()


def test_v2_conversion_without_application_key_is_explicitly_not_applicable(tmp_path: Path):
    work = tmp_path / "csa-work-v2"
    Repo(work).close()
    result = build_brief(work, "3.4")
    assert result["status"] == "V2_CONVERSION_NOT_REQUIRED"
    assert result["files"] == []
