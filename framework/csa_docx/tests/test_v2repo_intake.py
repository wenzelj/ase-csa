"""S585: the v2repo `intake` / `leads` / `gap_checks` surface.

`r.intake` — one `intake_record` per run, one `intake_file` per file; the record
finishes when its last pending file is completed (processed or failed).
`r.leads` — the open-question state machine (open -> resolved | not_an_answer |
retired); a lead leaves `open` exactly once.
`r.gap_checks` — one row per sweep, with the lead IDs it found.

Every mutation runs inside `with r.tx():` and appends a `review_event` row.
"""
import re

import pytest

from csa_docx.v2repo import Repo
import csa_docx.v2repo.intake  # noqa: F401  # registers r.intake / r.leads / r.gap_checks


def _repo(tmp_path):
    return Repo(tmp_path / "csa.sqlite")


def _events(r):
    return r.con.execute(
        "SELECT actor, action, subject_type, subject_id FROM review_event ORDER BY id").fetchall()


# --------------------------------------------------------------------------- intake.start

def test_start_with_three_files_creates_one_record_and_three_pending_files(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([
            {"rel_path": "a.txt"},
            {"rel_path": "b.txt"},
            {"rel_path": "c.txt"},
        ])
    rec = r.con.execute("SELECT * FROM intake_record WHERE id=?", (rid,)).fetchone()
    assert rec is not None
    assert rec[0] == rid
    assert rec[1] is not None                      # started_at
    assert rec[2] is None                          # finished_at
    assert rec[3] == 3                             # file_count
    assert rec[4] == 0                             # row_count
    files = r.con.execute(
        "SELECT record_id, rel_path, status, rows_added, error FROM intake_file ORDER BY rel_path"
    ).fetchall()
    assert [f[1] for f in files] == ["a.txt", "b.txt", "c.txt"]
    assert all(f[0] == rid and f[2] == "pending" and f[3] == 0 and f[4] is None for f in files)
    r.close()


def test_start_outside_tx_raises(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="transaction"):
        r.intake.start([{"rel_path": "a.txt"}])
    r.close()


def test_start_requires_files_and_unique_rel_paths(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(ValueError, match="files"):
        with r.tx():
            r.intake.start([])
    with pytest.raises(ValueError, match="rel_path"):
        with r.tx():
            r.intake.start([{"sha256": "x"}])
    with pytest.raises(ValueError, match="duplicate"):
        with r.tx():
            r.intake.start([{"rel_path": "a.txt"}, {"rel_path": "a.txt"}])
    r.close()


def test_start_twice_in_one_second_gets_distinct_ids(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        a = r.intake.start([{"rel_path": "a.txt"}])
        b = r.intake.start([{"rel_path": "b.txt"}])
    assert a != b and a.startswith("I-") and b.startswith("I-")
    r.close()


# ------------------------------------------------------------------- complete_file

def test_completing_every_file_finishes_the_record_with_row_count(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([{"rel_path": "a.txt"}, {"rel_path": "b.txt"}, {"rel_path": "c.txt"}])
    with r.tx():
        r.intake.complete_file(rid, "a.txt", rows_added=2)
    rec = r.con.execute("SELECT finished_at, row_count FROM intake_record WHERE id=?", (rid,)).fetchone()
    assert rec == (None, 0)                        # not finished while one file is pending
    with r.tx():
        r.intake.complete_file(rid, "b.txt", rows_added=3)
    rec = r.con.execute("SELECT finished_at, row_count FROM intake_record WHERE id=?", (rid,)).fetchone()
    assert rec[0] is None and rec[1] == 0
    with r.tx():
        r.intake.complete_file(rid, "c.txt", rows_added=4)
    rec = r.intake.latest()
    assert rec["finished_at"] is not None
    assert rec["row_count"] == 2 + 3 + 4
    assert r.intake.pending() == []
    assert r.intake.pending(rid) == []
    r.close()


def test_complete_file_for_unknown_record_or_file_raises(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([{"rel_path": "a.txt"}])
    with pytest.raises(KeyError):
        with r.tx():
            r.intake.complete_file("I-999999-999999.1", "a.txt")
    with pytest.raises(KeyError):
        with r.tx():
            r.intake.complete_file(rid, "missing.txt")
    r.close()


# ----------------------------------------------------------------------- failures

def test_failed_file_still_finishes_the_record_and_is_marked_failed(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([{"rel_path": "a.txt"}, {"rel_path": "b.txt"}])
    with r.tx():
        r.intake.complete_file(rid, "a.txt", rows_added=1, error="checksum mismatch")
    with r.tx():
        r.intake.complete_file(rid, "b.txt", rows_added=2)
    rec = r.intake.latest()
    assert rec["finished_at"] is not None          # the failed file counts as completed
    assert rec["row_count"] == 3
    row = r.con.execute(
        "SELECT status, rows_added, error FROM intake_file WHERE record_id=? AND rel_path=?",
        (rid, "a.txt")).fetchone()
    assert row == ("failed", 1, "checksum mismatch")
    assert r.intake.pending() == []
    r.close()


def test_a_record_with_only_failed_files_is_finished_but_has_no_rows(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([{"rel_path": "a.txt"}])
    with r.tx():
        r.intake.complete_file(rid, "a.txt", error="unreadable")
    rec = r.intake.latest()
    assert rec["finished_at"] is not None
    assert rec["row_count"] == 0
    r.close()


# ------------------------------------------------------------------ pending / latest

def test_pending_without_a_record_lists_all_pending_files(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid1 = r.intake.start([{"rel_path": "a.txt"}, {"rel_path": "b.txt"}])
    with r.tx():
        rid2 = r.intake.start([{"rel_path": "c.txt"}])
    pending = r.intake.pending()
    assert {(f["record_id"], f["rel_path"]) for f in pending} == {
        (rid1, "a.txt"), (rid1, "b.txt"), (rid2, "c.txt")}
    assert [f["rel_path"] for f in r.intake.pending(rid2)] == ["c.txt"]
    assert r.intake.pending("I-999999-999999.1") == []
    r.close()


def test_latest_returns_the_most_recent_record_and_records_orders_newest_first(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.intake.start([{"rel_path": "a.txt"}])
    with r.tx():
        r.intake.start([{"rel_path": "b.txt"}])
    first = r.intake.records()[1]["id"]
    second = r.intake.records()[0]["id"]
    assert r.intake.latest()["id"] == second
    assert [x["id"] for x in r.intake.records()] == [second, first]
    r.close()


def test_latest_is_none_on_an_empty_repo(tmp_path):
    r = _repo(tmp_path)
    assert r.intake.latest() is None
    assert r.intake.records() == []
    r.close()


# ---------------------------------------------------------------------- leads

def test_lead_create_then_resolve_then_get(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("What resolver do the OT hosts use?", "all 12 captured hosts")
    assert re.fullmatch(r"L-\d{6,}", lid)
    row = r.leads.get(lid)
    assert row["state"] == "open"
    assert row["question"] == "What resolver do the OT hosts use?"
    assert row["searched_scope"] == "all 12 captured hosts"
    assert row["evidence_ids"] is None
    with r.tx():
        r.leads.resolve(lid, ["E-001", "E-002"], by="wenzel", note="settled")
    row = r.leads.get(lid)
    assert row["state"] == "resolved"
    assert row["evidence_ids"] == "E-001;E-002"
    r.close()


def test_second_resolve_is_an_error_not_a_silent_noop(tmp_path):
    """Documented behaviour: a lead leaves `open` exactly once — `resolve` on an
    already-resolved lead raises `ValueError` instead of overwriting it."""
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("question?", "scope")
    with r.tx():
        r.leads.resolve(lid, ["E-001"])
    with pytest.raises(ValueError, match="already"):
        with r.tx():
            r.leads.resolve(lid, ["E-002"])
    assert r.leads.get(lid)["evidence_ids"] == "E-001"
    r.close()


def test_mark_not_an_answer_appends_a_review_event(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("question?", "scope", actor="wenzel")
    with r.tx():
        r.leads.mark_not_an_answer(lid, by="wenzel", note="answer was a guess")
    assert r.leads.get(lid)["state"] == "not_an_answer"
    assert ("wenzel", "leads.mark_not_an_answer", "lead", lid) in _events(r)
    r.close()


def test_retire_requires_a_reason_and_appends_a_review_event(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("question?", "scope", actor="wenzel")
    with pytest.raises(ValueError, match="reason"):
        with r.tx():
            r.leads.retire(lid, "  ")
    with r.tx():
        r.leads.retire(lid, "superseded by DR-AREA-09", by="wenzel")
    assert r.leads.get(lid)["state"] == "retired"
    assert ("wenzel", "leads.retire", "lead", lid) in _events(r)
    r.close()


def test_lead_states_are_mutually_exclusive(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("question?", "scope")
    with r.tx():
        r.leads.retire(lid, "closed early")
    with pytest.raises(ValueError, match="already"):
        with r.tx():
            r.leads.resolve(lid, ["E-001"])
    r.close()


def test_leads_list_filters_by_state(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        open1 = r.leads.create("one?", "scope")
        open2 = r.leads.create("two?", "scope")
        done = r.leads.create("three?", "scope")
    with r.tx():
        r.leads.resolve(done, ["E-001"])
    assert {x["id"] for x in r.leads.list()} == {open1, open2, done}
    assert {x["id"] for x in r.leads.list(state="open")} == {open1, open2}
    assert [x["id"] for x in r.leads.list(state="resolved")] == [done]
    with pytest.raises(ValueError, match="unknown state"):
        r.leads.list(state="bogus")
    r.close()


def test_leads_create_requires_question_and_scope(tmp_path):
    r = _repo(tmp_path)
    with pytest.raises(ValueError, match="question"):
        with r.tx():
            r.leads.create("   ", "scope")
    with pytest.raises(ValueError, match="searched_scope"):
        with r.tx():
            r.leads.create("question?", "")
    r.close()


# ------------------------------------------------------------------ gap_checks

def test_gap_check_run_stores_leads_found_and_latest_returns_the_most_recent(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        lid = r.leads.create("question?", "scope")
    with r.tx():
        g1 = r.gap_checks.run("DR-AREA-01", "sweep of section 3.1", [lid])
    with r.tx():
        g2 = r.gap_checks.run("DR-AREA-02", "sweep of section 3.2", [])
    latest = r.gap_checks.latest()
    assert latest["id"] == g2
    assert latest["dr_id"] == "DR-AREA-02"
    assert latest["leads_found"] == 0
    first = [g for g in r.gap_checks.list() if g["id"] == g1][0]
    assert first["leads_found"] == 1
    # the lead IDs are kept on the audit row for the sweep that found them
    ev = r.con.execute(
        "SELECT note FROM review_event WHERE action='gap_checks.run' AND subject_id=?", (g1,)).fetchone()
    assert lid in ev[0]
    r.close()


def test_gap_check_latest_is_none_on_an_empty_repo(tmp_path):
    r = _repo(tmp_path)
    assert r.gap_checks.latest() is None
    assert r.gap_checks.list() == []
    r.close()


def test_gap_check_list_filters_by_dr_id(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        r.gap_checks.run("DR-A-01", "one", [])
        r.gap_checks.run("DR-A-02", "two", [])
    assert {g["dr_id"] for g in r.gap_checks.list()} == {"DR-A-01", "DR-A-02"}
    assert [g["dr_id"] for g in r.gap_checks.list(dr_id="DR-A-02")] == ["DR-A-02"]
    assert r.gap_checks.list(dr_id="DR-Z-99") == []
    r.close()


# ------------------------------------------------------- review_event / atomicity

def test_every_state_change_appends_a_review_event(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        rid = r.intake.start([{"rel_path": "a.txt"}], actor="wenzel", note="first run")
    with r.tx():
        r.intake.complete_file(rid, "a.txt", rows_added=1, actor="wenzel")
    with r.tx():
        lid = r.leads.create("question?", "scope", actor="wenzel")
    with r.tx():
        r.leads.mark_not_an_answer(lid, by="wenzel")
    assert [e[1] for e in _events(r)] == [
        "intake.start",
        "intake.complete_file:processed",
        "leads.create",
        "leads.mark_not_an_answer",
    ]
    r.close()


def test_failed_tx_after_start_but_before_complete_file_leaves_no_partial_record(tmp_path):
    r = _repo(tmp_path)
    with r.tx():
        done = r.intake.start([{"rel_path": "a.txt"}])          # committed baseline
    with pytest.raises(RuntimeError, match="boom"):
        with r.tx():
            rid = r.intake.start([{"rel_path": "b.txt"}, {"rel_path": "c.txt"}])
            r.intake.complete_file(rid, "b.txt", rows_added=1)
            raise RuntimeError("boom")
    # the failed run's record and files are gone; the baseline is untouched
    assert r.con.execute("SELECT COUNT(*) FROM intake_record").fetchone()[0] == 1
    assert r.con.execute("SELECT COUNT(*) FROM intake_file").fetchone()[0] == 1
    assert r.intake.latest()["id"] == done
    assert r.intake.pending() == [f for f in r.intake.pending(done)]
    r.close()
