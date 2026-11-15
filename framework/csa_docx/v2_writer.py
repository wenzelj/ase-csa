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
    """Keep the writer-facing card contract, not legacy duplicate evidence projections."""
    keys = ("key", "number", "title", "system_name", "questions", "obligations", "frame",
            "ratings", "acronyms", "drawbridge_functions", "parts", "host_register", "role_tables",
            "role_table", "subsection_contract", "keep", "background_ids")
    return {key: card[key] for key in keys if key in card}


def _package_view(package: dict) -> dict:
    """Keep one bounded native package projection and remove derived duplicates."""
    keys = ("context", "package_version", "contract_version", "package_hash", "application_key",
            "section", "question", "revision", "hosts", "evidence", "connections", "truncated",
            "truncation_reasons", "warnings", "counts", "terms_used", "more_available")
    return {key: package[key] for key in keys if key in package}


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
    body = {
        "packet_version": VERSION,
        "project": project,
        "subsection": subsection,
        "instructions": INSTRUCTIONS.read_text(encoding="utf-8"),
        "output_contract": output_contract,
        "card": _card_view(card),
        "evidence_package": _package_view(package or card.get("package") or {}),
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
