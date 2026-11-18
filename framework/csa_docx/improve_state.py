"""Persistence helpers for the standalone CSA Improve lane.

Improve state lives below ``csa-work/improve`` and never reads or writes the
Draft lane's ``runs.json``.  The helpers are intentionally small and JSON based
so the Browser and CLI can share the same records.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .improve_contract import RUN_OUTCOMES, VERSION


STATE_VERSION = 1
ROOT_NAME = "improve"


def improve_root(work_dir: Path | str) -> Path:
    path = Path(work_dir)
    return path / ROOT_NAME if path.name == "csa-work" else path / "csa-work" / ROOT_NAME


def _root(path: Path | str) -> Path:
    return Path(path)


def runs_path(root: Path | str) -> Path:
    return _root(root) / "runs.json"


def section_dir(root: Path | str, section: str) -> Path:
    return _root(root) / section


def proposal_path(root: Path | str, section: str) -> Path:
    return section_dir(root, section) / "proposal.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run(section_key: str, *, context_hash: str | None = None, base_document_hash: str | None = None) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "contract_version": VERSION,
        "run_id": f"improve-{uuid4().hex}",
        "section_key": section_key,
        "status": "created",
        "created_at": _now(),
        "updated_at": _now(),
        "context_hash": context_hash,
        "base_document_hash": base_document_hash,
        "proposal_hash": None,
        "document_hash": None,
        "error": None,
    }


def validate_run(value: Mapping[str, Any]) -> tuple[str, ...]:
    errors = []
    if value.get("version") != STATE_VERSION:
        errors.append("unsupported Improve state version")
    if not isinstance(value.get("run_id"), str) or not value["run_id"].strip():
        errors.append("run_id is required")
    if not isinstance(value.get("section_key"), str) or not value["section_key"].strip():
        errors.append("section_key is required")
    if value.get("status") not in {"created", "context_built", "proposing", *RUN_OUTCOMES}:
        errors.append("unsupported Improve run status")
    return tuple(errors)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
    except (OSError, ValueError):
        return default


def read_runs(root: Path | str) -> list[dict[str, Any]]:
    data = _read_json(runs_path(root), {})
    rows = data.get("runs", []) if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def write_run(root: Path | str, run: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_run(run)
    if errors:
        raise ValueError("invalid Improve run: " + "; ".join(errors))
    target = runs_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = dict(run)
    row["updated_at"] = _now()
    rows = [item for item in read_runs(root) if item.get("run_id") != row["run_id"]]
    rows.append(row)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"version": STATE_VERSION, "runs": rows}, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    return row


def latest_run(root: Path | str, section_key: str) -> dict[str, Any] | None:
    rows = [row for row in read_runs(root) if row.get("section_key") == section_key]
    return rows[-1] if rows else None


def write_proposal(root: Path | str, section_key: str, proposal: Mapping[str, Any]) -> Path:
    target = proposal_path(root, section_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(dict(proposal), indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    return target


def read_proposal(root: Path | str, section_key: str) -> dict[str, Any] | None:
    value = _read_json(proposal_path(root, section_key), None)
    return value if isinstance(value, dict) else None


def proposal_hash(proposal: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(proposal), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def repeated_proposal(root: Path | str, section_key: str, proposal: Mapping[str, Any]) -> bool:
    digest = proposal_hash(proposal)
    return any(row.get("section_key") == section_key and row.get("proposal_hash") == digest
               # The current pending proposal is the one the user is being
               # asked to apply.  Treating ``proposed`` as a repeat blocked
               # every first Apply from the Evidence Browser.  Once it has
               # been applied (or otherwise closed), the same proposal must
               # not be applied again.
               and row.get("status") in {"applied", "checked", "discarded", "stale"}
               for row in read_runs(root))
