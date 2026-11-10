from __future__ import annotations

import base64
import os
import sys
import threading
import time
from pathlib import Path

from backend.terminal_sessions import BUFFER_BYTES, TerminalSession


def _session(script: str):
    session = TerminalSession.start([sys.executable, "-c", script], Path.cwd(), dict(os.environ))
    reader = threading.Thread(target=session.drain, daemon=True)
    reader.start()
    return session, reader


def test_pty_has_controlling_terminal_and_resizes():
    script = ("import os,sys; print('\\x1b[31mGROUP', os.tcgetpgrp(0), os.getpgrp(), '\\x1b[0m', flush=True); "
              "sys.stdin.readline(); print('SIZE', *os.get_terminal_size(0), flush=True)")
    session, reader = _session(script)
    deadline = time.monotonic() + 3
    page = session.output(0)
    while b"GROUP" not in base64.b64decode(page["data"]) and time.monotonic() < deadline:
        page = session.output(0)
    assert b"\x1b[31mGROUP" in base64.b64decode(page["data"])
    session.resize(42, 119)
    session.input(b"continue\n")
    reader.join(timeout=3)
    assert not reader.is_alive() and session.process.wait() == 0
    assert b"SIZE 119 42" in base64.b64decode(session.output(0)["data"])


def test_output_is_bounded_and_reports_lost_history():
    session, reader = _session("import sys; sys.stdout.write('x'*300000); sys.stdout.flush()")
    reader.join(timeout=3)
    assert not reader.is_alive() and session.process.wait() == 0
    page = session.output(0)
    assert page["truncated"] and page["ended"]
    assert len(base64.b64decode(page["data"])) <= BUFFER_BYTES
