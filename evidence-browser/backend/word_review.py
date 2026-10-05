"""S267 — Word approval handoff view and decision state.

Builds a read-only summary of the authoritative document and its sections
for the post-apply approval gate.  Never mutates Word revisions.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import commands, documents as doc_module, pipeline
from .models import WordReview, WordSectionReview


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_document(path: Path) -> dict[str, str]:
    """Open the document in its registered desktop application (local-only)."""
    try:
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"state": "opened"}
    except OSError as error:
        return {"state": "failed", "reason": str(error)}


def _word_lock_info(path: Path) -> dict[str, Any] | None:
    lock = doc_module.word_lock(path)
    if lock is None:
        return None
    stat = lock.stat()
    return {
        "owner": "Microsoft Word",
        "file": lock.name,
        "since": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _gate_path(project: dict[str, str]) -> Path:
    return Path(project["work_dir"]).expanduser() / "word-approval-gate.json"


def _latest_apply(project: dict[str, str]) -> dict[str, Any] | None:
    root = Path(project["work_dir"]).expanduser() / "ui-jobs"
    rows: list[dict[str, Any]] = []
    if root.is_dir():
        for metadata in root.glob("*/metadata.json"):
            try:
                row = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if row.get("operation") == "apply" and row.get("project_key") == project["key"]:
                rows.append(row)
    return max(rows, key=lambda row: str(row.get("finished_at") or row.get("created_at") or ""), default=None)


def _read_gate(project: dict[str, str]) -> dict[str, Any] | None:
    try:
        value = json.loads(_gate_path(project).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_gate(project: dict[str, str], value: dict[str, Any]) -> None:
    path = _gate_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_review(
    agents_dir: Path,
    project: dict[str, str],
    *,
    snapshot_runner: Callable[[str], Any] | None = None,
    document_opener: Callable[[Path], dict[str, str]] | None = None,
    word_lock_check: Callable[[dict[str, str]], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Build the Word approval handoff payload.

    Resolves the authoritative document, its lock state, and per-section
    summary from the pipeline snapshot.  Accepts injectable callables for
    every external dependency so tests can run without a live ``csa`` binary.
    """
    selected = doc_module.resolve(project)
    if selected["state"] != "ready":
        return {**selected, "sections": [], "gate": "blocked",
                "reason": selected.get("reason", "Document unavailable")}

    path: Path = selected["path"]
    stat = path.stat()
    lock_info = word_lock_check(project) if word_lock_check else _word_lock_info(path)

    # Read tracked-change and comment counts from the DOCX itself.
    tracked = {"insertions": 0, "deletions": 0, "total": 0}
    comment_count = 0
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as archive:
            doc_xml = archive.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            tracked["insertions"] = len(root.findall(".//" + W + "ins"))
            tracked["deletions"] = len(root.findall(".//" + W + "del"))
            tracked["total"] = tracked["insertions"] + tracked["deletions"]
            comments_xml = archive.read("word/comments.xml")
            comments_root = ET.fromstring(comments_xml)
            comment_count = len(comments_root.findall(".//" + W + "comment"))
    except (OSError, Exception):
        pass  # zero defaults already set

    # Pipeline state is authoritative in production; a runner remains injectable for tests.
    sections: list[WordSectionReview] = []
    try:
        snap = pipeline.snapshot(agents_dir, project, runner=snapshot_runner)
        for sec in snap.sections:
            has_change = bool(sec.change_file or sec.section_file)
            status = "has_comments" if sec.open_comments > 0 else "pending"
            sections.append(WordSectionReview(
                number=sec.visible_number,
                heading=sec.heading,
                change_count=1 if has_change else 0,
                comment_count=sec.open_comments,
                status=status,
                last_activity=sec.last_activity,
            ))
    except Exception:
        pass  # document-level gate remains available when pipeline inspection fails

    pending = sum(1 for s in sections if s.status == "pending")
    digest = _sha256(path)
    latest_apply = _latest_apply(project)
    apply_job_id = str((latest_apply or {}).get("id") or "")
    apply_output, _ = commands.parse_json_output(str((latest_apply or {}).get("stdout_tail") or ""))
    apply_details = apply_output if isinstance(apply_output, dict) else {}
    gate_record = _read_gate(project)
    if gate_record is None or (apply_job_id and gate_record.get("apply_job_id") != apply_job_id):
        gate_record = {
            "project_key": project["key"], "apply_job_id": apply_job_id or None,
            "document": str(path), "baseline_hash": digest,
            "baseline_mtime_ns": stat.st_mtime_ns, "created_at": _now(),
        }
        _write_gate(project, gate_record)

    gate = "awaiting_word_save"
    reason = "Open the document, inspect every tracked change and comment, then save and close Word."
    if lock_info:
        gate = "word_locked"
        reason = "The document is open in Word. Save and close it before refreshing this gate."
    elif gate_record.get("document") != str(path):
        gate = "blocked"
        reason = "The authoritative document changed. Resolve document selection before review."
    elif gate_record.get("baseline_hash") != digest and stat.st_mtime_ns > int(gate_record.get("baseline_mtime_ns") or 0):
        gate = "ready_for_review"
        reason = "Word is closed and the saved document differs from the post-apply baseline."

    return {
        "gate": gate,
        "authoritative_path": str(path),
        "document": path.name,
        "sha256": digest,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "word_lock": lock_info,
        "tracked_changes": tracked,
        "comment_count": comment_count,
        "section_count": len(sections),
        "pending_count": pending,
        "sections": [s.model_dump() for s in sections],
        "generated_at": _now(),
        "open_handler": {"state": "available"},
        "reason": reason,
        "apply_job_id": apply_job_id or None,
        "baseline_hash": gate_record.get("baseline_hash"),
        "baseline_modified_at": datetime.fromtimestamp(
            int(gate_record.get("baseline_mtime_ns") or stat.st_mtime_ns) / 1_000_000_000, timezone.utc
        ).isoformat(),
        "review_enabled": gate == "ready_for_review",
        "backup_path": apply_details.get("backup"),
        "applied_edit_ids": list(dict.fromkeys([
            *[str(value) for value in (apply_details.get("applied") or [])],
            *[str(value) for value in (apply_details.get("already_applied") or [])],
        ])),
    }


def open_authoritative(
    project: dict[str, str],
    *,
    document_opener: Callable[[Path], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Open the registered authoritative DOCX in its desktop application.

    Never accepts a client-supplied filesystem path — always resolves
    through ``documents.resolve(project)``.
    """
    selected = doc_module.resolve(project)
    if selected["state"] != "ready":
        return {**selected, "state": "blocked"}
    path: Path = selected["path"]
    opener = document_opener or _open_document
    result = opener(path)
    return {"authoritative_path": str(path), **result}


def record_operator_note(
    agents_dir: Path,
    project: dict[str, str],
    note: str,
) -> dict[str, Any]:
    """Persist an optional operator decision note tied to the apply job and
    document hash.  Labelled as an operator record, never proof of Word acceptance."""
    selected = doc_module.resolve(project)
    if selected["state"] != "ready":
        return {**selected, "state": "blocked"}
    path: Path = selected["path"]
    digest = _sha256(path)
    audit_path = Path(project["work_dir"]).expanduser() / "operator-decisions.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    gate = _read_gate(project) or {}
    record = {
        "project": project["key"],
        "document": path.name,
        "sha256": digest,
        "apply_job_id": gate.get("apply_job_id"),
        "note": note,
        "label": "operator_record",
        "recorded_at": _now(),
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return {"state": "recorded", "path": str(audit_path)}


def refresh_gate(
    agents_dir: Path,
    project: dict[str, str],
    *,
    snapshot_runner: Callable[[str], Any] | None = None,
    word_lock_check: Callable[[dict[str, str]], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Re-evaluate the approval gate state after the user has saved and
    closed the document in Word.

    Detects save/close by lock disappearance and document hash/mtime change.
    """
    return build_review(
        agents_dir, project,
        snapshot_runner=snapshot_runner,
        word_lock_check=word_lock_check,
    )


def check_document_integrity(
    project: dict[str, str],
    expected_hash: str | None = None,
) -> dict[str, Any]:
    """Check whether the authoritative document matches the expected hash
    or has been replaced/modified since the apply."""
    selected = doc_module.resolve(project)
    if selected["state"] != "ready":
        return {**selected, "integrity": "blocked"}
    path: Path = selected["path"]
    current = _sha256(path)
    stat = path.stat()
    if expected_hash and current != expected_hash:
        return {"integrity": "modified", "sha256": current,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
    return {"integrity": "unchanged" if expected_hash else "no_baseline",
            "sha256": current,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
