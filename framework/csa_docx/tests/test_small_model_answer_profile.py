import runpy
from pathlib import Path


CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def test_small_model_profile_is_bounded_and_block_scoped():
    profile = CSA["answer_profile"]("llama3b")
    assert profile["name"] == "llama3b"
    assert profile["context_bytes"] == 12000
    assert profile["output_tokens"] == 1800
    assert profile["fix_rounds"] == 2
    assert profile["by_block"] is True


def test_default_profile_is_not_replaced_by_small_model_profile():
    profile = CSA["answer_profile"]("evo")
    assert profile["name"] == "default"
    assert profile["by_block"] is False


def test_small_model_cli_command_is_configured():
    settings = CSA["settings"]()
    assert "llama3.2:3b" in settings["llama3b_headless"]
    assert "llama3.2:3b" in settings["llama3b_interactive"]
