"""Safe, no-apply author and card workflow for the CSA editing workspace."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import commands, documents, jobs, pipeline, sections
from .models import AuthorOutcomeSummary, AuthorPreflight, CommandRequest


Runner = Callable[[str], Any]
ARTIFACT_NAMES = {
    "brief": "Author brief",
    "card": "Section card",
    "card_json": "Section card data",
    "answer_sheet": "Answer sheet",
    "answer_check": "Answer check",
    "answer_errors": "Answer errors",
    "search_notes": "Evidence search notes",
    "author_report": "Author report",
    "timing": "Run timing",
}


def _run(agents_dir: Path, project: dict[str, str], runner: Runner | None, operation: str) -> Any:
    return (runner or (lambda name: pipeline._run(agents_dir, project, name)))(operation)


def _job_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def _normal_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    if not key or not commands.SAFE_SECTION.fullmatch(key):
        raise HTTPException(422, "Invalid section identifier")
    return key


def _matching_row(rows: Any, section: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    wanted = section.casefold()
    matches = [row for row in rows if isinstance(row, dict) and wanted in {
        str(row.get("section") or "").casefold(), str(row.get("subsection") or "").casefold(),
        str(row.get("stable_key") or row.get("key") or "").casefold(),
    }]
    return matches[0] if len(matches) == 1 else {}


def _section_identity(status: Any, builds: Any, section: str,
                      resolved: dict[str, Any] | None = None) -> tuple[str, str, str]:
    stable_key = str((resolved or {}).get("key") or section)
    number = str((resolved or {}).get("number") or section)
    revise = _matching_row(status, number) or _matching_row(status, section)
    build = _matching_row(builds, number) or _matching_row(builds, stable_key) or _matching_row(builds, section)
    row = revise or build
    stable_key = str(row.get("stable_key") or row.get("key") or stable_key)
    number = str(row.get("subsection") or row.get("section") or row.get("number") or number)
    return _normal_key(stable_key), number, "revise" if revise else "build" if build else "revise"


def _resolved_node(agents_dir: Path, project: dict[str, str], runner: Runner | None,
                   section: str) -> dict[str, Any] | None:
    try:
        spec = _run(agents_dir, project, runner, "spec_status")
        if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list):
            return None
        resolver = sections._resolver(agents_dir)
    except (HTTPException, OSError, ValueError, AttributeError, AssertionError):
        return None
    try:
        return resolver.resolve(spec, section)
    except resolver.ResolveError as error:
        raise HTTPException(409 if "more than one" in str(error) else 404, str(error)) from error


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _document_hash(project: dict[str, str]) -> str:
    try:
        metadata = documents.metadata(project)
        path = Path(str(metadata.get("path") or "")).expanduser()
        return _sha256(path) or "unavailable"
    except (HTTPException, OSError, ValueError):
        return "unavailable"


def _artifact_paths(project: dict[str, str], stable_key: str) -> dict[str, Path]:
    work = Path(project["work_dir"]).expanduser().resolve()
    author = work / "author" / stable_key
    cards = work / "cards"
    return {
        "brief": author / "brief.md", "card": cards / f"{stable_key}.md",
        "card_json": cards / f"{stable_key}.json", "answer_sheet": cards / f"{stable_key}.answer.md",
        "answer_check": cards / f"{stable_key}.check.md", "answer_errors": cards / f"{stable_key}.errors.md",
        "search_notes": author / "search-notes.md", "author_report": author / "author-report.md",
        "timing": author / "timing.json",
    }


def _artifact_rows(project: dict[str, str], stable_key: str) -> list[dict[str, Any]]:
    rows = []
    for key, path in _artifact_paths(project, stable_key).items():
        digest = _sha256(path)
        rows.append({"key": key, "label": ARTIFACT_NAMES[key], "exists": digest is not None,
                     "hash": digest, "size": path.stat().st_size if digest is not None else None})
    return rows


def _safe_selected_file(project: dict[str, str], row: dict[str, Any]) -> Path | None:
    raw = row.get("change_file") or row.get("file")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = Path(project["work_dir"]).expanduser() / "sections" / path
    path = path.resolve()
    roots = [Path(project[name]).expanduser().resolve() for name in ("project_root", "work_dir") if project.get(name)]
    if not path.is_file() or not any(path == root or root in path.parents for root in roots):
        return None
    return path


def _evidence(project: dict[str, str], section: str, stable_key: str) -> list[dict[str, str]]:
    path = Path(project["work_dir"]).expanduser() / "evidence-matrix.csv"
    if not path.is_file():
        return []
    wanted = {section.casefold(), stable_key.casefold(), stable_key.replace("-", " ").casefold()}
    result = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                scope = " ".join(str(row.get(key) or "") for key in ("section", "csa_area", "question", "claim")).casefold()
                if not any(value and value in scope for value in wanted):
                    continue
                result.append({key: str(row.get(key) or "") for key in
                               ("evidence_id", "status", "review_state", "question", "claim", "source_title", "page_or_location")})
    except (OSError, csv.Error):
        return []
    return result


def _cards(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    questions = value.get("questions", []) if isinstance(value, dict) else []
    return [{"id": str(row.get("id") or row.get("qid") or ""),
             "question": str(row.get("question") or row.get("text") or "")}
            for row in questions if isinstance(row, dict)]


def _fingerprint(project_key: str, section: str, document_hash: str,
                 evidence: list[dict[str, str]]) -> str:
    value = {"project": project_key, "section": section, "document": document_hash,
             "evidence": [(row.get("evidence_id"), row.get("status"), row.get("review_state")) for row in evidence]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _job_target(job: dict[str, Any]) -> str:
    args = [str(value) for value in job.get("display_args", [])]
    try:
        position = args.index("author")
    except ValueError:
        position = -1
    for value in args[position + 1:]:
        if not value.startswith("-"):
            return value
    return ""


def setup(agents_dir: Path, project: dict[str, str], section: str, *,
          runner: Runner | None = None, manager: jobs.JobManager | None = None) -> dict[str, Any]:
    """Return bounded inputs and artifacts for a no-apply author run."""
    commands.build_argv(agents_dir, project["key"], "author", CommandRequest(target=section))
    status = _run(agents_dir, project, runner, "status")
    builds = _run(agents_dir, project, runner, "sections")
    node = _resolved_node(agents_dir, project, runner, section)
    stable_key, number, lane = _section_identity(status, builds, section, node)
    selected = _matching_row(status, number) or _matching_row(status, section) or \
        _matching_row(builds, number) or _matching_row(builds, stable_key) or _matching_row(builds, section)
    proposal_path = _safe_selected_file(project, selected)
    artifacts = _artifact_rows(project, stable_key)
    evidence = _evidence(project, number, stable_key)
    document_hash = _document_hash(project)
    prior = []
    if manager is not None:
        prior = [_job_dict(job) for job in manager.list(project)]
        prior = [job for job in prior if job.get("operation") == "author" and _job_target(job) == section]
    exists = {row["key"]: row["exists"] for row in artifacts}
    stages = [
        {"key": "evidence", "label": "Evidence collection", "state": "ready" if evidence else "attention"},
        {"key": "card", "label": "Card preparation", "state": "ready" if exists["card"] else "pending"},
        {"key": "answer", "label": "Answer generation", "state": "ready" if exists["answer_sheet"] else "pending"},
        {"key": "writer", "label": "Writer output", "state": "ready" if proposal_path else "pending"},
        {"key": "proposal", "label": "Proposal editor", "state": "ready" if proposal_path else "pending"},
        {"key": "validation", "label": "Validation", "state": str(selected.get("validation") or selected.get("review") or "pending")},
    ]
    return {
        "project_key": project["key"], "section": section, "visible_number": number,
        "stable_key": stable_key, "lane": lane, "document_hash": document_hash,
        "model_route": {"author": "registered author agent", "answer": "registered answer agent"},
        "no_apply": True, "cards_available": True,
        "selected_cards": _cards(_artifact_paths(project, stable_key)["card_json"]),
        "author_brief": next(row for row in artifacts if row["key"] == "brief"),
        "answer_sheet": next(row for row in artifacts if row["key"] == "answer_sheet"),
        "evidence": evidence, "artifacts": artifacts, "stages": stages,
        "existing_proposal": {"exists": proposal_path is not None, "file": proposal_path.name if proposal_path else None,
                              "hash": _sha256(proposal_path), "validation": stages[-1]["state"]},
        "prior_runs": len(prior),
        "input_hash": _fingerprint(project["key"], section, document_hash, evidence),
    }


def preflight(agents_dir: Path, project: dict[str, str], section: str, *, cards: bool = False,
              runner: Runner | None = None, manager: jobs.JobManager | None = None) -> AuthorPreflight:
    current = setup(agents_dir, project, section, runner=runner, manager=manager)
    return AuthorPreflight(section=section, stable_key=current["stable_key"], lane=current["lane"],
                           cards=cards, no_apply=True, document_hash=current["document_hash"],
                           input_hash=current["input_hash"], existing_proposal=current["existing_proposal"],
                           prior_author_jobs=current["prior_runs"])


def _context_path(project: dict[str, str], job_id: str) -> Path:
    return Path(project["work_dir"]).expanduser() / "ui-jobs" / job_id / "author-context.json"


def _write_context(project: dict[str, str], job_id: str, current: dict[str, Any], cards: bool) -> None:
    path = _context_path(project, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"project_key": project["key"], "section": current["section"], "stable_key": current["stable_key"],
             "document_hash": current["document_hash"], "input_hash": current["input_hash"], "cards": cards,
             "artifact_hashes_before": {row["key"]: row["hash"] for row in current["artifacts"]}}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_context(project: dict[str, str], job_id: str) -> dict[str, Any]:
    try:
        value = json.loads(_context_path(project, job_id).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def submit(agents_dir: Path, project: dict[str, str], section: str, *, cards: bool = False,
           manager: jobs.JobManager | None = None, runner: Runner | None = None) -> dict[str, Any]:
    current = setup(agents_dir, project, section, runner=runner, manager=manager)
    request = CommandRequest(target=section, options={"no_apply": True, "cards": cards})
    manager = manager or jobs.JobManager(agents_dir)
    job = manager.submit(project, "author", request)
    row = _job_dict(job)
    _write_context(project, str(row["id"]), current, cards)
    return {"job": row, "section": section, "cards": cards, "no_apply": True,
            "input_hash": current["input_hash"]}


def outcome(job: dict[str, Any], current: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    raw_state = str(job.get("state") or "unknown").lower()
    output = " ".join(str(job.get(key) or "") for key in ("message", "stdout_tail", "stderr_tail")).casefold()
    if raw_state in {"queued", "running"}:
        state = raw_state.upper()
    elif raw_state == "succeeded":
        artifact_state = {row["key"]: row["exists"] for row in current["artifacts"]}
        if context.get("cards") and not (artifact_state.get("card") and artifact_state.get("answer_sheet")):
            state = "MISSING_CARDS"
        elif not current["existing_proposal"]["exists"]:
            state = "MALFORMED_OUTPUT"
        elif not current["evidence"]:
            state = "INCOMPLETE_EVIDENCE"
        else:
            state = "DRAFTED"
    elif raw_state == "cancelled":
        state = "CANCELLED"
    elif raw_state == "interrupted":
        state = "INTERRUPTED"
    elif "timed out" in output or "timeout" in output:
        state = "TIMEOUT"
    elif "blocked" in output or "missing card" in output or "missing evidence" in output:
        state = "BLOCKED"
    else:
        state = "ERROR"
    current_run = bool(context) and context.get("project_key") == current["project_key"] and \
        context.get("section") == current["section"] and context.get("document_hash") == current["document_hash"] and \
        context.get("input_hash") == current["input_hash"]
    reasons = []
    if not current_run:
        reasons.append("The saved run belongs to different or older section inputs and is not current.")
    if state == "MALFORMED_OUTPUT":
        reasons.append("The author command completed without a framework-selected proposal.")
    elif state == "MISSING_CARDS":
        reasons.append("Card authoring completed without both a section card and answer sheet.")
    elif state == "INCOMPLETE_EVIDENCE":
        reasons.append("The author command completed, but the section has no inspectable evidence set.")
    elif state in {"ERROR", "TIMEOUT", "BLOCKED", "CANCELLED", "INTERRUPTED"}:
        reasons.append(str(job.get("message") or job.get("stderr_tail") or f"Author run ended as {state}.")[:800])
    return AuthorOutcomeSummary(
        state=state, section=current["section"], lane=current["lane"], current=current_run,
        input_hash=str(context.get("input_hash") or ""), document_hash=str(context.get("document_hash") or ""),
        proposal=current["existing_proposal"], artifacts=current["artifacts"], stages=current["stages"],
        evidence=current["evidence"], routed_to_editor=state == "DRAFTED" and current_run,
        routed_to_validation=state == "DRAFTED" and current_run,
        warnings=[value for value in [str(job.get("stderr_tail") or "").strip()] if value],
        non_success_reasons=reasons,
    ).model_dump()


def get_job(agents_dir: Path, project: dict[str, str], section: str, job_id: str, *,
            manager: jobs.JobManager | None = None, runner: Runner | None = None) -> dict[str, Any]:
    manager = manager or jobs.JobManager(agents_dir)
    job = _job_dict(manager.get(project, job_id))
    if job.get("operation") != "author" or _job_target(job) != section:
        raise HTTPException(404, "Author job not found for this section")
    current = setup(agents_dir, project, section, runner=runner, manager=manager)
    return {"job": job, "outcome": outcome(job, current, _read_context(project, job_id))}


def latest(agents_dir: Path, project: dict[str, str], section: str, *,
           manager: jobs.JobManager | None = None, runner: Runner | None = None) -> dict[str, Any] | None:
    manager = manager or jobs.JobManager(agents_dir)
    matches = [_job_dict(job) for job in manager.list(project)]
    matches = [job for job in matches if job.get("operation") == "author" and _job_target(job) == section]
    if not matches:
        return None
    matches.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    job = matches[0]
    current = setup(agents_dir, project, section, runner=runner, manager=manager)
    return {"job": job, "outcome": outcome(job, current, _read_context(project, str(job["id"])))}


def artifact(project: dict[str, str], section: str, artifact_key: str, *,
             agents_dir: Path, runner: Runner | None = None) -> tuple[str, str]:
    if artifact_key not in ARTIFACT_NAMES:
        raise HTTPException(404, "Unknown author artifact")
    status = _run(agents_dir, project, runner, "status")
    builds = _run(agents_dir, project, runner, "sections")
    stable_key, _, _ = _section_identity(status, builds, section,
                                          _resolved_node(agents_dir, project, runner, section))
    path = _artifact_paths(project, stable_key)[artifact_key]
    if not path.is_file():
        raise HTTPException(404, "Author artifact is unavailable")
    try:
        return path.read_text(encoding="utf-8"), "application/json" if path.suffix == ".json" else "text/plain"
    except OSError as error:
        raise HTTPException(409, "Author artifact cannot be read") from error
