"""Framework orchestration for applying a reviewed Improve proposal."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import improve_context, improve_lane, improve_state, rating_pass


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def rating_summary(work, key, document):
    root = improve_state.improve_root(work)
    applied = next((run for run in reversed(improve_state.read_runs(root))
                    if run.get("section_key") == key and run.get("status") == "applied"), None)
    if not applied:
        return rating_pass.load_summary(work, key)
    rating = applied.get("rating") or {}
    if rating.get("status") != "OK":
        return None
    data = _json(rating_pass.ratings_path(root / key, key)) or {}
    runs = data.get("runs") or []
    if applied.get("document_hash") != improve_lane._document_hash(document):
        context = _json(root / key / "context.json") or {}
        text, _ = _rating_input(work, key, document, context)
        digest = sha256(text.encode("utf-8")).hexdigest()
        if not runs or runs[-1].get("sheet_sha256") != digest:
            return None
    return rating_pass.summary(data)


def _rating_input(work, key, document, context):
    card_path = work / "cards" / f"{key}.json"
    card = _json(card_path) or {}
    questions = [q for q in card.get("questions", []) if q.get("id")]
    section = improve_context.extract_section(document, context["section_key"], context.get("heading"))
    text = "Rate the applied DOCX subsection below against the listed card questions. The subsection is rendered document content; it has no answer-sheet Facts fields.\n"
    text += json.dumps(questions, ensure_ascii=False) + "\n\n"
    text += "\n".join(block["text"] for block in section["blocks"])
    return text, [q["id"] for q in questions]


def _rate_document(work, root, key, document, context, template):
    if not template:
        return {"status": "SKIPPED", "message": "No rating model configured"}
    text, ids = _rating_input(work, key, document, context)
    return rating_pass.rate_text(work, text, ids, key,
                                 root / key, template, output_dir=root / key)


def _refresh_context_for_apply(document: Path, context: dict[str, Any], proposal: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refresh a proposal after an unrelated section changed the DOCX.

    Improve proposals are scoped to one subsection, while the document hash is
    necessarily for the whole DOCX.  A prior improvement to another section
    should not invalidate an otherwise unchanged proposal.  Rebase only when
    every proposed ``before`` value is still present in the freshly extracted
    subsection; any real conflict remains a stale-proposal error in the shared
    lane.
    """
    current_hash = "sha256:" + sha256(document.read_bytes()).hexdigest()
    if context.get("document_hash") == current_hash and proposal.get("base_document_hash") == current_hash:
        return context, proposal
    extracted = improve_context.extract_section(
        document,
        str(context.get("section_key") or proposal.get("section_key") or ""),
        str(context.get("heading") or ""),
    )
    answer_text = "\n".join(block["text"] for block in extracted["blocks"])
    typed = improve_lane.ImprovementProposal.from_dict(proposal)
    for edit in typed.edits:
        if edit.operation != "keep" and edit.before not in answer_text:
            # Keep the old context/hash so the normal stale/conflict error is
            # returned rather than silently rebasing a changed subsection.
            return context, proposal
    refreshed = dict(context)
    refreshed.update({
        "heading": extracted["heading"],
        "blocks": extracted["blocks"],
        "answer_text": answer_text,
        "document_hash": current_hash,
        "base_document_hash": current_hash,
    })
    rebased = dict(proposal)
    rebased["base_document_hash"] = current_hash
    return refreshed, rebased


def _document_already_contains_proposal(document: Path, context: dict[str, Any], proposal: dict[str, Any]) -> bool:
    """Detect a prior DOCX mutation whose follow-up bookkeeping failed."""
    extracted = improve_context.extract_section(
        document,
        str(context.get("section_key") or proposal.get("section_key") or ""),
        str(context.get("heading") or ""),
    )
    answer_text = "\n".join(block["text"] for block in extracted["blocks"])
    edits = [edit for edit in improve_lane.ImprovementProposal.from_dict(proposal).edits
             if edit.operation != "keep"]
    def applied(edit):
        if edit.operation == "delete_row":
            return edit.before not in answer_text
        if edit.operation == "insert_row":
            return edit.before in answer_text and edit.after in answer_text
        return edit.before not in answer_text and edit.after in answer_text
    return bool(edits) and all(applied(edit) for edit in edits)


def apply_saved(work: Path, key: str, document: Path, model_template, *, cli=None) -> dict[str, Any]:
    root = improve_state.improve_root(work)
    context = _json(root / key / "context.json")
    proposal = improve_state.read_proposal(root, key)
    if not context or not proposal:
        return {"status": "BLOCKED", "errors": ["Improve context and proposal are required"]}
    already_applied = _document_already_contains_proposal(document, context, proposal)
    original_context = context
    original_proposal = proposal
    context, proposal = _refresh_context_for_apply(document, context, proposal)
    # Recover an older partial apply only after locating every post-image
    # in the target subsection. Validate the proposal's evidence and wording.
    if already_applied:
        recovery_context = dict(original_context)
        typed_original = improve_lane.ImprovementProposal.from_dict(original_proposal)
        recovery_context.update({
            "document_hash": original_proposal.get("base_document_hash"),
            # The DOCX table representation is not reproduced in the answer
            # sheet.  Include the proposal's own pre-images for the contract
            # check; the explicit already-applied detection above has already
            # proven that the current DOCX contains every corresponding
            # post-image instead.
            "answer_text": "\n".join(edit.before for edit in typed_original.edits if edit.operation != "keep"),
        })
        checked = improve_lane.check(original_proposal, recovery_context)
    else:
        checked = improve_lane.check(proposal, context)
    if not checked["valid"]:
        return {"status": "BLOCKED", "errors": checked["errors"]}
    if improve_state.repeated_proposal(root, key, original_proposal):
        return {"status": "BLOCKED", "errors": ["This identical proposal was already considered without a new document mutation."], "repeated": True}
    result = ({"status": "OK", "backup": None, "document_hash": "sha256:" + sha256(document.read_bytes()).hexdigest(),
               "section_key": proposal.get("section_key"), "edit_count": len([edit for edit in improve_lane.ImprovementProposal.from_dict(proposal).edits if edit.operation != "keep"]),
               "recovered": True}
              if already_applied else improve_lane.apply_proposal(document, proposal, context, root / "backups"))
    run = improve_state.latest_run(root, key)
    selected_cli = cli or (run or {}).get("cli") or "evo"
    if not run or run.get("status") == "applied":
        run = improve_state.new_run(key, base_document_hash=proposal.get("base_document_hash"))
        run["proposal_hash"] = improve_state.proposal_hash(proposal)
    if run:
        run.update({"status": "applied", "document_hash": result["document_hash"],
                    "proposal_hash": improve_state.proposal_hash(original_proposal), "cli": selected_cli,
                    "rating": None, "error": None})
        improve_state.write_run(root, run)
    pending = improve_state.proposal_path(root, key)
    if improve_state.read_proposal(root, key) == original_proposal:
        pending.unlink()
    try:
        rating = _rate_document(work, root, key, document, context, model_template(selected_cli))
    except Exception as exc:  # keep Apply successful even if rating is unavailable
        rating = {"status": "ERROR", "message": str(exc)}
    result["rating"] = rating
    run.update({"rating": rating, "error": None})
    improve_state.write_run(root, run)
    return result
