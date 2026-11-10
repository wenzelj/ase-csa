"""A register has one row per host or part, so its card keeps more evidence rows than an ordinary question (48, not 8)."""
from pathlib import Path

from csa_docx import section_card


def _rows(n):
    return [{"evidence_id": f"E-{4000 + i}", "status": "VERIFIED", "csa_area": "identity_and_access",
             "section": "x", "claim": f"The Remote Desktop Users output on HOST{i:03d} is empty", "question": "q"} for i in range(n)]


def _run(kind, n, monkeypatch):
    rows = _rows(n)
    monkeypatch.setattr(section_card, "_matrix_rows", lambda ws: rows)
    monkeypatch.setattr(section_card, "_rejected", lambda ws: set())
    monkeypatch.setattr(section_card, "_latest_capture", lambda ws: None)
    monkeypatch.setattr(section_card, "superseded", lambda r, latest: None)
    seen = {}

    def fake_matrix(ws, query, limit=section_card.MAX_ROWS_PER_QUESTION):
        seen["limit"] = limit
        return [dict(r, score=0.7) for r in rows[:limit]]

    monkeypatch.setattr(section_card, "_matrix", fake_matrix)
    node = {"title": "Remote Desktop Users Inventory", "key": "RDU"}
    q = {"id": "B1", "kind": kind, "text": "one row per host"}
    pack = section_card.evidence_pack(node, [q], Path("."), terms={"B1": []})
    return pack["B1"], seen["limit"]


def test_register_keeps_one_evidence_row_per_host(monkeypatch):
    block, limit = _run("register", 20, monkeypatch)
    assert len(block["rows"]) == 20 and block["cut"] == []
    assert limit == 2 * section_card.REGISTER_ROWS_PER_QUESTION


def test_other_questions_keep_the_old_cap(monkeypatch):
    block, limit = _run("narrative", 20, monkeypatch)
    assert len(block["rows"]) == section_card.MAX_ROWS_PER_QUESTION
    assert limit == 2 * section_card.MAX_ROWS_PER_QUESTION


def test_register_also_looks_up_its_first_column(monkeypatch):
    rows = _rows(3)
    monkeypatch.setattr(section_card, "_matrix_rows", lambda ws: rows)
    monkeypatch.setattr(section_card, "_rejected", lambda ws: set())
    monkeypatch.setattr(section_card, "_latest_capture", lambda ws: None)
    monkeypatch.setattr(section_card, "superseded", lambda r, latest: None)
    queries = []
    monkeypatch.setattr(section_card, "_matrix", lambda ws, query, limit=8: queries.append(query) or [])
    node = {"title": "User and Service Account Inventory", "key": "U"}
    q = {"id": "B1", "kind": "register", "text": "one row per account name", "columns": ["Account Name", "Type", "Hosts(s)"]}
    section_card.evidence_pack(node, [q], Path("."), terms={"B1": []})
    assert any(x.split()[:2] == ["Account", "Name"] and "Accounts" in x.split() for x in queries), queries


def test_host_first_register_is_not_widened(monkeypatch):
    rows = _rows(3)
    monkeypatch.setattr(section_card, "_matrix_rows", lambda ws: rows)
    monkeypatch.setattr(section_card, "_rejected", lambda ws: set())
    monkeypatch.setattr(section_card, "_latest_capture", lambda ws: None)
    monkeypatch.setattr(section_card, "superseded", lambda r, latest: None)
    queries = []
    monkeypatch.setattr(section_card, "_matrix", lambda ws, query, limit=8: queries.append(query) or [])
    node = {"title": "Local Administrators Inventory", "key": "L"}
    q = {"id": "B1", "kind": "register", "text": "one row per host", "columns": ["Host(s)", "Member Name"]}
    section_card.evidence_pack(node, [q], Path("."), terms={"B1": []})
    assert len(queries) == 1, queries
