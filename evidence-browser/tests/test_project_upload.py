"""Tests for backend.project_upload (S513: Staged folder upload service)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from backend import project_upload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest(*entries):
    return list(entries)


def _file(path, size, data=None):
    entry = {"path": path, "kind": "file", "size": size}
    return entry


def _dir(path):
    return {"path": path, "kind": "dir"}


def _session(tmp_path, manifest, **kw):
    """Create a session and return its id (fails the test on BLOCKED)."""
    result = project_upload.create_session(
        manifest, staging_root=tmp_path, **kw)
    assert result["status"] == "READY", result
    return result["session_id"]


def _upload_file(tmp_path, session_id, path, data: bytes):
    """Write a file in bounded chunks (mimics the client)."""
    chunk = 16
    offset = 0
    index = 0
    while offset < len(data):
        result = project_upload.write_chunk(
            session_id, path, index, data[offset:offset + chunk],
            staging_root=tmp_path)
        assert result["status"] == "OK", result
        offset += chunk
        index += 1
    if not data:
        (tmp_path / session_id / path).touch()
    # ensure parent directories exist (write_chunk creates them, but be safe)
    (tmp_path / session_id / path).parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Manifest validation (create_session)
# ---------------------------------------------------------------------------

def test_create_session_accepts_a_valid_manifest(tmp_path):
    sid = _session(tmp_path, _manifest(
        _file("docs/readme.txt", 3),
        _dir("docs"),
        _dir("empty"),
    ))
    assert len(sid) == 36
    # the session staging area exists; declared directories are created on finalise
    assert (tmp_path / sid).is_dir()
    status = project_upload.get_status(sid, staging_root=tmp_path)
    assert status["effective_status"] == "uploading"
    assert status["total_bytes"] == 3


def test_create_session_rejects_blank_paths(tmp_path):
    result = project_upload.create_session(
        _manifest({"path": "", "kind": "file", "size": 0}), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BLANK_PATH" for e in result["errors"])


def test_create_session_rejects_bad_kind(tmp_path):
    result = project_upload.create_session(
        _manifest({"path": "a.txt", "kind": "blob"}), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_KIND" for e in result["errors"])


def test_create_session_rejects_absolute_and_backslash_paths(tmp_path):
    for bad in ("/etc/passwd", "a\\b.txt", "a/\\b"):
        result = project_upload.create_session(
            _manifest({"path": bad, "kind": "file", "size": 0}), staging_root=tmp_path)
        assert result["status"] == "BLOCKED", bad
        assert any(e["code"] == "BAD_PATH" for e in result["errors"])


def test_create_session_rejects_traversal(tmp_path):
    for bad in ("..", "../secrets.txt", "a/../../b", "a/./b"):
        result = project_upload.create_session(
            _manifest({"path": bad, "kind": "file", "size": 0}), staging_root=tmp_path)
        assert result["status"] == "BLOCKED", bad
        codes = {e["code"] for e in result["errors"]}
        assert "TRAVERSAL" in codes or "BAD_PATH" in codes, (bad, result)


def test_create_session_rejects_reserved_top_level_paths(tmp_path):
    for reserved in ("csa-work", "reviews", "Discovery", "00 Knowlege", "00 Knowledge"):
        result = project_upload.create_session(
            _manifest({"path": f"{reserved}/file.txt", "kind": "file", "size": 0}),
            staging_root=tmp_path)
        assert result["status"] == "BLOCKED", reserved
        assert any(e["code"] == "RESERVED_PATH" for e in result["errors"]), reserved


def test_create_session_rejects_reserved_filenames(tmp_path):
    for name in (".DS_Store", "Thumbs.db", "desktop.ini"):
        result = project_upload.create_session(
            _manifest({"path": f"folder/{name}", "kind": "file", "size": 0}),
            staging_root=tmp_path)
        assert result["status"] == "BLOCKED", name
        assert any(e["code"] == "RESERVED_FILENAME" for e in result["errors"]), name


def test_create_session_rejects_duplicate_paths(tmp_path):
    result = project_upload.create_session(
        _manifest(_file("a.txt", 0), _file("a.txt", 0)), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DUPLICATE_PATH" for e in result["errors"])


def test_create_session_rejects_negative_or_bad_size(tmp_path):
    result = project_upload.create_session(
        _manifest({"path": "a.txt", "kind": "file", "size": -1}), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_SIZE" for e in result["errors"])

    result = project_upload.create_session(
        _manifest({"path": "a.txt", "kind": "file", "size": "big"}), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_SIZE" for e in result["errors"])


def test_create_session_rejects_oversized_files(tmp_path):
    result = project_upload.create_session(
        _manifest(_file("big.bin", project_upload.MAX_FILE_BYTES + 1)),
        staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "FILE_TOO_LARGE" for e in result["errors"])


def test_create_session_rejects_oversized_totals(tmp_path, monkeypatch):
    # a single file over the per-file limit is rejected with FILE_TOO_LARGE
    result = project_upload.create_session(
        _manifest(_file("big.bin", project_upload.MAX_FILE_BYTES + 1)), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "FILE_TOO_LARGE" for e in result["errors"])
    # two files each within the per-file limit but over the total are rejected
    monkeypatch.setattr(project_upload, "MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(project_upload, "MAX_FILE_BYTES", 60)
    result = project_upload.create_session(
        _manifest(_file("a.bin", 60), _file("b.bin", 60)), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "TOTAL_TOO_LARGE" for e in result["errors"])


def test_create_session_rejects_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(project_upload, "_MAX_MANIFEST_ENTRIES", 2)
    result = project_upload.create_session(
        _manifest(_file("a", 0), _file("b", 0), _file("c", 0)), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "TOO_MANY_ENTRIES" for e in result["errors"])


def test_create_session_rejects_bad_manifest_shapes(tmp_path):
    result = project_upload.create_session("not a list", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_SHAPE" for e in result["errors"])

    result = project_upload.create_session(
        [42, "x"], staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_SHAPE" for e in result["errors"])


def test_failed_create_session_leaves_no_staging_folder(tmp_path):
    project_upload.create_session(
        _manifest({"path": "../evil", "kind": "file", "size": 0}), staging_root=tmp_path)
    # no session directories were created (sessions.json may exist only after success)
    dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert dirs == []


# ---------------------------------------------------------------------------
# Chunk writes
# ---------------------------------------------------------------------------

def test_write_chunk_roundtrip_preserves_bytes(tmp_path):
    sid = _session(tmp_path, _manifest(_file("data.bin", 100)))
    payload = bytes(range(256))[:100]
    _upload_file(tmp_path, sid, "data.bin", payload)
    staged = (tmp_path / sid / "data.bin").read_bytes()
    assert staged == payload


def test_write_chunk_rejects_unknown_session(tmp_path):
    result = project_upload.write_chunk(
        "00000000-0000-4000-8000-000000000000", "a.txt", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "UNKNOWN_SESSION" for e in result["errors"])


def test_write_chunk_rejects_paths_outside_the_manifest(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)))
    result = project_upload.write_chunk(sid, "other.txt", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "NOT_IN_MANIFEST" for e in result["errors"])


def test_write_chunk_rejects_directory_entries(tmp_path):
    sid = _session(tmp_path, _manifest(_dir("d")))
    result = project_upload.write_chunk(sid, "d", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "WRONG_KIND" for e in result["errors"])


def test_write_chunk_rejects_oversized_chunks(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 8)))
    result = project_upload.write_chunk(
        sid, "a.txt", 0, b"x" * (project_upload._CHUNK_SIZE + 1), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "CHUNK_TOO_LARGE" for e in result["errors"])


def test_write_chunk_after_finalise_is_rejected(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 0)))
    (tmp_path / sid / "a.txt").touch()
    assert project_upload.finalise(sid, staging_root=tmp_path)["status"] == "READY"
    result = project_upload.write_chunk(sid, "a.txt", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "SESSION_COMPLETE" for e in result["errors"])


def test_write_file_convenience_helper(tmp_path):
    sid = _session(tmp_path, _manifest(_file("full.txt", 5)))
    result = project_upload.write_file(sid, "full.txt", b"hello", staging_root=tmp_path)
    assert result["status"] == "OK"
    assert (tmp_path / sid / "full.txt").read_bytes() == b"hello"


# ---------------------------------------------------------------------------
# Finalise
# ---------------------------------------------------------------------------

def test_finalise_ready_when_tree_matches_the_manifest(tmp_path):
    sid = _session(tmp_path, _manifest(
        _file("a.txt", 3),
        _file("nested/deep/b.txt", 2),
        _dir("empty"),
        _dir("nested"),
        _dir("nested/deep"),
    ))
    (tmp_path / sid / "a.txt").write_bytes(b"abc")
    (tmp_path / sid / "nested" / "deep").mkdir(parents=True, exist_ok=True)
    (tmp_path / sid / "nested" / "deep" / "b.txt").write_bytes(b"xy")
    (tmp_path / sid / "empty").mkdir(parents=True, exist_ok=True)

    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "READY", result
    assert Path(result["destination"]) == tmp_path / sid

    status = project_upload.get_status(sid, staging_root=tmp_path)
    assert status["effective_status"] == "complete"
    assert status["progress"] == 1.0


def test_finalise_rejects_missing_files(tmp_path):
    sid = _session(tmp_path, _manifest(_file("missing.txt", 1)))
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "FILE_MISSING" for e in result["errors"])


def test_finalise_rejects_byte_count_mismatches(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 5)))
    (tmp_path / sid / "a.txt").write_bytes(b"abc")
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "SIZE_MISMATCH" for e in result["errors"])


def test_finalise_rejects_missing_directories(tmp_path):
    sid = _session(tmp_path, _manifest(_dir("gone"), _file("a.txt", 0)))
    (tmp_path / sid / "a.txt").touch()
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DIR_MISSING" for e in result["errors"])

    # a declared directory that is never created (create_session skipped it) is also rejected
    sid2 = _session(tmp_path, _manifest(_dir("never-made"), _file("b.txt", 1)))
    (tmp_path / sid2 / "b.txt").write_bytes(b"z")
    (tmp_path / sid2 / "never-made").mkdir()
    (tmp_path / sid2 / "never-made").rmdir()
    result = project_upload.finalise(sid2, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DIR_MISSING" for e in result["errors"])


def test_finalise_rejects_unexpected_files(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 0)))
    (tmp_path / sid / "a.txt").touch()
    extra = tmp_path / sid / "sneaky"
    extra.mkdir()
    (extra / "x.txt").write_bytes(b"x")
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "UNEXPECTED_FILE" for e in result["errors"])


def test_finalise_rejects_symlinks(tmp_path):
    sid = _session(tmp_path, _manifest(_file("link.txt", 0)))
    target = tmp_path / "outside-target.txt"
    target.write_bytes(b"secret")
    (tmp_path / sid / "link.txt").symlink_to(target)
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "SYMLINK_FOUND" for e in result["errors"])
    # target untouched
    assert target.read_bytes() == b"secret"


def test_finalise_is_idempotent(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)))
    (tmp_path / sid / "a.txt").write_bytes(b"z")
    first = project_upload.finalise(sid, staging_root=tmp_path)
    second = project_upload.finalise(sid, staging_root=tmp_path)
    assert first["status"] == "READY"
    assert second["status"] == "READY"
    assert first["destination"] == second["destination"]


# ---------------------------------------------------------------------------
# Cancellation and expiry
# ---------------------------------------------------------------------------

def test_cancel_session_removes_the_staging_area(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)))
    (tmp_path / sid / "a.txt").write_bytes(b"x")
    result = project_upload.cancel_session(sid, staging_root=tmp_path)
    assert result["status"] == "OK"
    assert result["cancelled"] is True
    # the staged folder is gone -- nothing usable remains
    assert not (tmp_path / sid).exists()
    # the session is still listed as cancelled
    listed = {s["session_id"]: s for s in project_upload.list_sessions(staging_root=tmp_path)["sessions"]}
    assert listed[sid]["status"] == "cancelled"


def test_cancel_session_is_idempotent(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)))
    first = project_upload.cancel_session(sid, staging_root=tmp_path)
    second = project_upload.cancel_session(sid, staging_root=tmp_path)
    assert first == {"status": "OK", "cancelled": True}
    assert second["status"] == "OK"


def test_write_after_cancel_is_rejected(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)))
    project_upload.cancel_session(sid, staging_root=tmp_path)
    result = project_upload.write_chunk(sid, "a.txt", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    codes = {e["code"] for e in result["errors"]}
    assert codes & {"SESSION_CANCELLED", "UNKNOWN_SESSION"}


def test_expired_session_rejects_writes_and_finalise(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 1)), expires_in=-1)
    result = project_upload.write_chunk(sid, "a.txt", 0, b"x", staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "SESSION_EXPIRED" for e in result["errors"])
    assert not (tmp_path / sid).exists()

    sid2 = _session(tmp_path, _manifest(_file("b.txt", 1)), expires_in=-1)
    (tmp_path / sid2 / "b.txt").write_bytes(b"y")
    result = project_upload.finalise(sid2, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "SESSION_EXPIRED" for e in result["errors"])
    assert not (tmp_path / sid2).exists()


def test_cleanup_expired_removes_only_expired_uploading_sessions(tmp_path):
    expired = _session(tmp_path, _manifest(_file("a.txt", 0)), expires_in=-1)
    live = _session(tmp_path, _manifest(_file("b.txt", 0)), expires_in=9999)
    result = project_upload.cleanup_expired(staging_root=tmp_path)
    assert result["removed"] == 1
    assert not (tmp_path / expired).exists()
    assert (tmp_path / live).exists()


def test_get_status_reports_progress(tmp_path):
    sid = _session(tmp_path, _manifest(_file("a.txt", 10)))
    before = project_upload.get_status(sid, staging_root=tmp_path)
    assert before["received_bytes"] == 0
    _upload_file(tmp_path, sid, "a.txt", b"0123456789")
    after = project_upload.get_status(sid, staging_root=tmp_path)
    assert after["received_bytes"] == 10
    assert after["progress"] == 1.0


def test_list_sessions_reports_each_session(tmp_path):
    a = _session(tmp_path, _manifest(_file("a.txt", 1), _dir("d")))
    b = _session(tmp_path, _manifest(_file("b.txt", 2)))
    project_upload.cancel_session(a, staging_root=tmp_path)
    result = project_upload.list_sessions(staging_root=tmp_path)
    assert result["status"] == "OK"
    by_id = {s["session_id"]: s for s in result["sessions"]}
    assert by_id[a]["status"] == "cancelled"
    assert by_id[b]["status"] == "uploading"
    assert by_id[a]["file_count"] == 1
    assert by_id[a]["dir_count"] == 1


# ---------------------------------------------------------------------------
# Whole-tree scenarios
# ---------------------------------------------------------------------------

def test_nested_files_and_empty_directories_are_preserved(tmp_path):
    tree = {
        "01 Discovery Data/readme.txt": b"hello",
        "01 Discovery Data/hosts/hosts.csv": b"host\n",
        "01 Discovery Data/hosts/deep/nested.txt": b"nested",
    }
    manifest = []
    for path, data in tree.items():
        manifest.append(_file(path, len(data)))
    manifest.append(_dir("01 Discovery Data"))
    manifest.append(_dir("01 Discovery Data/hosts"))
    manifest.append(_dir("01 Discovery Data/hosts/deep"))
    manifest.append(_dir("archive/empty-folder"))

    sid = _session(tmp_path, _manifest(*manifest))
    for path, data in tree.items():
        _upload_file(tmp_path, sid, path, data)

    (tmp_path / sid / "archive" / "empty-folder").mkdir(parents=True, exist_ok=True)
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "READY", result
    destination = Path(result["destination"])

    assert (destination / "01 Discovery Data/readme.txt").read_bytes() == b"hello"
    assert (destination / "01 Discovery Data/hosts/hosts.csv").read_bytes() == b"host\n"
    assert (destination / "01 Discovery Data/hosts/deep/nested.txt").read_bytes() == b"nested"
    # empty directory declared in the manifest must exist
    assert (destination / "archive/empty-folder").is_dir()
    assert list((destination / "archive/empty-folder").iterdir()) == []


def test_interrupted_upload_leaves_no_destination_folder(tmp_path):
    """A session that never finalises is cancelled: nothing usable remains."""
    sid = _session(tmp_path, _manifest(_file("a.txt", 100)))
    _upload_file(tmp_path, sid, "a.txt", b"x" * 100)
    # the client disappears without finalising; the operator cancels
    project_upload.cancel_session(sid, staging_root=tmp_path)
    assert not (tmp_path / sid).exists()
    # the workspace (parent of the staging root) is untouched
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == []


def test_failed_finalise_leaves_no_committed_destination(tmp_path):
    """A failed finalise never produces a READY destination."""
    sid = _session(tmp_path, _manifest(_file("a.txt", 10)))
    (tmp_path / sid / "a.txt").write_bytes(b"short")
    result = project_upload.finalise(sid, staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert "destination" not in result
    # discarding the session removes everything
    project_upload.cancel_session(sid, staging_root=tmp_path)
    assert not (tmp_path / sid).exists()


def test_reserved_paths_are_rejected_even_when_nested(tmp_path):
    result = project_upload.create_session(
        _manifest(_file("src/.DS_Store", 4)), staging_root=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "RESERVED_FILENAME" for e in result["errors"])

    result = project_upload.create_session(
        _manifest(_file("src/csa-work/x", 1)), staging_root=tmp_path)
    assert result["status"] == "READY"  # only the *top-level* component is reserved


def test_pre_generated_session_id_is_accepted(tmp_path):
    fixed = "11111111-2222-4333-8444-555555555555"
    result = project_upload.create_session(
        _manifest(_file("a.txt", 0)), staging_root=tmp_path, session_id=fixed)
    assert result["status"] == "READY"
    assert result["session_id"] == fixed

    again = project_upload.create_session(
        _manifest(_file("a.txt", 0)), staging_root=tmp_path, session_id=fixed)
    assert again["status"] == "BLOCKED"
    assert any(e["code"] == "SESSION_EXISTS" for e in again["errors"])
