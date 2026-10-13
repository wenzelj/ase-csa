"""The index build records what came in: added, changed, removed and unreadable files (csa-work/intake/)."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3]
SCRIPT = AGENTS / "skills" / "csa-discovery-index" / "scripts" / "discovery_index.py"


def _project(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "proj"
    src = root / "src"
    work = root / "csa-work"
    src.mkdir(parents=True)
    work.mkdir()
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text("projects:\n  - key: t-intake\n"
                   f'    project_root: "{root}"\n    work_dir: "{work}"\n    default_source_set: "{src}"\n',
                   encoding="utf-8")
    env = {**os.environ, "CSA_PROJECTS_FILE": str(reg)}
    return src, work, env


def _build(env: dict) -> dict:
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _latest(work: Path) -> dict:
    return json.loads((work / "intake" / "latest.json").read_text(encoding="utf-8"))


def test_first_build_records_added_files(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("ROTPRDREV101 OT REVELOC server\n")
    (src / "b.png").write_bytes(b"\x89PNG not really")
    out = _build(env)
    rec = _latest(work)
    assert out["intake"] and Path(out["intake"]).is_file()
    assert {f["rel_path"] for f in rec["added"]} == {"src/a.txt", "src/b.png"}
    assert [f["rel_path"] for f in rec["unreadable"]] == ["src/b.png"]
    assert rec["unreadable"][0]["reason"] == "binary type .png"
    assert rec["id"] and (work / "intake" / f"{rec['id']}.json").is_file()


def test_record_lists_unreadable_files(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "deck.pptx").write_bytes(b"PK binary")
    _build(env)
    rec = _latest(work)
    assert rec["unreadable"][0]["status"] == "skipped" and rec["unreadable"][0]["ext"] == ".pptx"


def test_change_and_remove_are_recorded(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("one\n")
    (src / "b.png").write_bytes(b"x")
    _build(env)
    (src / "a.txt").write_text("one and two, a longer line\n")
    (src / "b.png").unlink()
    _build(env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["changed"]] == ["src/a.txt"]
    assert rec["removed"] == ["src/b.png"] and rec["added"] == []


def test_build_without_changes_keeps_latest(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("one\n")
    _build(env)
    before = (work / "intake" / "latest.json").read_bytes()
    out = _build(env)
    assert out["intake"] is None
    assert (work / "intake" / "latest.json").read_bytes() == before


def test_matrix_last_id_is_recorded(tmp_path):
    src, work, env = _project(tmp_path)
    (work / "evidence-matrix.csv").write_text("evidence_id,claim\nE-001,a\nE-002,b\nE-003,c\n", encoding="utf-8")
    (src / "a.txt").write_text("one\n")
    _build(env)
    assert _latest(work)["matrix_last_id"] == "E-003"


def _blank_pdf() -> bytes:
    """A valid one-page PDF with no text layer (what a scan without OCR looks like to pdftotext)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
            b"<< /Length 0 >>\nstream\n\nendstream"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def _text_pdf(text: str = "Fallback PDF text") -> bytes:
    """A self-contained one-page PDF with an extractable Helvetica text layer."""
    content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_pdf_text_falls_back_when_pdftotext_is_unavailable(tmp_path):
    src, work, env = _project(tmp_path)
    env["PATH"] = ""  # force the vendored pypdf path even when Poppler is installed on the test host
    (src / "document.pdf").write_bytes(_text_pdf())
    _build(env)
    rec = _latest(work)
    assert rec["added"][0]["status"] == "indexed" and rec["added"][0]["reason"] == "pdf text"
    assert rec["unreadable"] == []
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "search", "Fallback PDF text"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["results"][0]["source_title"] == "src/document.pdf"


def test_unchanged_pdf_previously_skipped_for_missing_pdftotext_is_retried(tmp_path):
    src, work, env = _project(tmp_path)
    env["PATH"] = ""
    (src / "document.pdf").write_bytes(_text_pdf("Retry this PDF"))
    _build(env)
    con = sqlite3.connect(work / "discovery-index.sqlite")
    file_id = con.execute("SELECT file_id FROM files WHERE rel_path='src/document.pdf'").fetchone()[0]
    chunk_ids = [r[0] for r in con.execute("SELECT chunk_id FROM chunk_map WHERE file_id=?", (file_id,))]
    con.executemany("DELETE FROM chunks WHERE rowid=?", [(i,) for i in chunk_ids])
    con.execute("DELETE FROM chunk_map WHERE file_id=?", (file_id,))
    con.execute("UPDATE files SET status='skipped', reason='pdf (pdftotext not available)' WHERE file_id=?", (file_id,))
    con.commit()
    con.close()

    _build(env)
    con = sqlite3.connect(work / "discovery-index.sqlite")
    assert con.execute("SELECT status, reason FROM files WHERE rel_path='src/document.pdf'").fetchone() == ("indexed", "pdf text")
    assert con.execute("SELECT COUNT(*) FROM chunk_map WHERE file_id=?", (file_id,)).fetchone()[0] > 0
    con.close()


def test_scanned_pdf_is_not_readable(tmp_path):
    src, work, env = _project(tmp_path)
    env["PATH"] = ""
    (src / "scan.pdf").write_bytes(_blank_pdf())
    _build(env)
    rec = _latest(work)
    assert rec["added"][0]["status"] == "skipped" and rec["added"][0]["reason"] == "pdf has no text layer (scanned)"
    assert [f["rel_path"] for f in rec["unreadable"]] == ["src/scan.pdf"]


def test_unreadable_lists_documents_not_capture_noise_or_empty_files(tmp_path):
    src, work, env = _project(tmp_path)
    cap = src / "REVELOC_discovery_HOSTA01_20260605T010203Z"
    cap.mkdir()
    (cap / "helper.dll").write_bytes(b"MZ binary")
    (cap / "03_time_status.txt").write_text("Source: ROTPRDSRV122\n")
    (src / "empty.txt").write_text("")
    (src / "deck.pptx").write_bytes(b"PK binary")
    _build(env)
    assert [f["rel_path"] for f in _latest(work)["unreadable"]] == ["src/deck.pptx"]


def test_rebuild_reports_only_real_changes(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("one\n")
    (src / "b.png").write_bytes(b"x")
    _build(env)
    (work / "intake" / f"{_latest(work)['id']}.evidence.md").write_text("# read\n")   # the agent has read it
    before = (work / "intake" / "latest.json").read_bytes()
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build", "--rebuild"],
                       capture_output=True, text=True, env=env)
    assert json.loads(r.stdout)["intake"] is None and (work / "intake" / "latest.json").read_bytes() == before
    (src / "c.txt").write_text("three\n")
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build", "--rebuild"],
                       capture_output=True, text=True, env=env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["added"]] == ["src/c.txt"] and rec["changed"] == [] and rec["removed"] == []


def test_second_ingest_carries_forward_documents_not_yet_read(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("one\n")
    _build(env)
    first = _latest(work)["id"]
    (src / "b.txt").write_text("two\n")
    _build(env)
    rec = _latest(work)
    assert rec["id"] != first and rec["carried_from"] == [first]
    assert sorted(f["rel_path"] for f in rec["added"]) == ["src/a.txt", "src/b.txt"]
    (work / "intake" / f"{rec['id']}.evidence.md").write_text("# read\n")   # the agent read both
    (src / "c.txt").write_text("three\n")
    _build(env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["added"]] == ["src/c.txt"] and rec["carried_from"] == []
