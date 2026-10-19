"""Dry run of the answer-quality checks over a project's answered subsections (no model).

    python3 -m csa_docx.card_report --workspace <project root> --docx <working DOCX> --work-dir <csa-work> [--key STOR] [--json]

For each answered subsection (csa-work/cards/<KEY>.manifest.json) the card is rebuilt as `csa answer` builds it (its
analysis frame appends finding rows to the evidence matrix as usual), and the answer applied to the document (the sheet
whose hash the manifest records) is checked against the new card in draft mode. The report says, per subsection, how
big the card is, what each requirement must address, and which hard checks the applied answer would now fail: the
re-answer load before anything is run. Written to csa-work/draft/card-report.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from csa_docx import answer_sheet as A


def summarise(card: dict, sheet_text: str, matrix: dict | None = None) -> dict:
    """{tokens, owed: {question: n}, errors: [code], warnings: {code: n}} for one card and its applied sheet."""
    owed = {q: len(v) for q, v in ((card.get("frame") or {}).get("must_address") or {}).items()}
    if not sheet_text:
        return {"tokens": card.get("tokens", 0), "owed": owed, "errors": ["NO_APPLIED_SHEET"], "warnings": {}}
    res = A.validate(A.parse(sheet_text), card, matrix or {}, draft=True)
    warns: dict[str, int] = {}
    for f in res["findings"]:
        if f["level"] == "WARN":
            warns[f["code"]] = warns.get(f["code"], 0) + 1
    return {"tokens": card.get("tokens", 0), "owed": owed,
            "errors": sorted({f["code"] for f in res["findings"] if f["level"] == "ERROR"}), "warnings": warns}


def applied_sheet(cards: Path, key: str) -> Path | None:
    """The sheet the document holds: the one whose hash the manifest recorded (else the newest of answer / prev)."""
    try:
        want = json.loads((cards / f"{key}.manifest.json").read_text(encoding="utf-8")).get("sheet_sha256")
    except (OSError, ValueError):
        want = None
    have = [p for p in (cards / f"{key}.answer.md", cards / f"{key}.answer.prev.md") if p.is_file()]
    for p in have:
        if want and hashlib.sha256(p.read_bytes()).hexdigest() == want:
            return p
    return have[0] if have else None


def report(workspace: Path, docx: Path, work_dir: Path, keys: list[str] | None = None) -> dict:
    from csa_docx import doc_spec, section_card, spec_cli
    spec = spec_cli.load(Path(docx), None, Path(work_dir))
    cards = Path(work_dir) / "cards"
    matrix = A.load_matrix(Path(work_dir) / "evidence-matrix.csv")
    rows = []
    for man in sorted(cards.glob("*.manifest.json")):
        key = man.name[: -len(".manifest.json")]
        if keys and key not in keys:
            continue
        try:
            node = doc_spec.resolve(spec, key)
        except Exception as e:                       # a section the document no longer has
            rows.append({"key": key, "number": "", "title": "", "error": str(e)[:200]})
            continue
        card = section_card.card(node, spec, Path(workspace))
        sheet = applied_sheet(cards, key)
        s = summarise(card, sheet.read_text(encoding="utf-8") if sheet else "", matrix)
        rows.append({"key": key, "number": node.get("number", ""), "title": node["title"], "sheet": sheet.name if sheet else None, **s})
    lines = ["# Card report (dry run, no model)", "",
             "| Section | Card tokens | Must address | Applied answer would fail | Warnings |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['key']} | - | - | not in the document: {r['error'][:80]} | - |")
            continue
        owed = ", ".join(f"{q} {n}" for q, n in r["owed"].items()) or "-"
        warns = ", ".join(f"{c} {n}" for c, n in sorted(r["warnings"].items())) or "-"
        lines.append(f"| {r['number']} {r['title']} ({r['key']}) | {r['tokens']} | {owed} | {', '.join(r['errors']) or 'passes'} | {warns} |")
    out = Path(work_dir) / "draft" / "card-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "OK", "file": str(out), "sections": rows,
            "would_fail": [r["key"] for r in rows if r.get("errors") and r["errors"] != ["NO_APPLIED_SHEET"]]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--docx", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--key", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = report(a.workspace, a.docx, a.work_dir, a.key or None)
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        print(Path(res["file"]).read_text(encoding="utf-8"), end="")
        print(f"\nWould fail now: {', '.join(res['would_fail']) or 'none'}  ({res['file']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
