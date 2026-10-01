"""Give every legacy fact a requirement ID, and group near-duplicate facts.

The assignment is a candidate list for the evidence agent, so it records how it was made (`rule`) and
how sure it is (`confidence`). A fact that a requirement's `not_evidence_for` describes is flagged, not
dropped: the agent decides.

    python3 -m csa_docx.requirement_assign --legacy-dir <csa-work/legacy>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REQ_MAP = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template"
           / "references" / "requirement-map.csv")

_SKIP_TYPES = ("evidence-ref", "legacy-score", "method")
_CLUSTER_THRESHOLD = 0.6
FACT_COLUMNS = ["fact_id", "legacy_id", "req_ids", "rule", "confidence", "not_evidence", "cluster", "stype",
                "qualifier", "absolute", "old_target", "path", "subject", "column", "scope", "text"]


def _terms_re(terms: list[str]) -> re.Pattern | None:
    terms = [t.strip() for t in terms if t.strip()]
    if not terms:
        return None
    alts = sorted((re.escape(t).replace(r"\ ", r"[\s-]+") for t in terms), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])", re.IGNORECASE)


def load_requirements(path: Path | str = REQ_MAP) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["rx"] = _terms_re(r["answer_terms"].split(";"))
        not_terms = [re.sub(r"\([^)]*\)", "", t).strip() for t in r["not_evidence_for"].split(";")]
        r["not_rx"] = _terms_re(not_terms)
    return rows


def _score(rx: re.Pattern | None, text: str) -> int:
    return len(rx.findall(text)) if rx else 0


def assign(facts: list[dict], reqs: list[dict]) -> list[dict]:
    by_domain: dict[str, list[dict]] = {}
    for r in reqs:
        by_domain.setdefault(r["domain"], []).append(r)
    by_id = {r["req_id"]: r for r in reqs}

    out = []
    for f in facts:
        f = dict(f)
        if f["stype"] in _SKIP_TYPES:
            f.update(req_ids=[], rule="n/a", confidence="n/a", not_evidence=False)
            out.append(f)
            continue
        text = f"{f.get('subject', '')} {f.get('column', '')} {f['text']}"
        scores = [(_score(r["rx"], text), r["req_id"]) for r in reqs]
        best = max(s for s, _ in scores)
        if best > 0:
            ids = [rid for s, rid in scores if s == best]
            # On a tie the requirement of the fact's own old section comes first (stable, so map order otherwise).
            ids.sort(key=lambda rid: by_id[rid]["domain"] != f.get("old_target", ""))
            f.update(req_ids=ids, rule="terms", confidence="medium" if len(ids) == 1 else "low")
        else:
            domain = by_domain.get(f.get("old_target", ""), [])
            if len(domain) == 1:
                f.update(req_ids=[domain[0]["req_id"]], rule="domain", confidence="low")
            else:
                f.update(req_ids=[], rule="none", confidence="")
        f["not_evidence"] = any(_score(by_id[rid]["not_rx"], f["text"]) > 0 for rid in f["req_ids"])
        out.append(f)
    return out


def _words(text: str) -> set[str]:
    text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", " ", text.lower())
    text = re.sub(r"[\d\W_]+", " ", text)
    return {w for w in text.split() if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cluster(facts: list[dict]) -> list[dict]:
    """Group near-duplicates inside the same first requirement and statement type."""
    reps: dict[tuple, list[tuple[str, set[str]]]] = {}  # key -> [(cluster id, representative words)]
    n = 0
    for f in facts:
        key = ((f["req_ids"] or [""])[0], f["stype"])
        words = _words(f["text"])
        for cid, rep in reps.setdefault(key, []):
            if _jaccard(words, rep) >= _CLUSTER_THRESHOLD:
                f["cluster"] = cid
                break
        else:
            n += 1
            cid = f"C-{n:04d}"
            reps[key].append((cid, words))
            f["cluster"] = cid
    return facts


def write(facts: list[dict], legacy_dir: Path) -> dict:
    legacy_dir = Path(legacy_dir)
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "facts.jsonl").write_text(
        "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts), encoding="utf-8")
    with (legacy_dir / "facts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FACT_COLUMNS)
        for f in facts:
            w.writerow([";".join(f["req_ids"]) if c == "req_ids" else f.get(c, "") for c in FACT_COLUMNS])
    by_req: dict[str, int] = {}
    for f in facts:
        for rid in f["req_ids"]:
            by_req[rid] = by_req.get(rid, 0) + 1
    return {"status": "OK", "assigned": sum(bool(f["req_ids"]) for f in facts),
            "unassigned": sum(f["rule"] == "none" for f in facts),
            "clusters": len({f["cluster"] for f in facts}), "by_req": dict(sorted(by_req.items()))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assign requirement IDs to legacy facts.")
    ap.add_argument("--legacy-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    path = a.legacy_dir / "facts.jsonl"
    if not path.is_file():
        print(json.dumps({"status": "ERROR", "message": "facts.jsonl missing; run csa_docx.legacy_facts first"}))
        return 2
    facts = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(write(cluster(assign(facts, load_requirements())), a.legacy_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
