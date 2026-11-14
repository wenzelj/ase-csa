import json
from pathlib import Path

from csa_docx import v2_access
from csa_docx.v2repo import Repo
from csa_docx.v2_cleanup import repair_provenance, resolve_source, restore_provenance

CAPTURE_A = "captures/APP_discovery_HOSTA_20260101T000000Z"
CAPTURE_B = "captures/APP_discovery_HOSTB_20260101T000000Z"
INDEXED = ["captures/source.txt", "docs/Asset Inventory.xlsx",
           f"{CAPTURE_A}/03_time_status.txt", f"{CAPTURE_B}/03_time_status.txt",
           f"{CAPTURE_A}/20_listening_ports.txt", f"{CAPTURE_B}/20_listening_ports.txt"]


def test_unique_provenance_repair_preserves_claim_and_id(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as c:
        c.execute("INSERT INTO indexed_file(rel_path) VALUES ('captures/source.txt')")
        c.execute("INSERT INTO evidence(id,claim,source_title,status) VALUES ('E-1','keep','source.txt','VERIFIED')")
    result = repair_provenance(tmp_path / "v2", dry_run=False)
    assert result["repaired"] == 1
    assert r.con.execute("SELECT id,claim,source_title FROM evidence").fetchone() == ('E-1','keep','captures/source.txt')
    r.close()


def _store(tmp_path) -> Path:
    """One row per case: unique match, capture-qualified match, several sources, ambiguous,
    missing source, a recorded search, and a rejected previous-CSA row."""
    v2 = tmp_path / "v2"
    r = Repo(v2)
    with r.tx() as c:
        c.executemany("INSERT INTO indexed_file(rel_path) VALUES (?)", [(p,) for p in INDEXED])
        rows = [("E-001", "unique", "legacy/Asset Inventory.xlsx", "VERIFIED", "accepted"),
                ("E-002", "capture", "APP_discovery_HOSTA_20260101T000000Z: 03_time_status.txt", "VERIFIED", "accepted"),
                ("E-003", "several", "APP_discovery_HOSTA_20260101T000000Z: 03_time_status.txt; "
                                     "APP_discovery_HOSTB_20260101T000000Z: 03_time_status.txt", "VERIFIED", "proposed"),
                ("E-004", "ambiguous", "20_listening_ports.txt", "VERIFIED", "accepted"),
                ("E-005", "missing", "legacy/never-indexed.docx", "VERIFIED", "accepted"),
                ("E-006", "searched", "searched: evidence matrix; discovery index", "NOT_FOUND", "proposed"),
                ("E-007", "previous CSA", "Previous_Current_State_Assessment.docx", "VERIFIED", "rejected"),
                ("E-008", "already canonical", "captures/source.txt", "VERIFIED", "accepted")]
        c.executemany("INSERT INTO evidence(id,claim,source_title,status,review_state) VALUES (?,?,?,?,?)", rows)
    r.close()
    return v2


def _evidence(v2):
    r = Repo(v2)
    try:
        return r.con.execute("SELECT id, claim, status, review_state, source_title FROM evidence ORDER BY id").fetchall()
    finally:
        r.close()


def test_resolver_matches_only_what_is_unique():
    assert resolve_source("legacy/Asset Inventory.xlsx", INDEXED)["paths"] == ["docs/Asset Inventory.xlsx"]
    assert resolve_source("APP_discovery_HOSTB_20260101T000000Z: 03_time_status.txt (line 4)", INDEXED)["paths"] == [
        f"{CAPTURE_B}/03_time_status.txt"]
    ambiguous = resolve_source("20_listening_ports.txt", INDEXED)
    assert ambiguous["state"] == "ambiguous" and ambiguous["paths"] == [] and len(ambiguous["candidates"]) == 2
    assert resolve_source("legacy/never-indexed.docx", INDEXED)["state"] == "unresolved"
    assert resolve_source("APP_discovery_HOSTC_20260101T000000Z: 03_time_status.txt", INDEXED)["state"] == "unresolved"
    assert resolve_source("searched: evidence matrix", INDEXED)["reason"] == "the row records a search, not a source file"
    assert resolve_source("", INDEXED)["state"] == "unresolved"
    # one part that does not resolve keeps the whole row out of the canonical state
    assert resolve_source("captures/source.txt; 20_listening_ports.txt", INDEXED)["state"] == "ambiguous"
    assert resolve_source("captures/source.txt; nowhere.txt", INDEXED)["state"] == "unresolved"


def test_repair_gives_every_active_row_a_canonical_path_or_a_review_state(tmp_path):
    v2 = _store(tmp_path)
    before = _evidence(v2)
    result = repair_provenance(v2, dry_run=False)
    assert (result["checked"], result["canonical"], result["ambiguous"], result["unresolved"]) == (7, 4, 1, 2)
    assert result["repaired"] == 2 and result["ambiguous_ids"] == ["E-004"]
    assert result["unresolved_ids"] == ["E-005", "E-006"]
    after = _evidence(v2)
    assert [row[:4] for row in after] == [row[:4] for row in before]            # ID, claim, status, review state kept
    assert len(after) == 8                                                      # nothing deleted
    titles = {row[0]: row[4] for row in after}
    assert titles["E-001"] == "docs/Asset Inventory.xlsx"
    assert titles["E-002"] == f"{CAPTURE_A}/03_time_status.txt"
    for unchanged in ("E-003", "E-004", "E-005", "E-006", "E-007"):
        assert titles[unchanged] == {row[0]: row[4] for row in before}[unchanged]
    provenance = v2_access.evidence_provenance(v2 / "csa.sqlite")
    assert set(provenance) == {f"E-00{i}" for i in (1, 2, 3, 4, 5, 6, 8)}       # the rejected row is left alone
    assert provenance["E-003"]["state"] == "canonical" and provenance["E-003"]["paths"] == [
        f"{CAPTURE_A}/03_time_status.txt", f"{CAPTURE_B}/03_time_status.txt"]
    assert provenance["E-001"]["original_source"] == "legacy/Asset Inventory.xlsx"
    # ambiguous and unresolved rows carry no resolved path
    assert provenance["E-004"]["state"] == "ambiguous" and provenance["E-004"]["paths"] == []
    assert len(provenance["E-004"]["candidates"]) == 2
    assert provenance["E-005"]["state"] == "unresolved" and provenance["E-005"]["paths"] == []
    assert provenance["E-006"]["reason"] == "the row records a search, not a source file"


def test_repair_keeps_review_history_and_adds_one_event(tmp_path):
    v2 = _store(tmp_path)
    r = Repo(v2)
    with r.tx():
        r.evidence.reject("E-005", by="reviewer", note="wrong")
    history = r.con.execute("SELECT id, action, subject_id, note FROM review_event ORDER BY id").fetchall()
    r.close()
    repair_provenance(v2, dry_run=False)
    r = Repo(v2)
    events = r.con.execute("SELECT id, action, subject_id, note FROM review_event ORDER BY id").fetchall()
    r.close()
    assert events[:len(history)] == history
    assert [e[1] for e in events[len(history):]] == ["cleanup.provenance"]


def test_dry_run_writes_nothing(tmp_path):
    v2 = _store(tmp_path)
    before = (_evidence(v2), sorted(p.name for p in v2.rglob("*") if p.name != "backups"))
    result = repair_provenance(v2, dry_run=True)
    assert result["status"] == "DRY-RUN" and result["canonical"] == 4 and "report" not in result
    assert (_evidence(v2), sorted(p.name for p in v2.rglob("*") if p.name != "backups")) == before
    assert v2_access.evidence_provenance(v2 / "csa.sqlite") == {}


def test_pack_records_counts_predicate_hash_and_rollback(tmp_path):
    v2 = _store(tmp_path)
    packs = v2 / "cleanup-packs"
    packs.mkdir()
    (packs / "provenance-repair.json").write_text('{"original": true}', encoding="utf-8")
    before = _evidence(v2)
    result = repair_provenance(v2, dry_run=False)
    pack = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert Path(result["report"]).name.startswith("provenance-repair-") and Path(result["report"]).parent == packs
    assert json.loads((packs / "provenance-repair.json").read_text(encoding="utf-8")) == {"original": True}
    assert {k: pack[k] for k in ("repaired", "canonical", "ambiguous", "unresolved")} == {
        "repaired": 2, "canonical": 4, "ambiguous": 1, "unresolved": 2}
    assert pack["selection_predicate"] == "evidence.review_state != 'rejected'"
    assert len(pack["db_hash"]) == 64 and pack["db_hash"] != pack["db_hash_after"]
    assert Path(pack["rollback"]["backup"]).is_file() and len(pack["rollback"]["previous"]) == 7
    assert restore_provenance(v2, result["report"]) == {"status": "OK", "restored": 7}
    assert _evidence(v2) == before
    assert v2_access.evidence_provenance(v2 / "csa.sqlite") == {}


def test_repeated_repair_is_stable_and_follows_the_index(tmp_path):
    v2 = _store(tmp_path)
    first = repair_provenance(v2, dry_run=False)
    second = repair_provenance(v2, dry_run=False)
    assert second["repaired"] == 0
    assert [second[k] for k in ("canonical", "ambiguous", "unresolved")] == [first[k] for k in ("canonical", "ambiguous", "unresolved")]
    r = Repo(v2)
    with r.tx() as c:                                       # the second listening-ports capture leaves the index
        c.execute("DELETE FROM indexed_file WHERE rel_path=?", (f"{CAPTURE_B}/20_listening_ports.txt",))
    r.close()
    third = repair_provenance(v2, dry_run=False)
    assert third["ambiguous"] == 0 and third["canonical"] == 5
    provenance = v2_access.evidence_provenance(v2 / "csa.sqlite")["E-004"]
    assert provenance["paths"] == [f"{CAPTURE_A}/20_listening_ports.txt"]
    assert provenance["original_source"] == "20_listening_ports.txt"


def test_source_provenance_resolves_unchecked_rows_with_the_same_rules(tmp_path):
    v2 = _store(tmp_path)
    db = v2 / "csa.sqlite"
    live = v2_access.source_provenance(db, "E-004", "20_listening_ports.txt")
    assert live["recorded"] is False and live["state"] == "ambiguous" and live["paths"] == []
    repair_provenance(v2, dry_run=False)
    recorded = v2_access.source_provenance(db, "E-001", "docs/Asset Inventory.xlsx")
    assert recorded["recorded"] is True and recorded["paths"] == ["docs/Asset Inventory.xlsx"]
