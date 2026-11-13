"""Derive compact, model-facing obligations from an assembled section card."""
from __future__ import annotations

from .answer_contract import VERSION


def _ids(rows):
    return sorted({str(row.get("id") or row.get("evidence_id") or "").upper()
                   for row in rows if row.get("id") or row.get("evidence_id")})


def build(card: dict, only=None) -> dict:
    """Return deterministic per-block obligations without consulting project files."""
    selected = {str(x).upper() for x in (only or [])}
    out = {}
    evidence = card.get("evidence") or {}
    for q in card.get("questions") or []:
        qid = str(q.get("id") or "").upper()
        if not qid or (selected and qid not in selected):
            continue
        pack = evidence.get(qid) or evidence.get(q.get("id")) or {}
        rows = pack.get("rows") or []
        digest_ids = [str(x).upper() for x in pack.get("digest_ids") or []]
        kept = [x for x in card.get("keep") or [] if str(x.get("question", "")).upper() == qid]
        findings = []
        for item in (card.get("frame") or {}).get("must_address", {}).get(qid, []):
            findings.append({"slot": item.get("slot", ""), "text": item.get("text", ""),
                             "evidence_ids": _ids([{"id": x} for x in item.get("ids", [])]),
                             "must_state": bool(item.get("must_state"))})
        out[qid] = {
            "contract_version": VERSION,
            "question": q.get("text", ""),
            "kind": q.get("kind", ""),
            "evidence_ids": _ids(rows),
            "digest_ids": sorted(set(digest_ids)),
            "must_preserve": [{"fact": x.get("fact", ""), "evidence_ids": _ids([{"id": i} for i in x.get("evidence_ids", [])])}
                              for x in kept],
            "findings": findings,
            "table_columns": list(q.get("columns") or []),
            "ratings": list(card.get("ratings") or []),
            "requirements_stories": bool(card.get("requirement_stories") and q.get("kind") == "requirement"),
            "repair": "rewrite only this block when a repair names it",
        }
    return {"contract_version": VERSION, "blocks": out}
