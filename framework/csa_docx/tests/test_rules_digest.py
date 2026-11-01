import pytest

from csa_docx import rules_digest as rd


@pytest.mark.parametrize("stage", rd.STAGES)
def test_digest_exists_small_and_mentions_check_change(stage):
    text = rd.digest(stage)
    assert len(text.encode("utf-8")) <= rd.LIMIT + rd.COMMON_LIMIT + rd.SHARED_LIMIT + 4
    assert len(rd.digest_path(stage).read_bytes()) <= rd.LIMIT
    assert "check-change" in text


def test_oversize_digest_is_refused(tmp_path, monkeypatch):
    (tmp_path / "answer.md").write_text("x" * (rd.LIMIT + 1), encoding="utf-8")
    monkeypatch.setattr(rd, "DIGESTS", tmp_path)
    with pytest.raises(ValueError):
        rd.digest("answer")


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        rd.digest("nope")


@pytest.mark.parametrize("stage", rd.STAGES)
def test_digest_carries_the_shared_plain_language_rule(stage):
    text = rd.digest(stage)
    assert "Plain language for the reader" in text
    assert "resolver pair" in text


def test_plain_language_section_is_required(tmp_path, monkeypatch):
    (tmp_path / "SKILL.md").write_text("no markers", encoding="utf-8")
    monkeypatch.setattr(rd, "STYLE_SKILL", tmp_path / "SKILL.md")
    with pytest.raises(ValueError):
        rd.plain_language()


@pytest.mark.parametrize("stage", rd.COMMON_STAGES)
def test_card_lane_digests_carry_the_shared_rules(stage):
    text = rd.digest(stage)
    assert "Shared rules (answer and draft)" in text
    assert "A connection has one side that opens it" in text


@pytest.mark.parametrize("stage", rd.COMMON_STAGES)
def test_cross_lane_rules_are_stated_once(stage):
    text = rd.digest(stage)
    for phrase in ("A connection has one side that opens it", "Another application's rows", "Re-answering:"):
        assert text.count(phrase) == 1, phrase
