from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import app as workspace


def make_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    agents = tmp_path / ".agents"
    context = agents / "csa-context"
    skills = agents / "skills"
    context.mkdir(parents=True)
    skills.mkdir()
    project = tmp_path / "IAMPS"
    sources = project / "source"
    work = project / "csa-work"
    sources.mkdir(parents=True)
    work.mkdir()
    context.joinpath("PROJECTS.yaml").write_text(
        "projects:\n"
        "  - key: iamps-08\n"
        "    label: \"IAMPS\"\n"
        f"    project_root: \"{project}\"\n"
        f"    work_dir: \"{work}\"\n"
        f"    default_source_set: \"{sources}\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_AGENTS_DIR", str(agents))
    db = sqlite3.connect(work / "discovery-index.sqlite")
    db.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);"
        "CREATE TABLE captures(capture_id INTEGER PRIMARY KEY,folder TEXT,host TEXT,collector TEXT,capture_utc TEXT,archived INTEGER,superseded_by INTEGER,file_count INTEGER);"
        "CREATE TABLE files(file_id INTEGER PRIMARY KEY,rel_path TEXT,capture_id INTEGER,host TEXT,ext TEXT,size INTEGER,mtime REAL,sha1 TEXT,status TEXT,reason TEXT,dup_of INTEGER,source_class TEXT,archived INTEGER);"
        "CREATE TABLE rows(file_id INTEGER,table_name TEXT,fmt TEXT,block_no INTEGER,line_no INTEGER,data TEXT);"
        "CREATE TABLE chunks(content TEXT);"
        "CREATE TABLE chunk_map(chunk_id INTEGER,file_id INTEGER,line_start INTEGER,line_end INTEGER);"
    )
    db.executemany("INSERT INTO meta VALUES(?,?)", [("complete", "1"), ("built_at_utc", "2026-10-03T00:00:00Z")])
    db.execute("INSERT INTO captures VALUES(1,'capture','HOST01','collector','2026-10-01T00:00:00Z',0,NULL,1)")
    db.commit()
    db.close()
    return project, sources


def add_file(project: Path, rel_path: str, content: str = "first\nneedle\nlast\n") -> int:
    path = project / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (rel_path, 1, "HOST01", path.suffix, path.stat().st_size, path.stat().st_mtime, "indexed", "text", "capture", 0),
    )
    db.commit()
    file_id = cursor.lastrowid
    db.close()
    return int(file_id)


def test_summary_and_current_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    add_file(project, "source/03_time_status.txt")
    result = workspace.get_summary("iamps")
    assert result["current_captures"] == 1
    assert result["files_by_status"] == {"indexed": 1}
    assert result["coverage"][0]["families"]["Time"] == 1


def test_safe_file_rejects_indexed_path_outside_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    db = sqlite3.connect(project / "csa-work" / "discovery-index.sqlite")
    cursor = db.execute(
        "INSERT INTO files(rel_path,capture_id,host,ext,size,mtime,status,reason,source_class,archived) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("../outside.txt", None, None, ".txt", 7, 0, "indexed", "text", "other", 0),
    )
    db.commit(); file_id = cursor.lastrowid; db.close()
    with pytest.raises(HTTPException) as caught:
        workspace.safe_file(workspace.system_project("iamps"), file_id)
    assert caught.value.status_code == 403


def test_text_preview_keeps_citation_line(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 301)), encoding="utf-8")
    result = workspace.text_preview(path, "evidence.txt lines 140-142")
    assert result["highlight"] == [140, 142]
    assert any(line["number"] == 141 for line in result["lines"])


def test_search_stops_when_matrix_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_workspace(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def fake(command: list[str], **_: object):
        calls.append(command)
        return {"status": "OK", "verdict": "LIKELY_ANSWERED", "matches": []}

    monkeypatch.setattr(workspace, "run_json", fake)
    result = workspace.search("iamps", workspace.SearchRequest(query="NTP source"))
    assert [stage["kind"] for stage in result["stages"]] == ["matrix"]
    assert len(calls) == 1


def test_search_continues_to_index_and_resolves_file_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = make_workspace(tmp_path, monkeypatch)
    file_id = add_file(project, "source/03_time_status.txt")
    responses = iter([
        {"status": "OK", "verdict": "NO_MATCH", "matches": []},
        {"status": "OK", "count": 1, "results": [{"rel_path": "source/03_time_status.txt"}]},
    ])
    monkeypatch.setattr(workspace, "run_json", lambda *_args, **_kwargs: next(responses))
    result = workspace.search("iamps", workspace.SearchRequest(query="NTP source"))
    assert [stage["kind"] for stage in result["stages"]] == ["matrix", "index"]
    assert result["stages"][1]["results"][0]["file_id"] == file_id


def test_commit_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_workspace(tmp_path, monkeypatch)
    draft = workspace.EvidenceDraft(csa_area="network_and_connectivity", question="q", claim="c", status="VERIFIED")
    with pytest.raises(HTTPException) as caught:
        workspace.commit_evidence("iamps", workspace.CommitRequest(draft=draft, confirmed=False))
    assert caught.value.status_code == 409

