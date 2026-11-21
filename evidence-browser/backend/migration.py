"""Status and safety gates for old-assessment migration in Evidence Browser."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _work(project: dict[str, str]) -> Path:
    return Path(project["project_root"]).expanduser().resolve() / "csa-work"


def status(project: dict[str, str]) -> dict[str, Any]:
    root = Path(project["project_root"]).expanduser().resolve()
    legacy = Path(project.get("legacy_docx") or "").expanduser()
    working = Path(project.get("working_docx") or "").expanduser()
    map_file = _work(project) / "legacy" / "map.csv"
    rows: list[dict[str, str]] = []
    if map_file.is_file():
        try:
            with map_file.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, csv.Error):
            rows = []
    mapped = sum(1 for row in rows if row.get("target") and row.get("job") in {"convert", "context", "mine"})
    unmapped = sum(1 for row in rows if not row.get("target") and row.get("job") in {"convert", "mine"})
    report = map_file.with_name("map-report.md")
    prepared = map_file.is_file() and report.is_file() and mapped > 0
    return {"status": "READY", "prepared": prepared, "can_migrate": prepared,
            "mapped": mapped, "unmapped": unmapped, "blocks": len(rows),
            "legacy_docx": str(legacy) if legacy else "", "working_docx": str(working) if working else "",
            "legacy_exists": legacy.is_file() and (not root or root in legacy.parents),
            "working_exists": working.is_file(), "map_report": str(report) if report.is_file() else ""}


def can_do(project: dict[str, str]) -> tuple[bool, str]:
    current = status(project)
    if not current["prepared"]:
        return False, "Prepare the old assessment migration successfully before running it."
    return True, ""
