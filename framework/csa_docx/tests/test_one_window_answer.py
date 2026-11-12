"""An answer run in one visible window: block by block when the agent's window closes itself, the advisory passes shown
while they run, a reply that is not a review never saved as one, and timers that suit a session someone is watching."""
import io
import json
import os
import runpy
import sys
import time
from pathlib import Path

from csa_docx import live_call, rating_pass, reader_pass as R, session_activity

ROOT = Path(__file__).parents[3]
CSA = runpy.run_path(str(ROOT / "bin" / "csa"))


# ---------------------------------------------------------------- block by block without --headless

def test_blocks_are_answered_one_call_each_when_headless_or_when_the_window_closes_itself():
    ok = CSA["by_block_run"]
    browser = {"CSA_CLOSE_ON_TURN_END": "1"}
    assert ok(True, "codex {prompt}", {})                                   # --headless: as before
    assert ok(False, "codex --profile evo-x3-qwen {prompt}", browser)      # the browser's Codex window closes at turn end
    assert not ok(False, "codex --profile evo-x3-qwen {prompt}", {})       # your own terminal: the window stays open
    assert not ok(False, "claude {prompt}", browser)                       # no turn-end signal for this CLI
    assert not ok(False, "", browser)


def test_an_interactive_run_answers_one_block_at_a_time():
    workers = CSA["by_block_workers"]
    assert workers(4, headless=True) == 4
    assert workers(4, headless=False) == 1                                 # two sessions cannot share one terminal
    assert workers(0, headless=True) == 1


# ---------------------------------------------------------------- the advisory passes are shown while they run

def test_a_live_call_shows_the_output_as_it_arrives_and_returns_it():
    shown = io.StringIO()
    code = "import sys; print('## Review'); print('- one'); print('progress', file=sys.stderr)"
    rc, out, err = live_call.run([sys.executable, "-c", code], cwd=Path.cwd(), timeout_s=30, show=shown)
    assert rc == 0 and out.strip() == "## Review\n- one" and err.strip() == "progress"
    assert "## Review" in shown.getvalue() and "progress" in shown.getvalue()


def test_a_quiet_live_call_says_it_is_still_running():
    shown = io.StringIO()
    rc, out, _ = live_call.run([sys.executable, "-c", "import time; time.sleep(1.2); print('done')"], cwd=Path.cwd(),
                               timeout_s=30, show=shown, heartbeat_s=0.4, label="reader pass")
    assert rc == 0 and out.strip() == "done" and "reader pass: still running" in shown.getvalue()


def test_a_live_call_shows_nothing_unless_asked():
    rc, out, _ = live_call.run([sys.executable, "-c", "print('x')"], cwd=Path.cwd(), timeout_s=30)
    assert rc == 0 and out.strip() == "x"


def test_a_live_call_is_stopped_at_its_time_limit():
    import subprocess
    try:
        live_call.run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=Path.cwd(), timeout_s=0.5)
    except subprocess.TimeoutExpired:
        return
    raise AssertionError("no timeout")


# ---------------------------------------------------------------- a reply that is not a review is never saved as one

def _sheet(tmp_path):
    sheet = tmp_path / "DNS.answer.md"
    sheet.write_text("## B1 SEP-X-01\nSummary: S.\n", encoding="utf-8")
    (tmp_path / "DNS.RESULT.md").write_text("# csa answer 3.5: APPLIED\n", encoding="utf-8")
    return sheet


def test_a_usage_limit_message_is_not_a_review(tmp_path):
    sheet = _sheet(tmp_path)
    template = f"{sys.executable} -c \"print('You\\'ve hit your 5-hour limit · resets 9:50am (Australia/Perth)')\" {{prompt}}"
    out = R.review(tmp_path, sheet, "DNS", tmp_path, template)
    assert out["status"] == "ERROR" and "limit" in out["message"]
    assert not (tmp_path / "DNS.review.md").exists()
    assert "Reader review" not in (tmp_path / "DNS.RESULT.md").read_text(encoding="utf-8")


def test_a_failed_reader_call_is_not_a_review_and_an_earlier_review_is_kept(tmp_path):
    sheet = _sheet(tmp_path)
    (tmp_path / "DNS.review.md").write_text("## Contradictions between blocks\n- None found.\n", encoding="utf-8")
    template = f"{sys.executable} -c \"import sys; print('something went wrong'); sys.exit(1)\" {{prompt}}"
    out = R.review(tmp_path, sheet, "DNS", tmp_path, template)
    assert out["status"] == "ERROR" and "exited with code 1" in out["message"]
    assert (tmp_path / "DNS.review.md").read_text(encoding="utf-8").startswith("## Contradictions")


def test_the_rating_pass_reports_a_usage_limit_instead_of_asking_again(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    card = tmp_path / "DNS.json"
    card.write_text(json.dumps({"questions": [{"id": "B1"}]}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(rating_pass, "rated_blocks", lambda s, c: ["B1"])
    monkeypatch.setattr(rating_pass, "build_prompt", lambda *a: "PROMPT")
    template = f"{sys.executable} -c \"print('You\\'ve hit your 5-hour limit')\" {{prompt}}"
    real = rating_pass._ask
    monkeypatch.setattr(rating_pass, "_ask", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    out = rating_pass.rate(tmp_path, sheet, card, "DNS", tmp_path, template)
    assert out["status"] == "ERROR" and "limit" in out["message"] and len(calls) == 1


# ---------------------------------------------------------------- timers for a session someone is watching

def _log(root: Path, name: str, cwd: Path, mtime: float) -> Path:
    day = root / time.strftime("%Y/%m/%d", time.localtime(mtime))
    day.mkdir(parents=True, exist_ok=True)
    f = day / f"rollout-{name}.jsonl"
    f.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(cwd)}}) + "\n", encoding="utf-8")
    os.utime(f, (mtime, mtime))
    return f


def test_session_activity_is_the_last_write_to_this_runs_own_session_log(tmp_path):
    cards, other, now = tmp_path / "cards", tmp_path / "elsewhere", time.time()
    cards.mkdir(); other.mkdir()
    root = tmp_path / "sessions"
    seen = session_activity.Activity(cards, since=now - 100, root=root)
    assert seen.last() is None                                             # no session log: nothing to go by
    _log(root, "old", cards, now - 500)                                    # an earlier run in the same folder
    _log(root, "other", other, now - 5)                                    # someone else's session
    assert seen.last() is None
    mine = _log(root, "mine", cards, now - 40)
    assert abs(seen.last() - (now - 40)) < 2
    os.utime(mine, (now - 3, now - 3))
    assert abs(seen.last() - (now - 3)) < 2


def test_the_idle_clock_counts_session_activity_but_not_for_ever():
    stop = CSA["idle_stop"]
    m = 60
    assert stop(last_work=0, last_active=None, now=25 * m, idle_min=25, no_work_min=60)            # nothing to go by: as before
    assert not stop(last_work=0, last_active=20 * m, now=30 * m, idle_min=25, no_work_min=60)      # reading a large card
    assert stop(last_work=0, last_active=20 * m, now=45 * m, idle_min=25, no_work_min=60)          # then quiet for 25 min
    assert stop(last_work=0, last_active=59 * m, now=60 * m, idle_min=25, no_work_min=60)          # busy but nothing written
    assert not stop(last_work=0, last_active=59 * m, now=60 * m, idle_min=25, no_work_min=0)       # 0 turns the cap off
    assert not stop(last_work=0, last_active=None, now=10 ** 6, idle_min=0, no_work_min=60)        # idle limit off: off


def test_a_window_that_closes_itself_is_not_restarted_for_being_quiet():
    wanted = CSA["stall_check_wanted"]
    assert wanted(3, turn_marker=None)
    assert not wanted(3, turn_marker=Path("turn.json"))                    # it may be waiting for the person watching
    assert not wanted(0, turn_marker=None)
