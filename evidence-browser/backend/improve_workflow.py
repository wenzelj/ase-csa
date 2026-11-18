"""Read-only Evidence Browser projection for the standalone Improve lane."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))

from csa_docx import improve_apply, improve_context, improve_lane, improve_state

from . import documents, draft_workflow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _state(root: Path, key: str) -> dict[str, Any]:
    run = improve_state.latest_run(root, key)
    history = [item for item in improve_state.read_runs(root) if item.get("section_key") == key]
    applied = next((item for item in reversed(history) if item.get("status") == "applied"), None)
    attempts = [item for item in reversed(history) if item.get("status") in {"failed", "interrupted", "stale"}]
    proposal = improve_state.read_proposal(root, key)
    context = _json(root / key / "context.json")
    if proposal:
        label = "proposal-ready"
    elif run:
        label = str(run.get("status") or "unknown")
    elif context:
        label = "context-ready"
    else:
        label = "not-started"
    return {
        "state": label,
        "run": run,
        "proposal_available": bool(proposal),
        "context_available": bool(context),
        "document_hash": (context or {}).get("document_hash"),
        "answer_run_id": (context or {}).get("answer_run_id"),
        "provenance": (context or {}).get("provenance", "legacy/unknown"),
        "last_applied": applied,
        "failed_attempts": attempts[:5],
        "history_count": len(history),
    }


def snapshot(agents_dir: Path, project: dict[str, str]) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    root = improve_state.improve_root(work)
    draft = draft_workflow.snapshot(agents_dir, project)
    sections = []
    document_hash = None
    hash_checked = False
    for row in draft.get("sections", []):
        item = dict(row)
        item["eligible"] = row.get("state") != "not-answered"
        item["improve"] = _state(root, row.get("key", "")) if item["eligible"] else {
            "state": "unavailable", "reason": "no answer has reached the working document",
        }
        applied = item["improve"].get("last_applied")
        if applied:
            if not hash_checked:
                hash_checked = True
                try:
                    document_hash = improve_lane._document_hash(_working_document(project))
                except (OSError, ValueError):
                    pass
            rating = applied.get("rating") or {}
            item["rating"] = ({"latest": rating["average"]}
                              if rating.get("status") == "OK" and applied.get("document_hash") == document_hash
                              else None)
            if item["rating"] is None and rating.get("status") == "OK" and document_hash:
                try:
                    item["rating"] = improve_apply.rating_summary(work, row["key"], _working_document(project))
                except (OSError, ValueError, KeyError):
                    pass
        sections.append(item)
    return {
        "project_key": project["key"],
        "stage": str(project.get("stage") or "draft").strip().lower(),
        "generated_at": _now(),
        "sections": sections,
        "eligible_count": sum(1 for row in sections if row.get("eligible")),
        "proposal_count": sum(1 for row in sections if row.get("improve", {}).get("proposal_available")),
    }


def section(agents_dir: Path, project: dict[str, str], key: str) -> dict[str, Any]:
    snap = snapshot(agents_dir, project)
    row = next((item for item in snap["sections"] if item.get("key") == key or item.get("number") == key), None)
    if row is None:
        return {"status": "NOT_FOUND", "section": key, "message": "section is not in the document specification"}
    if not row.get("eligible"):
        return {"status": "UNAVAILABLE", "section": key, "message": "no answer has reached the working document", "row": row}
    work = Path(project["work_dir"]).expanduser()
    root = improve_state.improve_root(work)
    actual_key = row.get("key", key)
    context = _json(root / actual_key / "context.json")
    # The saved context may predate the full-subsection extractor. Refresh the
    # document projection on every detail read while preserving evidence and
    # run metadata from the bounded Improve context.
    try:
        resolved = documents.resolve(project)
        if resolved.get("state") == "ready" and resolved.get("path"):
            document = Path(str(resolved["path"]))
            extracted = improve_context.extract_section(document, str(row.get("number") or actual_key), str(row.get("title") or ""))
            fresh = dict(context or {})
            fresh.update({
                "section_key": str(row.get("number") or actual_key),
                "heading": extracted["heading"],
                "answer_text": "\n".join(block["text"] for block in extracted["blocks"]),
                "blocks": extracted["blocks"],
                "document_hash": "sha256:" + __import__("hashlib").sha256(document.read_bytes()).hexdigest(),
            })
            context = fresh
            section_dir = root / actual_key
            section_dir.mkdir(parents=True, exist_ok=True)
            (section_dir / "context.json").write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError):
        if not context:
            context = None
    proposal = improve_state.read_proposal(root, actual_key)
    latest_run = improve_state.latest_run(root, actual_key)
    return {
        "status": "OK",
        "section": actual_key,
        "row": row,
        "current": {
            "heading": (context or {}).get("heading"),
            "text": (context or {}).get("answer_text"),
            "blocks": (context or {}).get("blocks", []),
            "rating": row.get("rating"),
            "document_hash": (context or {}).get("document_hash"),
            "provenance": (context or {}).get("provenance", "legacy/unknown"),
        },
        "findings": (context or {}).get("findings", []),
        "open_questions": (context or {}).get("open_questions", []),
        "reader_review": (context or {}).get("reader_review", ""),
        "rating_summary": (context or {}).get("rating_summary", {}),
        "rating_findings": (context or {}).get("rating_findings", []),
        "improvement_findings": (context or {}).get("improvement_findings", []),
        "gap_searches": ((context or {}).get("subsection_data") or {}).get("gap_searches", []),
        "evidence": {
            "supporting_ids": (context or {}).get("supporting_evidence_ids", []),
            "new": (context or {}).get("new_evidence", []),
            "related": (context or {}).get("related_evidence", []),
        },
        "proposal": proposal,
        "latest_run": latest_run,
    }


def _working_document(project: dict[str, str]) -> Path:
    resolved = documents.resolve(project)
    if resolved.get("state") != "ready" or not resolved.get("path"):
        raise ValueError("The authoritative working document is ambiguous or unavailable.")
    document = Path(str(resolved["path"]))
    if not document.is_file():
        raise ValueError(f"The working document is missing: {document.name}.")
    return document


def _model_template(cli: str = "evo") -> str:
    """Read the selected rating CLI from the shared framework config."""
    config = FRAMEWORK.parent / "cli.yaml"
    if not config.is_file():
        return ""
    prefix = f"{cli}_headless:"
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""




def check_proposal(project: dict[str, str], key: str, proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    root = improve_state.improve_root(work)
    context = _json(root / key / "context.json")
    proposal = proposal or improve_state.read_proposal(root, key)
    if not context or not proposal:
        return {"valid": False, "errors": ["Improve context and proposal are required"], "section_key": key}
    result = improve_lane.check(proposal, context)
    result["proposal"] = proposal
    return result


def apply_proposal(project: dict[str, str], key: str, cli: str | None = None) -> dict[str, Any]:
    return improve_apply.apply_saved(Path(project["work_dir"]).expanduser(), key,
                                     _working_document(project), _model_template, cli=cli)


def discard_proposal(project: dict[str, str], key: str) -> dict[str, Any]:
    root = improve_state.improve_root(Path(project["work_dir"]).expanduser())
    path = improve_state.proposal_path(root, key)
    if path.is_file():
        path.unlink()
    run = improve_state.latest_run(root, key)
    if run:
        run.update({"status": "discarded", "error": None})
        improve_state.write_run(root, run)
    return {"status": "OK", "section_key": key, "discarded": True}
