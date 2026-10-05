import json

from csa_docx import answer_cache as ac


def _setup(tmp_path):
    card = {"questions": [{"id": "B1", "text": "q1"}, {"id": "B2", "text": "q2"}],
            "evidence": {"B1": {"rows": [{"id": "E-001", "status": "VERIFIED", "claim": "a"}]},
                         "B2": {"rows": [{"id": "E-002", "status": "VERIFIED", "claim": "b"}]}}}
    cj = tmp_path / "K.json"
    cj.write_text(json.dumps(card), encoding="utf-8")
    mx = tmp_path / "m.csv"
    mx.write_text("evidence_id,claim\nE-001,a\nE-002,b\n", encoding="utf-8")
    sheet = tmp_path / "K.answer.md"
    sheet.write_text("## B1\nFacts:\n- x\n", encoding="utf-8")
    return cj, mx, sheet


def test_none_without_manifest(tmp_path):
    cj, mx, sheet = _setup(tmp_path)
    assert ac.compare(sheet, ac.fingerprint(cj, mx))["status"] == "NONE"


def test_reuse_when_unchanged(tmp_path):
    cj, mx, sheet = _setup(tmp_path)
    ac.write_manifest(sheet, ac.fingerprint(cj, mx))
    assert (tmp_path / "K.manifest.json").is_file()
    assert ac.compare(sheet, ac.fingerprint(cj, mx)) == {"status": "REUSE", "changed": []}


def test_partial_when_cited_matrix_row_changes(tmp_path):
    cj, mx, sheet = _setup(tmp_path)
    ac.write_manifest(sheet, ac.fingerprint(cj, mx))
    mx.write_text("evidence_id,claim\nE-001,a\nE-002,changed\n", encoding="utf-8")
    assert ac.compare(sheet, ac.fingerprint(cj, mx)) == {"status": "PARTIAL", "changed": ["B2"]}


def test_stale_when_sheet_edited(tmp_path):
    cj, mx, sheet = _setup(tmp_path)
    ac.write_manifest(sheet, ac.fingerprint(cj, mx))
    sheet.write_text("edited", encoding="utf-8")
    assert ac.compare(sheet, ac.fingerprint(cj, mx))["status"] == "STALE"


def test_stale_when_questions_change_or_hosts_change(tmp_path):
    cj, mx, sheet = _setup(tmp_path)
    hosts = tmp_path / "hosts.csv"
    hosts.write_text("h\n1\n", encoding="utf-8")
    ac.write_manifest(sheet, ac.fingerprint(cj, mx, hosts))
    hosts.write_text("h\n2\n", encoding="utf-8")
    assert ac.compare(sheet, ac.fingerprint(cj, mx, hosts))["status"] == "STALE"
    card = json.loads(cj.read_text())
    card["questions"].append({"id": "B3", "text": "q3"})
    cj.write_text(json.dumps(card), encoding="utf-8")
    assert ac.compare(sheet, ac.fingerprint(cj, mx, hosts))["status"] == "STALE"
