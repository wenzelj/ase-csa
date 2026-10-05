import pytest

from csa_docx import rules_digest as rd


@pytest.mark.parametrize("stage", rd.STAGES)
def test_digest_exists_small_and_mentions_check_change(stage):
    text = rd.digest(stage)
    assert len(text.encode("utf-8")) <= rd.LIMIT
    assert "check-change" in text


def test_oversize_digest_is_refused(tmp_path, monkeypatch):
    (tmp_path / "answer.md").write_text("x" * (rd.LIMIT + 1), encoding="utf-8")
    monkeypatch.setattr(rd, "DIGESTS", tmp_path)
    with pytest.raises(ValueError):
        rd.digest("answer")


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        rd.digest("nope")
