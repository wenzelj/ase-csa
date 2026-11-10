"""Open a tracked CSA command in macOS Terminal and wait for its exit status."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


def write_command(job_dir: Path, cwd: Path, argv: list[str]) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    script = job_dir / "claude-intake.command"
    pid = job_dir / "terminal.pid"
    status = job_dir / "terminal.exit"
    temporary = job_dir / "terminal.exit.tmp"
    script.write_text(
        "#!/bin/zsh\n"
        f"cd {shlex.quote(str(cwd))} || exit 1\n"
        f"printf '%s\\n' \"$$\" > {shlex.quote(str(pid))}\n"
        f"{shlex.join(argv)}\n"
        "result=$?\n"
        f"printf '%s\\n' \"$result\" > {shlex.quote(str(temporary))}\n"
        f"mv {shlex.quote(str(temporary))} {shlex.quote(str(status))}\n"
        "printf '\\nCSA evidence intake finished (exit %s). Press Return to close this window.\\n' \"$result\"\n"
        "read -r\n"
        "exit \"$result\"\n", encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def wait_for_exit(job_dir: Path, startup_seconds: float = 60) -> int:
    status = job_dir / "terminal.exit"
    pid_file = job_dir / "terminal.pid"
    deadline = time.monotonic() + startup_seconds
    while True:
        if status.is_file():
            try:
                return int(status.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                print("Claude window wrote an invalid exit status.", file=sys.stderr, flush=True)
                return 1
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8").strip()), 0)
            except ProcessLookupError:
                print("Claude window closed before evidence intake finished.", file=sys.stderr, flush=True)
                return 1
            except (OSError, ValueError):
                pass
        elif time.monotonic() >= deadline:
            print("Terminal did not start the Claude intake within 60 seconds.", file=sys.stderr, flush=True)
            return 1
        time.sleep(0.5)


def main(args: list[str]) -> int:
    if sys.platform != "darwin":
        print("Claude window mode requires macOS Terminal.", file=sys.stderr)
        return 1
    if len(args) < 3:
        print("usage: window_job.py JOB_DIR WORKSPACE CSA_COMMAND...", file=sys.stderr)
        return 2
    job_dir, cwd = Path(args[0]), Path(args[1])
    script = write_command(job_dir, cwd, args[2:])
    try:
        opened = subprocess.run(["/usr/bin/open", "-a", "Terminal", str(script)],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Could not open Terminal: {error}", file=sys.stderr, flush=True)
        return 1
    if opened.returncode:
        print(opened.stderr.strip() or "Terminal could not open the Claude intake window.",
              file=sys.stderr, flush=True)
        return opened.returncode
    print("Claude evidence intake opened in Terminal. Follow progress and answer prompts there.", flush=True)
    result = wait_for_exit(job_dir)
    print(f"Claude evidence intake finished (exit {result}).", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
