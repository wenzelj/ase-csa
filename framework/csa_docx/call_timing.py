"""Where the time of one model call went, read from the session log the CLI itself wrote (codex exec).

The log carries a timestamp on every event and every tool call. ``summarise`` returns the number of steps, the total
time, and the longest gaps between events with the step that came before each gap, so a slow call explains itself.
It reads only; a CLI without such a log gives None.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

SESSIONS = Path.home() / ".codex" / "sessions"


def _when(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def find_log(since: float, root: Path | None = None) -> Path | None:
    """The newest session log last written at or after ``since`` (epoch seconds)."""
    root = root or SESSIONS
    if not root.is_dir():
        return None
    logs = [p for p in root.rglob("rollout-*.jsonl") if p.stat().st_mtime >= since]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def summarise(since: float, root: Path | None = None, top: int = 3) -> dict | None:
    """{"steps", "minutes", "longest": [{"minutes", "after"}]} for the call that began at ``since``, or None."""
    log = find_log(since, root)
    return summarise_log(log, top) if log else None


def summarise_log(log: Path, top: int = 3) -> dict | None:
    events: list[tuple[float, str]] = []
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(line)
            at = _when(d["timestamp"])
        except (ValueError, KeyError, TypeError):
            continue
        p = d.get("payload") or {}
        label = ""
        if p.get("type") == "function_call":
            try:
                label = str(json.loads(p.get("arguments") or "{}").get("cmd") or "")
            except ValueError:
                label = str(p.get("arguments") or "")
        events.append((at, " ".join(label.split())[:90]))
    if len(events) < 2:
        return None
    events.sort(key=lambda e: e[0])
    # a step is what the model did between two tool calls: its thinking and the tool's run. Time between consecutive tool calls
    # (and from the last one to the end of the log) is that step's length, however many small events sit inside it.
    calls = [(at, label) for at, label in events if label]
    if not calls:
        return None
    gaps = [(b[0] - a[0], a[1]) for a, b in zip(calls, calls[1:])] + [(events[-1][0] - calls[-1][0], calls[-1][1])]
    gaps.sort(key=lambda g: g[0], reverse=True)
    return {"steps": len(calls), "minutes": round((events[-1][0] - events[0][0]) / 60, 1),
            "longest": [{"minutes": round(g / 60, 1), "after": label} for g, label in gaps[:top] if g >= 60]}


def line(s: dict) -> str:
    waits = ", ".join(f"{w['minutes']:g} min" + (f" (after: {w['after']})" if w["after"] else "") for w in s["longest"])
    return f"model call: {s['steps']} steps in {s['minutes']:g} min" + (f"; longest waits {waits}" if waits else "; no wait over a minute")
