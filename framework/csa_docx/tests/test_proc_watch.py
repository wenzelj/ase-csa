"""A model call that does nothing (no CPU, no connection) for a few minutes has stalled."""
from csa_docx import proc_watch as W

PS = """
  100     1   0:00.02
  101   100   0:00.07
  102   101   1:02.50
  200     1   9:99.00
"""


def test_cpu_time_formats():
    assert W.cpu_to_seconds("0:00.07") == 0.07
    assert W.cpu_to_seconds("12:34.50") == 754.5
    assert W.cpu_to_seconds("1:02:03") == 3723
    assert W.cpu_to_seconds("2-01:02:03") == 2 * 86400 + 3723


def test_tree_is_the_process_and_everything_below_it():
    t = W.tree(100, PS)
    assert set(t) == {100, 101, 102} and round(t[102], 2) == 62.5


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def watch(cpu_values, conn, stall_s=180):
    clock, it = Clock(), iter(cpu_values)
    state = {"last": cpu_values[0]}

    def cpu(pid):
        state["last"] = next(it, state["last"])
        return {pid: state["last"]}
    return clock, W.Watch(1, stall_s, now=clock, cpu=cpu, conn=lambda pids: conn)


def test_a_call_with_no_cpu_and_no_connection_stalls_after_the_window():
    clock, w = watch([0.07] * 20, conn=False)
    for _ in range(5):
        clock.t += 30
        assert not w.stalled()           # 150 s
    clock.t += 30
    assert w.stalled()                   # 180 s


def test_a_connection_keeps_a_quiet_call_alive():
    clock, w = watch([0.07] * 20, conn=True)
    for _ in range(10):
        clock.t += 60
        assert not w.stalled()


def test_cpu_use_keeps_a_call_alive_and_resets_the_clock():
    clock, w = watch([0.07, 0.07, 5.0, 5.0, 5.0, 5.0], conn=False)
    clock.t += 120; assert not w.stalled()               # quiet for 120 s: not yet
    clock.t += 120; assert not w.stalled()               # CPU rose to 5.0 at this poll: alive, the clock restarts
    clock.t += 170; assert not w.stalled()               # 170 s of quiet since
    clock.t += 30; assert w.stalled()                    # 200 s of quiet: stalled


def test_not_knowing_is_never_a_stall():
    clock, w = watch([0.07] * 20, conn=None)
    clock.t += 3600
    assert not w.stalled()
