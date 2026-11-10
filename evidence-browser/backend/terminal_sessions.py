"""Bounded, in-memory PTY transport for interactive browser jobs."""

from __future__ import annotations

import base64
import errno
import fcntl
import os
import pty
import secrets
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException


BUFFER_BYTES = 256 * 1024
PAGE_BYTES = 32 * 1024
INPUT_BYTES = 4096


def check_write_origin(origin: str | None, host: str | None) -> None:
    """A browser terminal can only be driven by its own loopback page."""
    if not origin or not host:
        raise HTTPException(403, "Terminal input requires a same-origin browser request")
    parsed = urlsplit(origin)
    hostname = (urlsplit(f"http://{host}").hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower() or \
            hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "Terminal input requires a same-origin loopback page")


class TerminalSession:
    def __init__(self, master: int, process: subprocess.Popen, *, rows: int = 30, cols: int = 100) -> None:
        self.master = master
        self.process = process
        self.capability = secrets.token_urlsafe(32)
        self._buffer = bytearray()
        self._base = 0
        self._ended = False
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self.resize(rows, cols)

    @classmethod
    def start(cls, argv: list[str], cwd: Path, env: dict[str, str]) -> "TerminalSession":
        master, slave = pty.openpty()
        try:
            worker_env = dict(env, TERM="xterm-256color", COLUMNS="100", LINES="30")
            command = [sys.executable, str(Path(__file__).with_name("terminal_exec.py")), *argv]
            process = subprocess.Popen(command, cwd=str(cwd), env=worker_env, shell=False,
                                       stdin=slave, stdout=slave, stderr=slave,
                                       close_fds=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        return cls(master, process)

    def drain(self) -> None:
        try:
            while True:
                ready, _, _ = select.select([self.master], [], [], .2)
                if ready:
                    try:
                        chunk = os.read(self.master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if not chunk:
                        break
                    with self._condition:
                        self._buffer.extend(chunk)
                        if len(self._buffer) > BUFFER_BYTES:
                            lost = len(self._buffer) - BUFFER_BYTES
                            del self._buffer[:lost]
                            self._base += lost
                        self._condition.notify_all()
                elif self.process.poll() is not None:
                    # A final read will return remaining output or EOF.
                    continue
        finally:
            with self._condition:
                self._ended = True
                self._condition.notify_all()
            os.close(self.master)

    def output(self, after: int, *, wait: float = .5) -> dict:
        if after < 0:
            raise HTTPException(422, "Terminal offset must be non-negative")
        with self._condition:
            if after >= self._base + len(self._buffer) and not self._ended:
                self._condition.wait(wait)
            truncated = after < self._base
            start = min(max(after, self._base), self._base + len(self._buffer))
            end = min(self._base + len(self._buffer), start + PAGE_BYTES)
            chunk = bytes(self._buffer[start - self._base:end - self._base])
            return {"data": base64.b64encode(chunk).decode("ascii"), "offset": end,
                    "truncated": truncated, "ended": self._ended,
                    "capability": self.capability}

    def snapshot(self) -> bytes:
        with self._condition:
            return bytes(self._buffer)

    def input(self, data: bytes) -> None:
        if not data or len(data) > INPUT_BYTES:
            raise HTTPException(422, "Terminal input must be 1–4096 bytes")
        with self._write_lock:
            if self._ended or self.process.poll() is not None:
                raise HTTPException(409, "Terminal job has ended")
            try:
                remaining = memoryview(data)
                while remaining:
                    remaining = remaining[os.write(self.master, remaining):]
            except OSError as error:
                raise HTTPException(409, "Terminal job has ended") from error

    def resize(self, rows: int, cols: int) -> None:
        if not 10 <= rows <= 200 or not 20 <= cols <= 400:
            raise HTTPException(422, "Terminal size is out of range")
        if self._ended:
            raise HTTPException(409, "Terminal job has ended")
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError as error:
            raise HTTPException(409, "Terminal job has ended") from error
        try:
            os.killpg(self.process.pid, signal.SIGWINCH)
        except ProcessLookupError:
            pass

