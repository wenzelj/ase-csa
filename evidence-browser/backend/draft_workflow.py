"""Draft lane page (before V1): what is answered, what is stale, today's changes and the open questions.

Read-only snapshot. The actions (ingest, stale check, answer, refresh, freeze) run as ordinary jobs through
`commands.OPERATIONS`, so they use the same job runner, locks and audit trail as every other operation.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import commands
from .models import CommandRequest

SKIP_KINDS = {"container", "reference", "controlled"}
_BLOCK = re.compile(r"^##\s+([BC]\d+)\b", re.M)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _unknowns(sheet: Path) -> int:
    if not sheet.is_file():
        return 0
    return sum(1 for line in sheet.read_text(encoding="utf-8").splitlines() if line.strip().lower().startswith("unknown:"))


def _changes(work: Path) -> dict[str, Any]:
    logs = sorted((work / "draft").glob("changes-*.md"))
    rows: list[dict[str, str]] = []
    for log in reversed(logs[-7:]):
        day = log.stem.replace("changes-", "")
        for line in reversed(log.read_text(encoding="utf-8").splitlines()):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 4 and re.fullmatch(r"\d{2}:\d{2}", cells[0]):
                rows.append({"day": day, "time": cells[0], "subsection": cells[1], "change": cells[2], "open": cells[3]})
    return {"rows": rows[:60], "file": str(logs[-1]) if logs else None}


def _open_questions(work: Path) -> dict[str, Any]:
    path = work / "draft" / "open-questions.md"
    groups: list[dict[str, Any]] = []
    if path.is_file():
        current: dict[str, Any] | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                current = {"title": line[3:].strip(), "items": []}
                groups.append(current)
            elif current is not None and line.startswith("- "):
                current["items"].append(line[2:].strip())
    return {"groups": groups, "total": sum(len(g["items"]) for g in groups), "file": str(path) if path.is_file() else None}


def snapshot(agents_dir: Path, project: dict[str, str]) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    cards = work / "cards"
    stage = str(project.get("stage") or "draft").strip().lower()
    stale_file = work / "draft" / "stale.json"
    stale: dict[str, str] = {}
    checked_at = None
    checked_ts = 0.0
    if stale_file.is_file():
        try:
            data = json.loads(stale_file.read_text(encoding="utf-8"))
            stale = {row["key"]: row.get("status", "") for row in data.get("sections", [])}
            checked_at = data.get("checked_at")
            checked_ts = stale_file.stat().st_mtime
        except (OSError, ValueError, KeyError):
            pass
    spec = commands.execute(agents_dir, project, "spec_status", CommandRequest())
    nodes = spec.parsed.get("nodes", []) if isinstance(spec.parsed, dict) else []
    sections: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("kind") in SKIP_KINDS or not node.get("key"):
            continue
        key = node["key"]
        manifest = cards / f"{key}.manifest.json"
        row: dict[str, Any] = {"number": node.get("number") or "", "key": key, "title": node.get("title") or "",
                               "kind": node.get("kind") or "", "level": node.get("level") or 2,
                               "document_state": (node.get("status") or {}).get("state", "")}
        if manifest.is_file():
            answered = manifest.stat().st_mtime
            status = stale.get(key, "")
            if answered >= checked_ts or status == "REUSE":
                state = "current" if checked_ts else "answered"
            elif status in ("PARTIAL", "STALE", "NONE"):
                state = "stale"
            else:
                state = "answered"
            row.update(state=state, answered_at=_iso(answered), open=_unknowns(cards / f"{key}.answer.md"))
        else:
            row.update(state="not-answered", answered_at=None, open=0)
        sections.append(row)
    if not sections:   # no document spec: list what was answered
        for manifest in sorted(cards.glob("*.manifest.json")) if cards.is_dir() else []:
            key = manifest.name[: -len(".manifest.json")]
            card = cards / f"{key}.json"
            info = json.loads(card.read_text(encoding="utf-8")) if card.is_file() else {}
            sections.append({"number": info.get("number", ""), "key": key, "title": info.get("title", key), "kind": "",
                             "level": 2, "document_state": "", "state": "answered",
                             "answered_at": _iso(manifest.stat().st_mtime), "open": _unknowns(cards / f"{key}.answer.md")})
    counts: dict[str, int] = {}
    for row in sections:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return {"project_key": project["key"], "stage": stage, "stale_checked_at": checked_at, "counts": counts,
            "sections": sections, "changes": _changes(work), "open_questions": _open_questions(work),
            "spec_error": None if nodes else (spec.stderr or "the document specification is unavailable")[-400:]}
