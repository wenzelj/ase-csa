"""Can each requirement be answered? A per-requirement audit before any agent writes.

For every requirement ID it shows what the old document offers (by statement type), what the discovery
captures hold, and whether each destination is over- or under-supplied. Counts are candidates, not
answers: the evidence agent builds the answer plan from them.

    python3 -m csa_docx.requirement_audit --work-dir <csa-work>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

from csa_docx import requirement_assign

_STYPES = ("observed", "design", "gap", "consequence", "recommendation")
_OVER_PER_REQUIREMENT = 25
_SUBSECTIONS = ("5.2", "5.3", "5.4", "5.5", "5.6")


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _facts(work: Path) -> list[dict]:
    path = work / "legacy" / "facts.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            f = json.loads(line)
            ids = f.get("req_ids", [])
            f["req_ids"] = ids.split(";") if isinstance(ids, str) else ids
            out.append(f)
    return out


def _index_tables(work: Path) -> dict[str, int]:
    """table name -> number of distinct hosts with rows, from the discovery index (read-only)."""
    path = work / "discovery-index.sqlite"
    if not path.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {t: n for t, n in con.execute(
                "SELECT r.table_name, COUNT(DISTINCT f.host) FROM rows r JOIN files f ON f.file_id = r.file_id "
                "GROUP BY r.table_name")}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def _verdict(index_hosts: int, clusters: int) -> str:
    if index_hosts > 0 and clusters >= 3:
        return "ANSWERABLE"
    if index_hosts > 0:
        return "MINE CAPTURES"
    if clusters >= 1:
        return "LEGACY ONLY"
    return "GAP"


def _target_key(t: str) -> tuple:
    return tuple(int(p) for p in t.split(".") if p.isdigit())


def audit(work_dir: Path) -> dict:
    work = Path(work_dir)
    reqs = requirement_assign.load_requirements()
    facts = _facts(work)
    tables = _index_tables(work)
    matrix = _read_csv(work / "evidence-matrix.csv")
    hosts = [h["host"] for h in _read_csv(work / "hosts" / "hosts.csv")
             if h.get("host") and not (h.get("in_scope") or "").strip()]

    entries = []
    for r in reqs:
        mine = [f for f in facts if r["req_id"] in f["req_ids"]]
        by_type: dict[str, int] = {}
        for f in mine:
            by_type[f["stype"]] = by_type.get(f["stype"], 0) + 1
        clusters = len({f.get("cluster") for f in mine if f["stype"] == "observed"})
        blob = " ".join(f"{f['text']} {f.get('scope', '')}" for f in mine).lower()
        named = [h for h in hosts if h.lower() in blob]

        pattern = r["index_tables"].strip()
        matched = {t: n for t, n in tables.items() if pattern and re.search(pattern, t, re.I)}
        index_hosts = max(matched.values(), default=0)

        evidence: dict[str, int] = {}
        for m in matrix:
            section = (m.get("section") or "").strip()
            if re.match(rf"{re.escape(r['domain'])}(?!\d)", section) or (r["rx"] and r["rx"].search(m.get("claim") or "")):
                status = m.get("status") or "?"
                evidence[status] = evidence.get(status, 0) + 1

        entries.append({
            "req_id": r["req_id"], "domain": r["domain"], "facts": by_type, "clusters": clusters,
            "absolute": sum(bool(f.get("absolute")) for f in mine),
            "not_evidence": sum(bool(f.get("not_evidence")) for f in mine),
            "hosts": named, "index_tables": matched, "index_hosts": index_hosts, "evidence": evidence,
            "verdict": _verdict(index_hosts, clusters),
        })

    # Supply per destination.
    per_target: dict[str, int] = {}
    for m in _read_csv(work / "legacy" / "map.csv"):
        if m.get("job") in ("convert", "context", "mine") and m.get("target"):
            per_target[m["target"]] = per_target.get(m["target"], 0) + 1
    owned: dict[str, int] = {}
    for r in reqs:
        owned[r["domain"]] = owned.get(r["domain"], 0) + 1
    over = [{"target": t, "blocks": n, "requirements": owned.get(t, 1)}
            for t, n in sorted(per_target.items(), key=lambda kv: _target_key(kv[0]))
            if n > _OVER_PER_REQUIREMENT * owned.get(t, 1)]
    empty = [t for t in sorted(set(owned) | set(_SUBSECTIONS), key=_target_key) if not per_target.get(t)]

    by_verdict: dict[str, int] = {}
    for e in entries:
        by_verdict[e["verdict"]] = by_verdict.get(e["verdict"], 0) + 1

    lines = ["# Requirement audit (generated)", "",
             "Counts are candidates, not answers: keyword assignment can misfire, which is why the answer plan is an "
             "agent step with these as inputs.", "",
             "| Req | Legacy facts (obs / design / gap / consequence / rec) | Clusters | Captures (max hosts) | Evidence rows | Verdict |",
             "| --- | --- | --- | --- | --- | --- |"]
    for e in entries:
        counts = [e["facts"].get(s, 0) for s in _STYPES]
        ev = ", ".join(f"{n} {s}" for s, n in sorted(e["evidence"].items())) or "0"
        lines.append(f"| {e['req_id']} | {sum(counts)} ({' / '.join(map(str, counts))}) | {e['clusters']} | "
                     f"{e['index_hosts']} | {ev} | {e['verdict']} |")
    lines += ["", "## Over-supplied targets", ""]
    lines += [f"- {o['target']}: {o['blocks']} blocks for {o['requirements']} requirement(s)" for o in over] or ["None."]
    lines += ["", "## Empty targets", ""]
    lines += [f"- {t}" for t in empty] or ["None."]
    lines += ["", "## Absolute claims to qualify", ""]
    absolutes = [(f["fact_id"], ", ".join(f["req_ids"]) or "unassigned", f["text"]) for f in facts if f.get("absolute")]
    lines += [f"- `{fid}` ({req}) {text}" for fid, req, text in absolutes] or ["None."]
    text = "\n".join(lines) + "\n"

    out_dir = work / "convert"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "requirement-audit.md"
    if md.is_file() and "<!-- keep -->" in md.read_text(encoding="utf-8"):
        md = out_dir / "requirement-audit.generated.md"
    md.write_text(text, encoding="utf-8")
    (out_dir / "requirement-audit.json").write_text(
        json.dumps({"requirements": entries, "over": over, "empty": empty}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return {"status": "OK", "requirements": len(entries), "by_verdict": by_verdict,
            "over": [o["target"] for o in over], "empty": empty}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit whether each requirement can be answered.")
    ap.add_argument("--work-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    print(json.dumps(audit(a.work_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
