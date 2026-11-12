"""Codex notify program: record that the agent's turn has ended.

    turn_done.py MARKER '{"type": "agent-turn-complete", ...}'

Codex runs its `notify` program with the event as the last argument. `csa` passes this program for an interactive answer
run started by the Evidence Browser and closes the agent's window once the marker exists and a sheet was written.
Standard library only: it is started by the CLI, outside the framework's import path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 2
    try:
        event = json.loads(argv[-1])
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("type") != "agent-turn-complete":
        return 0
    marker = Path(argv[1])
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"type": event["type"], "turn-id": event.get("turn-id")}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
