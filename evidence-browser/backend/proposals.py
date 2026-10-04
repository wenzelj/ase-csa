from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import pipeline


Runner = Callable[[str], Any]
EDIT = re.compile(r"^###\s+(S\d+-E\d+|[EA]-\d+)\s+-\s+(.+?)\s*$", re.M)
FIELD = re.compile(r"^\*\*(Where|Do|Facts|Text|Why|Note):\*\*\s*(.*?)(?=^\*\*(?:Where|Do|Facts|Text|Why|Note):\*\*|\n---\s*(?:\n|\Z)|\Z)", re.M | re.S)
STATUS = re.compile(r"^\*\*Status:\*\*.*$", re.M)
STABLE_ID = re.compile(r"@H\d+(?:\.\d+)*(?:-(?:P|T)\d+(?:-R\d+)?)?")


def _etag(path: Path) -> str:
    return '"' + hashlib.sha256(path.read_bytes()).hexdigest() + '"'


def _value(block: str, name: str) -> str:
    match = next((match for match in FIELD.finditer(block) if match.group(1) == name), None)
    if not match:
        return ""
    value = match.group(2).strip()
    if name == "Text":
        value = "\n".join(line[2:] if line.startswith("> ") else line[1:] if line.startswith(">") else line
                          for line in value.splitlines()).strip()
    return value.strip("`")


def _records(markdown: str) -> list[dict[str, str]]:
    matches = list(EDIT.finditer(markdown))
    rows = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        block = markdown[match.start():end]
        rows.append({"edit_id": match.group(1), "title": match.group(2),
                     "target": _value(block, "Where"), "operation": _value(block, "Do"),
                     "replacement": _value(block, "Text"), "facts": _value(block, "Facts"),
                     "rationale": _value(block, "Why"), "note": _value(block, "Note"),
                     "evidence_ids": sorted(set(re.findall(r"\bE-\d{3,}\b", _value(block, "Facts") + " " +
                                                               _value(block, "Why") + " " + _value(block, "Note"))))})
    return rows


def _selected(node: dict[str, Any], status: list[dict[str, Any]], builds: list[dict[str, Any]], project: dict[str, str]) -> tuple[str, Path]:
    number = str(node.get("number") or "")
    revise = [row for row in status if str(row.get("subsection") or row.get("section") or "") == number]
    if len(revise) == 1 and revise[0].get("change_file"):
        return "revise", Path(revise[0]["change_file"]).expanduser().resolve()
    build = [row for row in builds if " ".join(str(row.get("heading") or "").split()).casefold() ==
             " ".join(str(node.get("title") or "").split()).casefold()]
    if len(build) == 1 and build[0].get("file"):
        path = Path(build[0]["file"])
        if not path.is_absolute():
            path = Path(project["work_dir"]).expanduser() / "sections" / path
        return "build", path.resolve()
    raise HTTPException(409, "The framework has not selected exactly one proposal file for this section")


def _resolve(agents_dir: Path, project: dict[str, str], section: str, run: Runner) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    from .sections import _resolver
    spec = run("spec_status")
    try:
        node = _resolver(agents_dir).resolve(spec, section)
    except Exception as error:
        raise HTTPException(404, str(error)) from error
    lane, path = _selected(node, run("status"), run("sections"), project)
    root = Path(project["project_root"]).expanduser().resolve()
    work = Path(project["work_dir"]).expanduser().resolve()
    if not path.is_file() or (root != path and root not in path.parents and work != path and work not in path.parents):
        raise HTTPException(409, "The framework-selected proposal file is unavailable or outside the project")
    return node, lane, path, spec


def _stable_ids(node: dict[str, Any]) -> set[str]:
    ids = {str(node.get("hid") or "")}
    for part in node.get("parts", []):
        ids.update(str(part.get(key) or "") for key in ("pid", "table"))
        ids.update(str(value) for value in part.get("pids", []))
        table = str(part.get("table") or "")
        ids.update(f"{table}-R{req.get('row')}" for req in part.get("requirements", []) if table and req.get("row"))
    return {value for value in ids if value}


def _next_edit_id(path: Path, node: dict[str, Any], project: dict[str, str]) -> str:
    major = str(node.get("number") or "0").split(".")[0]
    root = Path(project["project_root"]).expanduser().resolve()
    numbers = []
    for candidate in root.rglob(f"ChangesCSA_*_Section{major}*.md"):
        if any("archive" in part.casefold() or part.casefold().startswith("old") for part in candidate.parts):
            continue
        try:
            numbers.extend(int(value) for value in re.findall(rf"\bS{re.escape(major)}-E(\d+)\b", candidate.read_text(encoding="utf-8")))
        except OSError:
            continue
    return f"S{major}-E{max(numbers, default=0) + 1}"


def load(agents_dir: Path, project: dict[str, str], section: str, *, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or (lambda operation: pipeline._run(agents_dir, project, operation))
    node, lane, path, _ = _resolve(agents_dir, project, section, run)
    content = path.read_text(encoding="utf-8")
    approval = path.with_name(path.stem + ".approval.json")
    return {"section": {"visible_number": node.get("number"), "stable_key": node.get("key"),
                         "heading": node.get("title"), "stable_id": node.get("hid")},
            "lane": lane, "file": path.name, "etag": _etag(path), "approved": approval.is_file(),
            "approval_warning": "Saving a changed approved record revokes readiness; validate and approve it again."
                                if approval.is_file() else None,
            "stable_ids": sorted(_stable_ids(node)), "next_edit_id": _next_edit_id(path, node, project),
            "records": _records(content) if lane == "revise" else [], "content": content if lane == "build" else None}


def _render_record(row: dict[str, Any]) -> str:
    values = {key: str(row.get(key) or "").strip() for key in
              ("edit_id", "title", "target", "operation", "replacement", "facts", "rationale", "note")}
    if not all(values[key] for key in ("edit_id", "title", "target", "operation", "replacement", "rationale")):
        raise HTTPException(422, "Every change requires an edit ID, title, target, operation, replacement and rationale")
    text = "\n".join(f"> {line}" if line else ">" for line in values["replacement"].splitlines())
    optional = (f"\n\n**Facts:** {values['facts']}" if values["facts"] else "") + (f"\n\n**Note:** {values['note']}" if values["note"] else "")
    return (f"### {values['edit_id']} - {values['title']}\n\n**Where:** {values['target']}\n\n"
            f"**Do:** {values['operation']}{optional}\n\n**Text:**\n\n{text}\n\n**Why:** {values['rationale']}\n\n---")


def _render_revise(original: str, records: list[dict[str, Any]]) -> str:
    matches = list(EDIT.finditer(original))
    if not matches:
        raise HTTPException(422, "The selected change file has no structured edit records")
    separator = re.search(r"\n---\s*(?:\n|\Z)", original[matches[-1].end():])
    tail = matches[-1].end() + separator.end() if separator else len(original)
    prefix = original[:matches[0].start()].rstrip()
    suffix = original[tail:].lstrip()
    rendered = prefix + "\n\n" + "\n\n".join(_render_record(row) for row in records) + "\n\n"
    return rendered + (suffix if suffix else "")


def save(agents_dir: Path, project: dict[str, str], section: str, payload: dict[str, Any], *,
         runner: Runner | None = None) -> dict[str, Any]:
    run = runner or (lambda operation: pipeline._run(agents_dir, project, operation))
    node, lane, path, _ = _resolve(agents_dir, project, section, run)
    if payload.get("lane") != lane or payload.get("file") != path.name:
        raise HTTPException(409, "Proposal identity does not match the framework-selected section file")
    if payload.get("etag") != _etag(path):
        raise HTTPException(409, "This proposal changed after it was loaded. Reload before saving.")
    original = path.read_text(encoding="utf-8")
    if lane == "revise":
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            raise HTTPException(422, "At least one structured edit record is required")
        allowed = _stable_ids(node)
        seen: set[str] = set()
        for row in records:
            edit_id = str(row.get("edit_id") or "")
            if edit_id in seen:
                raise HTTPException(422, f"Duplicate edit ID: {edit_id}")
            seen.add(edit_id)
            target_ids = STABLE_ID.findall(str(row.get("target") or ""))
            if not target_ids or any(value not in allowed for value in target_ids):
                raise HTTPException(422, f"Invalid stable target for {edit_id or 'change record'}")
            evidence_ids = row.get("evidence_ids") or []
            missing_evidence = [value for value in evidence_ids if value not in str(row.get("facts") or "")]
            if missing_evidence:
                facts = str(row.get("facts") or "").rstrip()
                row["facts"] = (facts + (" " if facts else "") + "Evidence: " + ", ".join(missing_evidence)).strip()
        updated = _render_revise(original, records)
    else:
        updated = str(payload.get("content") or "")
        if not updated.startswith("---\n") or "\n---\n" not in updated:
            raise HTTPException(422, "Build section content must retain its YAML front matter")
    if updated == original:
        return {"saved": False, "etag": _etag(path), "backup": None, "approval_revoked": False}

    backup_dir = Path(project["work_dir"]).expanduser() / "backups" / "proposals"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, backup)
    approval = path.with_name(path.stem + ".approval.json")
    approval_revoked = approval.is_file()
    if approval_revoked:
        shutil.copy2(approval, backup_dir / f"{approval.name}.{stamp}.bak")
        approval.unlink()
        updated = STATUS.sub("**Status:** Proposed changes for approval. Revalidation and approval are required after browser editing.", updated, count=1)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated.rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"saved": True, "etag": _etag(path), "backup": str(backup),
            "approval_revoked": approval_revoked,
            "message": "Draft saved. Validate and approve the proposal again before application."
                       if approval_revoked else "Draft saved. Validate it before application."}
