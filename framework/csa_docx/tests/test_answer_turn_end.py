"""An interactive answer run started by the Evidence Browser ends when the agent's turn ends with work produced.

The interactive Codex window stays open after the answer is written, so `csa` used to wait out the idle limit before it
checked the sheet. Codex's notify hook now writes a marker when a turn ends; a turn that produced a sheet closes the run.
"""
import json
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
CSA = runpy.run_path(str(ROOT / "bin" / "csa"))


def test_the_hook_is_added_only_for_an_interactive_codex_window_when_asked(tmp_path):
    args = CSA["turn_end_args"]
    marker = tmp_path / "turn.json"
    on = {"CSA_CLOSE_ON_TURN_END": "1"}
    got = args(["codex", "--profile", "evo-x3-qwen", "PROMPT"], "interactive", marker, on)
    assert got[0] == "-c" and got[1].startswith("notify=[")
    assert json.loads(got[1][len("notify="):])[-1] == str(marker)
    assert args(["codex", "PROMPT"], "interactive", marker, {}) == []                  # your own terminal: stays open
    assert args(["codex", "exec", "PROMPT"], "headless", marker, on) == []            # exits by itself already
    assert args(["claude", "PROMPT"], "interactive", marker, on) == []                # no such hook


def test_a_turn_closes_the_run_only_when_it_produced_work(tmp_path):
    ended = CSA["turn_ended_with_work"]
    marker = tmp_path / "turn.json"
    before, after = (), (("TIME.answer.md", 10, 1),)
    assert not ended(marker, before, after)                    # the turn is still running
    marker.write_text("{}")
    assert not ended(marker, before, before)                   # the agent stopped to ask something: leave it open
    assert not marker.exists()                                 # ...and a later turn has to end again to close the run
    marker.write_text("{}")
    assert ended(marker, before, after)
    assert not ended(None, before, after)                      # hook not in use


def test_browser_work_close_fallback_requires_browser_marker_and_quiet_work():
    ready = CSA["browser_work_close_ready"]
    before, after = (), (("TIME.patch-B1.md", 10, 2),)
    assert ready("interactive", {"CSA_CLOSE_ON_TURN_END": "1"}, before, after, 0, 5)
    assert not ready("interactive", {}, before, after, 0, 5)
    assert not ready("headless", {"CSA_CLOSE_ON_TURN_END": "1"}, before, after, 0, 5)
    assert not ready("interactive", {"CSA_CLOSE_ON_TURN_END": "1"}, before, after, 4, 5)


def test_browser_turn_cannot_close_until_the_block_wrote_work(tmp_path):
    ready = CSA["browser_turn_ready"]
    marker = tmp_path / "turn.json"
    assert not ready(marker, (), ())
    marker.write_text("{}")
    assert not ready(marker, (), ())
    assert ready(marker, (), (("TIME.patch-B1.md", 10, 2),))


def test_browser_turn_marker_is_checked_before_the_work_helper_can_clear_it(tmp_path):
    marker = tmp_path / "turn.json"
    marker.write_text("{}")
    # This is the exact no-patch state: the browser completion marker exists,
    # but the answer/patch signature has not changed.  The browser path must
    # close the child instead of delegating to turn_ended_with_work(), which
    # intentionally clears a no-work marker for an ordinary terminal run.
    assert CSA["browser_turn_ready"](marker, (), (("TIME.patch-B1.md", 10, 2),))
    assert not CSA["turn_ended_with_work"](marker, (), ())
    assert not marker.exists()


def test_the_notify_program_writes_the_marker(tmp_path):
    marker = tmp_path / "turn.json"
    payload = json.dumps({"type": "agent-turn-complete", "last-assistant-message": "done"})
    subprocess.run([sys.executable, str(ROOT / "framework" / "csa_docx" / "turn_done.py"), str(marker), payload], check=True)
    assert json.loads(marker.read_text())["type"] == "agent-turn-complete"
    legacy = tmp_path / "legacy.json"
    subprocess.run([sys.executable, str(ROOT / "framework" / "csa_docx" / "turn_done.py"), str(legacy), "turn-ended"], check=True)
    assert json.loads(legacy.read_text())["type"] == "agent-turn-complete"
    other = tmp_path / "other.json"
    subprocess.run([sys.executable, str(ROOT / "framework" / "csa_docx" / "turn_done.py"), str(other),
                    json.dumps({"type": "something-else"})], check=True)
    assert not other.exists()                                  # only the end of a turn counts
