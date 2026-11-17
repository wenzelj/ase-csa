"""Typed contract for the incremental CSA Improve lane.

The Improve lane proposes bounded edits to an answer that is already in the
working document.  This contract is deliberately separate from answer sheets,
change records and draft run state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Mapping


VERSION = "improve-contract-v1"

PROPOSAL_STATUSES = frozenset({"improve", "no_material_change", "blocked"})
RATING_DECISIONS = frozenset({"keep", "change"})
EDIT_OPERATIONS = frozenset({"replace_sentence", "insert_after", "replace_row", "keep"})
RUN_OUTCOMES = frozenset({"proposed", "checked", "applied", "discarded", "stale", "failed", "interrupted"})
_EVIDENCE_ID = re.compile(r"^E-[A-Za-z0-9._-]+$")


class ContractError(ValueError):
    """Raised when a proposal cannot be represented by this contract."""


def _text(value: Any, name: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise ContractError(f"{name} is required")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be a list of strings")
    result = []
    for item in value:
        result.append(_text(item, name))
    return tuple(result)


@dataclass(frozen=True)
class EditOperation:
    block_id: str
    operation: str
    before: str
    after: str = ""
    reason: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EditOperation":
        if not isinstance(value, Mapping):
            raise ContractError("edit must be an object")
        operation = _text(value.get("operation"), "edit.operation")
        if operation not in EDIT_OPERATIONS:
            raise ContractError(f"edit.operation must be one of {sorted(EDIT_OPERATIONS)}")
        evidence_ids = _strings(value.get("evidence_ids"), "edit.evidence_ids")
        invalid = [item for item in evidence_ids if not _EVIDENCE_ID.fullmatch(item)]
        if invalid:
            raise ContractError(f"edit.evidence_ids contains invalid IDs: {', '.join(invalid)}")
        after = _text(value.get("after"), "edit.after", required=operation != "keep")
        return cls(
            block_id=_text(value.get("block_id"), "edit.block_id"),
            operation=operation,
            before=_text(value.get("before"), "edit.before"),
            after=after,
            reason=_text(value.get("reason"), "edit.reason"),
            evidence_ids=evidence_ids,
        )

    def validate(self) -> tuple[str, ...]:
        errors = []
        if self.operation != "keep" and not self.evidence_ids:
            errors.append(f"{self.block_id}: changed edits require evidence_ids")
        if self.operation == "keep" and self.after:
            errors.append(f"{self.block_id}: keep edits cannot contain after text")
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_ids"] = list(self.evidence_ids)
        return result


@dataclass(frozen=True)
class ImprovementProposal:
    section_key: str
    base_document_hash: str
    status: str
    rating_decision: str
    edits: tuple[EditOperation, ...] = field(default_factory=tuple)
    base_answer_run_id: str | None = None
    diagnosis: tuple[str, ...] = field(default_factory=tuple)
    new_rating: str | None = None
    rating_basis: str | None = None
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    remaining_questions: tuple[str, ...] = field(default_factory=tuple)
    version: str = VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImprovementProposal":
        if not isinstance(value, Mapping):
            raise ContractError("proposal must be an object")
        status = _text(value.get("status"), "status")
        if status not in PROPOSAL_STATUSES:
            raise ContractError(f"status must be one of {sorted(PROPOSAL_STATUSES)}")
        rating_decision = _text(value.get("rating_decision", "keep"), "rating_decision")
        if rating_decision not in RATING_DECISIONS:
            raise ContractError(f"rating_decision must be one of {sorted(RATING_DECISIONS)}")
        edits = tuple(EditOperation.from_dict(item) for item in (value.get("edits") or []))
        evidence_ids = _strings(value.get("evidence_ids"), "evidence_ids")
        invalid = [item for item in evidence_ids if not _EVIDENCE_ID.fullmatch(item)]
        if invalid:
            raise ContractError(f"evidence_ids contains invalid IDs: {', '.join(invalid)}")
        return cls(
            version=_text(value.get("version", VERSION), "version"),
            section_key=_text(value.get("section_key"), "section_key"),
            base_document_hash=_text(value.get("base_document_hash"), "base_document_hash"),
            base_answer_run_id=_text(value.get("base_answer_run_id"), "base_answer_run_id", required=False) or None,
            status=status,
            diagnosis=_strings(value.get("diagnosis"), "diagnosis"),
            edits=edits,
            rating_decision=rating_decision,
            new_rating=_text(value.get("new_rating"), "new_rating", required=False) or None,
            rating_basis=_text(value.get("rating_basis"), "rating_basis", required=False) or None,
            evidence_ids=evidence_ids,
            remaining_questions=_strings(value.get("remaining_questions"), "remaining_questions"),
        )

    def validate(self) -> tuple[str, ...]:
        errors = list(edit_error for edit in self.edits for edit_error in edit.validate())
        if self.status == "improve" and not self.edits:
            errors.append("improve proposals require at least one edit")
        if self.status != "improve" and self.edits:
            errors.append(f"{self.status} proposals cannot contain edits")
        if self.rating_decision == "change":
            if not self.new_rating:
                errors.append("rating changes require new_rating")
            if not self.rating_basis:
                errors.append("rating changes require rating_basis")
            if not self.evidence_ids:
                errors.append("rating changes require evidence_ids")
        elif self.new_rating or self.rating_basis:
            errors.append("new_rating and rating_basis require rating_decision=change")
        if self.status == "blocked" and not self.diagnosis:
            errors.append("blocked proposals require diagnosis")
        return tuple(errors)

    def checked(self) -> "ImprovementProposal":
        errors = self.validate()
        if errors:
            raise ContractError("invalid improvement proposal: " + "; ".join(errors))
        return self

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["edits"] = [edit.to_dict() for edit in self.edits]
        for key in ("diagnosis", "evidence_ids", "remaining_questions"):
            result[key] = list(result[key])
        return result


def validate_proposal(value: Mapping[str, Any] | ImprovementProposal) -> tuple[str, ...]:
    """Return deterministic validation messages without mutating the proposal."""
    try:
        proposal = value if isinstance(value, ImprovementProposal) else ImprovementProposal.from_dict(value)
    except ContractError as exc:
        return (str(exc),)
    return proposal.validate()
