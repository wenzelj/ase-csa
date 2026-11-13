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


def load_summary(work_dir, key: str) -> dict | None:
    """summary() of the stored history; None when there is none or the file cannot be read."""
    try:
        return summary(json.loads(ratings_path(work_dir, key).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _ask(template: str, prompt: str, cwd: Path, timeout_s: int) -> str:
    from csa_docx.reader_pass import argv_for
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as last:
        proc = subprocess.run(argv_for(template, prompt, last.name), cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout_s, stdin=subprocess.DEVNULL)
        return proc.stdout.strip() or Path(last.name).read_text(encoding="utf-8").strip()


def rate(work_dir, sheet, card, key: str, cwd, template: str, timeout_s: int = 600) -> dict:
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
            reply = _ask(template, build_prompt(work_dir, text, ids, error), cwd, timeout_s)
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
    a = ap.parse_args(argv)
    print(json.dumps(rate(a.work_dir, a.sheet, a.card, a.key, a.cwd, a.template, a.timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
