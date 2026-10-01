"""Give every block of an old-format CSA a job and a target template subsection.

Order of decision: a person's `moved.csv`, the project's `legacy-map.csv`, the default map, the
scope map's legacy headings, then signal terms. The result is data a person can read and correct
before any writing starts.

    python3 -m csa_docx.legacy_map --blocks <blocks.jsonl> --out <dir> [--project-map <csv>] [--moved <csv>]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from csa_docx import scope_map

DEFAULT_MAP = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template"
               / "references" / "legacy-map-default.csv")

MAP_COLUMNS = ["id", "path", "kind", "job", "target", "rule", "confidence"]
_KEPT_JOBS = ("parked", "evidence-only", "controlled")


def load_rules(path: Path | str) -> list[dict]:
    """Read a map CSV (pattern,target,job,note). A missing file gives no rules."""
    path = Path(path)
    if not path.is_file():
        return []
    rules = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=1):
            pattern = (row.get("pattern") or "").strip()
            if not pattern:
                continue
            rules.append({
                "row": n,
                "pattern": re.compile(pattern, re.IGNORECASE),
                "target": (row.get("target") or "").strip(),
                "job": (row.get("job") or "").strip(),
                "note": (row.get("note") or "").strip(),
            })
    return rules


def load_moved(path: Path | str) -> dict[str, str]:
    """Read `id,target` rows. A missing file gives {}."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {(r.get("id") or "").strip(): (r.get("target") or "").strip()
                for r in csv.DictReader(fh) if (r.get("id") or "").strip()}


def _first_rule(rules, path: str) -> dict | None:
    return next((r for r in rules if r["pattern"].search(path)), None)


def map_blocks(blocks: list[dict], *, project_rules=(), default_rules=None,
               moved: dict | None = None, domains: dict | None = None) -> list[dict]:
    default_rules = load_rules(DEFAULT_MAP) if default_rules is None else default_rules
    domains = scope_map.load() if domains is None else domains
    moved = moved or {}
    all_keys = list(domains)
    out = []
    for b in blocks:
        path = " > ".join(b["path"])
        sub = " > ".join(b["path"][1:])
        signal_text = f"{sub} {b['text']}"

        def row(job, target, rule, conf):
            if b["kind"] == "figure" and job not in _KEPT_JOBS:
                job = "figure"
            return {"id": b["id"], "path": path, "kind": b["kind"], "job": job,
                    "target": target, "rule": rule, "confidence": conf}

        if b["kind"] == "heading":
            out.append(row("skip", "", "none", "high"))
            continue
        if b["id"] in moved:
            out.append(row("convert", moved[b["id"]], "moved", "high"))
            continue

        ordered = [(f"project:{r['row']}", r) for r in project_rules] + [(f"default:{r['row']}", r) for r in default_rules]
        mined = False
        rule, label = None, ""
        for lab, r in ordered:
            if not r["pattern"].search(path):
                continue
            if r["job"] == "mine":          # keep the job, but route by the rules that follow
                mined = True
                continue
            rule, label = r, lab
            break

        def final(job, target, rule_name, conf):
            if mined:
                job, rule_name = "mine", f"mine+{rule_name}"
            out.append(row(job, target, rule_name, conf))

        if rule:
            job = rule["job"] or "convert"
            target, conf = rule["target"], "high"
            if target == "signal":
                key, sc, tie = scope_map.best_by_terms(signal_text, all_keys, domains)
                if not key or sc == 0:
                    target, conf = "", "low"
                else:
                    target, conf = key, "low" if tie else "medium"
            final(job, target, label, conf)
            continue

        keys = scope_map.legacy_hosts(b["path"][0], domains) if b["path"] else []
        if len(keys) == 1:
            final("convert", keys[0], "legacy-heading", "high")
        elif keys:
            key, sc, tie = scope_map.best_by_terms(signal_text, keys, domains)
            final("convert", key, "signal-terms", "low" if (sc == 0 or tie) else "medium")
        else:
            final("convert", "", "none", "low")
    return out


def _target_key(t: str) -> tuple:
    try:
        return (0, tuple(int(p) for p in t.split(".")))
    except ValueError:
        return (1, (t,))


def _lines(title: str, rows: list[dict]) -> list[str]:
    out = [f"## {title}", ""]
    if not rows:
        return out + ["None.", ""]
    return out + [f"- `{r['id']}` {r['path'] or '(front matter)'}" for r in rows] + [""]


def write_map(rows: list[dict], out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "map.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MAP_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    live = [r for r in rows if r["job"] in ("convert", "context", "mine")]
    by_target: dict[str, list[dict]] = {}
    for r in live:
        if r["target"]:
            by_target.setdefault(r["target"], []).append(r)
    unmapped = [r for r in rows if r["job"] in ("convert", "mine") and not r["target"]]
    low = [r for r in rows if r["confidence"] == "low"]

    md = ["# Legacy map report", "", "## Blocks per target", "",
          "| Target | Blocks | Old sections |", "| --- | --- | --- |"]
    for t in sorted(by_target, key=_target_key):
        paths = sorted({r["path"] for r in by_target[t]})
        md.append(f"| {t} | {len(by_target[t])} | {'; '.join(paths)} |")
    md.append("")
    md += _lines("Unmapped", unmapped)
    md += _lines("Low confidence", low)
    md += _lines("Parked", [r for r in rows if r["job"] == "parked"])
    md += _lines("Evidence only", [r for r in rows if r["job"] == "evidence-only"])
    md += _lines("Figures", [r for r in rows if r["job"] == "figure"])
    md += _lines("Controlled", [r for r in rows if r["job"] == "controlled"])
    (out_dir / "map-report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {"status": "OK", "blocks": len(rows),
            "mapped": sum(len(v) for v in by_target.values()),
            "unmapped": len(unmapped), "low_confidence": len(low),
            "by_target": {t: len(by_target[t]) for t in sorted(by_target, key=_target_key)}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Map every block of an old CSA to a job and target.")
    ap.add_argument("--blocks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project-map", type=Path)
    ap.add_argument("--moved", type=Path)
    a = ap.parse_args(argv)
    if not a.blocks.is_file():
        print(json.dumps({"status": "ERROR", "message": f"blocks file not found: {a.blocks}"}))
        return 2
    blocks = [json.loads(line) for line in a.blocks.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = map_blocks(
        blocks,
        project_rules=load_rules(a.project_map) if a.project_map else (),
        moved=load_moved(a.moved) if a.moved else None,
    )
    print(json.dumps(write_map(rows, a.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
