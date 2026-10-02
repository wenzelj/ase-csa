"""Look for evidence before a gap is recorded as not found.

A gap ("confirm the role of HOST", "confirm whether an OT DNS service exists") is only a gap when the
evidence does not answer it. This runs the framework's own lookups in the usual order:

1. the evidence matrix (`evidence_matrix.py lookup`), ignoring rows that only restate the previous
   assessment (`gap_or_action` starts `legacy L-`), earlier NOT_FOUND rows and rejected rows;
2. the discovery index (`discovery_index.py search`): by host name in workbooks and documents, and by
   host plus topic word in the captures. Every usable hit is added to the matrix as an UNCONFIRMED row
   that quotes the source (read it: a person or the evidence agent promotes it to VERIFIED with a claim,
   or rejects it with `evidence_matrix.py review --state rejected`; a rejected row is not offered again).

Verdicts: ANSWERED (the matrix already answers it), CANDIDATES (something was found, so the gap is not
yet a gap), NOT_FOUND (nothing; `searched` says exactly what was looked in, for the NOT_FOUND row).

After reading what was found, a person or the evidence agent settles it one of two ways:
  * it answers the question: record a VERIFIED row that states the answer and restate the gap;
  * it does not: `python3 -m csa_docx.gap_lookup confirm --workspace W --dr DR-DNS-01 --text "..."
    --considered E-052,E-053 --ask "who to ask"` rejects the candidate rows and records a NOT_FOUND row that
    lists the rows considered, so the same rows are not offered again.

    python3 -m csa_docx.gap_lookup check   --workspace W --dr DR-DNS-01 --text "..." [--legacy-docx F]
    python3 -m csa_docx.gap_lookup confirm --workspace W --dr DR-DNS-01 --text "..." --considered E-1,E-2 --ask "..."
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2] / "skills"
MATRIX_SCRIPT = _SKILLS / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
INDEX_SCRIPT = _SKILLS / "csa-discovery-index" / "scripts" / "discovery_index.py"

_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
_STOP = set("""confirm whether exists exist that this with from have were would which their there where also into only
observed captures captured capture evidence found need needs needed show shows shown states stated source sources
role roles site sites what does did each every other any some being been than then them they these those about
after before while when will should could including observe observing not are was did its but has can who how why
either neither both none nor may might must shall the and for you your our out off per via yet""".split())
_NOISE_PATHS = ("89_output_file_inventory", ".ps1", "preflight")
_MAX_QUERIES = 12
_MAX_CANDIDATES = 6
_MIN_TOPIC_COVERAGE = 0.5   # share of the gap's topic words a hit must contain when no host ties it to the gap


def relevant(excerpt: str, text: str) -> bool:
    """A hit is only a candidate when it is about the gap. A host named in the gap and found in the hit ties it
    to the gap. Otherwise the hit must hold at least two of the gap's topic words and half of them, so a page
    that happens to say "network" and "time" is not offered as the answer to a question about resolver zones."""
    low = (excerpt or "").lower()
    hosts = [h.lower() for h in hosts_in(text)]
    if hosts and any(h in low for h in hosts):
        return True
    words = topic_words(text, limit=8)
    if not words:
        return not hosts        # a host-only gap needs the host in the hit; with neither there is nothing to judge by
    hit = sum(1 for w in words if w[:5] in low)
    return hit >= 2 and hit / len(words) >= _MIN_TOPIC_COVERAGE
_ANSWER_SCORE, _ANSWER_COVERAGE = 0.6, 0.75


def _run(cmd: list[str]) -> dict | None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def _rejected(workspace: Path) -> set[str]:
    """Evidence IDs whose latest review is `rejected` (evidence-reviews.jsonl)."""
    path = workspace / "csa-work" / "evidence-reviews.jsonl"
    latest: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec["evidence_id"].upper()] = rec.get("state", "")
    return {i for i, s in latest.items() if s == "rejected"}


def _acknowledged(workspace: Path, dr_id: str) -> set[str]:
    """Evidence IDs a earlier `confirm` recorded as considered and not an answer to this gap."""
    path = workspace / "csa-work" / "evidence-matrix.csv"
    out: set[str] = set()
    if path.is_file():
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") == "NOT_FOUND" and dr_id in (r.get("gap_or_action") or ""):
                    out.update(re.findall(r"E-\d+", r.get("inference_reason") or ""))
    return out


def hosts_in(text: str) -> list[str]:
    return list(dict.fromkeys(_HOST.findall(text or "")))


def topic_words(text: str, limit: int = 6) -> list[str]:
    words = [w.lower() for w in _WORD.findall(_HOST.sub(" ", text or ""))]
    return list(dict.fromkeys(w for w in words if w not in _STOP))[:limit]


def queries(text: str) -> list[tuple[str, str | None]]:
    """(search terms, path-like filter) pairs. Hosts: the host alone in workbooks and documents, then host
    plus a topic word in the captures. No host: pairs of topic words."""
    hosts, words = hosts_in(text), topic_words(text)
    out: list[tuple[str, str | None]] = []
    for h in hosts[:4]:
        out += [(h, ".xlsx"), (h, ".docx")]
        out += [(f"{h} {w}", None) for w in words[:3]]
    if not hosts:
        if len(words) >= 2:
            out += [(f"{a} {b}", None) for a, b in combinations(words[:5], 2)]   # every pair of the leading topic words
        elif words:
            out.append((words[0], None))
    return out[:_MAX_QUERIES]


def _matrix_stage(workspace: Path, text: str, rejected: set[str]) -> tuple[str, list[str]]:
    res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "lookup", text, "--limit", "8"])
    if not res or res.get("status") != "OK":
        return "NO_MATRIX", []
    kept = []
    for m in res.get("matches", []):
        if m["evidence_id"].upper() in rejected or m.get("status") == "NOT_FOUND":
            continue
        if (m.get("gap_or_action") or "").startswith("legacy L-"):
            continue
        kept.append(m)
    answered = any(m["status"] in ("VERIFIED", "INFERRED") and m["score"] >= _ANSWER_SCORE
                   and m["coverage"] >= _ANSWER_COVERAGE for m in kept)
    return ("ANSWERED" if answered else "CANDIDATES" if kept else "NONE"), [m["evidence_id"] for m in kept]


def _index_stage(workspace: Path, text: str, exclude: tuple[str, ...]) -> tuple[list[dict], list[str], bool]:
    hits, seen, ran, has_index = [], set(), [], True
    for terms, path_like in queries(text):
        cmd = [sys.executable, str(INDEX_SCRIPT), "--workspace", str(workspace), "search", terms, "--limit", "5", "--per-file", "1"]
        if path_like:
            cmd += ["--path-like", path_like]
        res = _run(cmd)
        if not res or res.get("status") != "OK":
            has_index = False
            break
        ran.append(terms + (f" [{path_like}]" if path_like else ""))
        for h in res.get("results", []):
            rel = h.get("rel_path", "")
            key = (rel, h.get("page_or_location"))
            if key in seen or any(n in rel for n in _NOISE_PATHS) or any(e and e in rel for e in exclude):
                continue
            if len(h.get("evidence_excerpt", "")) < 20 or not relevant(h.get("evidence_excerpt", ""), text):
                continue
            seen.add(key)
            hits.append(h)
    return hits[:_MAX_CANDIDATES], ran, has_index


def _add_candidates(workspace: Path, dr_id: str, text: str, hits: list[dict], rejected: set[str]) -> list[str]:
    rows = [{
        "csa_area": "gap_lookup", "question": f"{dr_id}: {text}"[:400],
        "claim": f"Possible answer to {dr_id}: the source reads: {h['evidence_excerpt'][:260]}",
        "status": "UNCONFIRMED", "source_title": h["source_title"], "source_version": h.get("source_version", ""),
        "section": "", "page_or_location": h.get("page_or_location", ""), "evidence_excerpt": h["evidence_excerpt"][:1200],
        "inference_reason": "", "confidence": "low",
        "gap_or_action": (f"Found by the gap lookup for {dr_id}. Read it: if it answers the question, record a VERIFIED row "
                          "that states the answer; if not, reject this row (evidence_matrix.py review --state rejected)"),
    } for h in hits]
    ids: list[str] = []
    for row in rows:            # one call each, so a row the matrix refuses does not stop the others
        res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append", "--agent", "gap lookup",
                    "--context", dr_id, "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)])
        if not res:
            continue
        for w in res.get("written", []):
            ids.append(w["evidence_id"])
        for s in res.get("skipped_duplicates", []):
            dup = s.get("duplicate_of", "")
            if dup and dup.upper() not in rejected:
                ids.append(dup)
    return list(dict.fromkeys(ids))


def lookup_gap(workspace: Path, dr_id: str, text: str, *, exclude: tuple[str, ...] = ()) -> dict:
    """Search the matrix, then the index, for evidence on a gap; add what is found to the matrix."""
    workspace = Path(workspace)
    rejected = _rejected(workspace) | _acknowledged(workspace, dr_id)
    matrix_state, matrix_ids = _matrix_stage(workspace, text, rejected)
    hits, ran, has_index = _index_stage(workspace, text, exclude)
    index_ids = _add_candidates(workspace, dr_id, text, hits, rejected) if hits else []
    found = list(dict.fromkeys(matrix_ids + [i for i in index_ids if i.upper() not in rejected]))
    if matrix_state == "ANSWERED" and not matrix_ids:
        matrix_state = "NONE"
    verdict = "ANSWERED" if matrix_state == "ANSWERED" else "CANDIDATES" if found else "NOT_FOUND"
    scope = ("evidence matrix" + ("" if matrix_state != "NO_MATRIX" else " (none)")
             + "; discovery index" + (f" ({len(ran)} searches: {'; '.join(ran)})" if has_index else " (no index built)"))
    return {"verdict": verdict, "matrix": matrix_ids, "index": index_ids, "evidence_ids": found,
            "queries": ran, "searched": scope}


def confirm_gap(workspace: Path, dr_id: str, text: str, considered: list[str], *, ask: str,
                exclude: tuple[str, ...] = ()) -> dict:
    """Record that the evidence found for a gap was read and does not answer it: reject the candidate rows the
    lookup added, and append a NOT_FOUND row that names everything considered and what was searched."""
    workspace = Path(workspace)
    look = lookup_gap(workspace, dr_id, text, exclude=exclude)
    ids = sorted({i.upper() for i in considered} | {i.upper() for i in look["evidence_ids"]})
    with (workspace / "csa-work" / "evidence-matrix.csv").open(newline="", encoding="utf-8-sig") as fh:
        candidates = {r["evidence_id"].upper() for r in csv.DictReader(fh)
                      if r["status"] == "UNCONFIRMED" and r["claim"].startswith(f"Possible answer to {dr_id}")}
    to_reject = [i for i in ids if i in candidates]
    if to_reject:
        subprocess.run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "review", *to_reject,
                        "--by", "gap lookup", "--state", "rejected",
                        "--note", f"read for {dr_id}: does not answer the question"], capture_output=True, text=True)
    row = {"csa_area": "discovery_required", "question": text[:400],
           "claim": f"No evidence in the matrix or the discovery index answers: {text[:300]}",
           "status": "NOT_FOUND", "source_title": f"searched: {look['searched']}"[:1400], "source_version": "",
           "section": "8 Discovery Required", "page_or_location": "", "evidence_excerpt": "",
           "inference_reason": f"read and considered, not an answer to {dr_id}: {', '.join(ids)}" if ids else "",
           "confidence": "low", "gap_or_action": f"{dr_id} {ask}"}
    res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append", "--agent", "gap lookup",
                "--context", f"confirm {dr_id}", "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)])
    written = (res or {}).get("written", [])
    return {"status": "OK" if written or (res or {}).get("skipped_duplicates") else "ERROR",
            "dr_id": dr_id, "not_found_row": written[0]["evidence_id"] if written else "",
            "rejected": to_reject, "considered": ids}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Search the evidence matrix and the discovery index for a gap.")
    ap.add_argument("action", choices=["check", "confirm"])
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--dr", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--considered", default="", help="confirm: evidence IDs read and judged not to answer it")
    ap.add_argument("--ask", default="Confirm with the site team or the application owner", help="confirm: who to ask")
    ap.add_argument("--legacy-docx", type=Path)
    a = ap.parse_args(argv)
    exclude = (a.legacy_docx.name,) if a.legacy_docx else ()
    if a.action == "check":
        print(json.dumps(lookup_gap(a.workspace, a.dr, a.text, exclude=exclude), ensure_ascii=False))
        return 0
    considered = [x.strip() for x in a.considered.split(",") if x.strip()]
    res = confirm_gap(a.workspace, a.dr, a.text, considered, ask=a.ask, exclude=exclude)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
