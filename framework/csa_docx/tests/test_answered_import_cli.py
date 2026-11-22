from pathlib import Path


def test_cli_help_exposes_import_answers():
    import subprocess
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([str(root / "bin" / "csa"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "import-answers" in result.stdout
