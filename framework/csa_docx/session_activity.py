"""Is an answer call's agent session doing anything? Read from the session log the CLI itself writes (Codex).

An answer call is stopped when it has written no sheet or patch for a while. Reading a large card writes nothing, so a
session that was working could be stopped before its first write. ``Activity.last()`` is the time of the last write to this
call's own session log: every model reply and tool call is one. Only logs written since the call began, by a session whose
working folder is the call's folder, count. A CLI that keeps no such log gives None, and the caller goes by the sheet alone.

    seen = Activity(cards_folder, since=time.time())
    ... every poll:  seen.last()   # epoch seconds, or None
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SESSIONS = Path.home() / ".codex" / "sessions"


class Activity:
    def __init__(self, cwd, since: float, root: Path | None = None):
        self.cwd = os.path.realpath(str(cwd))
        self.since = since
        self.root = Path(root) if root is not None else SESSIONS
        self._mine: dict[str, bool] = {}            # log path -> written by a session working in cwd

    def _days(self) -> list[Path]:
        """The log folders (one per local day) from the day the call began to today."""
        out, t = [], self.since
        end = time.time()
        while True:
            day = self.root / time.strftime("%Y/%m/%d", time.localtime(t))
            if day not in out:
                out.append(day)
            if t >= end:
                break
            t = min(t + 86400, end)
        return out

    def _is_mine(self, log: Path) -> bool:
        key = str(log)
        if key not in self._mine:
            mine = False
            try:
                with open(log, encoding="utf-8", errors="ignore") as fh:
                    meta = json.loads(fh.readline() or "{}")
                cwd = (meta.get("payload") or {}).get("cwd")
                mine = bool(cwd) and os.path.realpath(str(cwd)) == self.cwd
            except (OSError, ValueError, AttributeError):
                return False                        # not readable yet: look again at the next poll
            self._mine[key] = mine
        return self._mine[key]

    def last(self) -> float | None:
        best = None
        for day in self._days():
            try:
                logs = list(day.glob("rollout-*.jsonl"))
            except OSError:
                continue
            for log in logs:
                try:
                    mtime = log.stat().st_mtime
                except OSError:
                    continue
                if mtime >= self.since and (best is None or mtime > best) and self._is_mine(log):
                    best = mtime
        return best
