"""Is a model call doing anything? A headless CLI that hangs (waiting on stdin, or never reaching its server) looks the
same as one that is thinking, until the 45-minute timeout. A call is alive while its process tree uses CPU or holds an
open network connection to the model; it has stalled when it has done neither for a few minutes.

    w = Watch(proc.pid, stall_s=180)
    ... every poll:  if w.stalled(): stop the call and start it again
"""
from __future__ import annotations

import subprocess
import time


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout


def cpu_to_seconds(t: str) -> float:
    """ps TIME ("0:00.07", "12:34.50", "1:02:03", "2-01:02:03") in seconds."""
    t = t.strip()
    days = 0
    if "-" in t:
        d, t = t.split("-", 1)
        days = int(d)
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + float(part)
    return days * 86400 + secs


def tree(pid: int, table: str | None = None) -> dict[int, float]:
    """{pid: cpu seconds} for ``pid`` and every process below it."""
    table = table if table is not None else (_run(["ps", "-axo", "pid=,ppid=,time="]) or "")
    rows: dict[int, tuple[int, float]] = {}
    for line in table.splitlines():
        f = line.split()
        if len(f) == 3:
            try:
                rows[int(f[0])] = (int(f[1]), cpu_to_seconds(f[2]))
            except ValueError:
                continue
    out: dict[int, float] = {}
    todo = [pid]
    while todo:
        p = todo.pop()
        if p in rows and p not in out:
            out[p] = rows[p][1]
            todo += [c for c, (pp, _) in rows.items() if pp == p]
    return out


def has_connection(pids: list[int]) -> bool | None:
    """True when any of the processes holds an established TCP connection, False when none does, None when it cannot
    be told (no lsof): an unknown is never read as a stall."""
    if not pids:
        return False
    out = _run(["lsof", "-nP", "-a", "-p", ",".join(str(p) for p in pids), "-iTCP", "-sTCP:ESTABLISHED"])
    if out is None:
        return None
    return any(line.strip() and not line.startswith("COMMAND") for line in out.splitlines())


class Watch:
    """Progress of one model call: CPU used by its process tree, or a network connection it holds."""

    def __init__(self, pid: int, stall_s: float, now=time.time, cpu=tree, conn=has_connection):
        self.pid, self.stall_s, self._now, self._cpu, self._conn = pid, stall_s, now, cpu, conn
        self.last_seen = now()
        self.cpu_total = sum(cpu(pid).values())

    def alive(self) -> bool:
        """Record what the call is doing now; True when it shows a sign of life."""
        procs = self._cpu(self.pid)
        total = sum(procs.values())
        busy = total - self.cpu_total >= 0.3
        self.cpu_total = max(total, self.cpu_total)
        link = self._conn(list(procs))
        if busy or link is None or link:
            self.last_seen = self._now()
            return True
        return False

    def stalled(self) -> bool:
        self.alive()
        return self.stall_s > 0 and self._now() - self.last_seen >= self.stall_s
