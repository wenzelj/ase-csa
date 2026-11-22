"""Shared section readiness projection for Draft and Improve consumers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def project(work_dir: Path | str, key: str, *, legacy_state: str | None = None) -> dict[str, Any]:
    """Return one additive state projection without changing legacy fields."""
    cards = Path(work_dir) / "cards"
    imported = _read(cards / f"{key}.IMPORT.json")
    manifest = _read(cards / f"{key}.manifest.json")
    if imported:
        state = str(imported.get("state") or "not-answered")
        outcome = str(imported.get("outcome") or "")
        provenance = imported.get("provenance") or {}
        rating = imported.get("rating") or {}
        reasons = [str(reason) for reason in imported.get("warnings") or []]
        reasons.extend(str(reason) for reason in imported.get("unmappable") or [])
        if outcome == "PARTIAL" or imported.get("unmappable"):
            reasons.append("incomplete import")
        if outcome == "SOURCE_CHANGED" or state == "stale":
            reasons.append("changed document")
        if (rating.get("assessment_status") or "unresolved") != "resolved":
            reasons.append("missing assessment rating")
        if (rating.get("quality_status") or "unrated") != "rated":
            reasons.append("answer quality is unrated")
        eligible = state == "ready-for-improve" and outcome in {"READY", "UNCHANGED", ""}
        return {
            "state": "ready-for-improve" if eligible else state,
            "draft_state": "answered-imported" if state != "not-answered" else "not-answered",
            "eligible_for_improve": eligible,
            "provenance": provenance.get("label", "document-imported baseline"),
            "rating": rating,
            "rating_status": {
                "assessment_status": rating.get("assessment_status", "unresolved"),
                "quality_status": rating.get("quality_status", "unrated"),
                "quality_error": rating.get("quality_error"),
            },
            "readiness_reasons": list(dict.fromkeys(reasons)),
            "warnings": imported.get("warnings") or [],
            "source_document_hash": provenance.get("source_document_hash"),
        }
    if manifest:
        return {"state": "answered", "draft_state": "answered", "eligible_for_improve": True,
                "provenance": "recorded", "rating": {}, "rating_status": {},
                "readiness_reasons": [], "warnings": []}
    if legacy_state and legacy_state != "not-answered":
        return {"state": legacy_state, "draft_state": legacy_state, "eligible_for_improve": True,
                "provenance": "recorded", "rating": {}, "rating_status": {},
                "readiness_reasons": [], "warnings": []}
    return {"state": "not-answered", "draft_state": "not-answered", "eligible_for_improve": False,
            "provenance": "none", "rating": {}, "rating_status": {},
            "readiness_reasons": [], "warnings": []}
