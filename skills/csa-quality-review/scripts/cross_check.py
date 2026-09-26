import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csa-writing-style" / "scripts"))
import prose_lint as pl
W = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
NUM = r"(\d+|" + "|".join(W) + r")"
RE = re.compile(r"\b" + NUM + r"\s+((?:[A-Za-z-]+\s+){0,2}?)(hosts|servers|workstations)\b", re.I)
ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--hosts-file"); ap.add_argument("--json", action="store_true")
a = ap.parse_args(); p = Path(a.path)
secs = pl.split_sections(pl.read_docx(p) if p.suffix.lower() == ".docx" else pl.read_markdown(p))
found = {}
hosts = [h.strip() for h in Path(a.hosts_file).read_text().splitlines() if h.strip()] if a.hosts_file else []
hm = {h: [] for h in hosts}
for s in secs:
    text = " ".join(x.text for x in s.paras)
    for m in RE.finditer(text):
        n = int(m[1]) if m[1].isdigit() else W.index(m[1].lower()) + 1
        phrase = (m[2] + m[3]).strip().lower()
        found.setdefault(phrase, []).append({"section": s.index, "title": s.title, "number": n})
    for h in hosts:
        if re.search(rf"\b{re.escape(h)}\b", text, re.I) and s.title not in hm[h]:
            hm[h].append(s.title)
mm = [{"phrase": k, "values": v} for k, v in found.items() if len({x["number"] for x in v}) > 1]
if a.json:
    print(json.dumps({"mismatches": mm, "hosts": hm}, indent=2))
else:
    print("## Count mismatches\n")
    for m in mm:
        print("MISMATCH " + m["phrase"] + ": " + "; ".join(f"{v['title']} = {v['number']}" for v in m["values"]))
    print("\n## Host mentions\n\n| Host | Sections |\n|---|---|")
    for h, t in hm.items():
        print(f"| {h} | {', '.join(t) or '-'} |")
