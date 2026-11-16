"""Question-scoped evidence slices for the V2 simple writer.

The slice is the shared V2 evidence boundary: the writer packet and the
structured validator can consume the same compact rows without carrying the
native package's duplicate provenance, tables or connection dumps.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

VERSION = "v2-evidence-slice-v1"


def _compact(row: dict, evidence_id: str | None = None) -> dict:
    out = {}
    if evidence_id:
        out["evidence_id"] = str(evidence_id).upper()
    for key in ("evidence_id", "id", "text", "claim", "excerpt", "source", "where",
                "location", "status", "review_state", "basis"):
        if key in row and row[key] is not None:
            out["evidence_id" if key == "id" else key] = row[key]
    if "evidence_id" not in out:
        return {}
    if "text" not in out:
        out["text"] = out.get("claim") or out.get("excerpt") or ""
    return out


def _package_rows(package: dict) -> dict[str, dict]:
    rows = {}
    for row in package.get("evidence", []) if isinstance(package, dict) else []:
        if not isinstance(row, dict):
            continue
        ids = row.get("evidence_ids") or ([row.get("evidence_id")] if row.get("evidence_id") else [])
        for evidence_id in ids:
            compact = _compact(row, str(evidence_id))
            if compact:
                rows[compact["evidence_id"]] = compact
    return rows


def build_slices(card: dict, package: dict | None = None) -> dict[str, dict]:
    """Build deterministic, question-scoped slices from a card and native package."""
    package = package or card.get("package") or {}
    package_rows = _package_rows(package)
    out = {}
    questions = {str(q.get("id")): q for q in card.get("questions", []) if isinstance(q, dict) and q.get("id")}
    for qid, question in questions.items():
        block = (card.get("evidence") or {}).get(qid, {})
        # The native package is the only citeable source.  IDs copied into
        # obligations, frames or digests without a package row are derived
        # references, not evidence, and must not reach the writer.
        rows = dict(package_rows)
        warnings = [w for w in (package.get("warnings", []) if isinstance(package, dict) else [])
                    if isinstance(w, dict) and (not w.get("evidence_id") or str(w.get("evidence_id")).upper() in rows)]
        conflicts = list(block.get("disagree", []) if isinstance(block, dict) else [])
        conflicts += [w for w in warnings if w.get("kind") in ("conflict", "superseded")]
        gaps = [
            {"evidence_id": row["evidence_id"], "text": row.get("text", ""), "status": row.get("status")}
            for row in rows.values() if row.get("status") in ("NOT_FOUND", "CONFLICTING")
        ]
        hosts = (package.get("hosts") or {}) if isinstance(package, dict) else {}
        out[qid] = {
            "slice_version": VERSION,
            "question_id": qid,
            "question": question,
            "allowed_evidence_ids": sorted(rows),
            "evidence": [rows[evidence_id] for evidence_id in sorted(rows)],
            "hosts": {key: list(value) for key, value in hosts.items() if isinstance(value, list)},
            "conflicts": conflicts,
            "known_gaps": gaps,
        }
    return out


def write_slices(directory: str | Path, slices: dict[str, dict]) -> dict[str, str]:
    """Write inspectable JSON and Markdown artifacts; return JSON paths by block."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for qid, value in slices.items():
        json_path = root / f"{qid}.json"
        md_path = root / f"{qid}.md"
        json_path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        lines = [f"# {value['question_id']} evidence slice", "", "## Question", "",
                 value.get("question", {}).get("text", ""), "", "## Evidence", "",
                 "| ID | Claim | Status | Basis | Source |", "|---|---|---|---|---|"]
        for row in value.get("evidence", []):
            claim = str(row.get("text", "")).replace("|", "\\|").replace("\n", " ")
            source = str(row.get("source", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {row['evidence_id']} | {claim} | {row.get('status', '')} | {row.get('basis', '')} | {source} |")
        lines += ["", "## Evidence boundary", "", "Only the IDs listed above may be cited.", ""]
        md_path.write_text("\n".join(lines), encoding="utf-8")
        paths[qid] = str(json_path)
    return paths
