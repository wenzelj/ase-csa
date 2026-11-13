import json
from csa_docx import rating_pass as R


def _blocks(a, b):
    return {"B1": {"score": a, "reason": "x"}, "B2": {"score": b, "reason": "y"}}


def test_reply_is_validated_and_rounded():
    ok, err = R.parse_reply('noise {"B1": {"score": 7.46, "reason": "good"}, "B2": {"score": 6, "reason": "thin"}} tail', ["B1", "B2"])
    assert err == "" and ok["B1"]["score"] == 7.5 and ok["B2"]["score"] == 6.0
    assert R.parse_reply('{"B1": {"score": 11, "reason": ""}}', ["B1"])[0] is None
    assert R.parse_reply('{"B1": {"score": 7, "reason": ""}}', ["B1", "B2"])[0] is None     # B2 missing
    assert R.parse_reply("sorry", ["B1"])[0] is None


def test_history_keeps_the_last_three_runs_and_flags_blocks_that_got_worse(tmp_path):
    for a, b in ((7, 7), (8, 7), (8, 6.5), (8.5, 6.5)):
        R.record(tmp_path, "K", _blocks(a, b))
    data = json.loads((tmp_path / "ratings" / "K.json").read_text())
    assert len(data["runs"]) == 3
    s = R.load_summary(tmp_path, "K")
    assert s["latest"] == 7.5 and s["average"] == 7.4 and s["worse"] == []   # B2 6.5 -> 6.5, B1 rose
    R.record(tmp_path, "K", _blocks(7.0, 6.5))
    assert R.load_summary(tmp_path, "K")["worse"] == ["B1"]                  # fell by 1.5


def test_small_drop_is_not_worse_and_unreadable_history_is_none(tmp_path):
    R.record(tmp_path, "K", _blocks(8.0, 7.0)); R.record(tmp_path, "K", _blocks(7.6, 7.0))
    assert R.load_summary(tmp_path, "K")["worse"] == []
    (tmp_path / "ratings" / "K.json").write_text("{not json")
    assert R.load_summary(tmp_path, "K") is None and R.load_summary(tmp_path, "NOPE") is None


def test_only_answered_blocks_are_rated():
    sheet = {"B1": {"summary": "s"}, "B2": {}, "B3": {"rows": [["h"]]}}
    card = {"questions": [{"id": "B1"}, {"id": "B2"}, {"id": "B3"}]}
    assert R.rated_blocks(sheet, card) == ["B1", "B3"]


def test_improvements_are_kept_trimmed_to_three_and_shown_in_the_summary(tmp_path):
    blocks, err = R.parse_reply('{"B1": {"score": 6, "reason": "r", "improve": ["a", "b", "c", "d", " "]}, "B2": {"score": 9.5, "reason": "ok"}}',
                                ["B1", "B2"])
    assert err == "" and blocks["B1"]["improve"] == ["a", "b", "c"] and blocks["B2"]["improve"] == []
    R.record(tmp_path, "K", blocks)
    assert R.load_summary(tmp_path, "K")["improve"] == {"B1": ["a", "b", "c"]}


def test_result_rating_is_used_when_migrated_workspace_has_no_json_history(tmp_path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "TIME.RESULT.md").write_text(
        "# result\n\n## Answer rating\n\nAverage 6.6 (B1 6.3, B2 6.5, B3 7.0). "
        "Lower than the previous run: B2, B3.\n", encoding="utf-8")
    out = R.load_summary(tmp_path, "TIME")
    assert out["latest"] == 6.6
    assert out["average"] == 6.6
    assert out["worse"] == ["B2", "B3"]
    assert out["runs"][0]["blocks"] == {"B1": 6.3, "B2": 6.5, "B3": 7.0}


def test_result_fallback_is_not_cross_key_or_cross_workspace(tmp_path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "TIME.RESULT.md").write_text("## Answer rating\n\nAverage 6.0 (B1 6.0).\n", encoding="utf-8")
    assert R.load_summary(tmp_path, "DNS") is None


def test_legacy_rating_is_used_only_for_an_identical_current_answer(tmp_path):
    import hashlib
    cards = tmp_path / "cards"
    cards.mkdir()
    answer = cards / "MGT.answer.md"
    answer.write_text("current V2 answer", encoding="utf-8")
    digest = hashlib.sha256(answer.read_bytes()).hexdigest()
    legacy = tmp_path / "../csa-work/ratings"
    legacy.mkdir(parents=True)
    (legacy / "MGT.json").write_text(json.dumps({"runs": [
        {"at": "2026-11-01T00:00:00Z", "sheet_sha256": digest, "average": 7.2,
         "blocks": {"B1": {"score": 7.2, "reason": "same"}}},
        {"at": "2026-11-02T00:00:00Z", "sheet_sha256": "different", "average": 2.0,
         "blocks": {"B1": {"score": 2.0, "reason": "wrong answer"}}}
    ]}), encoding="utf-8")
    assert R.load_summary(tmp_path, "MGT")["latest"] == 7.2
    answer.write_text("changed V2 answer", encoding="utf-8")
    assert R.load_summary(tmp_path, "MGT") is None
