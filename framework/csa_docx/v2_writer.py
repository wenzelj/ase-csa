"""The separate V2 simple-writer packet and prompt.

This module deliberately does not import the legacy agent definitions or prompt
digests. It turns the already-built card and native evidence package into one
stable model-facing packet. The validator remains outside this module.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

VERSION = "v2-writer-packet-v2"
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
                "acronyms", "drawbridge_functions", "subsection_contract", "background_ids",
                "writing_purpose", "current_content", "current_tables"):
        if key in card:
            view[key] = card[key]
    def without_evidence_ids(value):
        if isinstance(value, dict):
            return {key: without_evidence_ids(item) for key, item in value.items()
                    if key not in {"evidence_ids", "digest_ids", "capture_ids"}}
        if isinstance(value, list):
            return [without_evidence_ids(item) for item in value]
        return value

    obligations = card.get("obligations")
    if isinstance(obligations, dict):
        fields = ("contract_version", "question", "kind", "evidence_ids", "digest_ids",
                  "must_preserve", "table_columns", "ratings", "requirements_stories", "repair")
        blocks = {
            qid: without_evidence_ids({key: block[key] for key in fields if key in block})
            for qid, block in (obligations.get("blocks") or {}).items()
            if qid in qids and isinstance(block, dict)
        }
        view["obligations"] = {"contract_version": obligations.get("contract_version"), "blocks": blocks}
    keep = [item for item in (card.get("keep") or [])
            if isinstance(item, dict) and (not qids or str(item.get("question")) in qids)]
    if keep:
        view["keep"] = without_evidence_ids(keep)
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


def _question_evidence_ids(card: dict, question_ids: set[str]) -> set[str]:
    """IDs explicitly routed to the requested question blocks."""
    wanted: set[str] = set()
    blocks = (card.get("obligations") or {}).get("blocks") or {}
    for qid in question_ids:
        block = blocks.get(qid) or blocks.get(qid.upper()) or {}
        wanted.update(str(i).upper() for i in block.get("evidence_ids", []) if i)
        for item in block.get("must_preserve", []) + block.get("findings", []):
            if isinstance(item, dict):
                wanted.update(str(i).upper() for i in item.get("evidence_ids", []) if i)
        rows = (card.get("evidence") or {}).get(qid) or (card.get("evidence") or {}).get(qid.upper()) or {}
        wanted.update(str(row.get("id")).upper() for row in rows.get("rows", [])
                      if isinstance(row, dict) and row.get("id"))
        wanted.update(str(i).upper() for i in rows.get("digest_ids", []) if i)
    for item in card.get("keep", []) or []:
        if isinstance(item, dict) and (not question_ids or str(item.get("question")) in question_ids):
            wanted.update(str(i).upper() for i in item.get("evidence_ids", []) if i)
            wanted.update(str(i).upper() for i in item.get("capture_ids", []) if i)
    return wanted


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


def _clean_repair_request(errors: str, card: dict, package: dict) -> str:
    """Discard stale unknown-ID messages once the native package proves validity."""
    if not errors:
        return ""
    valid = _evidence_ids(package)
    lines = []
    for line in str(errors).splitlines():
        if "UNKNOWN_EVIDENCE" in line:
            found = re.findall(r"\bE-\d+\b", line.upper())
            if found and found[0] in valid:
                continue
        if "EVIDENCE_DROPPED" in line:
            found = re.findall(r"\bE-\d+\b", line.upper())
            remaining = [item for item in found if item not in valid]
            if not remaining:
                continue
            prefix = line.split(":", 1)[0]
            line = prefix + ": " + ", ".join(remaining)
        lines.append(line)
    return "\n".join(lines).strip()


def build_packet(*, project: str, subsection: str, card: dict,
                 package: dict | None = None, answer: str = "", errors: str = "",
                 only: str | list[str] | None = None) -> dict:
    """Build one complete, deterministic writer input from prepared framework data."""
    if isinstance(only, str):
        only_ids = {item.strip().upper() for item in only.split(",") if item.strip()}
    else:
        only_ids = {str(item).strip().upper() for item in (only or []) if str(item).strip()}
    if only_ids:
        # A focused call must receive only its own question contract.  The
        # retained answer still carries earlier blocks for continuity, but the
        # model no longer spends context re-reading every other plan and slice.
        card = dict(card)
        card["questions"] = [q for q in card.get("questions", [])
                             if isinstance(q, dict) and str(q.get("id", "")).upper() in only_ids]
        obligations = dict(card.get("obligations") or {})
        blocks = obligations.get("blocks") or {}
        obligations["blocks"] = {qid: block for qid, block in blocks.items()
                                  if str(qid).upper() in only_ids}
        card["obligations"] = obligations
        card["evidence"] = {qid: value for qid, value in (card.get("evidence") or {}).items()
                             if str(qid).upper() in only_ids}
        card["v2_evidence_slices"] = {qid: value for qid, value in (card.get("v2_evidence_slices") or {}).items()
                                      if str(qid).upper() in only_ids}
        card["v2_answer_plan"] = {qid: value for qid, value in (card.get("v2_answer_plan") or {}).items()
                                   if str(qid).upper() in only_ids}
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
    if only_ids and isinstance(native_package, dict):
        routed = _question_evidence_ids(card, only_ids)
        if routed:
            native_package = dict(native_package)
            native_package["evidence"] = [
                row for row in native_package.get("evidence", [])
                if str(row.get("evidence_id") or "").upper() in routed
            ]
    body = {
        "packet_version": VERSION,
        "project": project,
        "subsection": subsection,
        "instructions": INSTRUCTIONS.read_text(encoding="utf-8"),
        "output_contract": output_contract,
        "card": _card_view(card),
        # This is the single citeable evidence set. The validator reads the
        # same native package rows; no second slice or plan allowlist exists.
        "evidence": _package_view(native_package),
        "retained_answer": answer,
        "repair_request": _clean_repair_request(errors, card, native_package),
    }
    body["packet_hash"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16]
    return body


def render_prompt(packet: dict, *, card_path: str, sheet_path: str,
                  allow_output_tool: bool = False) -> str:
    """Render a self-contained prompt.

    Interactive calls may use the file tool only for the supplied output path;
    all evidence remains packet-only and no investigation tools are allowed.
    """
    payload = _canonical(packet)
    output_rule = ("You may use the file tool once to write the final Markdown answer to SHEET_PATH. "
                   "Do not use tools for investigation or to read any other file.\n"
                   if allow_output_tool else
                   "Do not call tools or read files. Return the final Markdown answer in your response.\n")
    return ("Act as the V2 Simple Writer. The packet below is complete. Do not load legacy agent files, "
            "skills, prompts or source files.\n" + output_rule + "\n"
            f"CARD_PATH={card_path}\nSHEET_PATH={sheet_path}\n"
            "V2_WRITER_PACKET (JSON):\n" + payload + "\n")


def packet_metadata(packet: dict) -> dict:
    return {"packet_version": packet["packet_version"], "packet_hash": packet["packet_hash"],
            "project": packet["project"], "subsection": packet["subsection"]}
