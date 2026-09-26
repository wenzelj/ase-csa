import argparse, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_matrix as em
def cell(v): return (v or "").replace("|", "\\|").replace("\n", " ")
ap = argparse.ArgumentParser(); ap.add_argument("--workspace"); ap.add_argument("--matrix"); ap.add_argument("--out"); ap.add_argument("--all", action="store_true")
a = ap.parse_args()
ws, matrix = em.resolve_paths(a)
header, body, *_ = em.load(matrix)
rows = [em.as_dict(header, r) for r in body if r]
keep = [r for r in rows if a.all or r["status"] in ("VERIFIED", "INFERRED")]
nf = [r for r in rows if r["status"] == "NOT_FOUND"]
out = ["# Evidence appendix", "", f"Generated from csa-work/evidence-matrix.csv on {date.today()}. {len(rows)} evidence items.", ""]
for src in sorted({r["source_title"] for r in keep}):
    out += [f"## {src}", "", "| ID | Claim | Status | Location |", "|---|---|---|---|"]
    for r in sorted((r for r in keep if r["source_title"] == src), key=lambda r: r["evidence_id"]):
        out.append(f"| {r['evidence_id']} | {cell(r['claim'])} | {r['status']} | {cell(r['page_or_location'] or r['section'])} |")
    out.append("")
out += ["## Searched and not found", "", "| ID | What was looked for | Scope searched |", "|---|---|---|"]
for r in nf:
    out.append(f"| {r['evidence_id']} | {cell(r['claim'] or r['question'])} | {cell(r['source_title'])} |")
text = "\n".join(out) + "\n"
Path(a.out).write_text(text) if a.out else print(text)
