"""Evidence Browser source lookup over repaired V2 provenance (S618)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENTS / "framework"))

from csa_docx.v2repo import Repo                        # noqa: E402
from csa_docx.v2_cleanup import repair_provenance       # noqa: E402
from backend import app as browser                      # noqa: E402

CAPTURE = "sources/APP_discovery_HOSTA_20260101T000000Z"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A V2 project whose source boundary is <root>/sources. One indexed file sits outside it."""
    root = tmp_path / "project"
    for rel in (f"{CAPTURE}/03_time_status.txt", "sources/docs/Asset Inventory.xlsx",
                "sources/a/20_listening_ports.txt", "sources/b/20_listening_ports.txt",
                "outside/private-notes.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
    work = root / "csa-work-v2"
    repo = Repo(work)
    with repo.tx() as con:
        con.executemany("INSERT INTO indexed_file(rel_path) VALUES (?)",
                        [(f"{CAPTURE}/03_time_status.txt",), ("sources/docs/Asset Inventory.xlsx",),
                         ("sources/a/20_listening_ports.txt",), ("sources/b/20_listening_ports.txt",),
                         ("outside/private-notes.txt",), ("sources/docs/deleted-later.txt",)])
        rows = [("E-001", "unique", "legacy/Asset Inventory.xlsx", "accepted"),
                ("E-002", "capture", "APP_discovery_HOSTA_20260101T000000Z: 03_time_status.txt", "accepted"),
                ("E-003", "ambiguous", "20_listening_ports.txt", "accepted"),
                ("E-004", "missing", "legacy/never-indexed.docx", "accepted"),
                ("E-005", "outside", "outside/private-notes.txt", "accepted"),
                ("E-006", "previous CSA", "Previous_Current_State_Assessment.docx", "rejected"),
                ("E-007", "file gone", "sources/docs/deleted-later.txt", "accepted")]
        con.executemany("INSERT INTO evidence(id,claim,source_title,status,review_state) VALUES (?,?,?,'VERIFIED',?)", rows)
    repo.close()
    project = {"key": "test", "label": "Test", "project_root": str(root), "work_dir": str(work),
               "default_source_set": str(root / "sources"), "index_extra_sources": ""}
    monkeypatch.setattr(browser, "system_project", lambda key: project)
    monkeypatch.setattr(browser, "agents_dir", lambda: AGENTS)
    return work


def _file_id(work: Path, rel_path: str) -> int:
    repo = Repo(work)
    try:
        return repo.con.execute("SELECT rowid FROM indexed_file WHERE rel_path=?", (rel_path,)).fetchone()[0]
    finally:
        repo.close()


def test_repaired_rows_open_their_canonical_source(store):
    assert repair_provenance(store, dry_run=False)["canonical"] == 4
    unique = browser.evidence_sources("test", "E-001")
    assert unique["state"] == "found" and unique["provenance"]["recorded"] is True
    assert unique["sources"] == [{"file_id": _file_id(store, "sources/docs/Asset Inventory.xlsx"),
                                  "rel_path": "sources/docs/Asset Inventory.xlsx", "host": "", "status": "indexed"}]
    assert unique["provenance"]["original_source"] == "legacy/Asset Inventory.xlsx"
    capture = browser.evidence_sources("test", "E-002")
    assert capture["state"] == "found"
    assert [row["rel_path"] for row in capture["sources"]] == [f"{CAPTURE}/03_time_status.txt"]
    # the returned file opens through the same boundary check the file viewer uses
    row, path = browser.safe_file(browser.system_project("test"), capture["sources"][0]["file_id"])
    assert path.is_file() and row["rel_path"] == f"{CAPTURE}/03_time_status.txt"


def test_ambiguous_and_unresolved_rows_are_not_resolved_links(store):
    repair_provenance(store, dry_run=False)
    ambiguous = browser.evidence_sources("test", "E-003")
    assert ambiguous["state"] == "ambiguous" and ambiguous["sources"] == []
    assert ambiguous["candidates"] == ["sources/a/20_listening_ports.txt", "sources/b/20_listening_ports.txt"]
    assert ambiguous["provenance"]["state"] == "ambiguous" and "several indexed files" in ambiguous["provenance"]["reason"]
    missing = browser.evidence_sources("test", "E-004")
    assert missing["state"] == "unavailable" and missing["sources"] == [] and missing["candidates"] == []
    assert missing["provenance"] == {"state": "unresolved", "recorded": True,
                                     "reason": "no indexed file matches: legacy/never-indexed.docx",
                                     "original_source": "legacy/never-indexed.docx"}


def test_paths_outside_the_source_boundary_are_rejected(store):
    repair_provenance(store, dry_run=False)
    outside = browser.evidence_sources("test", "E-005")
    assert outside["state"] == "unavailable" and outside["sources"] == []
    assert outside["unavailable"] == [{"rel_path": "outside/private-notes.txt",
                                       "reason": "the cited path is outside the project source boundary"}]
    gone = browser.evidence_sources("test", "E-007")
    assert gone["state"] == "unavailable" and gone["sources"] == []
    assert gone["unavailable"][0]["reason"] == "the source file is unavailable"


def test_unchecked_store_uses_the_same_rules_without_a_repair(store):
    unchecked = browser.evidence_sources("test", "E-002")
    assert unchecked["state"] == "found" and unchecked["provenance"]["recorded"] is False
    assert browser.evidence_sources("test", "E-003")["state"] == "ambiguous"
    assert browser.evidence_sources("test", "E-003")["sources"] == []


def test_previous_csa_evidence_stays_rejected_and_offers_no_source(store):
    result = repair_provenance(store, dry_run=False)
    assert "E-006" not in result["ambiguous_ids"] + result["unresolved_ids"] and result["checked"] == 6
    rejected = browser.evidence_sources("test", "E-006")
    assert rejected["state"] == "rejected" and rejected["sources"] == []
    listed = {row["evidence_id"]: row for row in browser.evidence("test", limit=50)["rows"]}
    assert listed["E-006"]["review_state"] == "rejected"                    # labelled, never shown as current
    assert listed["E-006"]["source_title"] == "Previous_Current_State_Assessment.docx"
    assert not (store.parent / "csa-work").exists()                         # no V1 review log or matrix is written


# --------------------------------------------------------------------------- S619: live, read-only

def test_live_v2_source_lookup_never_leaves_the_source_boundary():
    """Every registered V2 store: a source link is offered only for a canonical path inside the
    project's source boundary; everything else is reported as ambiguous, unavailable or rejected."""
    import os
    import sqlite3
    registry = Path(os.environ.get("CSA_PROJECTS_FILE") or AGENTS / "csa-context" / "PROJECTS.yaml")
    if not registry.is_file():
        pytest.skip("no project registry here: nothing live to check")
    checked = 0
    for project in browser.projects().values():
        work = Path(project["work_dir"]).expanduser()
        if work.name != "csa-work-v2" or not (work / "csa.sqlite").is_file():
            continue
        roots = browser.source_roots(project)
        with sqlite3.connect(f"file:{work / 'csa.sqlite'}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(row) for row in con.execute(
                "SELECT id AS evidence_id, source_title, review_state FROM evidence ORDER BY id")]
        states: dict[str, int] = {}
        for target in rows[::25]:                       # an even sample across the store
            result = browser._v2_evidence_sources(project, target)
            states[result["state"]] = states.get(result["state"], 0) + 1
            assert result["state"] in ("found", "ambiguous", "unavailable", "rejected")
            if result["state"] != "found":
                assert result["sources"] == []
            for source in result["sources"]:
                path = browser.resolve_indexed_path(project, source["rel_path"])
                assert path.is_file() and any(root in path.parents for root in roots)
            checked += 1
        print(project["key"], states)
    if not checked:
        pytest.skip("no registered V2 store is available on this machine")
