"""The index build records what came in: added, changed, removed and unreadable files (csa-work/intake/)."""
import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
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


def _search(env: dict, terms: str) -> dict:
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "search", terms],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


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
    with zipfile.ZipFile(src / "deck.pptx", "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    _build(env)
    rec = _latest(work)
    assert rec["unreadable"][0]["status"] == "skipped" and rec["unreadable"][0]["ext"] == ".pptx"


def test_pptx_slide_notes_and_comments_are_indexed(tmp_path):
    src, work, env = _project(tmp_path)
    with zipfile.ZipFile(src / "deck.pptx", "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>SlideFact</a:t></a:r></a:p></p:sld>')
        z.writestr("ppt/notesSlides/notesSlide1.xml", '<p:notes xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>NoteFact</a:t></a:r></a:p></p:notes>')
        z.writestr("ppt/comments/comment1.xml", '<p:cmLst xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>CommentFact</a:t></a:r></a:p></p:cmLst>')
    _build(env)
    assert _latest(work)["added"][0]["status"] == "indexed"
    for term in ("SlideFact", "NoteFact", "CommentFact"):
        assert _search(env, term)["results"]


def test_older_index_retries_unchanged_pptx_that_was_skipped(tmp_path):
    src, work, env = _project(tmp_path)
    with zipfile.ZipFile(src / "deck.pptx", "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="p" xmlns:a="a"><a:t>RecoveredSlideFact</a:t></p:sld>')
    _build(env)
    con = sqlite3.connect(work / "discovery-index.sqlite")
    fid = con.execute("SELECT file_id FROM files WHERE rel_path='src/deck.pptx'").fetchone()[0]
    chunk_ids = [r[0] for r in con.execute("SELECT chunk_id FROM chunk_map WHERE file_id=?", (fid,))]
    con.executemany("DELETE FROM chunks WHERE rowid=?", [(i,) for i in chunk_ids])
    con.execute("DELETE FROM chunk_map WHERE file_id=?", (fid,))
    con.execute("UPDATE files SET status='skipped', reason='binary type .pptx' WHERE file_id=?", (fid,))
    con.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    con.commit(); con.close()
    _build(env)
    assert _search(env, "RecoveredSlideFact")["results"]
    assert _latest(work)["changed"][0]["status"] == "indexed"


def test_docx_headers_footers_notes_and_comments_are_indexed(tmp_path):
    src, work, env = _project(tmp_path)
    with zipfile.ZipFile(src / "report.docx", "w") as z:
        for part, fact in (("document", "BodyFact"), ("header1", "HeaderFact"), ("footer1", "FooterFact"),
                           ("footnotes", "FootnoteFact"), ("endnotes", "EndnoteFact"), ("comments", "CommentFact")):
            z.writestr(f"word/{part}.xml", f'<w:root xmlns:w="w"><w:p><w:r><w:t>{fact}</w:t></w:r></w:p></w:root>')
    _build(env)
    for term in ("BodyFact", "HeaderFact", "FooterFact", "FootnoteFact", "EndnoteFact", "CommentFact"):
        assert _search(env, term)["results"]


def test_xlsx_rows_beyond_twenty_thousand_are_indexed(tmp_path):
    src, work, env = _project(tmp_path)
    rows = ['<row r="1"><c r="A1" t="inlineStr"><is><t>Value</t></is></c></row>']
    rows += [f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>row-{n}</t></is></c></row>'
             for n in range(2, 20002)]
    rows.append('<row r="20002"><c r="A20002" t="inlineStr"><is><t>LastSpreadsheetFact</t></is></c></row>')
    with zipfile.ZipFile(src / "large.xlsx", "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   + "".join(rows) + '</sheetData></worksheet>')
    _build(env)
    assert _search(env, "LastSpreadsheetFact")["results"]
    con = sqlite3.connect(work / "discovery-index.sqlite")
    assert con.execute("SELECT COUNT(*) FROM rows WHERE table_name='large/data'").fetchone()[0] == 20001
    con.close()


def test_same_size_same_mtime_document_change_is_detected(tmp_path):
    src, work, env = _project(tmp_path)
    path = src / "a.txt"
    path.write_text("first\n")
    stamp = time.time() - 60
    os.utime(path, (stamp, stamp))
    _build(env)
    path.write_text("other\n")
    os.utime(path, (stamp, stamp))
    _build(env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["changed"]] == ["src/a.txt"]
    assert _search(env, "other")["results"] and not _search(env, "first")["results"]


def test_missing_source_fails_without_replacing_live_index(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("RetainedFact\n")
    _build(env)
    before = (work / "discovery-index.sqlite").read_bytes()
    src.rename(src.with_name("source-offline"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "SOURCE_NOT_AVAILABLE" in r.stdout
    assert (work / "discovery-index.sqlite").read_bytes() == before


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


def test_gpresult_html_and_xml_are_indexed_with_source_lines(tmp_path):
    src, work, env = _project(tmp_path)
    cap = src / "REVELOC_discovery_HOSTA01_20261029T010203Z"
    cap.mkdir()
    (cap / "62_gpresult.html").write_text(
        "<html>\n<body><div>VisiblePolicyValue</div></body>\n"
        "<EventXml>&amp;lt;Data Name='PolicyPath'&amp;gt;EscapedPolicyValue&amp;lt;/Data&amp;gt;</EventXml>\n</html>\n",
        encoding="utf-8")
    (cap / "64_gpresult.xml").write_text(
        "<Rsop>\n<GPO ID='{ABC}'><Name>DetailedPolicyName</Name></GPO>\n</Rsop>\n", encoding="utf-8")
    (cap / "76_logs_dns_ntp_auth.xml").write_text(
        "<Event><System><EventID>4624</EventID></System><EventData>FirstEvent</EventData></Event>\n"
        "<Event><System><EventID>4648</EventID></System><EventData>SecondUniqueEvent</EventData></Event>\n",
        encoding="utf-8")
    _build(env)
    rec = _latest(work)
    assert {f["status"] for f in rec["added"]} == {"indexed"}
    assert rec["unreadable"] == []
    assert _search(env, "VisiblePolicyValue")["results"][0]["page_or_location"].endswith("line 2")
    assert _search(env, "EscapedPolicyValue")["results"][0]["page_or_location"].endswith("line 3")
    assert _search(env, "DetailedPolicyName")["results"][0]["source_title"].endswith("64_gpresult.xml")
    assert _search(env, "SecondUniqueEvent")["results"][0]["page_or_location"].endswith("line 2")


def test_large_repeating_xml_is_fully_indexed(tmp_path):
    src, work, env = _project(tmp_path)
    payload = "x" * 3600
    lines = ["<Root>"] + [f"<Item key='{i}'>{payload}{' KeepThisRepeatedValue' if i == 250 else ''}</Item>"
                              for i in range(300)] + ["</Root>"]
    (src / "large.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _build(env)
    added = _latest(work)["added"][0]
    assert added["status"] == "indexed" and added["reason"].startswith("xml lines=301")
    hit = _search(env, "KeepThisRepeatedValue")["results"][0]
    assert hit["source_title"] == "src/large.xml" and hit["page_or_location"].endswith("line 252")


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
    (work / "intake" / f"{_latest(work)['id']}.evidence.md").write_text("# read\nsrc/a.txt\nsrc/b.png\n")
    before = (work / "intake" / "latest.json").read_bytes()
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build", "--rebuild"],
                       capture_output=True, text=True, env=env)
    assert json.loads(r.stdout)["intake"] is None and (work / "intake" / "latest.json").read_bytes() == before
    (src / "c.txt").write_text("three\n")
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build", "--rebuild"],
                       capture_output=True, text=True, env=env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["added"]] == ["src/c.txt"] and rec["changed"] == [] and rec["removed"] == []


def test_rebuild_reports_file_that_becomes_readable(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "gpresult.xml").write_text("<Rsop><Name>NewlySearchablePolicy</Name></Rsop>\n", encoding="utf-8")
    _build(env)
    first = _latest(work)
    (work / "intake" / f"{first['id']}.evidence.md").write_text("# read\nsrc/gpresult.xml\n")
    con = sqlite3.connect(work / "discovery-index.sqlite")
    fid = con.execute("SELECT file_id FROM files WHERE rel_path='src/gpresult.xml'").fetchone()[0]
    chunk_ids = [r[0] for r in con.execute("SELECT chunk_id FROM chunk_map WHERE file_id=?", (fid,))]
    con.executemany("DELETE FROM chunks WHERE rowid=?", [(i,) for i in chunk_ids])
    con.execute("DELETE FROM chunk_map WHERE file_id=?", (fid,))
    con.execute("UPDATE files SET status='skipped', reason='rendering duplicated by a text file in the same capture' "
                "WHERE file_id=?", (fid,))
    con.commit()
    con.close()
    r = subprocess.run([sys.executable, str(SCRIPT), "--project", "t-intake", "build", "--rebuild"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = _latest(work)
    assert rec["added"] == [] and [f["rel_path"] for f in rec["changed"]] == ["src/gpresult.xml"]
    assert rec["changed"][0]["status"] == "indexed"


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
    (work / "intake" / f"{rec['id']}.evidence.md").write_text("# read\nsrc/a.txt\nsrc/b.txt\n")
    (src / "c.txt").write_text("three\n")
    _build(env)
    rec = _latest(work)
    assert [f["rel_path"] for f in rec["added"]] == ["src/c.txt"] and rec["carried_from"] == []


def test_incomplete_intake_report_does_not_mark_document_read(tmp_path):
    src, work, env = _project(tmp_path)
    (src / "a.txt").write_text("one\n")
    _build(env)
    first = _latest(work)
    (work / "intake" / f"{first['id']}.evidence.md").write_text("# report exists but omits its source\n")
    (src / "b.txt").write_text("two\n")
    _build(env)
    rec = _latest(work)
    assert rec["carried_from"] == [first["id"]]
    assert sorted(f["rel_path"] for f in rec["added"]) == ["src/a.txt", "src/b.txt"]


def test_capture_only_intake_is_carried_until_report_exists(tmp_path):
    src, work, env = _project(tmp_path)
    cap = src / "REVELOC_discovery_HOSTA01_20261029T010203Z"
    cap.mkdir()
    (cap / "03_time_status.txt").write_text("Source: TIME01\n")
    _build(env)
    first = _latest(work)
    (cap / "14_resolver.txt").write_text("DNS: 10.0.0.1\n")
    _build(env)
    rec = _latest(work)
    assert rec["carried_from"] == [first["id"]]
    assert sorted(Path(f["rel_path"]).name for f in rec["added"]) == ["03_time_status.txt", "14_resolver.txt"]
