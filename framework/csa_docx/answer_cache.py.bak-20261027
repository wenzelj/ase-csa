"""Reuse a validated answer sheet while its inputs are unchanged.

`csa author <N> --cards` writes `cards/<KEY>.answer.md`. After the sheet validates, a manifest
`cards/<KEY>.manifest.json` records a fingerprint of what the answer was built from: per question, its id, text,
columns, the evidence rows the card lists for it and the current matrix rows those cite; plus `hosts/hosts.csv`.
On the next run `compare` says whether the sheet can be reused as it is.

    REUSE    every question hash matches
    PARTIAL  some questions changed (ids in "changed"); only those blocks need rewriting
    STALE    the sheet was edited since the manifest, the questions were added or removed, or hosts.csv changed
    NONE     no sheet or no manifest

    python3 -m csa_docx.answer_cache check <sheet> --card <card.json> --matrix <csv> [--hosts <csv>] --json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def manifest_path(sheet: Path) -> Path:
    name = sheet.name[: -len(".answer.md")] if sheet.name.endswith(".answer.md") else sheet.stem
    return sheet.with_name(f"{name}.manifest.json")


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _file_sha(path: Path | None) -> str:
    return _sha(path.read_bytes()) if path and path.is_file() else ""


def _matrix_rows(matrix: Path) -> dict[str, dict]:
    if not matrix.is_file():
        return {}
    with matrix.open(newline="", encoding="utf-8-sig") as fh:
        return {r.get("evidence_id", ""): r for r in csv.DictReader(fh)}


def fingerprint(card_json: Path, matrix: Path, hosts_csv: Path | None = None) -> dict:
    """{"questions": {id: sha256}, "matrix": sha256 of all cited rows, "hosts": sha256 or ""}."""
    card = json.loads(Path(card_json).read_text(encoding="utf-8"))
    rows = _matrix_rows(Path(matrix))
    evidence = card.get("evidence") or {}
    questions: dict[str, str] = {}
    cited_all: set[str] = set()
    for q in card.get("questions") or []:
        qid = q["id"]
        listed = [{"id": r.get("id"), "status": r.get("status"), "claim": r.get("claim")}
                  for r in (evidence.get(qid) or {}).get("rows", []) if not r.get("established")]
        cited = sorted({r["id"] for r in listed if r["id"]})
        cited_all.update(cited)
        current = [rows.get(i) or {"evidence_id": i, "missing": True} for i in cited]
        questions[qid] = _sha(json.dumps({"id": qid, "text": q.get("text", ""), "columns": q.get("columns") or [],
                                           "card_rows": listed, "matrix_rows": current}, sort_keys=True))
    matrix_hash = _sha(json.dumps([rows.get(i) or {"evidence_id": i, "missing": True} for i in sorted(cited_all)],
                                  sort_keys=True))
    return {"questions": questions, "matrix": matrix_hash, "hosts": _file_sha(Path(hosts_csv) if hosts_csv else None)}


def write_manifest(sheet: Path, fp: dict) -> Path:
    sheet = Path(sheet)
    path = manifest_path(sheet)
    data = {"fingerprint": fp, "sheet_sha256": _file_sha(sheet),
            "written": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def compare(sheet: Path, fp: dict) -> dict:
    sheet = Path(sheet)
    path = manifest_path(sheet)
    if not sheet.is_file() or not path.is_file():
        return {"status": "NONE", "changed": []}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        old = saved["fingerprint"]
    except (OSError, ValueError, KeyError):
        return {"status": "NONE", "changed": []}
    if saved.get("sheet_sha256") != _file_sha(sheet):
        return {"status": "STALE", "changed": [], "reason": "the sheet was edited after it was validated"}
    old_q, new_q = old.get("questions", {}), fp.get("questions", {})
    if set(old_q) != set(new_q):
        return {"status": "STALE", "changed": sorted(set(old_q) ^ set(new_q)), "reason": "the card's questions changed"}
    if old.get("hosts", "") != fp.get("hosts", ""):
        return {"status": "STALE", "changed": [], "reason": "hosts.csv changed"}
    changed = [q for q in new_q if old_q[q] != new_q[q]]
    return {"status": "PARTIAL" if changed else "REUSE", "changed": changed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "write"):
        s = sub.add_parser(name)
        s.add_argument("sheet", type=Path)
        s.add_argument("--card", type=Path, required=True)
        s.add_argument("--matrix", type=Path, required=True)
        s.add_argument("--hosts", type=Path)
        s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    fp = fingerprint(a.card, a.matrix, a.hosts)
    if a.cmd == "write":
        out = {"status": "OK", "manifest": str(write_manifest(a.sheet, fp))}
    else:
        out = compare(a.sheet, fp)
    print(json.dumps(out) if a.json else f"{out['status']} {' '.join(out.get('changed', []))}".strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
