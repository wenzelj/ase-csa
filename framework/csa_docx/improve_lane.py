"""Deterministic checks for proposals in the standalone CSA Improve lane."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

from .improve_contract import ImprovementProposal, validate_proposal


_FUTURE_WORDS = ("should", "recommend", "recommended", "future state", "target state")
_ABSENCE_ONLY = ("not found", "no evidence", "not observed", "no record")


def _context_evidence_ids(context: Mapping[str, Any]) -> set[str]:
    ids = set(context.get("supporting_evidence_ids") or ())
    for key in ("new_evidence", "related_evidence"):
        for row in context.get(key) or ():
            if isinstance(row, Mapping) and row.get("evidence_id"):
                ids.add(str(row["evidence_id"]))
    return ids


def validate_for_context(
    proposal: ImprovementProposal | Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate a proposal against the exact current-answer context.

    This function is intentionally read-only.  It does not apply edits, call a
    model or search the index.
    """
    errors = list(validate_proposal(proposal))
    if errors:
        return tuple(errors)
    typed = proposal if isinstance(proposal, ImprovementProposal) else ImprovementProposal.from_dict(proposal)
    if typed.section_key != context.get("section_key"):
        errors.append("proposal section_key does not match the context")
    if typed.base_document_hash != context.get("document_hash"):
        errors.append("proposal base_document_hash is stale")
    answer_text = str(context.get("answer_text") or "")
    available = _context_evidence_ids(context)
    cited = set(typed.evidence_ids)
    for edit in typed.edits:
        cited.update(edit.evidence_ids)
        if edit.operation != "keep" and edit.before not in answer_text:
            errors.append(f"{edit.block_id}: before text is not in the current answer")
        if re.search(r"\bE-\d+\b", edit.after):
            errors.append(f"{edit.block_id}: evidence IDs belong in evidence_ids metadata, not answer text")
        if any(word in f"{edit.after} {edit.reason}".lower() for word in _FUTURE_WORDS):
            errors.append(f"{edit.block_id}: future-state recommendations are not current-state edits")
    unknown = sorted(cited - available)
    if unknown:
        errors.append("proposal cites evidence outside the supplied context: " + ", ".join(unknown))
    if typed.rating_decision == "change" and typed.new_rating == "Not Met":
        basis = (typed.rating_basis or "").lower()
        if any(phrase in basis for phrase in _ABSENCE_ONLY):
            errors.append("Not Met cannot be based only on an absence of evidence")
    return tuple(dict.fromkeys(errors))


def check(proposal: ImprovementProposal | Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_for_context(proposal, context)
    return {"valid": not errors, "errors": list(errors), "section_key": context.get("section_key"),
            "base_document_hash": context.get("document_hash")}


def _document_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _apply_text(path: Path, proposal: ImprovementProposal) -> None:
    text = path.read_text(encoding="utf-8")
    for edit in proposal.edits:
        if edit.operation == "keep":
            continue
        if edit.before not in text:
            raise ValueError(f"{edit.block_id}: before text is no longer in the document")
        replacement = edit.after if edit.operation == "replace_sentence" else edit.before + "\n" + edit.after
        text = text.replace(edit.before, replacement, 1)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _apply_docx(path: Path, proposal: ImprovementProposal) -> None:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - depends on the host runtime
        raise ValueError("python-docx is required for draft Improve application") from exc
    document = Document(str(path))
    paragraphs = list(document.paragraphs)
    active = False
    selected: list[Any] = []
    heading_re = re.compile(r"^\d+(?:\.\d+)*\b")
    for paragraph in paragraphs:
        text = paragraph.text.strip()
        if text.startswith(proposal.section_key) and (len(text) == len(proposal.section_key) or text[len(proposal.section_key):len(proposal.section_key) + 1].isspace()):
            active = True
            continue
        if active and heading_re.match(text):
            break
        if active:
            selected.append(paragraph)
    answer = "\n".join(paragraph.text for paragraph in selected)
    for edit in proposal.edits:
        if edit.operation == "keep":
            continue
        paragraph = next((item for item in selected if edit.before in item.text), None)
        if paragraph is None:
            raise ValueError(f"{edit.block_id}: before text is no longer in the document")
        if edit.operation == "replace_sentence":
            paragraph.text = paragraph.text.replace(edit.before, edit.after, 1)
        else:
            paragraph.text = paragraph.text + " " + edit.after
    if answer == "\n".join(paragraph.text for paragraph in selected):
        raise ValueError("Improve proposal made no document change")
    temporary = path.with_suffix(path.suffix + ".tmp")
    document.save(str(temporary))
    temporary.replace(path)


def apply_proposal(
    document_path: Path | str,
    proposal: ImprovementProposal | Mapping[str, Any],
    context: Mapping[str, Any],
    backup_dir: Path | str,
) -> dict[str, Any]:
    """Apply a checked proposal with a backup and hash guard.

    This is the draft-stage plain-text path.  It never creates tracked changes.
    """
    source = Path(document_path)
    typed = proposal if isinstance(proposal, ImprovementProposal) else ImprovementProposal.from_dict(proposal)
    errors = validate_for_context(typed, context)
    if errors:
        raise ValueError("cannot apply Improve proposal: " + "; ".join(errors))
    if _document_hash(source) != context.get("document_hash"):
        raise ValueError("working document changed since the Improve proposal was built")
    destination = Path(backup_dir)
    destination.mkdir(parents=True, exist_ok=True)
    backup = destination / f"{source.stem}-before-improve-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{source.suffix}"
    shutil.copy2(source, backup)
    if source.suffix.lower() == ".docx":
        _apply_docx(source, typed)
    else:
        _apply_text(source, typed)
    return {"status": "OK", "backup": str(backup), "document_hash": _document_hash(source),
            "section_key": typed.section_key, "edit_count": len([edit for edit in typed.edits if edit.operation != "keep"])}
