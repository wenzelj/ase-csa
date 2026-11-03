"""An answer call is stopped when it produces no work, not when a fixed time is up."""
import os
import runpy
from pathlib import Path

CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def test_the_idle_clock_runs_only_when_no_work_is_produced():
    expired = CSA["idle_expired"]
    assert not expired(last_work=0, now=24 * 60, idle_min=25)
    assert expired(last_work=0, now=25 * 60, idle_min=25)
    assert not expired(last_work=0, now=10 ** 6, idle_min=0)          # 0 turns it off


def test_work_is_a_sheet_or_patch_written_or_changed_and_nothing_else(tmp_path):
    sig = CSA["work_signature"]
    (tmp_path / "STOR.md").write_text("card")
    (tmp_path / "STOR.focus-B2.md").write_text("focused card")
    (tmp_path / "STOR.errors-B2.md").write_text("errors")
    (tmp_path / "scratch.py").write_text("print(1)")
    empty = sig(tmp_path)
    assert empty == ()                                                  # inputs and scratch files are not work
    (tmp_path / "STOR.patch-B2.md").write_text("## B2\n")
    first = sig(tmp_path)
    assert [x[0] for x in first] == ["STOR.patch-B2.md"]
    (tmp_path / "STOR.patch-B2.md").write_text("## B2\nFacts:\n- more\n")
    os.utime(tmp_path / "STOR.patch-B2.md", ns=(10 ** 18, 10 ** 18))
    assert sig(tmp_path) != first                                       # a change restarts the clock
    (tmp_path / "STOR.answer.md").write_text("sheet")
    assert [x[0] for x in sig(tmp_path)] == ["STOR.answer.md", "STOR.patch-B2.md"]
