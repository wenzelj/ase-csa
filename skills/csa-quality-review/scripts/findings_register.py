import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csa-writing-style" / "scripts"))
import prose_lint as pl
ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--json", action="store_true")
a = ap.parse_args(); p = Path(a.path)
secs = pl.split_sections(pl.read_docx(p) if p.suffix.lower() == ".docx" else pl.read_markdown(p))
items = []
for s in secs:
    lvl = None; head = None
    for x in s.paras:
        if x.kind == "heading":
            if lvl is not None and x.level <= lvl:
                lvl = None
            if x.level >= 2 and "finding" in x.text.lower():
                lvl, head = x.level, x.text
            continue
        if lvl is not None and x.kind in ("text", "bullet") and x.text.strip():
            first = re.split(r"(?<=[.!?])\s+", x.text.strip())[0][:200]
            rating = next((r for r in ("Not Applicable", "Partially Met", "Not Met", "Met") if r in x.text), "-")
            items.append({"section": s.index, "section_title": s.title, "heading": head, "finding": first, "rating": rating})
if a.json:
    print(json.dumps(items, indent=2))
else:
    print("# Findings register\n\n| # | Section | Heading | Finding | Rating |\n|---|---|---|---|---|")
    for i, it in enumerate(items, 1):
        print(f"| {i} | {it['section']} {it['section_title']} | {it['heading']} | {it['finding']} | {it['rating']} |")
