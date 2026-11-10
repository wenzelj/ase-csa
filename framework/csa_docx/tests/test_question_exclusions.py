"""Questions the owner removed from the open list: left out of open-questions.md, gap-check and Discovery Required."""
import json

import pytest

from csa_docx import discovery_required as dr
from csa_docx import draft_lane, gap_sweep as gs, question_exclusions as qx

KEEP = "Is there a documented patch cycle for the OT TETRA/Reveloc hosts, and who owns it?"
DROP = "How is an urgent patch escalated outside the six-monthly cycle?"


def _work(tmp_path):
    work = tmp_path / "workspace" / "csa-work"          # the test workspace the conftest registers
    (work / "cards").mkdir(parents=True)
    (work / "draft").mkdir()
    (work / "cards" / "PATCH.answer.md").write_text(
        "## B1 SEP-PATCH-01\nFacts:\n- a fact. (E-1)\n" f"QUESTION: {KEEP}\nQUESTION: {DROP}\nSummary: s\nStory: t\n", encoding="utf-8")
    (work / "cards" / "PATCH.json").write_text(
        json.dumps({"key": "PATCH", "number": "3.10", "title": "Patch & Lifecycle Management"}), encoding="utf-8")
    return work


def _remove(work, *dr_ids):
    (work / "draft" / "question-exclusions.json").write_text(json.dumps(
        {"excluded": [{"dr_id": d, "text": "x", "category": "Duplicate", "reason": "r", "duplicate_of": None} for d in dr_ids]}),
        encoding="utf-8")


def _ids(work):
    draft_lane.open_questions(work)
    return {q["text"]: q["dr_id"] for q in gs.parse_open_questions((work / "draft" / "open-questions.md").read_text(encoding="utf-8"))}


def test_a_missing_list_removes_nothing_and_a_malformed_one_is_an_error(tmp_path):
    work = _work(tmp_path)
    assert qx.load(work) == {}
    (work / "draft" / "question-exclusions.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed question exclusions"):
        qx.load(work)


def test_load_reads_entries_by_dr_id_and_skips_rows_without_one(tmp_path):
    work = _work(tmp_path)
    (work / "draft" / "question-exclusions.json").write_text(json.dumps(
        {"excluded": [{"dr_id": "DR-A-B1-Q1", "reason": "dup"}, {"reason": "no id"}, "junk"]}), encoding="utf-8")
    assert list(qx.load(work)) == ["DR-A-B1-Q1"] and qx.load(work)["DR-A-B1-Q1"]["reason"] == "dup"


def test_a_removed_card_question_is_left_out_of_the_open_questions_file_and_the_others_stay(tmp_path):
    work = _work(tmp_path)
    before = _ids(work)
    assert set(before) == {KEEP, DROP}
    _remove(work, before[DROP])
    after = _ids(work)
    assert set(after) == {KEEP} and after[KEEP] == before[KEEP]            # the kept question keeps its id
    assert draft_lane.open_questions(work)["open"] == 1


def test_a_section_with_every_question_removed_loses_its_heading(tmp_path):
    work = _work(tmp_path)
    ids = _ids(work)
    _remove(work, *ids.values())
    draft_lane.open_questions(work)
    assert "3.10" not in (work / "draft" / "open-questions.md").read_text(encoding="utf-8")


def test_reworded_question_is_a_new_question_and_comes_back(tmp_path):
    work = _work(tmp_path)
    ids = _ids(work)
    _remove(work, ids[DROP])
    sheet = work / "cards" / "PATCH.answer.md"
    sheet.write_text(sheet.read_text(encoding="utf-8").replace(DROP, DROP.replace("urgent", "emergent")), encoding="utf-8")
    assert any("emergent" in t for t in _ids(work))


def test_figure_and_role_table_gaps_are_removed_by_their_own_dr_ids(tmp_path):
    work = _work(tmp_path)
    (work / "figures").mkdir()
    (work / "figures" / "gaps.json").write_text(json.dumps({"TIME": [
        {"dr_id": "DR-TIME-F01", "text": "HOSTONE1: not in the discovery captures", "section": "3.4 Time"},
        {"dr_id": "DR-TIME-F02", "text": "HOSTTWO2: not in the discovery captures", "section": "3.4 Time"}]}), encoding="utf-8")
    (work / "topic-tables").mkdir()
    (work / "topic-tables" / "gaps.json").write_text(json.dumps({"DNS": [
        {"dr_id": "DR-DNS-T01", "text": "Capture the DNS settings of HOSTONE1", "section": "3.5 DNS", "role": "r", "hosts": ["HOSTONE1"]}]}),
        encoding="utf-8")
    _remove(work, "DR-TIME-F01", "DR-DNS-T01")
    text = (draft_lane.open_questions(work) and (work / "draft" / "open-questions.md").read_text(encoding="utf-8"))
    assert "DR-TIME-F02" in text and "DR-TIME-F01" not in text and "DR-DNS-T01" not in text and "Role table for" not in text


def test_gap_check_leaves_removed_questions_out_and_records_which(tmp_path, monkeypatch):
    work = _work(tmp_path)
    ws = work.parent
    ids = _ids(work)
    (work / "draft" / "open-questions.md").write_text(                    # a file written before the removal still lists both
        "# Open questions\n\n## 3.10 Patch & Lifecycle Management (PATCH)\n\n" f"- [B1] {KEEP}\n- [B1] {DROP}\n", encoding="utf-8")
    _remove(work, ids[DROP])
    seen = []
    monkeypatch.setattr(gs.gap_lookup, "lookup_gap", lambda w, dr_id, text, exclude=(): (seen.append(dr_id) or {
        "verdict": "NOT_FOUND", "answer_evidence_ids": [], "related_evidence_ids": [], "lead_ids": [], "searched": "x"}))
    res = gs.sweep(ws)
    assert seen == [ids[KEEP]] and [q["dr_id"] for q in res["questions"]] == [ids[KEEP]]
    assert res["removed_by_owner"] == [ids[DROP]]


def test_discovery_required_leaves_removed_gaps_out_and_a_merged_group_leads_with_a_kept_one(tmp_path):
    work = _work(tmp_path)
    (work / "topic-tables").mkdir()
    gaps = [{"dr_id": f"DR-DNS-T0{i}", "text": "Capture the DNS settings of HOSTONE1", "section": "3.5 DNS", "role": "r", "hosts": ["HOSTONE1"]}
            for i in (1, 2)] + [{"dr_id": "DR-DNS-T03", "text": "Capture the DNS settings of HOSTTWO2", "section": "3.5 DNS",
                                  "role": "r2", "hosts": ["HOSTTWO2"]}]
    (work / "topic-tables" / "gaps.json").write_text(json.dumps({"DNS": gaps}), encoding="utf-8")
    assert {i["dr_id"] for i in dr._collect(work)} == {"DR-DNS-T01", "DR-DNS-T03"}          # the two topics of one group merge
    _remove(work, "DR-DNS-T01", "DR-DNS-T03")
    assert [i["dr_id"] for i in dr._collect(work)] == ["DR-DNS-T02"]
