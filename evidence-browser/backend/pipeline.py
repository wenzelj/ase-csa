from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import commands
from .jobs import word_lock
from .models import CommandRequest, PipelineDocument, PipelineIssue, PipelineSection, PipelineSnapshot


Runner = Callable[[str], Any]


def _run(agents_dir: Path, project: dict[str, str], operation: str) -> Any:
    definition, argv = commands.build_argv(agents_dir, project["key"], operation, CommandRequest())
    try:
        result = subprocess.run(
            argv, cwd=str(agents_dir.parent), env=commands._minimal_environment(agents_dir),
            shell=False, capture_output=True, text=True, timeout=definition.timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise HTTPException(504, f"Pipeline command '{operation}' timed out") from error
    parsed, valid = commands.parse_json_output(result.stdout)
    if result.returncode or not valid:
        detail = result.stderr.strip() or result.stdout.strip() or "no machine-readable output"
        raise HTTPException(502, f"Pipeline command '{operation}' failed: {detail[-600:]}")
    return parsed


def _normal(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _mtime(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _newest(paths: list[Path]) -> str | None:
    existing = [path for path in paths if path.is_file()]
    return _mtime(max(existing, key=lambda path: path.stat().st_mtime_ns)) if existing else None


def _path(value: Any) -> Path | None:
    return Path(value).expanduser() if value else None


def _lane(node: dict[str, Any], revise: dict | None, build: dict | None) -> str:
    if revise and build:
        return "unknown"
    if revise:
        return "revise"
    if build:
        return "build"
    return "revise" if node.get("kind") == "requirement-block" else "build"


def _find_revise(node: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    number = str(node.get("number") or "")
    by_number = [row for row in rows if str(row.get("subsection") or row.get("section") or "") == number]
    if len(by_number) == 1:
        return by_number[0]
    by_title = [row for row in rows if _normal(row.get("title")) == _normal(node.get("title"))]
    return by_title[0] if len(by_title) == 1 else None


def _find_build(node: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [row for row in rows if _normal(row.get("heading")) == _normal(node.get("title"))]
    return matches[0] if len(matches) == 1 else None


def _comment_count(node: dict[str, Any], comments: list[dict[str, Any]]) -> int:
    title = _normal(node.get("title"))
    number = str(node.get("number") or "")
    count = 0
    for comment in comments:
        headings = [_normal(value) for value in comment.get("heading_path", [])]
        if title in headings or any(number and heading.startswith(_normal(number)) for heading in headings):
            count += 1
    return count


def _revise_states(row: dict[str, Any], issues: list[PipelineIssue], section: str) -> tuple[str, str, str, str]:
    validation = "valid" if row.get("authored") and row.get("edits") is not None else "unknown"
    raw_apply = str(row.get("apply_status") or "").upper()
    if raw_apply == "SECTION_COMPLETE":
        applied = "complete"
    elif raw_apply == "BLOCKED":
        applied = "blocked"
    elif raw_apply == "NOT_STARTED":
        applied = "not_started"
    elif raw_apply in {"PARTIAL_COMPLETE", "IN_PROGRESS"} or row.get("completed") or row.get("next_edit"):
        applied = "partial"
    else:
        applied = "unknown"
        issues.append(PipelineIssue(code="APPLY_STATE_UNKNOWN", section=section,
                                    message="The change file has no authoritative apply state."))
    review = str(row.get("review_result") or "not_started").lower().replace(" ", "_")
    cleanup = "complete" if row.get("cleaned") is True else "not_started" if row.get("cleaned") is False else "unknown"
    return validation, applied, review, cleanup


def _build_states(row: dict[str, Any], issues: list[PipelineIssue], section: str) -> tuple[str, str, str, str]:
    if row.get("problem"):
        validation = "failed"
        issues.append(PipelineIssue(code="SECTION_FILE_INVALID", section=section, message=str(row["problem"])))
    else:
        validation = str(row.get("review") or "unknown").lower().replace(" ", "_")
    status = str(row.get("status") or "").lower()
    applied = "complete" if status == "built" else "not_started" if status in {"draft", "ready"} else "unknown"
    if applied == "unknown":
        issues.append(PipelineIssue(code="BUILD_STATE_UNKNOWN", section=section,
                                    message="The section file has no authoritative placement state."))
    review = str(row.get("review") or "unknown").lower().replace(" ", "_")
    return validation, applied, review, "not_applicable"


def _etag(project: dict[str, str], spec: dict[str, Any], status: list[dict[str, Any]],
          build: list[dict[str, Any]]) -> str:
    paths: set[Path] = set()
    for value in (spec.get("source"), spec.get("template_file")):
        if value:
            paths.add(Path(value).expanduser())
    for row in status:
        for value in [row.get("change_file"), *(row.get("other_change_files") or [])]:
            if value:
                paths.add(Path(value).expanduser())
    work = Path(project["work_dir"]).expanduser()
    for row in build:
        if row.get("file"):
            paths.add(work / "sections" / str(row["file"]))
    for pattern in ("run-state/*.md", "section-reviews/*.md", "spec/*.json"):
        paths.update(work.glob(pattern))
    digest = hashlib.sha256()
    for path in sorted(paths, key=str):
        try:
            stat = path.stat()
        except OSError:
            digest.update(f"{path}:missing\n".encode())
        else:
            digest.update(f"{path}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    return '"' + digest.hexdigest() + '"'


def snapshot(agents_dir: Path, project: dict[str, str], *, runner: Runner | None = None) -> PipelineSnapshot:
    run = runner or (lambda operation: _run(agents_dir, project, operation))
    status = run("status")
    next_rows = run("next")
    build = run("sections")
    spec = run("spec_status")
    comments = run("comments")
    if not isinstance(status, list) or not isinstance(next_rows, list) or not isinstance(build, list):
        raise HTTPException(502, "Pipeline commands returned an unexpected structure")
    if not isinstance(spec, dict):
        raise HTTPException(502, "Document specification returned an unexpected structure")
    if not isinstance(comments, list):
        comments = []

    global_issues: list[PipelineIssue] = []
    nodes = spec.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        global_issues.append(PipelineIssue(code="MANIFEST_UNAVAILABLE",
                                           message="The document specification has no ordered section manifest."))
    document_path = _path(spec.get("source"))
    if document_path is None or not document_path.is_file():
        global_issues.append(PipelineIssue(code="DOCUMENT_IDENTITY_UNKNOWN",
                                           message="The document specification does not identify a readable document."))
    lock = word_lock(project)
    sections: list[PipelineSection] = []
    matched_revise: set[int] = set()
    matched_build: set[int] = set()
    for node in nodes:
        if not node.get("number") and not node.get("key"):
            continue
        revise = _find_revise(node, status)
        section_build = _find_build(node, build)
        if revise:
            matched_revise.add(id(revise))
        if section_build:
            matched_build.add(id(section_build))
        section_id = str(node.get("number") or node.get("key") or "unknown")
        issues: list[PipelineIssue] = []
        lane = _lane(node, revise, section_build)
        if revise and section_build:
            issues.append(PipelineIssue(code="AMBIGUOUS_LANE", section=section_id,
                                        message="Both revise and build records claim this document section."))
        if revise:
            validation, applied, review, cleanup = _revise_states(revise, issues, section_id)
            activity = _newest([path for path in [_path(revise.get("change_file"))] if path])
        elif section_build:
            validation, applied, review, cleanup = _build_states(section_build, issues, section_id)
            section_path = Path(project["work_dir"]).expanduser() / "sections" / str(section_build.get("file"))
            activity = _newest([section_path])
        else:
            validation = applied = review = cleanup = "unknown"
            activity = None
            issues.append(PipelineIssue(code="PIPELINE_RECORD_MISSING", section=section_id,
                                        message="This document section has no revise or build pipeline record."))
        sections.append(PipelineSection(
            visible_number=str(node.get("number") or ""), stable_key=str(node.get("key") or ""),
            stable_path=node.get("path"), heading=str(node.get("title") or "Untitled section"), lane=lane,
            change_file=revise.get("change_file") if revise else None,
            section_file=section_build.get("file") if section_build else None,
            validation_result=validation, applied_state=applied, review_verdict=review,
            cleanup_state=cleanup, open_comments=_comment_count(node, comments),
            last_activity=activity, issues=issues,
        ))
    for row in status:
        if id(row) not in matched_revise:
            global_issues.append(PipelineIssue(code="ORPHAN_CHANGE_RECORD",
                                               section=str(row.get("subsection") or row.get("section") or ""),
                                               message="A revise record could not be matched to the document specification."))
    for row in build:
        if id(row) not in matched_build:
            global_issues.append(PipelineIssue(code="ORPHAN_SECTION_FILE", message=f"Section file {row.get('file')} could not be matched to the document specification."))
    next_action = next_rows[0] if next_rows else None
    if next_action is None and any(section.applied_state not in {"complete"} for section in sections):
        global_issues.append(PipelineIssue(code="NEXT_ACTION_UNKNOWN",
                                           message="The framework reported no next action while pipeline work remains unresolved."))
    stat = document_path.stat() if document_path and document_path.is_file() else None
    etag = _etag(project, spec, status, build)
    return PipelineSnapshot(
        project_key=project["key"], project_label=project.get("label", project["key"]),
        spec_mode=project.get("spec_mode", "shadow"),
        assessment_lane="build" if str(project.get("assessment_lane") or "revise").lower() == "build" else "revise",
        document=PipelineDocument(path=str(document_path) if document_path else None,
                                  name=document_path.name if document_path else None,
                                  size=stat.st_size if stat else None, modified_at=_mtime(document_path)),
        word_locked=lock is not None, word_lock_file=lock.name if lock else None,
        next_action=next_action, sections=sections, issues=global_issues, etag=etag,
    )
