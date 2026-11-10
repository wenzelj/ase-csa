"""Gap check: every open question in draft/open-questions.md is looked up in the matrix and the index."""
import csv
import json

from csa_docx import gap_lookup as gl
from csa_docx import gap_sweep as gs
from csa_docx import leads

OPEN = """# Open questions (draft lane, 2026-10-10 20:56)

## 3.11 Backup & Recovery (BAK)

- [B1] the exact backup product and service could be confirmed by the backup owner.
- [B1] where the backup target volume for ROKPRDOPS116 lives

## 3.17 Internet Access & Communications (Proxy / SMTP) (INET)

- [B2] which hosts actually send SMTP alerts.

## 2.1 Executive Summary (EXECUTIVE_SUMMARY)

- [B1] whether ROKPRDOPS112 is in scope.

## Figure for 2.1 Executive Summary

- [DR-EXECUTIVE_SUMMARY-F01] MOTPRDLOG103: role not recorded

## Figure for 3.4 Time Synchronisation

- [DR-TIME-F01] ROTPRDREV101: time source not known
"""


def test_parse_open_questions():
    qs = gs.parse_open_questions(OPEN)
    got = [(q["number"], q["key"], q["qid"], q["dr_id"]) for q in qs]
    assert got == [("3.11", "BAK", "B1", gs._generated_dr_id("DR-BAK-B1", "the exact backup product and service could be confirmed by the backup owner.")),
                   ("3.11", "BAK", "B1", gs._generated_dr_id("DR-BAK-B1", "where the backup target volume for ROKPRDOPS116 lives")),
                   ("3.17", "INET", "B2", gs._generated_dr_id("DR-INET-B2", "which hosts actually send SMTP alerts.")),
                   ("2.1", "EXECUTIVE_SUMMARY", "B1", gs._generated_dr_id("DR-EXECUTIVE_SUMMARY-B1", "whether ROKPRDOPS112 is in scope.")),
                   ("2.1", "EXECUTIVE_SUMMARY", "F01", "DR-EXECUTIVE_SUMMARY-F01"),
                   ("3.4", "FIGURE-3.4", "F01", "DR-TIME-F01")]
    # qid stays the bare block token (the answer sheet and answered_blocks match B1, B2 ...)
    assert [q["qid"] for q in qs] == ["B1", "B1", "B2", "B1", "F01", "F01"]
    assert [q["dr_id"] for q in gs.parse_open_questions(OPEN)] != [q["dr_id"] for q in qs][:0]
    assert qs[1]["title"] == "Backup & Recovery"
    assert qs[4]["text"] == "MOTPRDLOG103: role not recorded"


def test_parse_dedupes_explicit_dr_brackets():
    text = ("## 3.11 Backup & Recovery (BAK)\n\n"
            "- [DR-BAK-B1] first question\n- [DR-BAK-B1] second question\n")
    ids = [q["dr_id"] for q in gs.parse_open_questions(text)]
    assert ids == ["DR-BAK-B1", gs._generated_dr_id("DR-BAK-B1", "second question")]


def test_generated_question_ids_survive_reordering_and_change_when_words_change():
    heading = "## 3.11 Backup & Recovery (BAK)\n\n"
    first = gs.parse_open_questions(heading + "- [B1] first question\n- [B1] second question\n")
    reordered = gs.parse_open_questions(heading + "- [B1] second question\n- [B1] first question\n")
    assert {q["text"]: q["dr_id"] for q in first} == {q["text"]: q["dr_id"] for q in reordered}
    changed = gs.parse_open_questions(heading + "- [B1] first question changed\n")[0]
    assert changed["dr_id"] != first[0]["dr_id"]


def test_role_table_lines_parse_with_own_ids():
    text = ("## 3.4 Time Synchronisation (TIME)\n\n"
            "- [B1] first\n\n"
            "## Role table for Time Synchronisation\n\n"
            "- [DR-TIME-T01] capture host A\n- [DR-TIME-T02] capture host B\n")
    qs = gs.parse_open_questions(text)
    assert [(q["key"], q["qid"], q["dr_id"]) for q in qs] == [
        ("TIME", "B1", gs._generated_dr_id("DR-TIME-B1", "first")),
        ("ROLETABLE-3.4", "T01", "DR-TIME-T01"),
        ("ROLETABLE-3.4", "T02", "DR-TIME-T02")]
    assert gs._safe_for_retirement(text, qs) is True


def test_parse_skips_malformed():
    text = "## Notes without a number\n\n- [B1] orphan line\n\n## 3.5 DNS (DNS)\n\n- no id here\n- [B3] fallback\n"
    qs = gs.parse_open_questions(text)
    assert [(q["key"], q["qid"]) for q in qs] == [("DNS", "B3")]
    assert gs.parse_open_questions("") == []


def _workspace(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "csa-work" / "draft").mkdir(parents=True)
    (ws / "csa-work" / "draft" / "open-questions.md").write_text(OPEN, encoding="utf-8")
    return ws


def test_sweep_writes_affected_sections(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)

    def lookup(workspace, dr_id, text, exclude=()):
        if text.startswith("the exact backup product"):
            return {"verdict": "CANDIDATES", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": ["L-000510"], "searched": "x"}
        if dr_id == "DR-EXECUTIVE_SUMMARY-F01":
            return {"verdict": "ANSWERED", "answer_evidence_ids": ["E-495"], "related_evidence_ids": [], "lead_ids": [], "searched": "x"}
        return {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": [], "searched": "x"}
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lookup)
    res = gs.sweep(ws)
    assert res["affected"] == [
        {"number": "3.11", "key": "BAK", "title": "Backup & Recovery", "answered": 0, "candidates": 1},
        {"number": "2.1", "key": "EXECUTIVE_SUMMARY", "title": "Executive Summary", "answered": 1, "candidates": 0}]
    saved = json.loads((ws / "csa-work" / "intake" / "gap-check-latest.json").read_text(encoding="utf-8"))
    assert saved == res and saved["schema_version"] == 4 and len(saved["questions"]) == 6 and saved["checked_at"]
    candidate = next(q for q in saved["questions"] if q["text"].startswith("the exact backup product"))
    assert candidate["lead_ids"] == ["L-000510"] and candidate["evidence_ids"] == []
    assert next(q for q in saved["questions"] if q["key"] == "INET")["verdict"] == "NOT_FOUND"
    only = gs.sweep(ws, section_key="BAK")
    assert [q["dr_id"] for q in only["questions"]] == [q["dr_id"] for q in gs.parse_open_questions(OPEN)[:2]]


HIT = {"rel_path": "src/IS-REVELOC.pdf", "page_or_location": "line 40", "source_title": "src/IS-REVELOC.pdf",
       "source_version": "", "evidence_excerpt": "MOTPRDLOG103 OT Tetra Log Server WIN2019 (Virtual)"}


def _stateful_run(appended):
    def run(cmd):
        if "lookup" in cmd:
            return {"status": "OK", "matches": []}
        if "search" in cmd:
            return {"status": "OK", "results": [HIT]}
        if "append" in cmd:
            appended.append(cmd)
        return None
    return run


def test_sweep_is_idempotent(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    appended: list = []
    monkeypatch.setattr(gl, "_run", _stateful_run(appended))
    first = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    second = gs.sweep(ws, section_key="EXECUTIVE_SUMMARY")
    f01 = lambda r: next(q for q in r["questions"] if q["dr_id"] == "DR-EXECUTIVE_SUMMARY-F01")
    assert f01(first)["lead_ids"] == f01(second)["lead_ids"] == ["L-000001"]
    assert not appended
    assert len((ws / "csa-work" / "intake" / "leads.jsonl").read_text().splitlines()) == 1


def test_sweep_skips_terminal_leads(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setattr(gl, "_run", _stateful_run([]))
    assert {q["dr_id"]: q["verdict"] for q in gs.sweep(ws, "EXECUTIVE_SUMMARY")["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "CANDIDATES"
    lead_id = leads.open_leads(ws, "DR-EXECUTIVE_SUMMARY-F01")[0]["lead_id"]
    leads.review(ws, [lead_id], "not_an_answer", "tester", "read")
    again = gs.sweep(ws, "EXECUTIVE_SUMMARY")
    assert {q["dr_id"]: q["verdict"] for q in again["questions"]}["DR-EXECUTIVE_SUMMARY-F01"] == "NOT_FOUND"
    assert again["affected"] == []


def test_sweep_carries_open_lead_by_exact_dr_id(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    dr_id = gs.parse_open_questions(OPEN)[0]["dr_id"]
    lead_id = leads.add_leads(ws, dr_id, "B1", "the exact backup product", [HIT])[0]
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda *args, **kwargs:
                        {"verdict": "CANDIDATES", "answer_evidence_ids": [], "related_evidence_ids": [],
                         "lead_ids": [lead_id], "searched": "x"})
    result = gs.sweep(ws, "BAK")
    assert result["questions"][0]["verdict"] == "CANDIDATES"
    assert result["questions"][0]["lead_ids"] == [lead_id]
    assert result["questions"][0]["evidence_ids"] == []
    assert result["affected"][0] == {"number": "3.11", "key": "BAK", "title": "Backup & Recovery",
                                  "answered": 0, "candidates": 2}


def test_successful_scoped_sweep_retires_only_absent_questions_in_that_section(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    old_bak = leads.add_leads(ws, "DR-BAK-B9", "B9", "old backup question", [HIT])[0]
    other = leads.add_leads(ws, "DR-INET-B9", "B9", "old internet question", [dict(HIT, page_or_location="line 50")])[0]
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda *args, **kwargs:
                        {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [],
                         "lead_ids": [], "searched": "x"})
    result = gs.sweep(ws, "BAK")
    assert result["retired_lead_ids"] == [old_bak]
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [other]


def test_missing_or_malformed_question_input_never_retires_leads(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-BAK-B9", "B9", "old backup question", [HIT])[0]
    source = ws / "csa-work" / "draft" / "open-questions.md"
    source.write_text("## malformed\n\n- [B1] orphan\n", encoding="utf-8")
    assert gs.sweep(ws)["retired_lead_ids"] == []
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [lead_id]
    source.unlink()
    assert gs.sweep(ws)["retired_lead_ids"] == []
    assert [r["lead_id"] for r in leads.open_leads(ws)] == [lead_id]


def test_duplicate_block_lines_get_unique_ids_and_are_searched_separately(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    first_id = gs._generated_dr_id("DR-BAK-B1", "first question")
    second_id = gs._generated_dr_id("DR-BAK-B1", "second question")
    lead_id = leads.add_leads(ws, first_id, "B1", "first question", [HIT])[0]
    source = ws / "csa-work" / "draft" / "open-questions.md"
    source.write_text("## 3.11 Backup & Recovery (BAK)\n\n- [B1] first question\n- [B1] second question\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda workspace, dr_id, text, exclude=():
                        (seen.append((dr_id, text)), {"verdict": "NOT_FOUND", "answer_evidence_ids": [],
                         "related_evidence_ids": [], "lead_ids": [], "searched": "x"})[1])
    result = gs.sweep(ws, "BAK")
    assert [q["dr_id"] for q in result["questions"]] == [first_id, second_id]
    assert [q["verdict"] for q in result["questions"]] == ["NOT_FOUND", "NOT_FOUND"]
    assert seen == [(first_id, "first question"), (second_id, "second question")]
    # "first question" now closes NOT_FOUND in this run, so its lead is drained; it stays open for a still-open question
    assert result["retired_lead_ids"] == [] and result["drained_lead_ids"] == [lead_id]
    assert [r["lead_id"] for r in leads.open_leads(ws)] == []


def test_csa_has_gap_check_and_resolve_commands():
    import subprocess
    import sys
    from pathlib import Path
    csa = Path(__file__).resolve().parents[3] / "bin" / "csa"
    r = subprocess.run([sys.executable, str(csa), "gap-check", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "open question" in r.stdout
    r = subprocess.run([sys.executable, str(csa), "resolve-gaps", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "resolve-gaps" in r.stdout and "section" in r.stdout


def test_the_run_report_counts_what_the_lookup_did():
    results = [
        {"verdict": "NOT_FOUND", "lead_ids": [], "kind": "document", "owners": ["backup service owner"], "related": [], "searches": 12},
        {"verdict": "NOT_FOUND", "lead_ids": [], "kind": "document", "owners": ["backup service owner", "application owner"], "related": ["E-1"], "searches": 12},
        {"verdict": "CANDIDATES", "lead_ids": ["L-000009", "L-000010"], "kind": "system", "owners": [], "related": [], "searches": 4},
    ]
    s = gs.summarise(results)
    assert s["gaps"] == 3 and s["by_kind"] == {"document": 2, "system": 1} and s["searches"] == 28
    assert s["candidates_to_read"] == 2 and s["gaps_with_related_rows"] == 1
    assert s["to_ask"] == {"backup service owner": 2, "application owner": 1}
    text = " ".join(gs.report_lines(s))
    assert "3 open question(s)" in text and "28 search(es)" in text and "backup service owner (2)" in text


def test_sweep_drains_open_leads_of_questions_it_closes(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    source = ws / "csa-work" / "draft" / "open-questions.md"
    source.write_text("## 3.11 Backup & Recovery (BAK)\n\n"
                      "- [DR-BAK-N1] which backup product serves the site\n"
                      "- [DR-BAK-A1] which host runs the agent\n"
                      "- [DR-BAK-C1] where the target volume lives\n", encoding="utf-8")
    not_found = "DR-BAK-N1"
    answered = "DR-BAK-A1"
    candidates = "DR-BAK-C1"
    nf_lead = leads.add_leads(ws, not_found, "N1", "which backup product serves the site", [HIT])[0]
    a_lead = leads.add_leads(ws, answered, "A1", "which host runs the agent", [dict(HIT, page_or_location="line 41")])[0]
    c_lead = leads.add_leads(ws, candidates, "C1", "where the target volume lives", [dict(HIT, page_or_location="line 42")])[0]
    # VERIFIED row that explicitly answers the second question
    matrix = ws / "csa-work" / "evidence-matrix.csv"
    with matrix.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["evidence_id", "status", "gap_or_action"])
        w.writerow(["E-001", "VERIFIED", f"Answers {answered}"])
    (ws / "csa-work" / "evidence-reviews.jsonl").write_text('{"evidence_id": "E-001", "state": "reviewed"}\n', encoding="utf-8")
    res = gl.resolve_gap(ws, answered, "which host runs the agent", ["E-001"], by="tester")
    assert res["status"] == "OK"
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda workspace, dr_id, text, exclude=():
                        {"verdict": "ANSWERED" if dr_id == answered else "CANDIDATES" if dr_id == candidates else "NOT_FOUND",
                         "answer_evidence_ids": ["E-001"] if dr_id == answered else [],
                         "related_evidence_ids": [], "lead_ids": [c_lead] if dr_id == candidates else [],
                         "searched": "evidence matrix; discovery index (documents only, since it is about a policy; 3 searches: a; b; c)"})
    result = gs.sweep(ws, "BAK")
    by_state = {r["lead_id"]: r["state"] for r in leads._overlay(*leads._records(ws)[:2])}
    assert by_state == {nf_lead: "not_an_answer", a_lead: "retired", c_lead: "open"}
    assert sorted(result["drained_lead_ids"]) == sorted([nf_lead, a_lead])
    assert result["retired_lead_ids"] == []
    cand = next(q for q in result["questions"] if q["dr_id"] == candidates)
    assert cand["verdict"] == "CANDIDATES" and cand["lead_ids"] == [c_lead]
    # append-only: the lead file was never rewritten, only reviews were appended
    assert len((ws / "csa-work" / "intake" / "leads.jsonl").read_text().splitlines()) == 3
    reviews = (ws / "csa-work" / "intake" / "leads-reviews.jsonl").read_text().splitlines()
    assert len(reviews) == 2
    # the swept question left no evidence-matrix rows behind (append-only confirm path untouched)
    with matrix.open(encoding="utf-8") as fh:
        assert [r for r in csv.reader(fh)] == [["evidence_id", "status", "gap_or_action"], ["E-001", "VERIFIED", "Answers DR-BAK-A1"]]


def _q(verdict, *, ask=False, owners=(), leads=(), key="PATCH", number="3.10", title="Patch & Lifecycle Management", qid="B1", text="a question"):
    return {"verdict": verdict, "ask": ask, "owners": list(owners), "lead_ids": list(leads), "kind": "document" if ask else "system",
            "related": [], "searches": 1, "key": key, "number": number, "title": title, "qid": qid, "text": text}


def test_to_ask_counts_every_open_question_a_person_must_answer_under_its_owner_or_to_be_assigned():
    results = [_q("NOT_FOUND", ask=True), _q("CANDIDATES", ask=True, leads=["L-1"]), _q("ANSWERED", ask=True),
               _q("NOT_FOUND", ask=True, owners=["backup service owner", "application owner"]),
               _q("NOT_FOUND"),                                           # a system fact nobody has to be asked
               _q("NOT_FOUND", owners=["network owner"])]                 # names an owner, so it is still asked as before
    assert gs.summarise(results)["to_ask"] == {"to be assigned": 2, "backup service owner": 1, "application owner": 1, "network owner": 1}


def test_to_ask_file_groups_by_owner_and_section_and_marks_possible_answers(tmp_path):
    path = tmp_path / "to-ask-latest.md"
    gs.write_to_ask(path, [
        _q("NOT_FOUND", ask=True, text="Who is the authority contact for urgent patches?", qid="B2"),
        _q("CANDIDATES", ask=True, leads=["L-1", "L-2"], text="Is the cycle written down in a procedure?", qid="B2"),
        _q("ANSWERED", ask=True, text="answered already"),
        _q("NOT_FOUND", text="a system fact"),
        _q("NOT_FOUND", ask=True, owners=["backup service owner"], key="BAK", number="3.11", title="Backup & Recovery",
           text="Who owns the restore test?")], "2026-11-10T00:00:00Z")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Questions for people (2026-11-10T00:00:00Z)")
    assert "## backup service owner" in text and "## to be assigned" in text
    assert text.index("## backup service owner") < text.index("## to be assigned")
    assert "### 3.10 Patch & Lifecycle Management" in text and "### 3.11 Backup & Recovery" in text
    assert "- [B2] Is the cycle written down in a procedure? (leads to read: 2)" in text
    assert "answered already" not in text and "a system fact" not in text


def test_sweep_records_ask_and_writes_the_to_ask_file(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)

    def lookup(workspace, dr_id, text, exclude=()):
        return {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": [], "searched": "x",
                "ask": text.startswith("the exact backup product"), "owners": []}
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lookup)
    res = gs.sweep(ws)
    flagged = [q["text"] for q in res["questions"] if q["ask"]]
    assert flagged == ["the exact backup product and service could be confirmed by the backup owner."]
    assert res["summary"]["to_ask"] == {"to be assigned": 1}
    listed = (ws / "csa-work" / "intake" / "to-ask-latest.md").read_text(encoding="utf-8")
    assert "the exact backup product" in listed and "which hosts actually send SMTP alerts" not in listed


def _card(work, key, blocks):
    (work / "cards").mkdir(parents=True, exist_ok=True)
    (work / "cards" / f"{key}.json").write_text(json.dumps({"evidence": {
        qid: {"rows": [{"id": i} for i in ids]} for qid, ids in blocks.items()}}), encoding="utf-8")


def test_card_listed_reads_the_rows_the_card_showed_for_one_block(tmp_path):
    work = tmp_path / "csa-work"
    _card(work, "PATCH", {"B1": ["E-3289", "e-3290"], "B2": []})
    cache = {}
    assert gs.card_listed(work, "PATCH", "B1", cache) == {"E-3289", "E-3290"}      # ids are compared in upper case
    assert gs.card_listed(work, "PATCH", "B2", cache) == set()                     # a block that listed nothing
    assert gs.card_listed(work, "PATCH", "B9", cache) is None                      # no such block
    assert gs.card_listed(work, "NOCARD", "B1", cache) is None                     # no card file
    assert "PATCH" in cache and "NOCARD" in cache                                  # each card is read once


def test_card_listed_tolerates_a_malformed_card(tmp_path):
    work = tmp_path / "csa-work"
    (work / "cards").mkdir(parents=True)
    (work / "cards" / "BAK.json").write_text("{not json", encoding="utf-8")
    assert gs.card_listed(work, "BAK", "B1", {}) is None


def test_sweep_records_the_related_rows_the_card_never_listed_and_changes_nothing_else(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    _card(ws / "csa-work", "BAK", {"B1": ["E-10", "E-11"]})

    def lookup(workspace, dr_id, text, exclude=()):
        return {"verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": ["E-10", "E-12", "E-13"],
                "lead_ids": [], "searched": "x"}
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lookup)
    res = gs.sweep(ws)
    bak_b1 = [q for q in res["questions"] if q["key"] == "BAK" and q["qid"] == "B1"]
    assert bak_b1 and all(q["card_block"] and q["unseen_related"] == ["E-12", "E-13"] for q in bak_b1)
    assert all(q["related_evidence_ids"] == ["E-10", "E-12", "E-13"] and q["verdict"] == "NOT_FOUND" for q in res["questions"])
    other = next(q for q in res["questions"] if q["key"] == "INET")                    # no card for this section
    assert other["card_block"] is False and other["unseen_related"] == []
    s = res["summary"]
    assert s["card_blocks"] == len(bak_b1) and s["gaps_with_unseen_related"] == len(bak_b1)
    assert f"{len(bak_b1)} of {len(bak_b1)} question(s) with a card block have related rows the card never listed" in " ".join(gs.report_lines(s))


def test_the_summary_leaves_out_the_card_line_when_no_question_has_a_card_block():
    s = gs.summarise([{"verdict": "NOT_FOUND", "lead_ids": [], "kind": "system", "owners": [], "related": [], "searches": 1}])
    assert s["card_blocks"] == 0 and s["gaps_with_unseen_related"] == 0
    assert "card" not in " ".join(gs.report_lines(s))
