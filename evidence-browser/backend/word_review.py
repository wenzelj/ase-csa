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
from types import SimpleNamespace
from typing import Any, Callable

from . import documents as doc_module, pipeline
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
        "owner": lock.name[2:],  # strip ~$ prefix
        "since": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


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

    # Try to get per-section detail from the pipeline if a runner is available.
    sections: list[WordSectionReview] = []
    if snapshot_runner is not None:
        try:
            snap = pipeline.snapshot(agents_dir, project, runner=snapshot_runner)
            for sec in snap.sections:
                has_change = bool(sec.change_file)
                if has_change and (sec.applied_state == "complete" or sec.validation_result == "valid"):
                    status = "decided"
                elif sec.open_comments > 0:
                    status = "has_comments"
                else:
                    status = "pending"
                sections.append(WordSectionReview(
                    number=sec.visible_number,
                    heading=sec.heading,
                    change_count=1 if has_change else 0,
                    comment_count=sec.open_comments,
                    status=status,
                    last_activity=sec.last_activity,
                ))
        except Exception:
            pass  # sections stay empty; gate still works from document-level data

    pending = sum(1 for s in sections if s.status == "pending")
    gate = "approval"
    if lock_info:
        gate = "word_locked"
    elif not sections:
        gate = "awaiting_first_decision"

    return {
        "gate": gate,
        "authoritative_path": str(path),
        "sha256": _sha256(path),
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
    record = {
        "project": project["key"],
        "document": path.name,
        "sha256": digest,
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
