"""The reader pass: after a subsection's answer is written, one model call reads the whole sheet as the customer and reports
contradictions between blocks, terms a customer may not know, repeated wording, claims that go beyond the cited facts and
whether each story answers its question. It never edits the sheet; the report is saved as cards/<KEY>.review.md and added to
the RESULT file. The prompt is prompts/answer/review.md (editable per project like the other answer prompts).

    review(work_dir, sheet, key, cwd, template) -> {"status", "file", "words"}
"""
from __future__ import annotations

import re
import shlex
import subprocess
import tempfile
from pathlib import Path

HEADING = "## Reader review (advisory)"


def build_prompt(work_dir, sheet_text: str) -> str:
    from csa_docx import prompts
    rules, _ = prompts.resolve("review", work_dir)
    return f"{prompts._body(rules)}\n\n--- ANSWER SHEET ---\n{sheet_text.strip()}\n--- END OF ANSWER SHEET ---\n"


def clean(text: str) -> str:
    """The model's reply from its first '## ' heading on (anything before it is chat)."""
    text = (text or "").strip()
    m = re.search(r"(?m)^## ", text)
    return text[m.start():].strip() if m else text


def argv_for(template: str, prompt: str, last: str) -> list[str]:
    return [prompt if t == "{prompt}" else last if t == "{last}" else t for t in shlex.split(template)]


def append_to_result(result: Path, review: str) -> None:
    result = Path(result)
    if not result.is_file():
        return
    body = result.read_text(encoding="utf-8")
    body = body.split("\n" + HEADING)[0].rstrip("\n")           # a second run replaces the first review
    result.write_text(body + "\n\n" + HEADING + "\n\n" + review.strip()[:6000] + "\n", encoding="utf-8")


def review(work_dir, sheet, key: str, cwd, template: str, timeout_s: int = 600, show=None) -> dict:
    """``show`` is a stream (the terminal) that gets the call's output while it runs; None keeps it quiet."""
    from csa_docx import live_call
    sheet, cwd = Path(sheet), Path(cwd)
    if not sheet.is_file():
        return {"status": "SKIPPED", "message": f"no sheet at {sheet}"}
    prompt = build_prompt(work_dir, sheet.read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as last:
        argv = argv_for(template, prompt, last.name)
        try:
            rc, out, err = live_call.run(argv, cwd, timeout_s, show=show, label="reader pass")
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"status": "ERROR", "message": f"{type(e).__name__}: {e}"}
        text = out.strip() or Path(last.name).read_text(encoding="utf-8").strip()
    # A CLI that could not make the call (usage limit, no login, a crash) still prints something. That is not a review:
    # nothing is saved, and a review kept from an earlier run stays as it is.
    problem = live_call.failure_notice(rc, text, err)
    if problem:
        return {"status": "ERROR", "message": problem}
    text = clean(text)
    if not text:
        return {"status": "ERROR", "message": (err or "no reply")[-300:]}
    out = cwd / f"{key}.review.md"
    out.write_text(text + "\n", encoding="utf-8")
    append_to_result(cwd / f"{key}.RESULT.md", text)
    return {"status": "OK", "file": str(out), "words": len(text.split())}


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["review"])
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--show", action="store_true", help="copy the call's output to stderr while it runs")
    a = ap.parse_args(argv)
    import sys
    print(json.dumps(review(a.work_dir, a.sheet, a.key, a.cwd, a.template, a.timeout, show=sys.stderr if a.show else None),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
