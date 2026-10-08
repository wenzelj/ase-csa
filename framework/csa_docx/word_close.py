"""Make sure the working DOCX is not open in Word before the framework changes it, and carry on.

Word leaves an owner file beside a document it has open (``~$`` + the name, the first two characters dropped for
long names). Before this module the framework stopped whenever that file was there. Now:

1. No owner file: nothing to do.
2. macOS: ask Word (without starting it) which documents it has open.
   - Word is not running, or it does not have this document open: the owner file is stale (left by a crash or a
     forced quit). It is removed and the run carries on.
   - Word has it open: Word saves and closes that one document (others stay open), the run waits for the owner file
     to go, and carries on. An owner file Word leaves behind after closing is removed.
3. Not macOS (no Word to ask): an owner file older than ``STALE_AFTER`` seconds is treated as stale and removed;
   a fresh one is reported.

    python3 -m csa_docx.word_close <docx> [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

STALE_AFTER = 12 * 3600


def lock_files(docx: Path) -> list[Path]:
    docx = Path(docx)
    names = {f"~${docx.name}"} | ({f"~${docx.name[2:]}"} if len(docx.name) > 2 else set())
    return [docx.with_name(n) for n in sorted(names) if docx.with_name(n).exists()]


def _osascript(script: str, timeout: int = 60) -> tuple[int, str, str]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _word_running() -> bool:
    rc, out, _ = _osascript('application "Microsoft Word" is running')
    return rc == 0 and out.lower() == "true"


def _open_in_word(docx: Path) -> tuple[bool | None, str]:
    """(True/False, "") when Word answered; (None, error) when it could not be asked."""
    script = ('tell application "Microsoft Word"\n'
              '  set out to ""\n'
              '  repeat with d in documents\n'
              '    set out to out & (name of d) & linefeed\n'
              '  end repeat\n'
              '  return out\n'
              'end tell')
    rc, out, err = _osascript(script)
    if rc != 0:
        return None, err
    return docx.name in [x.strip() for x in out.splitlines()], ""


def _remove(locks: list[Path]) -> list[str]:
    gone = []
    for lock in locks:
        try:
            lock.unlink()
            gone.append(lock.name)
        except OSError:
            pass
    return gone


def ensure_closed(docx: Path, wait: float = 30.0) -> dict:
    """{"status": "OK" | "CLOSED" | "STALE_REMOVED" | "LOCKED", "message": ...}. Anything but LOCKED means go on."""
    docx = Path(docx)
    locks = lock_files(docx)
    if not locks:
        return {"status": "OK", "message": ""}
    on_mac = sys.platform == "darwin" and shutil.which("osascript")
    if not on_mac:
        age = time.time() - max(lock.stat().st_mtime for lock in locks)
        if age > STALE_AFTER:
            _remove(locks)
            return {"status": "STALE_REMOVED", "message": f"removed a Word owner file {age / 3600:.0f} h old"}
        return {"status": "LOCKED", "message": f"{docx.name} looks open in Word ({locks[0].name}); this machine cannot ask Word to close it"}
    if not _word_running():
        _remove(locks)
        return {"status": "STALE_REMOVED", "message": "Word is not running; removed the leftover owner file"}
    is_open, err = _open_in_word(docx)
    if is_open is None:
        return {"status": "LOCKED", "message": (f"could not ask Word about {docx.name} ({err[:160]}). Allow your Terminal to control "
                                                 "Microsoft Word: System Settings > Privacy & Security > Automation")}
    if not is_open:
        _remove(lock_files(docx))
        return {"status": "STALE_REMOVED", "message": f"Word does not have {docx.name} open; removed the leftover owner file"}
    name = docx.name.replace('"', '\\"')
    rc, _, err = _osascript('tell application "Microsoft Word"\n'
                            '  repeat with d in (documents)\n'
                            f'    if (name of d) is "{name}" then close d saving yes\n'
                            '  end repeat\n'
                            'end tell', timeout=int(wait) + 30)
    end = time.time() + wait
    while time.time() < end and lock_files(docx):
        still, _ = _open_in_word(docx)
        if still is False:
            break
        time.sleep(0.5)
    still, _ = _open_in_word(docx)
    if still:
        return {"status": "LOCKED", "message": f"Word did not close {docx.name}{': ' + err[:160] if rc else ''} (a dialog may be waiting in Word)"}
    _remove(lock_files(docx))
    return {"status": "CLOSED", "message": f"saved and closed {docx.name} in Word"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = ensure_closed(a.docx)
    print(json.dumps(res) if a.json else f"{res['status']}: {res['message'] or 'not open in Word'}")
    return 0 if res["status"] != "LOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
