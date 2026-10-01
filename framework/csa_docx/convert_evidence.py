"""Evidence pre-pass for `csa convert`: every old fact becomes a citable evidence row (no LLM).

Each legacy block mapped to a target gets one VERIFIED row that quotes the old document itself. The
old document is in the discovery index, so the matrix's automated source check approves the row. The
evidence agent then only has to corroborate or contradict these rows from the discovery captures.

    python3 -m csa_docx.convert_evidence --workspace <project root> --target 3.5 --legacy-docx <path> [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from csa_docx import scope_map
from csa_docx.convert_brief import _template_title

MATRIX_SCRIPT = (Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix"
                 / "scripts" / "evidence_matrix.py")

_CLAIM_MAX = 1500
_EXCERPT_MAX = 1200


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _area(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _excerpt(block: dict) -> str:
    if block["kind"] == "table_row":
        return " | ".join(block.get("cells") or []) or block["text"]
    text = block["text"]
    if len(text) <= _EXCERPT_MAX:
        return text
    cut = text[:_EXCERPT_MAX]
    return cut[:cut.rfind(" ")] if " " in cut else cut


def _error_reason(out: dict) -> str:
    parts = []
    for r in out.get("rejected", []):
        parts += r.get("errors", [])
    return "; ".join(parts) or out.get("message") or "rejected"


def prepass(workspace: Path, target: str, *, legacy_docx: Path, dry_run: bool = False) -> dict:
    workspace, legacy_docx = Path(workspace), Path(legacy_docx)
    if re.search(r"\s", legacy_docx.name):
        return {"status": "ERROR", "message": "legacy document name has spaces; the source check cannot match it. "
                "Copy it to a name without spaces and set legacy_docx to the copy."}

    work = workspace / "csa-work"
    blocks = {}
    bpath = work / "legacy" / "blocks.jsonl"
    if bpath.is_file():
        for line in bpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                b = json.loads(line)
                blocks[b["id"]] = b
    rows = [r for r in _read_csv(work / "legacy" / "map.csv")
            if r.get("target") == target and r.get("job") in ("convert", "context") and r["id"] in blocks]

    result = {"status": "OK", "target": target, "appended": [], "skipped": [], "rejected": []}
    if not rows:
        return result

    try:
        domains = scope_map.load()
    except (ValueError, OSError):
        domains = {}
    title = domains[target]["title"] if target in domains else (_template_title(target) or target)

    existing = " ".join(r.get("gap_or_action") or "" for r in _read_csv(work / "evidence-matrix.csv"))

    for m in rows:
        lid, b = m["id"], blocks[m["id"]]
        if re.search(rf"legacy {re.escape(lid)}(?!\d)", existing):
            result["skipped"].append(lid)
            continue
        row = {
            "csa_area": _area(title),
            "question": f"What did the previous assessment record about {m['path']}?",
            "claim": b["text"][:_CLAIM_MAX],
            "status": "VERIFIED",
            "source_title": legacy_docx.name,
            "source_version": "previous assessment",
            "section": f"{target} {title}",
            "page_or_location": f"{m['path']} ({lid})",
            "evidence_excerpt": _excerpt(b),
            "inference_reason": "",
            "confidence": "medium",
            "gap_or_action": f"legacy {lid}",
        }
        cmd = [sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append",
               "--agent", "csa convert pre-pass", "--context", f"convert {target}",
               "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)]
        if dry_run:
            cmd.append("--dry-run")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            result["rejected"].append({"id": lid, "reason": (proc.stderr or proc.stdout).strip()[-300:] or "no output"})
            continue
        if proc.returncode != 0 or out.get("status") == "ERROR":
            result["rejected"].append({"id": lid, "reason": _error_reason(out)})
            continue
        written = out.get("written") or out.get("would_write") or []
        if written:
            result["appended"].append(written[0]["evidence_id"])
        else:
            dup = (out.get("skipped_duplicates") or [{}])[0].get("duplicate_of", "")
            result["rejected"].append({"id": lid, "reason": f"duplicate of {dup}".strip()})
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Append one evidence row per legacy fact of a target.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--legacy-docx", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    res = prepass(a.workspace, a.target, legacy_docx=a.legacy_docx, dry_run=a.dry_run)
    print(json.dumps(res, ensure_ascii=False))
    return 2 if res.get("status") == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
