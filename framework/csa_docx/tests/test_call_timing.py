import json
from datetime import datetime, timedelta, timezone

from csa_docx import call_timing as T


def log(tmp_path, steps):
    """steps: [(minutes after the start, command or None)]; a None command is a small event with no tool call."""
    t0 = datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc)
    lines = []
    for mins, cmd in steps:
        at = (t0 + timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")
        p = {"type": "function_call", "arguments": json.dumps({"cmd": cmd})} if cmd else {"type": "token_count"}
        lines.append(json.dumps({"timestamp": at, "payload": p}))
    f = tmp_path / "rollout-x.jsonl"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def test_a_long_step_is_found_however_many_small_events_sit_inside_it(tmp_path):
    f = log(tmp_path, [(0, "cat card"), (1, None), (5, None), (12, None), (28, "grep ids"), (29, "write sheet"), (30, None)])
    s = T.summarise_log(f)
    assert s["steps"] == 3 and s["minutes"] == 30
    assert s["longest"][0] == {"minutes": 28.0, "after": "cat card"}


def test_no_tool_calls_or_no_log_gives_none(tmp_path):
    assert T.summarise_log(log(tmp_path, [(0, None), (1, None)])) is None
    assert T.summarise(10**12, root=tmp_path) is None


def test_the_line_names_the_slow_steps(tmp_path):
    s = T.summarise_log(log(tmp_path, [(0, "cat card"), (28, "grep ids"), (29, None)]))
    assert "longest waits 28 min (after: cat card)" in T.line(s)
