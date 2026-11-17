from pathlib import Path


def test_improve_cli_help_lists_separate_command():
    root = Path(__file__).resolve().parents[2].parent
    text = (root / "bin" / "csa").read_text(encoding="utf-8")
    assert 'sp("improve", cmd_improve' in text
    assert 'sp("refresh-draft", cmd_refresh_draft' in text


def test_improve_agent_contract_is_not_an_answer_sheet():
    root = Path(__file__).resolve().parents[2].parent
    prompt = (root / "csa-improve-agent.md").read_text(encoding="utf-8")
    assert "bounded JSON proposal" in prompt
    assert "not an answer sheet" in prompt
    assert "no_material_change" in prompt
