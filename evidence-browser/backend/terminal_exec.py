"""Give an Evidence Browser child its own controlling terminal before exec."""

from __future__ import annotations

import fcntl
import os
import sys
import termios


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit("terminal_exec requires a command")
    os.setsid()
    fcntl.ioctl(sys.stdin.fileno(), termios.TIOCSCTTY, 0)
    os.execvpe(argv[0], argv, os.environ)


if __name__ == "__main__":
    main(sys.argv[1:])
