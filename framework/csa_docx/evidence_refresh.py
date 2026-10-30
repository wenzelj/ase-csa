"""Keep existing evidence true to its sources after new data comes in (no model). Run by `csa ingest`
after the index build and graph sync.

1. changed / removed files (intake/latest.json): every live VERIFIED row citing one is source-checked
   again. A row whose file is gone is rejected in the review log, with the reason. A row whose quote is
   no longer in a changed file is listed for re-check: the intake agent re-reads the file, writes the
   current quote as a new row and rejects the old one (or rejects it when the file no longer says it).
2. superseded captures (index `captures.superseded_by`): rows the framework regenerates from every
   capture (host profile: what a host runs and connects to; graph sync: configured DNS and time
   servers) are rejected when they cite an older capture of a host, so only the latest capture speaks
   for it. Other rows citing an older capture are listed for re-check, not changed.

Writes intake/refresh-latest.json. Rejections are appended to evidence-reviews.jsonl (by
"evidence-refresh") and can be reversed with `evidence_matrix.py review <id> --state reviewed`.

    python3 -m csa_docx.evidence_refresh --work-dir <csa-work> [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

from csa_docx import evidence_live

BY = "evidence-refresh"
REGENERATED = re.compile(r"^(What does \S+ run\?|What connects to \S+\?|What does \S+ connect to\?|"
                         r"Which DNS servers is \S+ configured to use\?|Which time source does \S+ synchronise from\?)$")


def _em():
    p = Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
    spec = importlib.util.spec_from_file_location("evidence_matrix_refresh", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cites(row: dict, name: str) -> bool:
    src = row.get("source_title") or ""
    return name in src or Path(name).name in src


def run(work_dir: Path, dry_run: bool = False) -> dict:
    work_dir = Path(work_dir)
    matrix = work_dir / "evidence-matrix.csv"
    rows = evidence_live.read(matrix, drop_rejected=True)
    out = {"status": "OK", "checked": 0, "rejected": [], "recheck": [], "dry_run": dry_run}
    rec_p = work_dir / "intake" / "latest.json"
    rec = json.loads(rec_p.read_text(encoding="utf-8")) if rec_p.is_file() else {}
    db = work_dir / "discovery-index.sqlite"
    con = sqlite3.connect(str(db)) if db.is_file() else None
    reject: dict[str, str] = {}

    # 1. changed and removed files
    em = _em() if con is not None else None
    for kind in ("changed", "removed"):
        for f in rec.get(kind) or []:
            # discovery_index records removed files as path strings because no
            # live file metadata remains. Added/changed entries are mappings.
            # Accept both shapes so older and current intake records refresh.
            if isinstance(f, str):
                rel, source_class = f, ""
            elif isinstance(f, dict):
                rel = f.get("rel_path") or ""
                source_class = f.get("source_class") or ""
            else:
                continue
            name = Path(rel).name
            if not name or source_class == "capture":
                continue
            for r in rows:
                if r.get("status") != "VERIFIED" or r["evidence_id"] in reject or not _cites(r, name):
                    continue
                out["checked"] += 1
                if kind == "removed":
                    reject[r["evidence_id"]] = f"source file removed from the evidence folders: {rel}"
                    continue
                res = em.source_check(r, con)
                if res.get("verdict") in ("SOURCE_MISMATCH", "SOURCE_NOT_FOUND"):
                    out["recheck"].append({"evidence_id": r["evidence_id"], "file": rel, "kind": "changed source",
                                           "why": f"quote no longer in the changed file ({res['verdict']})",
                                           "claim": (r.get("claim") or "")[:160]})

    # 2. rows citing a superseded capture
    if con is not None:
        try:
            old = con.execute("select c.folder, c.host, n.folder from captures c join captures n on n.capture_id = c.superseded_by "
                              "where c.superseded_by is not null").fetchall()
        except sqlite3.OperationalError:
            old = []
        for folder, host, newer in old:
            cap = Path(folder).name
            for r in rows:
                if r["evidence_id"] in reject or not (r.get("source_title") or "").startswith(cap):
                    continue
                if REGENERATED.match((r.get("question") or "").strip()):
                    reject[r["evidence_id"]] = f"superseded: {host} has a newer capture ({Path(newer).name})"
                else:
                    out["recheck"].append({"evidence_id": r["evidence_id"], "file": cap, "kind": "older capture",
                                           "why": f"{host} has a newer capture ({Path(newer).name})",
                                           "claim": (r.get("claim") or "")[:160]})
    if con is not None:
        con.close()

    out["rejected"] = [{"evidence_id": i, "reason": why} for i, why in sorted(reject.items())]
    if reject and not dry_run:
        log = matrix.with_name("evidence-reviews.jsonl")
        at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with log.open("a", encoding="utf-8") as fh:
            for i, why in sorted(reject.items()):
                fh.write(json.dumps({"evidence_id": i, "state": "rejected", "by": BY, "at": at, "note": why},
                                    ensure_ascii=False) + "\n")
    if not dry_run:
        (work_dir / "intake").mkdir(exist_ok=True)
        (work_dir / "intake" / "refresh-latest.json").write_text(
            json.dumps({**out, "record": rec.get("id", ""),
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}, indent=1),
            encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.work_dir, a.dry_run)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"Re-checked {res['checked']} row(s) citing changed or removed files; "
              f"{len(res['rejected'])} rejected as out of date; {len(res['recheck'])} row(s) to re-check (changed file or older capture).")
        for r in res["rejected"][:20]:
            print(f"  {r['evidence_id']}: {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
