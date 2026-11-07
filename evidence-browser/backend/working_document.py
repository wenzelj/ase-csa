"""Choose an application's authoritative working DOCX without editing its contents."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .project_setup import _CommitLock

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _root(project: dict[str, str]) -> Path:
    return Path(project["project_root"]).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    return path != root and root in path.parents


def _error(field: str, code: str, message: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "errors": [{"field": field, "code": code, "message": message}]}


def _valid_docx(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".docx" or path.name.startswith("~$"):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return "[Content_Types].xml" in archive.namelist() and "word/document.xml" in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def options(project: dict[str, str]) -> dict[str, Any]:
    root = _root(project)
    excluded = {"Discovery", "csa-work", project.get("knowledge_dir") or "00 Knowlege"}
    candidates: list[dict[str, Any]] = []
    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if current == root:
                dirnames[:] = [name for name in dirnames if name not in excluded and not name.startswith(".")]
            else:
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for name in sorted(filenames):
                path = current / name
                if path.suffix.lower() != ".docx" or name.startswith("~$") or path.is_symlink():
                    continue
                candidates.append({"relative_path": path.relative_to(root).as_posix(), "size": path.stat().st_size})
                if len(candidates) >= 200:
                    break
            if len(candidates) >= 200:
                break
    configured = project.get("working_docx") or ""
    return {"project_key": project["key"], "project_root": str(root),
            "configured_path": configured, "candidates": candidates, "max_upload_bytes": MAX_UPLOAD_BYTES}


def _set_registry_path(agents_dir: Path, project: dict[str, str], document: Path) -> dict[str, Any]:
    lock = _CommitLock(agents_dir)
    if not lock.acquire():
        return _error("working_docx", "REGISTRY_LOCKED", "The project registry is busy; try again.")
    try:
        registry = agents_dir / "csa-context" / "PROJECTS.yaml"
        original = registry.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        starts = [index for index, line in enumerate(lines) if line.startswith("  - key:")]
        target = next((index for index in starts if lines[index].split(":", 1)[1].strip().strip("\"'") == project["key"]), None)
        if target is None:
            return _error("working_docx", "PROJECT_MISSING", "The application is no longer in the project registry.")
        end = next((index for index in starts if index > target), len(lines))
        value = f"    working_docx: {json.dumps(str(document))}\n"
        current = next((index for index in range(target + 1, end) if lines[index].startswith("    working_docx:")), None)
        if current is None:
            lines.insert(end, value)
        else:
            lines[current] = value
        fd, temp_name = tempfile.mkstemp(prefix="PROJECTS.working-", suffix=".tmp", dir=registry.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("".join(lines))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, stat.S_IMODE(registry.stat().st_mode))
            os.replace(temp_name, registry)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return {"status": "READY", "project_key": project["key"], "working_docx": str(document)}
    except OSError as error:
        return _error("working_docx", "REGISTRY_WRITE_FAILED", str(error))
    finally:
        lock.release()


def select(project: dict[str, str], agents_dir: Path, relative_path: str) -> dict[str, Any]:
    root = _root(project)
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        return _error("relative_path", "INVALID_PATH", "Choose a DOCX inside the application folder.")
    document = (root / relative).resolve()
    if not _inside(document, root) or not _valid_docx(document):
        return _error("relative_path", "INVALID_DOCX", "The selected file must be an existing, readable DOCX inside the application folder.")
    return _set_registry_path(agents_dir, project, document)


def upload(project: dict[str, str], agents_dir: Path, filename: str, data: bytes) -> dict[str, Any]:
    root = _root(project)
    if not filename or Path(filename).name != filename or "\\" in filename or "\x00" in filename or filename.startswith("~$") or not filename.lower().endswith(".docx"):
        return _error("filename", "INVALID_FILENAME", "Choose one DOCX file with a simple filename.")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        return _error("file", "INVALID_SIZE", "The DOCX is empty or exceeds the 50 MiB upload limit.")
    folder = root / "02 Current State Assessment"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    if destination.exists():
        return _error("filename", "FILE_EXISTS", "A file with this name already exists in the application folder.")
    fd, temp_name = tempfile.mkstemp(prefix=".working-docx-", suffix=".tmp", dir=folder)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            with zipfile.ZipFile(temp) as archive:
                if "[Content_Types].xml" not in archive.namelist() or "word/document.xml" not in archive.namelist():
                    return _error("file", "INVALID_DOCX", "The uploaded file is not a readable Word DOCX.")
        except (OSError, zipfile.BadZipFile):
            return _error("file", "INVALID_DOCX", "The uploaded file is not a readable Word DOCX.")
        os.link(temp, destination)
        result = _set_registry_path(agents_dir, project, destination)
        if result["status"] != "READY":
            destination.unlink(missing_ok=True)
        return result
    except FileExistsError:
        return _error("filename", "FILE_EXISTS", "A file with this name already exists in the application folder.")
    finally:
        temp.unlink(missing_ok=True)
