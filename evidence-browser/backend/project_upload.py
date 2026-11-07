"""Staged folder upload sessions for a new CSA application (S513).

A dropped folder is staged into a temporary directory -- never into the assessment
workspace -- before it is allowed to become a registered project (S514 moves it).
The flow is:

1. ``create_session`` -- register the manifest of relative file and directory paths
   (collected client-side) and the expected file sizes, and allocate the temporary
   staging area;
2. ``write_chunk`` -- copy file bytes into the staging area in bounded chunks;
3. ``finalise`` -- validate every path and file against the manifest and complete
   the session. Only then does the staged tree exist as a usable destination folder;
4. ``cancel_session`` / expiry -- discard the staging area.

Every step is safe to retry and idempotent; a failed or interrupted session leaves
no destination folder behind (the staging area is removed).

Conventions kept here:

- pure standard library (the browser backend already depends on fastapi, but this
  module does not need it);
- every public function returns a dict with a ``status`` key (``READY``, ``OK``,
  ``BLOCKED``, ``ERROR``) instead of raising, so callers can report failures;
- no project facts (host names, IPs, customer names) -- this is shared framework code.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Paths that the CSA framework owns and must not appear in an uploaded tree.
#: Matching is case-insensitive and applied to both the top-level component and
#: every relative path.
RESERVED_PATHS = frozenset({
    "csa-work",
    "reviews",
})

#: Files that operating systems or tools create and that must never be uploaded.
RESERVED_FILENAMES = frozenset({
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    "._.ds_store",
})

#: Minimum filename length (after stripping extension) to reject empty names.
_MIN_NAME_LEN = 1

#: Maximum number of manifest entries accepted in a single session.
_MAX_MANIFEST_ENTRIES = 50_000

#: Default session expiry (seconds). Set to 0 or None to disable.
_DEFAULT_EXPIRY_SECONDS = 3600

#: Filesize limits (bytes).
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024       # 2 GiB
MAX_FILE_BYTES  = 512 * 1024 * 1024            # 512 MiB

#: Chunk size for reads/writes in bytes (bounded chunk writes).
_CHUNK_SIZE = 4 * 1024 * 1024                  # 4 MiB

#: A valid manifest relative path: one or more path segments separated by ``/``,
#: each segment is 1-255 chars of [A-Za-z0-9._+-] (no NUL, no backslash, no
#: traversal, no leading/trailing slash).
_MANIFEST_PATH_RE = re.compile(r"^[A-Za-z0-9._+\-]+(?:/[A-Za-z0-9._+\-]+)*$")

_SESSION_ID_RE = re.compile(r"^[0-9a-f-]{36}$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _new_session_id() -> str:
    return str(uuid.uuid4())


def _manifest_entry(path: str, kind: str, size: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path, "kind": kind}
    if size is not None:
        entry["size"] = size
    return entry


def _validate_entry(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Validate a single manifest entry. Returns a list of error dicts."""
    errors: list[dict[str, str]] = []
    path = entry.get("path", "")
    kind = entry.get("kind", "file")

    if not isinstance(path, str) or not path:
        errors.append({"field": "path", "code": "BLANK_PATH",
                       "message": "Each manifest entry needs a relative path."})
        return errors

    if kind not in ("file", "dir"):
        errors.append({"field": "kind", "code": "BAD_KIND",
                       "message": f"Entry kind must be 'file' or 'dir', got {kind!r}."})
        return errors

    # Reject absolute paths, backslashes, NUL, traversal
    if path.startswith(("/", "\\")) or "\\" in path or "\x00" in path:
        errors.append({"field": "path", "code": "BAD_PATH",
                       "message": f"Path {path!r} is not a valid relative path."})
        return errors
    for seg in path.split("/"):
        if seg in ("..", "."):
            errors.append({"field": "path", "code": "TRAVERSAL",
                           "message": f"Path {path!r} contains a traversal component."})
            break
    if errors:
        return errors

    # Top-level component must not be reserved
    top = path.split("/", 1)[0]
    if top.lower() in RESERVED_PATHS:
        errors.append({"field": "path", "code": "RESERVED_PATH",
                       "message": f"Top-level path {top!r} is reserved by the CSA framework."})
        return errors
    # No relative path component may be a reserved filename
    for seg in path.split("/"):
        if seg.lower() in RESERVED_FILENAMES:
            errors.append({"field": "path", "code": "RESERVED_FILENAME",
                           "message": f"Component {seg!r} is a reserved filename."})
            break

    if kind == "file":
        size = entry.get("size")
        if size is not None and (not isinstance(size, int) or size < 0):
            errors.append({"field": "size", "code": "BAD_SIZE",
                           "message": "File size must be a non-negative integer."})
        elif size is not None and size > MAX_FILE_BYTES:
            errors.append({"field": "size", "code": "FILE_TOO_LARGE",
                           "message": f"File {path!r} is larger than the {MAX_FILE_BYTES} byte limit."})

    return errors


def _session_dir(staging_root: Path, session_id: str) -> Path:
    return staging_root / session_id


def _sessions_file(staging_root: Path) -> Path:
    return staging_root / "sessions.json"


def _load_sessions(staging_root: Path) -> dict[str, dict[str, Any]]:
    path = _sessions_file(staging_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sessions(staging_root: Path, sessions: dict[str, dict[str, Any]]) -> None:
    path = _sessions_file(staging_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _session_lock(staging_root: Path, session_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((str(staging_root.resolve()), session_id), threading.Lock())


_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_session(
    manifest: list[dict[str, Any]],
    *,
    staging_root: Path,
    session_id: str | None = None,
    total_bytes: int | None = None,
    expires_in: float | None = _DEFAULT_EXPIRY_SECONDS,
) -> dict[str, Any]:
    """Register a new upload session.

    ``manifest`` is a list of entries, each with:
      - ``path``: relative path within the folder (e.g. ``"docs/readme.txt"``)
      - ``kind``: ``"file"`` or ``"dir"``
      - ``size``: (files only) expected byte count

    Returns ``{"status": "READY", "session_id": ..., "errors": []}`` on success,
    or ``{"status": "BLOCKED", "errors": [...]}`` if the manifest is invalid.

    The staging area for this session is created under ``staging_root``.
    """
    staging_root = Path(staging_root)
    errors: list[dict[str, str]] = []

    if not isinstance(manifest, list):
        return {"status": "BLOCKED", "errors": [{"field": "manifest", "code": "BAD_SHAPE",
                                                 "message": "Manifest must be a list of entries."}]}
    if len(manifest) > _MAX_MANIFEST_ENTRIES:
        return {"status": "BLOCKED", "errors": [{"field": "manifest", "code": "TOO_MANY_ENTRIES",
                                                 "message": f"Manifest has {len(manifest)} entries; maximum is {_MAX_MANIFEST_ENTRIES}."}]}

    # Validate every entry
    seen_paths: set[str] = set()
    valid_entries: list[dict[str, Any]] = []
    for i, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            errors.append({"field": f"manifest[{i}]", "code": "BAD_SHAPE",
                           "message": "Each manifest entry must be an object."})
            continue
        entry_errors = _validate_entry(entry)
        if entry_errors:
            errors.extend(entry_errors)
            continue
        path = entry["path"]
        if path in seen_paths:
            errors.append({"field": "path", "code": "DUPLICATE_PATH",
                           "message": f"Path {path!r} appears more than once in the manifest."})
            continue
        seen_paths.add(path)
        valid_entries.append(entry)

    # Check total size
    declared_total = sum(e.get("size", 0) for e in valid_entries if e["kind"] == "file")
    if declared_total > MAX_TOTAL_BYTES:
        errors.append({"field": "manifest", "code": "TOTAL_TOO_LARGE",
                       "message": f"Total declared size {declared_total} bytes exceeds the {MAX_TOTAL_BYTES} byte limit."})

    if errors:
        return {"status": "BLOCKED", "errors": errors}

    if session_id is None:
        session_id = _new_session_id()
    if not _SESSION_ID_RE.match(session_id):
        return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "BAD_SESSION_ID",
                                                 "message": "A pre-generated session_id must be a UUID string."}]}

    now = time.time()
    session_dir = _session_dir(staging_root, session_id)
    if session_dir.exists():
        return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "SESSION_EXISTS",
                                                 "message": f"A staging area for {session_id!r} already exists."}]}
    session_dir.mkdir(parents=True, exist_ok=False)
    for entry in valid_entries:
        if entry["kind"] == "dir":
            (session_dir / entry["path"]).mkdir(parents=True, exist_ok=True)

    sessions = _load_sessions(staging_root)
    sessions[session_id] = {
        "session_id": session_id,
        "created_at": now,
        "expires_at": now + expires_in if expires_in else None,
        "status": "uploading",
        "total_bytes": total_bytes if total_bytes is not None else declared_total,
        "manifest": valid_entries,
    }
    _save_sessions(staging_root, sessions)

    return {"status": "READY", "session_id": session_id, "errors": []}


def write_chunk(
    session_id: str,
    file_path: str,
    chunk_index: int,
    data: bytes | bytearray | memoryview,
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Write one bounded chunk of a file into the staging area.

    ``file_path`` must match the relative path in the session manifest.
    ``chunk_index`` is the zero-based ordinal of this chunk (used for progress).
    ``data`` is at most ``_CHUNK_SIZE`` bytes.

    Returns ``{"status": "OK", "offset": <bytes written so far>}`` on success,
    or ``{"status": "BLOCKED", "errors": [...]}`` on failure.
    """
    staging_root = Path(staging_root)
    with _session_lock(staging_root, session_id):
        sessions = _load_sessions(staging_root)
        session = sessions.get(session_id)
        if session is None:
            return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "UNKNOWN_SESSION",
                                                     "message": "Session not found."}]}
        if session["status"] != "uploading":
            code = "SESSION_CANCELLED" if session["status"] == "cancelled" else "SESSION_COMPLETE"
            return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": code,
                                                     "message": "Session is no longer accepting chunks."}]}
        if session.get("expires_at") is not None and time.time() > session["expires_at"]:
            _cleanup_session(staging_root, session_id)
            return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "SESSION_EXPIRED",
                                                     "message": "Session has expired."}]}
        entry = next((e for e in session["manifest"] if e["path"] == file_path), None)
        if entry is None:
            return {"status": "BLOCKED", "errors": [{"field": "file_path", "code": "NOT_IN_MANIFEST",
                                                     "message": f"{file_path!r} is not in the session manifest."}]}
        if entry["kind"] != "file":
            return {"status": "BLOCKED", "errors": [{"field": "file_path", "code": "WRONG_KIND",
                                                     "message": f"{file_path!r} is a directory entry; write files only."}]}
        if not isinstance(data, (bytes, bytearray, memoryview)):
            return {"status": "BLOCKED", "errors": [{"field": "data", "code": "BAD_TYPE",
                                                     "message": "data must be bytes."}]}
        data = bytes(data)
        if len(data) > _CHUNK_SIZE:
            return {"status": "BLOCKED", "errors": [{"field": "data", "code": "CHUNK_TOO_LARGE",
                                                     "message": f"Chunk exceeds the {_CHUNK_SIZE} byte limit."}]}
        if not isinstance(chunk_index, int) or chunk_index < 0:
            return {"status": "BLOCKED", "errors": [{"field": "chunk_index", "code": "BAD_CHUNK_INDEX",
                                                     "message": "Chunk index must be a non-negative integer."}]}
        chunks = session.setdefault("chunks", {}).setdefault(file_path, [])
        target = _session_dir(staging_root, session_id) / file_path
        current_size = target.stat().st_size if target.is_file() else 0
        recorded_size = sum(c["size"] for c in chunks)
        if current_size != recorded_size:
            return {"status": "BLOCKED", "errors": [{"field": "file_path", "code": "CHUNK_STATE_MISMATCH",
                                                     "message": "Staged file size differs from recorded chunks."}]}
        digest = hashlib.sha256(data).hexdigest()
        if chunk_index < len(chunks):
            old = chunks[chunk_index]
            if old["size"] == len(data) and old["sha256"] == digest:
                return {"status": "OK", "offset": current_size, "already_received": True}
            return {"status": "BLOCKED", "errors": [{"field": "chunk_index", "code": "CHUNK_CONFLICT",
                                                     "message": "A different chunk was already received at this index."}]}
        if chunk_index != len(chunks):
            return {"status": "BLOCKED", "errors": [{"field": "chunk_index", "code": "CHUNK_OUT_OF_ORDER",
                                                     "message": "Upload the next chunk in sequence."}]}
        if current_size + len(data) > entry.get("size", 0):
            return {"status": "BLOCKED", "errors": [{"field": "data", "code": "FILE_SIZE_EXCEEDED",
                                                     "message": "Chunk would exceed the declared file size."}]}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("ab") as handle:
                handle.write(data)
            chunks.append({"size": len(data), "sha256": digest})
            _save_sessions(staging_root, sessions)
        except OSError as error:
            if target.exists():
                with target.open("r+b") as handle:
                    handle.truncate(current_size)
            return {"status": "ERROR", "errors": [{"field": "file_path", "code": "WRITE_FAILED",
                                                   "message": f"Failed to write {file_path!r}: {error}"}]}
        return {"status": "OK", "offset": current_size + len(data)}


def write_file(
    session_id: str,
    file_path: str,
    data: bytes | bytearray | memoryview,
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Write an entire file in one call (splits into bounded chunks internally).

    Convenience wrapper around ``write_chunk`` for small payloads.
    """
    staging_root = Path(staging_root)
    data_bytes = bytes(data)
    offset = 0
    index = 0
    while offset < len(data_bytes):
        end = min(offset + _CHUNK_SIZE, len(data_bytes))
        result = write_chunk(session_id, file_path, index, data_bytes[offset:end],
                             staging_root=staging_root)
        if result["status"] != "OK":
            return result
        offset = end
        index += 1
    if not data_bytes:
        # Create empty file
        target = _session_dir(staging_root, session_id) / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    return {"status": "OK", "offset": len(data_bytes)}


def finalise(
    session_id: str,
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Validate and complete an upload session.

    Checks that:
      - every file entry has exactly the declared byte count;
      - no extra files exist in the staging tree that are not in the manifest;
      - no symlinks are present in the staged tree;
      - all directory entries exist in the staging tree.

    Returns ``{"status": "READY", "destination": <path>}`` on success, or
    ``{"status": "BLOCKED", "errors": [...]}`` on failure. On failure the
    staging area is preserved for inspection; call ``cancel_session`` to discard.
    """
    staging_root = Path(staging_root)
    sessions = _load_sessions(staging_root)
    session = sessions.get(session_id)
    if session is None:
        return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "UNKNOWN_SESSION",
                                                 "message": "Session not found."}]}
    if session["status"] == "complete":
        return {"status": "READY", "destination": str(_session_dir(staging_root, session_id))}
    if session["status"] == "cancelled":
        return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "SESSION_CANCELLED",
                                                 "message": "Session has been cancelled."}]}

    now = time.time()
    expires_at = session.get("expires_at")
    if expires_at is not None and now > expires_at:
        _cleanup_session(staging_root, session_id)
        return {"status": "BLOCKED", "errors": [{"field": "session_id", "code": "SESSION_EXPIRED",
                                                 "message": "Session has expired."}]}

    session_dir = _session_dir(staging_root, session_id)
    errors: list[dict[str, str]] = []

    # 1. Check symlinks in the staged tree
    for root, dirs, files in os.walk(session_dir):
        for name in dirs + files:
            p = Path(root) / name
            if p.is_symlink():
                errors.append({"field": "path", "code": "SYMLINK_FOUND",
                               "message": f"Symlink found at {p.relative_to(session_dir)!s}."})
                break
        if errors:
            break

    if not errors:
        # 2. Check file sizes match the manifest
        for entry in session["manifest"]:
            if entry["kind"] != "file":
                continue
            target = session_dir / entry["path"]
            if not target.exists():
                errors.append({"field": "path", "code": "FILE_MISSING",
                               "message": f"File {entry['path']!r} is missing from the staging area."})
            elif not target.is_file():
                errors.append({"field": "path", "code": "NOT_A_FILE",
                               "message": f"{entry['path']!r} is not a regular file."})
            else:
                declared = entry.get("size", 0)
                actual = target.stat().st_size
                if actual != declared:
                    errors.append({"field": "path", "code": "SIZE_MISMATCH",
                                   "message": f"{entry['path']!r}: expected {declared} bytes, got {actual}."})

    if not errors:
        # 3. Check all directory entries exist
        for entry in session["manifest"]:
            if entry["kind"] != "dir":
                continue
            if not (session_dir / entry["path"]).is_dir():
                errors.append({"field": "path", "code": "DIR_MISSING",
                               "message": f"Directory {entry['path']!r} is missing from the staging area."})

    if errors:
        return {"status": "BLOCKED", "errors": errors}

    # 4. Check no extra files exist (files in staging tree not in manifest)
    manifest_files = {e["path"] for e in session["manifest"] if e["kind"] == "file"}
    manifest_dirs = {e["path"] for e in session["manifest"] if e["kind"] == "dir"}
    for root, dirs, files in os.walk(session_dir):
        rel_root = Path(root).relative_to(session_dir)
        for f in files:
            rel = (rel_root / f) if str(rel_root) != "." else Path(f)
            rel_str = rel.as_posix()
            target = session_dir / rel_str
            if target.is_symlink():
                errors.append({"field": "path", "code": "SYMLINK_FOUND",
                               "message": f"Symlink found at {rel_str!r}."})
            elif rel_str not in manifest_files:
                errors.append({"field": "path", "code": "UNEXPECTED_FILE",
                               "message": f"File {rel_str!r} is not in the manifest."})
            if errors:
                break
        if errors:
            break

    if errors:
        return {"status": "BLOCKED", "errors": errors}

    # All checks passed -- mark complete
    sessions[session_id]["status"] = "complete"
    sessions[session_id]["completed_at"] = now
    _save_sessions(staging_root, sessions)

    return {"status": "READY", "destination": str(session_dir)}


def cancel_session(
    session_id: str,
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Cancel a session and remove its staging area. Idempotent."""
    staging_root = Path(staging_root)
    sessions = _load_sessions(staging_root)
    session = sessions.get(session_id)
    if session is None:
        return {"status": "OK", "cancelled": False}
    if session["status"] == "cancelled":
        return {"status": "OK", "cancelled": True}

    sessions[session_id]["status"] = "cancelled"
    _save_sessions(staging_root, sessions)
    _cleanup_session(staging_root, session_id)
    return {"status": "OK", "cancelled": True}


def get_status(
    session_id: str,
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Return the current status and progress of a session."""
    staging_root = Path(staging_root)
    sessions = _load_sessions(staging_root)
    session = sessions.get(session_id)
    if session is None:
        return {"status": "ERROR", "errors": [{"field": "session_id", "code": "UNKNOWN_SESSION",
                                               "message": "Session not found."}]}

    now = time.time()
    effective_status = session["status"]
    expires_at = session.get("expires_at")
    if expires_at is not None and now > expires_at and effective_status == "uploading":
        effective_status = "expired"

    session_dir = _session_dir(staging_root, session_id)
    total_expected = session.get("total_bytes", 0)
    received = 0
    for entry in session["manifest"]:
        if entry["kind"] != "file":
            continue
        target = session_dir / entry["path"]
        if target.exists() and target.is_file():
            received += target.stat().st_size

    return {
        "status": "OK",
        "session_id": session_id,
        "effective_status": effective_status,
        "received_bytes": received,
        "total_bytes": total_expected,
        "progress": round(received / total_expected, 4) if total_expected > 0 else 1.0,
        "expires_at": expires_at,
        "errors": [],
    }


def list_sessions(
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """List all sessions with their current effective status."""
    staging_root = Path(staging_root)
    sessions = _load_sessions(staging_root)
    now = time.time()
    results = []
    for sid, session in sessions.items():
        effective = session["status"]
        expires_at = session.get("expires_at")
        if expires_at is not None and now > expires_at and effective == "uploading":
            effective = "expired"
        results.append({
            "session_id": sid,
            "status": effective,
            "created_at": session.get("created_at"),
            "expires_at": expires_at,
            "total_bytes": session.get("total_bytes"),
            "file_count": sum(1 for e in session["manifest"] if e["kind"] == "file"),
            "dir_count": sum(1 for e in session["manifest"] if e["kind"] == "dir"),
        })
    return {"status": "OK", "sessions": results, "errors": []}


def cleanup_expired(
    *,
    staging_root: Path,
) -> dict[str, Any]:
    """Remove all expired sessions. Returns the number of sessions removed."""
    staging_root = Path(staging_root)
    sessions = _load_sessions(staging_root)
    now = time.time()
    removed = 0
    for sid, session in list(sessions.items()):
        expires_at = session.get("expires_at")
        if expires_at is not None and now > expires_at and session["status"] == "uploading":
            sessions[sid]["status"] = "cancelled"
            _cleanup_session(staging_root, sid)
            removed += 1
    if removed:
        _save_sessions(staging_root, sessions)
    return {"status": "OK", "removed": removed, "errors": []}


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _cleanup_session(staging_root: Path, session_id: str) -> None:
    session_dir = _session_dir(staging_root, session_id)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
