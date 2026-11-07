"""New document topics get usable frames without a shared topic profile."""
import json

from csa_docx import section_card as SC
from csa_docx import topic_frames as TF


def _node():
    return {"key": "NEW_TOPIC", "number": "4.7", "title": "New Service Records", "kind": "discovery",
            "comments": [], "parts": [
                {"kind": "narrative", "question": "Which service records are maintained?"},
                {"kind": "register", "columns": ["Service", "Record owner", "Review date"]}]}


def test_new_subsection_card_gets_frame_and_table_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(TF, "FRAMES", tmp_path / "no-profiles")
    card = SC.card(_node(), {}, workspace=tmp_path)
    frame = card["frame"]
    assert frame["origin"] == "document_questions"
    assert frame["answer_blocks"] == {"S1": "B1", "S2": "B2"}
    assert "Record owner, Review date" in card["text"]
    assert "Answer in B2." in card["text"]
    assert frame["ids"] == []
    assert not card["role_table"]
    assert "nothing in the captures answers this" not in card["text"]
    saved = json.loads((tmp_path / "csa-work/topic-frames/NEW_TOPIC.json").read_text())
    assert saved["origin"] == "document_questions"
    assert not (tmp_path / "no-profiles").exists()


def test_existing_profile_takes_precedence(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "custom.json").write_text(json.dumps({
        "headings": ["New Service Records"], "slots": [
            {"id": "S9", "question": "Who owns the service records?", "source": {}}]}))
    monkeypatch.setattr(TF, "FRAMES", profiles)
    fr = TF.build(tmp_path, "New Service Records", "NEW_TOPIC", questions=SC.questions(_node()))
    assert fr["origin"] == "topic_profile"
    assert [s["id"] for s in fr["slots"]] == ["S9"]


def test_fallback_selects_only_verified_candidates(tmp_path, monkeypatch):
    from csa_docx import evidence_live
    monkeypatch.setattr(TF, "FRAMES", tmp_path / "no-profiles")
    rows = [{"evidence_id": f"E-{n}", "claim": "The service records are maintained by the application owner.",
             "status": status} for n, status in [(1, "VERIFIED"), (2, "UNCONFIRMED"), (3, "NOT_FOUND")]]
    monkeypatch.setattr(evidence_live, "get_verified_evidence", lambda _: rows)
    fr = TF.build(tmp_path, "New Service Records", "NEW_TOPIC", questions=SC.questions(_node()))
    assert TF.all_ids(fr) == {"E-1"}
    assert all(not s["findings"] for s in fr["slots"])
    assert "check whether they answer the question" in "\n".join(TF.card_lines(fr))


def test_requirement_binding_and_comment_exclusion():
    qs = [{"id": "B1", "kind": "requirement", "req_id": "NEW-01", "text": "Retain service records."},
          {"id": "C1", "kind": "comment", "text": "Review this wording."}]
    profile = TF.question_profile("New topic", "NEW", qs)
    assert len(profile["slots"]) == 1
    assert profile["slots"][0]["requirements"] == ["NEW-01"]
    assert TF.question_profile("New topic", "NEW", qs[1:]) is None
