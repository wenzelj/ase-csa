"""Run one model CLI call, keep its output, and optionally show it while it runs.

The reader and rating passes used to capture their call's output, so a run sat silent for up to ten minutes. ``run`` reads
both streams as they arrive, copies each line to ``show`` (the terminal) when one is given, and says the call is still
running when it has printed nothing for ``heartbeat_s``. It also names a reply that is a CLI's failure notice (a usage
limit, no login) so that such a reply is never saved as the model's answer.

    rc, out, err = run(argv, cwd, timeout_s, show=sys.stderr, label="reader pass")
    reason = failure_notice(rc, out, err)      # "" when the reply is a real one
"""
from __future__ import annotations

import re
import subprocess
import threading
import time

# What a CLI prints instead of a model reply when it cannot make the call. Matched on a short reply only: a real review or
# rating may well mention a rate limit in the assessed system.
_NOTICE = re.compile(r"hit your .{0,40}limit|usage limit|rate limit|limit reached|credit balance is too low|"
                     r"invalid api key|please run /login|not logged in|authentication[_ ]error|overloaded", re.I)
_NOTICE_MAX_CHARS = 400


def run(argv: list[str], cwd, timeout_s: float, show=None, heartbeat_s: float = 30, label: str = "model call"):
    """(exit code, stdout, stderr) of ``argv``. Raises subprocess.TimeoutExpired after ``timeout_s`` (the call is stopped)."""
    proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace")
    kept: dict[str, list[str]] = {"out": [], "err": []}
    lock = threading.Lock()
    last_line = [time.time()]

    def emit(text: str) -> None:
        if show is None:
            return
        try:
            show.write(text)
            show.flush()
        except (OSError, ValueError):               # showing is a courtesy; it never decides whether the call worked
            pass

    def pump(name: str, stream) -> None:
        for line in iter(stream.readline, ""):
            with lock:
                kept[name].append(line)
                last_line[0] = time.time()
                emit("  | " + line if line.endswith("\n") else "  | " + line + "\n")
        stream.close()

    readers = [threading.Thread(target=pump, args=("out", proc.stdout), daemon=True),
               threading.Thread(target=pump, args=("err", proc.stderr), daemon=True)]
    for t in readers:
        t.start()
    began = time.time()
    while True:
        try:
            proc.wait(timeout=min(0.2, heartbeat_s) if heartbeat_s else 0.2)
            break
        except subprocess.TimeoutExpired:
            now = time.time()
            if now - began >= timeout_s:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(argv[:1], timeout_s) from None
            with lock:
                if heartbeat_s and now - last_line[0] >= heartbeat_s:
                    last_line[0] = now
                    emit(f"  {label}: still running ({now - began:.0f} s)\n")
    for t in readers:
        t.join(timeout=5)
    return proc.returncode, "".join(kept["out"]), "".join(kept["err"])


def failure_notice(rc: int, out: str, err: str = "") -> str:
    """Why this call's output is not a model reply ("" when it is one): a non-zero exit, or a short reply that is the
    CLI's own notice (usage limit, no login)."""
    reply = (out or "").strip()
    if rc != 0:
        tail = (reply or (err or "").strip() or "no output")[-300:]
        return f"the model call exited with code {rc}: {tail}"
    if reply and len(reply) <= _NOTICE_MAX_CHARS and _NOTICE.search(reply):
        return f"the model CLI returned a notice instead of a reply: {reply[:300]}"
    return ""
