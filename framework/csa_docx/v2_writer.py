"""The separate V2 simple-writer packet and prompt.

This module deliberately does not import the legacy agent definitions or prompt
digests. It turns the already-built card and native evidence package into one
stable model-facing packet. The validator remains outside this module.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VERSION = "v2-writer-packet-v1"
INSTRUCTIONS = Path(__file__).with_name("v2_writer_instructions.md")


def _read(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _card_view(card: dict) -> dict:
    """Keep the writer-facing question contract, not duplicate derived card projections."""
    qids = {str(q.get("id")) for q in card.get("questions", []) if isinstance(q, dict) and q.get("id")}
    view = {}
    for key in ("key", "number", "title", "system_name", "questions", "ratings",
                "acronyms", "drawbridge_functions", "subsection_contract", "background_ids"):
        if key in card:
            view[key] = card[key]
    obligations = card.get("obligations")
    if isinstance(obligations, dict):
        fields = ("contract_version", "question", "kind", "evidence_ids", "digest_ids",
                  "must_preserve", "table_columns", "ratings", "requirements_stories", "repair")
        blocks = {
            qid: {key: block[key] for key in fields if key in block}
            for qid, block in (obligations.get("blocks") or {}).items()
            if qid in qids and isinstance(block, dict)
        }
        view["obligations"] = {"contract_version": obligations.get("contract_version"), "blocks": blocks}
    keep = [item for item in (card.get("keep") or [])
            if isinstance(item, dict) and (not qids or str(item.get("question")) in qids)]
    if keep:
        view["keep"] = keep
    return view


def _compact_evidence(rows: list) -> list[dict]:
    """Keep claim-level provenance; omit repeated filesystem path and candidate dumps."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {key: row[key] for key in ("evidence_id", "text", "source", "location", "status", "review_state", "basis")
                if row.get(key) is not None}
        if item:
            out.append(item)
    return out


def _package_view(package: dict) -> dict:
    """Keep one bounded native package projection and remove derived duplicates."""
    keys = ("context", "package_version", "contract_version", "package_hash", "application_key",
            "section", "question", "revision", "hosts", "truncated",
            "truncation_reasons", "warnings", "counts", "terms_used", "more_available")
    view = {key: package[key] for key in keys if key in package}
    if "evidence" in package:
        view["evidence"] = _compact_evidence(package.get("evidence") or [])
    return view


def _evidence_ids(package: dict) -> set[str]:
    ids = set()
    for row in package.get("evidence", []):
        if isinstance(row, dict):
            ids.update(str(i).upper() for i in (row.get("evidence_ids") or ([row.get("evidence_id")] if row.get("evidence_id") else [])))
    return {i for i in ids if i}


def _card_evidence(card: dict, package: dict) -> dict:
    """Return only card evidence that is not already in the native package."""
    package_ids = _evidence_ids(package)
    out = {}
    for qid, block in (card.get("evidence") or {}).items():
        extras = []
        for row in block.get("rows", []):
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").upper()
            if eid and eid not in package_ids:
                extras.append({k: row.get(k) for k in ("id", "claim", "excerpt", "source", "where", "status") if row.get(k) is not None})
        extra_ids = [str(i).upper() for i in (block.get("cut") or []) if str(i).upper() not in package_ids]
        digest_ids = [str(i).upper() for i in (block.get("digest_ids") or []) if str(i).upper() not in package_ids]
        if extras or extra_ids or digest_ids:
            out[qid] = {"rows": extras, "cut_ids": extra_ids, "digest_ids": digest_ids}
    return out


def build_packet(*, project: str, subsection: str, card: dict,
                 package: dict | None = None, answer: str = "", errors: str = "") -> dict:
    """Build one complete, deterministic writer input from prepared framework data."""
    output_contract = {
        "version": "v2-output-v1",
        "format": "Markdown answer sheet",
        "blocks": [
            {"id": q.get("id"), "kind": q.get("kind"),
             "fields": q.get("fields") or ["Facts", "Summary", "Story", "Rating", "Rating reason", "Rows", "QUESTION"]}
            for q in card.get("questions", [])
        ],
        "return_only": "the requested blocks in card order",
    }
    native_package = package or card.get("package") or {}
    body = {
        "packet_version": VERSION,
        "project": project,
        "subsection": subsection,
        "instructions": INSTRUCTIONS.read_text(encoding="utf-8"),
        "output_contract": output_contract,
        "card": _card_view(card),
        "evidence_package": _package_view(native_package),
        "card_evidence_additions": _card_evidence(card, native_package),
        "retained_answer": answer,
        "repair_request": errors,
    }
    body["packet_hash"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16]
    return body


def render_prompt(packet: dict, *, card_path: str, sheet_path: str) -> str:
    """Render a self-contained prompt. Paths identify output only, not inputs to search."""
    payload = _canonical(packet)
    return ("Act as the V2 Simple Writer. The packet below is complete. Do not load legacy agent files, "
            "skills, prompts or source files. Return only the Markdown answer sheet.\n\n"
            f"CARD_PATH={card_path}\nSHEET_PATH={sheet_path}\n"
            "V2_WRITER_PACKET (JSON):\n" + payload + "\n")


def packet_metadata(packet: dict) -> dict:
    return {"packet_version": packet["packet_version"], "packet_hash": packet["packet_hash"],
            "project": packet["project"], "subsection": packet["subsection"]}
