from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend import window_job


def test_terminal_command_keeps_csa_interactive_and_reports_exit(tmp_path: Path, monkeypatch, capsys):
    job = tmp_path / "job with spaces"
    command = ["/framework/bin/csa", "--project", "tetra-reveloc", "intake", "--cli", "claude"]
    script = window_job.write_command(job, tmp_path, command)
    text = script.read_text()
    assert script.stat().st_mode & 0o777 == 0o700
    assert "intake --cli claude" in text
    assert "--headless" not in text and " --permission-mode " not in text
    assert "terminal.exit" in text

    def fake_open(argv, **_kwargs):
        assert argv == ["/usr/bin/open", "-a", "Terminal", str(script)]
        (job / "terminal.exit").write_text("0\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(window_job.sys, "platform", "darwin")
    monkeypatch.setattr(window_job.subprocess, "run", fake_open)
    assert window_job.main([str(job), str(tmp_path), *command]) == 0
    assert "opened in Terminal" in capsys.readouterr().out


def test_terminal_exit_status_is_forwarded(tmp_path: Path):
    (tmp_path / "terminal.exit").write_text("7\n")
    assert window_job.wait_for_exit(tmp_path) == 7
