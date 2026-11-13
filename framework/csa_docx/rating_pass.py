"""The rating pass: after a subsection's answer is written, one model call scores each answer block 1 to 10 for quality. The
scores are kept per subsection in <work_dir>/ratings/<KEY>.json (the last RUNS_KEPT runs, newest last) and shown on the Draft
answers page. It never edits the sheet. The prompt is prompts/answer/rating.md (editable per project like the other prompts).

    rate(work_dir, sheet, card, key, cwd, template) -> {"status", "file", "average"}
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RUNS_KEPT = 3
WORSE_BY = 0.5          # a block is "worse" when its score fell by at least this much since the previous run


def ratings_path(work_dir, key: str) -> Path:
    return Path(work_dir) / "ratings" / f"{key}.json"


def rated_blocks(sheet: dict, card: dict) -> list[str]:
    """Ids of the card's questions the sheet answers with prose, facts or rows (an empty block is not scored)."""
    ids = []
    for q in card.get("questions", []):
        b = sheet.get(q["id"]) or {}
        if any(b.get(k) for k in ("summary", "story", "text", "facts", "rows", "bullets")):
            ids.append(q["id"])
    return ids


def build_prompt(work_dir, sheet_text: str, ids: list[str], error: str = "") -> str:
    from csa_docx import prompts
    rules, _ = prompts.resolve("rating", work_dir)
    tail = f"\nBlock ids to score: {', '.join(ids)}\n"
    if error:
        tail += f"\nYour last reply was rejected: {error}. Reply with the JSON only.\n"
    return f"{prompts._body(rules)}\n\n--- ANSWER SHEET ---\n{sheet_text.strip()}\n--- END OF ANSWER SHEET ---\n{tail}"


def parse_reply(text: str, ids: list[str]) -> tuple[dict | None, str]:
    """The model's JSON, checked: every id present, score a number from 1 to 10 (rounded to one decimal), a short reason."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None, "no JSON object found"
    try:
        raw = json.loads(m.group(0))
    except ValueError as e:
        return None, f"invalid JSON ({e})"
    out: dict[str, dict] = {}
    for i in ids:
        v = raw.get(i)
        score = v.get("score") if isinstance(v, dict) else None
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 1 <= score <= 10:
            return None, f"{i} needs a score from 1 to 10"
        tips = v.get("improve") if isinstance(v.get("improve"), list) else []
        out[i] = {"score": round(float(score), 1), "reason": " ".join(str(v.get("reason", "")).split())[:240],
                  "improve": [" ".join(str(t).split())[:300] for t in tips if str(t).strip()][:3]}
    return out, ""


def record(work_dir, key: str, blocks: dict[str, dict], model: str = "", sheet_sha256: str = "", at: str = "") -> dict:
    """Append this run to the subsection's history (newest last, RUNS_KEPT kept). Atomic write."""
    path = ratings_path(work_dir, key)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError:
        data = {}
    runs = list(data.get("runs") or [])
    avg = round(sum(b["score"] for b in blocks.values()) / len(blocks), 1)
    runs.append({"at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model,
                 "sheet_sha256": sheet_sha256, "average": avg, "blocks": blocks})
    data = {"key": key, "runs": runs[-RUNS_KEPT:]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return data


def summary(data: dict | None) -> dict | None:
    """What the Draft answers page shows: latest average, average of the kept runs, per-run scores, blocks that got worse."""
    runs = (data or {}).get("runs") or []
    if not runs:
        return None
    latest, prev = runs[-1], (runs[-2] if len(runs) > 1 else None)
    worse = [b for b, v in latest["blocks"].items()
             if prev and b in prev["blocks"] and prev["blocks"][b]["score"] - v["score"] >= WORSE_BY]
    return {"latest": latest["average"], "average": round(sum(r["average"] for r in runs) / len(runs), 1),
            "worse": worse, "runs": [{"at": r["at"], "average": r["average"],
                                      "blocks": {b: v["score"] for b, v in r["blocks"].items()}} for r in runs],
            "reasons": {b: v.get("reason", "") for b, v in latest["blocks"].items()},
            "improve": {b: v.get("improve", []) for b, v in latest["blocks"].items() if v.get("improve")}}


def _result_summary(work_dir, key: str) -> dict | None:
    """Recover a rating from the current workspace when JSON history was not migrated.

    This is deliberately scoped to ``work_dir/cards/<key>.RESULT.md``.
    """
    result = Path(work_dir) / "cards" / f"{key}.RESULT.md"
    if not result.is_file():
        return None
    text = result.read_text(encoding="utf-8", errors="replace")
    section = text.split(HEADING, 1)[1] if HEADING in text else ""
    match = re.search(r"Average\s+([0-9]+(?:\.[0-9]+)?)\s*\(([^)]*)\)", section)
    if not match:
        return None
    blocks: dict[str, dict] = {}
    for item in match.group(2).split(","):
        part = re.match(r"\s*([BC]\d+)\s+([0-9]+(?:\.[0-9]+)?)\s*$", item)
        if part:
            blocks[part.group(1)] = {"score": float(part.group(2)), "reason": "", "improve": []}
    if not blocks:
        return None
    worse_match = re.search(r"Lower than the previous run:\s*([^\.]+)\.", section)
    worse = [x.strip() for x in worse_match.group(1).split(",")] if worse_match else []
    at = datetime.fromtimestamp(result.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = summary({"key": key, "runs": [{"at": at, "average": float(match.group(1)), "blocks": blocks}]})
    if out is not None:
        out["worse"] = worse
    return out


def _matching_legacy_summary(work_dir, key: str) -> dict | None:
    """Use same-application legacy history only when its sheet hash matches V2 exactly."""
    sheet = Path(work_dir) / "cards" / f"{key}.answer.md"
    legacy = Path(work_dir).parent / "csa-work" / "ratings" / f"{key}.json"
    if not sheet.is_file() or not legacy.is_file():
        return None
    digest = hashlib.sha256(sheet.read_bytes()).hexdigest()
    data = json.loads(legacy.read_text(encoding="utf-8"))
    runs = [run for run in data.get("runs", []) if run.get("sheet_sha256") == digest]
    return summary({"key": key, "runs": runs}) if runs else None


def load_summary(work_dir, key: str) -> dict | None:
    """Summary of current history, migrated RESULT data, or hash-safe same-app legacy history."""
    try:
        path = ratings_path(work_dir, key)
        if path.is_file():
            return summary(json.loads(path.read_text(encoding="utf-8")))
        return _result_summary(work_dir, key) or _matching_legacy_summary(work_dir, key)
    except (OSError, ValueError, KeyError, TypeError):
        return None


class CallFailed(Exception):
    """The CLI could not make the model call (usage limit, no login, a crash): asking again would fail the same way."""


def _ask(template: str, prompt: str, cwd: Path, timeout_s: int, show=None) -> str:
    from csa_docx import live_call
    from csa_docx.reader_pass import argv_for
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as last:
        rc, out, err = live_call.run(argv_for(template, prompt, last.name), cwd, timeout_s, show=show, label="rating pass")
        reply = out.strip() or Path(last.name).read_text(encoding="utf-8").strip()
    problem = live_call.failure_notice(rc, reply, err)
    if problem:
        raise CallFailed(problem)
    return reply


def rate(work_dir, sheet, card, key: str, cwd, template: str, timeout_s: int = 600, show=None) -> dict:
    """``show`` is a stream (the terminal) that gets the call's output while it runs; None keeps it quiet."""
    from csa_docx import answer_sheet
    sheet, cwd = Path(sheet), Path(cwd)
    if not sheet.is_file():
        return {"status": "SKIPPED", "message": f"no sheet at {sheet}"}
    text = sheet.read_text(encoding="utf-8")
    ids = rated_blocks(answer_sheet.parse(text), json.loads(Path(card).read_text(encoding="utf-8")))
    if not ids:
        return {"status": "SKIPPED", "message": "no answered block to rate"}
    error = ""
    for _ in range(2):                                  # one retry with the reason the first reply was rejected
        try:
            reply = _ask(template, build_prompt(work_dir, text, ids, error), cwd, timeout_s, show=show)
        except CallFailed as e:
            return {"status": "ERROR", "message": str(e)}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"status": "ERROR", "message": f"{type(e).__name__}: {e}"}
        blocks, error = parse_reply(reply, ids)
        if blocks:
            data = record(work_dir, key, blocks, sheet_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
            run = data["runs"][-1]
            _append_to_result(cwd / f"{key}.RESULT.md", run, summary(data))
            return {"status": "OK", "file": str(ratings_path(work_dir, key)), "average": run["average"]}
    return {"status": "ERROR", "message": error}


HEADING = "## Answer rating"


def _append_to_result(result: Path, run: dict, s: dict | None) -> None:
    if not result.is_file():
        return
    body = result.read_text(encoding="utf-8").split("\n" + HEADING)[0].rstrip("\n")
    line = ", ".join(f"{b} {v['score']}" for b, v in run["blocks"].items())
    worse = f" Lower than the previous run: {', '.join(s['worse'])}." if s and s["worse"] else ""
    tips = "".join(f"\n- {b}: {t}" for b, v in run["blocks"].items() for t in v.get("improve", []))
    result.write_text(f"{body}\n\n{HEADING}\n\nAverage {run['average']} ({line}).{worse}"
                      + (f"\n\nSuggested improvements (advisory):{tips}" if tips else "") + "\n", encoding="utf-8")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["rate"])
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--card", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--show", action="store_true", help="copy the call's output to stderr while it runs")
    a = ap.parse_args(argv)
    import sys
    print(json.dumps(rate(a.work_dir, a.sheet, a.card, a.key, a.cwd, a.template, a.timeout,
                          show=sys.stderr if a.show else None), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
