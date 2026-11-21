"""Contracts and small helpers for importing an already-answered DOCX.

The import lane reconstructs framework state from an existing rendered document;
it does not claim that the document is a fresh model answer or new evidence.
Extraction and persistence are layered on top of these explicit outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
import json
import re

from . import answer_sheet, draft_lane, improve_context, improve_state, rating_pass


class ImportState(str, Enum):
    NOT_ANSWERED = "not-answered"
    ANSWERED_IMPORTED = "answered-imported"
    ANSWERED_MODEL = "answered-model"
    READY_FOR_IMPROVE = "ready-for-improve"
    STALE = "stale"


class ImportOutcome(str, Enum):
    READY = "READY"
    UNCHANGED = "UNCHANGED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RatingStatus:
    """Keep compliance assessment and answer-quality scores separate."""

    assessment_rating: str | None = None
    assessment_status: str = "unresolved"
    quality_status: str = "unrated"
    quality_score: float | None = None
    quality_hash: str | None = None


@dataclass(frozen=True)
class ImportProvenance:
    source: str = "working-document"
    label: str = "document-imported baseline"
    source_document_hash: str | None = None
    answer_sheet_hash: str | None = None
    import_run_id: str | None = None


@dataclass(frozen=True)
class ImportResult:
    outcome: ImportOutcome
    state: ImportState
    section_key: str
    provenance: ImportProvenance = field(default_factory=ImportProvenance)
    rating: RatingStatus = field(default_factory=RatingStatus)
    warnings: tuple[str, ...] = ()
    unmappable: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    message: str = ""

    @property
    def eligible_for_improve(self) -> bool:
        return self.state == ImportState.READY_FOR_IMPROVE and self.outcome in {
            ImportOutcome.READY, ImportOutcome.UNCHANGED
        }


def document_hash(path: Path | str) -> str:
    """Return a stable hash for the authoritative source document."""
    return "sha256:" + sha256(Path(path).read_bytes()).hexdigest()


def answer_sheet_hash(text: str) -> str:
    return "sha256:" + sha256(str(text).encode("utf-8")).hexdigest()


def source_outcome(path: Path | str, *, recorded_hash: str | None = None) -> ImportOutcome:
    """Classify source availability before any reconstruction is attempted."""
    source = Path(path)
    if not source.is_file():
        return ImportOutcome.MISSING
    current = document_hash(source)
    if recorded_hash and recorded_hash != current:
        return ImportOutcome.SOURCE_CHANGED
    return ImportOutcome.UNCHANGED if recorded_hash else ImportOutcome.READY


def result_from(value: Mapping[str, Any]) -> ImportResult:
    """Load a persisted result without widening unknown values into claims."""
    provenance = value.get("provenance") or {}
    rating = value.get("rating") or {}
    return ImportResult(
        outcome=ImportOutcome(str(value.get("outcome", ImportOutcome.BLOCKED.value))),
        state=ImportState(str(value.get("state", ImportState.NOT_ANSWERED.value))),
        section_key=str(value.get("section_key", "")),
        provenance=ImportProvenance(**{k: provenance.get(k) for k in ImportProvenance.__dataclass_fields__}),
        rating=RatingStatus(**{k: rating.get(k) for k in RatingStatus.__dataclass_fields__}),
        warnings=tuple(str(x) for x in value.get("warnings", ())),
        unmappable=tuple(str(x) for x in value.get("unmappable", ())),
        open_questions=tuple(str(x) for x in value.get("open_questions", ())),
        message=str(value.get("message", "")),
    )


def extract_section(path: Path | str, section_key: str, section_title: str | None = None) -> dict[str, Any]:
    """Read one bounded current subsection from the authoritative document."""
    return improve_context.extract_section(path, section_key, section_title)


def resolve_section(document_spec: Mapping[str, Any], section_key: str | None = None,
                    section_title: str | None = None) -> dict[str, Any] | None:
    """Resolve a subsection from the live specification, never from its filename."""
    nodes = document_spec.get("nodes", document_spec.get("sections", ()))
    candidates = [node for node in nodes if isinstance(node, Mapping)]
    key = (section_key or "").casefold().strip()
    title = (section_title or "").casefold().strip()
    matches = [node for node in candidates if key and str(node.get("key", node.get("number", ""))).casefold() == key]
    if not matches and title:
        matches = [node for node in candidates if str(node.get("title", "")).casefold().strip() == title]
    return dict(matches[0]) if len(matches) == 1 else None


def _question_blocks(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(q) for q in card.get("questions", []) if isinstance(q, Mapping) and q.get("id")]


def map_current_content(card: Mapping[str, Any], section: Mapping[str, Any]) -> dict[str, Any]:
    """Map rendered content into the answer-sheet shape without inventing evidence.

    The document is the baseline source here. Facts are therefore represented as
    document text with ``basis=documented`` and no evidence IDs; later evidence
    reconciliation may replace or qualify them.
    """
    blocks = list(section.get("blocks") or [])
    paragraphs = [str(b.get("text", "")).strip() for b in blocks
                  if b.get("kind") != "table" and str(b.get("text", "")).strip()]
    tables = [b for b in blocks if b.get("kind") == "table" and b.get("rows")]
    questions = _question_blocks(card)
    rating_re = re.compile(r"^rating\s*:\s*(.*?)\s*$", re.I)
    rating_lines = [line for line in paragraphs if rating_re.match(line)]
    controlled = rating_re.match(rating_lines[-1]).group(1).strip() if rating_lines else None
    ratings = {str(r).casefold() for r in card.get("ratings", ("Met", "Partially Met", "Not Met", "Not Applicable"))}
    valid_rating = controlled if controlled and controlled.casefold() in ratings else ""
    rating_warning = None
    if controlled is not None and not valid_rating:
        rating_warning = ("Blank controlled rating" if not controlled
                          else f"Invalid or unsupported controlled rating: {controlled}")
    explicit = tuple(line.split(":", 1)[1].strip() for line in paragraphs
                     if line.upper().startswith(("QUESTION:", "UNKNOWN:", "OPEN QUESTION:")) and ":" in line)
    if not questions:
        unmappable = tuple(line for line in paragraphs if line not in explicit)
        if rating_warning:
            unmappable += (rating_warning,)
        return {"blocks": blocks, "paragraphs": paragraphs, "tables": tables,
                "sheet": {}, "rating": valid_rating,
                "unmappable": unmappable, "open_questions": explicit}

    sheet: dict[str, dict[str, Any]] = {}
    # A table row is deterministic when its first cell is a known question ID or
    # requirement ID; a table without an identifier is only deterministic for a
    # card with one question.
    table_rows: dict[str, list[list[str]]] = {str(q["id"]): [] for q in questions}
    row_keys = {
        str(value).strip(): str(q["id"])
        for q in questions
        for value in (q.get("id"), q.get("req_id"))
        if value
    }
    unmappable_tables: list[str] = []
    for table in tables:
        for row in table["rows"]:
            key = str(row[0]).strip() if row else ""
            qid = row_keys.get(key)
            if qid:
                table_rows[qid].append(row)
            elif len(questions) == 1:
                table_rows[str(questions[0]["id"])].append(row)
            else:
                unmappable_tables.append(" | ".join(str(cell) for cell in row))
    for index, question in enumerate(questions):
        qid = str(question["id"])
        text = "\n\n".join(paragraphs) if index == 0 else ""
        rows = table_rows[qid]
        unknown = explicit if index == 0 else ()
        sheet[qid] = {
            "text": text,
            "summary": text if question.get("kind") == "requirement" else "",
            "story": "" if question.get("kind") == "requirement" else text,
            "facts": [], "rows": rows, "bullets": [], "unknown": list(unknown),
            "rating": valid_rating, "rating_reason": "", "keep": "", "provenance": "document-imported",
        }
    unmappable = tuple(paragraphs[1:] if paragraphs else ()) + tuple(unmappable_tables)
    if rating_warning:
        unmappable += (rating_warning,)
    return {"blocks": blocks, "paragraphs": paragraphs, "tables": tables,
            "sheet": sheet, "rating": valid_rating, "unmappable": unmappable,
            "open_questions": tuple(q for b in sheet.values() for q in b["unknown"])}


def _sheet_text(sheet: Mapping[str, Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for qid, block in sheet.items():
        lines.append(f"## {qid}")
        if block.get("summary"):
            lines.append(f"Summary: {block['summary']}")
        if block.get("story"):
            lines.append(f"Story: {block['story']}")
        for question in block.get("unknown", ()):
            lines.append(f"QUESTION: {question}")
        if block.get("rating"):
            lines.append(f"Rating: {block['rating']}")
        if block.get("rating_reason"):
            lines.append(f"Rating reason: {block['rating_reason']}")
        for row in block.get("rows", ()):
            lines.append("Rows: | " + " | ".join(str(cell) for cell in row) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def import_state(work_dir: Path | str, card: Mapping[str, Any], document_path: Path | str,
                 *, recorded_hash: str | None = None) -> ImportResult:
    """Reconstruct the inspectable answer state for one existing subsection.

    This first vertical slice writes only framework metadata under ``work_dir``;
    the authoritative DOCX is never opened for writing.
    """
    source = Path(document_path)
    key = str(card.get("key") or "").strip()
    if not key:
        return ImportResult(ImportOutcome.AMBIGUOUS, ImportState.NOT_ANSWERED, key,
                            message="card key is required")
    outcome = source_outcome(source, recorded_hash=recorded_hash)
    if outcome is ImportOutcome.MISSING:
        return ImportResult(outcome, ImportState.NOT_ANSWERED, key, message=f"working document is missing: {source}")
    if outcome is ImportOutcome.SOURCE_CHANGED:
        return ImportResult(outcome, ImportState.STALE, key, message="working document changed since the previous import")
    current_hash = document_hash(source)
    root = Path(work_dir)
    cards = root / "cards"
    existing = cards / f"{key}.IMPORT.json"
    if existing.is_file():
        try:
            prior = result_from(json.loads(existing.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            prior = None
        if prior and prior.provenance.source_document_hash == current_hash:
            return ImportResult(ImportOutcome.UNCHANGED, prior.state, prior.section_key,
                                provenance=prior.provenance, rating=prior.rating,
                                warnings=prior.warnings, unmappable=prior.unmappable,
                                open_questions=prior.open_questions, message=prior.message)
    try:
        section = extract_section(source, str(card.get("number") or key), str(card.get("title") or ""))
    except (OSError, ValueError) as exc:
        return ImportResult(ImportOutcome.BLOCKED, ImportState.NOT_ANSWERED, key,
                            provenance=ImportProvenance(source_document_hash=current_hash),
                            message=f"cannot extract answered subsection: {exc}")
    mapped = map_current_content(card, section)
    sheet_text = _sheet_text(mapped["sheet"])
    run_id = f"import-{uuid4().hex}"
    sheet_hash = answer_sheet_hash(sheet_text)
    provenance = ImportProvenance(source_document_hash=current_hash,
                                  answer_sheet_hash=sheet_hash, import_run_id=run_id)
    cards.mkdir(parents=True, exist_ok=True)
    (cards / f"{key}.json").write_text(json.dumps(dict(card), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (cards / f"{key}.answer.md").write_text(sheet_text, encoding="utf-8")
    parsed = answer_sheet.parse(sheet_text)
    validation_card = dict(card)
    validation_card["questions"] = [
        {**dict(question), "kind": question.get("kind", "requirement")}
        for question in card.get("questions", ()) if isinstance(question, Mapping)
    ]
    validation = answer_sheet.validate(parsed, validation_card, relaxed=True)
    validation_reasons = tuple(
        f"{item.get('level', 'ERROR')} {item.get('code', 'VALIDATION')}: {item.get('message', '')}"
        for item in validation.get("findings", ()) if item.get("level") == "ERROR"
    )
    rating = RatingStatus(assessment_rating=mapped["rating"] or None,
                          assessment_status="resolved" if mapped["rating"] else "unresolved")
    quality = {"status": "SKIPPED", "message": "no answered block to rate"}
    try:
        ids = rating_pass.rated_blocks(parsed, dict(card))
        quality = rating_pass.rate_text(root, sheet_text, ids, key, cards,
                                        str(card.get("rating_template") or ""),
                                        output_dir=root)
    except (OSError, TypeError, ValueError, IndexError, KeyError) as exc:
        quality = {"status": "ERROR", "message": f"rating pass failed: {exc}"}
    if quality.get("status") == "OK" and quality.get("average") is not None:
        rating = RatingStatus(assessment_rating=rating.assessment_rating,
                              assessment_status=rating.assessment_status,
                              quality_status="rated", quality_score=float(quality["average"]),
                              quality_hash=sheet_hash)
    reasons = tuple(mapped["unmappable"]) + validation_reasons
    warnings = ("Imported document content requires evidence revalidation.",) if reasons else ()
    result = ImportResult(ImportOutcome.PARTIAL if validation_reasons else ImportOutcome.READY,
                          ImportState.READY_FOR_IMPROVE, key, provenance=provenance, rating=rating,
                          warnings=warnings, unmappable=reasons,
                          open_questions=tuple(mapped["open_questions"]),
                          message="; ".join(validation_reasons))
    manifest = {"version": 1, "key": key, "status": "IMPORTED", "source": "document-imported",
                "source_document_hash": current_hash, "sheet_sha256": provenance.answer_sheet_hash,
                "import_run_id": run_id, "state": ImportState.READY_FOR_IMPROVE.value}
    (cards / f"{key}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (cards / f"{key}.IMPORT.json").write_text(json.dumps({
        "outcome": result.outcome.value, "state": result.state.value, "section_key": key,
        "provenance": provenance.__dict__, "rating": result.rating.__dict__,
        "warnings": result.warnings, "unmappable": result.unmappable,
        "open_questions": result.open_questions, "message": result.message,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (cards / f"{key}.RESULT.md").write_text(
        f"# Answered document import: {key}\n\n"
        f"Status: {result.outcome.value}\n"
        f"Source: document-imported baseline\n"
        f"Document hash: {current_hash}\n"
        f"Answer sheet hash: {sheet_hash}\n\n"
        f"Answer quality: {rating.quality_status}"
        + (f" ({rating.quality_score})" if rating.quality_score is not None else "")
        + (f"\nQuality hash: {rating.quality_hash}" if rating.quality_hash else "")
        + "\n\n"
        + ("Import validation findings:\n" + "\n".join(f"- {r}" for r in validation_reasons) + "\n"
           if validation_reasons else "Import validation: OK\n"), encoding="utf-8")
    try:
        draft_lane.record_run(root, key, str(card.get("number") or ""), str(card.get("title") or ""),
                              "READY", detail=result.message, phase="answered-document-import",
                              model="document-import", sheet_hash=sheet_hash)
        draft_lane.open_questions(root)
    except (OSError, ValueError, TypeError):
        pass
    try:
        context = improve_context.build_context(
            str(card.get("number") or key), source, section_title=str(card.get("title") or ""),
            rating=rating.assessment_rating, answer_run_id=run_id,
            findings=result.warnings + result.unmappable, open_questions=result.open_questions,
            rating_summary=rating_pass.load_summary(root, key),
            subsection_data=improve_context.collect_subsection_data(dict(card)),
        )
        improve_root = improve_state.improve_root(root)
        section_dir = improve_state.section_dir(improve_root, key)
        section_dir.mkdir(parents=True, exist_ok=True)
        context_path = section_dir / "context.json"
        context_path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        improve_run = improve_state.new_run(key, context_hash=answer_sheet_hash(json.dumps(context, sort_keys=True)),
                                            base_document_hash=current_hash)
        improve_run["status"] = "context_built"
        improve_state.write_run(improve_root, improve_run)
    except (OSError, ValueError, TypeError) as exc:
        result = ImportResult(result.outcome, result.state, result.section_key,
                              provenance=result.provenance, rating=result.rating,
                              warnings=result.warnings + (f"Improve context unavailable: {exc}",),
                              unmappable=result.unmappable, open_questions=result.open_questions,
                              message=result.message)
    (cards / f"{key}.IMPORT.json").write_text(json.dumps({
        "outcome": result.outcome.value, "state": result.state.value, "section_key": key,
        "provenance": result.provenance.__dict__, "rating": result.rating.__dict__,
        "warnings": result.warnings, "unmappable": result.unmappable,
        "open_questions": result.open_questions, "message": result.message,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
