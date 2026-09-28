#!/usr/bin/env python3
"""CSA evidence matrix helper: matrix-first lookup and append-only writes.

Used by csa-change-authoring, csa-document and csa-change-review agents (see
../SKILL.md). Standard library only; runs on Python 3.8+.

Commands
  lookup   find existing evidence rows for a question/claim (READ)
  get      print rows by evidence_id                          (READ)
  stats    counts by status / area / review_state             (READ)
  verify   structural health check of the matrix              (READ)
  append   add new evidence rows, append-only, validated      (WRITE)

Every command prints one JSON document to stdout. Exit code 0 = OK,
2 = rejected / error (nothing was written).
"""
import argparse
import csv
import datetime
import fcntl
import io
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

COLUMNS = [
    "evidence_id", "csa_area", "question", "claim", "status", "source_title",
    "source_version", "section", "page_or_location", "evidence_excerpt",
    "inference_reason", "confidence", "gap_or_action", "review_state",
]
STATUSES = ("VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND")
ANSWER_STATUSES = ("VERIFIED", "INFERRED")
CONFIDENCES = ("high", "medium", "low")
REVIEW_STATES = ("pending", "reviewed", "accepted", "disputed")
MAX_EXCERPT = 1200
MAX_FIELD = 1500

FIELD_WEIGHT = {
    "claim": 3.0, "question": 3.0, "evidence_excerpt": 2.0, "source_title": 1.5,
    "csa_area": 1.0, "section": 1.0, "page_or_location": 1.0,
    "inference_reason": 1.0, "gap_or_action": 1.0, "source_version": 0.5,
}
STOP = set(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was were with which what who where when how do does did than then "
    "into per any all not no can our their there these those".split()
)
SECRET_RE = re.compile(
    r"(?i)\b(pass(word|wd)?|pwd|secret|api[_-]?key|access[_-]?key|token|private[_-]?key)\b\s*[:=]\s*\S+"
)


# --------------------------------------------------------------------------- paths
def _load_project_registry():
    """Parse csa-context/PROJECTS.yaml (fixed-shape, no PyYAML dependency).
    Returns [] if the registry can't be found or read -- callers then skip
    the cross-project check rather than blocking every command on a
    framework installation problem.

    This script's own location is .agents/skills/csa-evidence-matrix/scripts/
    -- three parents up is .agents/.
    """
    registry_path = (
        Path(os.environ["CSA_PROJECTS_FILE"])
        if os.environ.get("CSA_PROJECTS_FILE")
        else Path(__file__).resolve().parents[3] / "csa-context" / "PROJECTS.yaml"
    )
    if not registry_path.is_file():
        return []
    projects = []
    current = {}
    try:
        for raw_line in registry_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if raw_line[:1] not in (" ", "\t"):
                # Top-level key (e.g. the "projects:" list header) -- not
                # part of an entry, so nothing to record.
                continue
            if stripped.startswith("- key:"):
                if current:
                    projects.append(current)
                current = {}
                stripped = stripped[2:]
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip().strip('"').strip("'")
        if current:
            projects.append(current)
    except OSError:
        return []
    return projects


def _resolve_registered_project(workspace):
    for project in _load_project_registry():
        root = project.get("project_root")
        if not root:
            continue
        try:
            root_path = Path(root).expanduser().resolve()
        except OSError:
            continue
        if workspace == root_path or root_path in workspace.parents:
            return project
    return None


def resolve_paths(args):
    ws = args.workspace or os.environ.get("CSA_WORKSPACE")
    if ws:
        workspace = Path(ws).expanduser().resolve()
    else:
        # No --workspace / CSA_WORKSPACE given: fall back to cwd, the same
        # default the csa-mcp server uses (CSA_MCP_WORKSPACE / cwd). Do NOT
        # guess a path relative to this script's own location -- this
        # script is shared by every CSA project, so a relative guess from
        # here has no reliable relationship to any one project's root.
        workspace = Path.cwd().resolve()

    # Cross-project safety guard: this script (like the rest of the shared
    # .agents framework) is used by more than one CSA project. Refuse to
    # read or write an evidence matrix whose workspace isn't a registered
    # project's project_root (or a path under it) in csa-context/PROJECTS.yaml
    # -- never silently fall back to a wrong or empty project's matrix. If
    # the registry itself can't be read, skip this check rather than
    # blocking every command on an installation problem.
    registry = _load_project_registry()
    if registry and _resolve_registered_project(workspace) is None:
        fail(
            f"WORKSPACE_NOT_REGISTERED: {workspace} is not the project_root (or a "
            "path under it) of any project listed in csa-context/PROJECTS.yaml. "
            "Refusing to read or write an evidence matrix for an unregistered "
            "workspace -- pass --workspace <project_root> explicitly, or register "
            "this project in PROJECTS.yaml first.",
            workspace=str(workspace),
        )

    matrix = args.matrix or os.environ.get("CSA_EVIDENCE_MATRIX")
    matrix = Path(matrix).expanduser().resolve() if matrix else workspace / "csa-work" / "evidence-matrix.csv"
    return workspace, matrix


# --------------------------------------------------------------------------- io
def load(path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text[:8192] else "\n"
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        raise ValueError("matrix file is empty (no header row)")
    return rows[0], rows[1:], bom, nl, raw


def as_dict(header, row):
    row = list(row) + [""] * (len(COLUMNS) - len(row))
    return dict(zip(COLUMNS, row[: len(COLUMNS)]))


def fail(msg, **extra):
    out = {"status": "ERROR", "message": msg}
    out.update(extra)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(2)


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- text
def stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def toks(text):
    out = set()
    for t in re.findall(r"[a-z0-9]+(?:[._\-\\/:][a-z0-9]+)*", (text or "").lower()):
        parts = [t]
        if re.search(r"[._\-\\/:]", t):
            parts += re.split(r"[._\-\\/:]", t)
        for p in parts:
            p = stem(p)
            if len(p) > 1 and p not in STOP:
                out.add(p)
    return out


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# --------------------------------------------------------------------------- lookup
def cmd_lookup(args):
    workspace, matrix = resolve_paths(args)
    header, body, *_ = load(matrix)
    rows = [as_dict(header, r) for r in body]
    n = len(rows)
    field_toks = [{f: toks(r[f]) for f in FIELD_WEIGHT} for r in rows]
    df = {}
    for ft in field_toks:
        seen = set().union(*ft.values())
        for t in seen:
            df[t] = df.get(t, 0) + 1

    q = toks(args.query)
    if not q:
        fail("query has no searchable terms")
    idf = {t: math.log(1 + n / max(df.get(t, 0), 0.5)) for t in q}
    den = sum(idf.values()) * 3.0

    wanted_status = {s.strip().upper() for s in args.status.split(",")} if args.status else None
    area = args.area.strip().lower() if args.area else None
    host = args.host.strip().lower() if args.host else None

    scored = []
    for r, ft in zip(rows, field_toks):
        if wanted_status and r["status"].upper() not in wanted_status:
            continue
        if area and area not in r["csa_area"].lower():
            continue
        if host and host not in " ".join(r.values()).lower():
            continue
        num, matched = 0.0, []
        for t in q:
            best = max((FIELD_WEIGHT[f] for f in FIELD_WEIGHT if t in ft[f]), default=0.0)
            if best:
                num += idf[t] * best
                matched.append(t)
        score = num / den if den else 0.0
        if norm(args.query) in norm(r["claim"]) or norm(args.query) in norm(r["question"]):
            score = min(1.0, score + 0.1)
        if score >= args.min_score:
            scored.append((score, len(matched) / len(q), r, sorted(matched)))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]["evidence_id"]))
    top = scored[: args.limit]

    best = scored[0] if scored else None
    best_status = best[2]["status"] if best else None
    answered = bool(best) and best_status in ANSWER_STATUSES and best[0] >= 0.6 and best[1] >= 0.75
    if not answered and best and best_status not in ("NOT_FOUND", "CONFLICTING", "UNCONFIRMED"):
        answered = any(r["status"] in ANSWER_STATUSES and s >= 0.6 and c >= 0.75 for s, c, r, _ in scored[:3])
    if answered:
        verdict = "LIKELY_ANSWERED"
        nxt = ("Read each match's claim, excerpt, host and capture date and confirm it answers "
               "THIS question for THIS host/date. If it does, cite the evidence_id and use it; "
               "do not re-search Discovery Data for it. If it only partly answers, search "
               "Discovery Data for the remainder and append what you find.")
    elif best and best_status == "NOT_FOUND" and best[0] >= 0.5:
        verdict = "PRIOR_NOT_FOUND"
        nxt = ("An earlier search recorded NOT_FOUND. Read its source_title (searched scope). "
               "Search only sources OUTSIDE that scope, or captures newer than it, then append "
               "the result (a new VERIFIED/INFERRED row, or a new NOT_FOUND with the wider scope).")
    elif best and best_status in ("CONFLICTING", "UNCONFIRMED") and best[0] >= 0.45:
        verdict = "OPEN_ON_RECORD"
        nxt = ("The matrix already holds a CONFLICTING/UNCONFIRMED entry. Do not present it as "
               "settled. Search Discovery Data for the deciding evidence; append the outcome as a "
               "new row that cites the earlier evidence_id in gap_or_action.")
    elif scored:
        verdict = "PARTIAL_MATCH"
        nxt = ("Related rows exist but none clearly answers the question. Search Discovery Data, "
               "then append the new finding.")
    else:
        verdict = "NO_MATCH"
        nxt = ("Nothing on record. Search Discovery Data, then append every finding "
               "(and a NOT_FOUND with the searched scope if nothing is found).")

    emit({
        "status": "OK",
        "matrix": str(matrix),
        "rows_total": n,
        "query": args.query,
        "verdict": verdict,
        "next_step": nxt,
        "matches": [
            dict(score=round(s, 3), coverage=round(c, 2), matched_terms=m, **r)
            for s, c, r, m in top
        ],
    })


# --------------------------------------------------------------------------- get/stats/verify
def cmd_get(args):
    _, matrix = resolve_paths(args)
    header, body, *_ = load(matrix)
    ids = {i.strip().upper() for i in args.ids}
    rows = [as_dict(header, r) for r in body if r and r[0].upper() in ids]
    reviews = latest_reviews(matrix)
    rows = [with_review(r, reviews) for r in rows]
    found = {r["evidence_id"].upper() for r in rows}
    emit({"status": "OK", "rows": rows, "not_found": sorted(ids - found)})


def cmd_stats(args):
    _, matrix = resolve_paths(args)
    header, body, *_ = load(matrix)
    rows = [as_dict(header, r) for r in body]
    def count(key):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))
    emit({"status": "OK", "matrix": str(matrix), "rows": len(rows),
          "by_status": count("status"), "by_area": count("csa_area"),
          "by_review_state": count("review_state"),
          "last_evidence_id": rows[-1]["evidence_id"] if rows else None})


def cmd_verify(args):
    _, matrix = resolve_paths(args)
    header, body, bom, nl, _ = load(matrix)
    issues = []
    if header != COLUMNS:
        issues.append({"row": 0, "issue": "header differs from template", "found": header})
    seen, last = set(), 0
    for i, r in enumerate(body, start=2):
        eid = r[0] if r else ""
        if len(r) != len(COLUMNS):
            issues.append({"row": i, "evidence_id": eid, "issue": f"{len(r)} columns, expected {len(COLUMNS)}"})
            continue
        d = as_dict(header, r)
        m = re.fullmatch(r"E-(\d{3,})", eid)
        if not m:
            issues.append({"row": i, "evidence_id": eid, "issue": "evidence_id not E-nnn"})
        else:
            k = int(m.group(1))
            if k <= last:
                issues.append({"row": i, "evidence_id": eid, "issue": "evidence_id not increasing"})
            last = max(last, k)
        if eid in seen:
            issues.append({"row": i, "evidence_id": eid, "issue": "duplicate evidence_id"})
        seen.add(eid)
        if d["status"] not in STATUSES:
            issues.append({"row": i, "evidence_id": eid, "issue": f"invalid status {d['status']!r}"})
        if d["confidence"] and d["confidence"] not in CONFIDENCES:
            issues.append({"row": i, "evidence_id": eid,
                           "issue": "confidence column is not high/medium/low",
                           "found": d["confidence"][:80]})
        if d["review_state"] not in REVIEW_STATES:
            issues.append({"row": i, "evidence_id": eid, "issue": f"invalid review_state {d['review_state']!r}"})
    emit({"status": "OK" if not issues else "ISSUES", "matrix": str(matrix),
          "rows": len(body), "bom": bom, "newline": "CRLF" if nl == "\r\n" else "LF",
          "issue_count": len(issues), "issues": issues})


# --------------------------------------------------------------------------- append
def one_line(v):
    v = "" if v is None else str(v)
    v = re.sub(r"\s*[\r\n]+\s*", " | ", v.strip())
    return v


def validate_row(raw, known_areas, allow_new_area):
    errs = []
    unknown = set(raw) - set(COLUMNS)
    if unknown:
        errs.append(f"unknown field(s): {sorted(unknown)}")
    if "evidence_id" in raw and raw["evidence_id"]:
        errs.append("evidence_id is assigned by the tool; do not supply it")
    row = {c: one_line(raw.get(c, "")) for c in COLUMNS}
    row["evidence_id"] = ""
    row["status"] = row["status"].upper()
    row["confidence"] = row["confidence"].lower()
    row["review_state"] = row["review_state"].lower() or "pending"
    if row["review_state"] != "pending":
        errs.append("review_state must be 'pending' on append (reviewing is a human decision)")
    for req in ("csa_area", "question", "claim", "status"):
        if not row[req]:
            errs.append(f"{req} is required")
    if row["status"] and row["status"] not in STATUSES:
        errs.append(f"status must be one of {list(STATUSES)}")
    if row["csa_area"] and row["csa_area"] not in known_areas and not allow_new_area:
        errs.append(f"csa_area {row['csa_area']!r} is not an existing area {sorted(known_areas)}; "
                    "use one of them, or pass --allow-new-area if a new area is truly needed")
    if row["confidence"] and row["confidence"] not in CONFIDENCES:
        errs.append("confidence must be high, medium, low or empty")
    st = row["status"]
    if st == "VERIFIED":
        for f in ("source_title", "evidence_excerpt"):
            if not row[f]:
                errs.append(f"VERIFIED requires {f}")
        if not (row["page_or_location"] or row["section"]):
            errs.append("VERIFIED requires page_or_location or section (file name / location in source)")
    elif st == "INFERRED":
        if not row["inference_reason"]:
            errs.append("INFERRED requires inference_reason (the reasoning from verified facts)")
    elif st == "NOT_FOUND":
        if not row["source_title"]:
            errs.append("NOT_FOUND requires source_title = the scope that was searched")
        if not row["gap_or_action"]:
            errs.append("NOT_FOUND requires gap_or_action (what is missing / who to ask)")
    elif st == "CONFLICTING":
        if not row["source_title"] or not row["gap_or_action"]:
            errs.append("CONFLICTING requires source_title and gap_or_action naming the disagreeing sources or evidence_ids")
    elif st == "UNCONFIRMED":
        if not row["gap_or_action"]:
            errs.append("UNCONFIRMED requires gap_or_action")
    if len(row["evidence_excerpt"]) > MAX_EXCERPT:
        errs.append(f"evidence_excerpt is {len(row['evidence_excerpt'])} chars; keep <= {MAX_EXCERPT} (quote only the supporting lines)")
    for f in COLUMNS:
        if len(row[f]) > MAX_FIELD and f != "evidence_excerpt":
            errs.append(f"{f} is too long ({len(row[f])} chars)")
    for f in ("claim", "evidence_excerpt", "inference_reason", "source_title"):
        if SECRET_RE.search(row[f]):
            errs.append(f"{f} looks like it contains a credential/secret value; redact it before recording")
    return row, errs


def next_id_number(body):
    top = 0
    for r in body:
        m = re.fullmatch(r"E-(\d+)", r[0]) if r else None
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def cmd_append(args):
    workspace, matrix = resolve_paths(args)
    if args.rows_file:
        payload = sys.stdin.read() if args.rows_file == "-" else Path(args.rows_file).read_text(encoding="utf-8")
    elif args.row_json:
        payload = args.row_json
    else:
        fail("supply --row-json '<json>' or --rows-file <path|->")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        fail(f"input is not valid JSON: {e}")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data or not all(isinstance(x, dict) for x in data):
        fail("input must be a JSON object or a non-empty array of objects")

    lock_path = matrix.parent / ".evidence-matrix.lock"
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            header, body, bom, nl, raw = load(matrix)
            if header != COLUMNS:
                fail("matrix header differs from the template; run 'verify' and repair before appending")
            existing = [as_dict(header, r) for r in body]
            known_areas = {r["csa_area"] for r in existing if r["csa_area"]}

            prepared, errors = [], []
            for i, item in enumerate(data):
                row, errs = validate_row(item, known_areas, args.allow_new_area)
                if errs:
                    errors.append({"index": i, "claim": (item.get("claim") or "")[:100], "errors": errs})
                else:
                    prepared.append(row)
            if errors:
                fail("rows rejected; nothing written", rejected=errors)

            n = next_id_number(body)
            written, skipped, also = [], [], []
            batch_keys = set()
            for row in prepared:
                key = (norm(row["claim"]), row["status"], norm(row["source_title"]))
                dup = next((e for e in existing
                            if (norm(e["claim"]), e["status"], norm(e["source_title"])) == key), None)
                if (dup or key in batch_keys) and not args.allow_duplicate:
                    skipped.append({"claim": row["claim"][:100],
                                    "duplicate_of": dup["evidence_id"] if dup else "(same batch)"})
                    continue
                batch_keys.add(key)
                same = [e["evidence_id"] for e in existing
                        if norm(e["claim"]) == norm(row["claim"]) and e["evidence_id"] != (dup or {}).get("evidence_id")]
                row["evidence_id"] = f"E-{n:03d}"
                n += 1
                written.append(row)
                if same:
                    also.append({"evidence_id": row["evidence_id"], "same_claim_as": same})

            if args.dry_run or not written:
                emit({"status": "DRY_RUN" if args.dry_run else "NOTHING_TO_WRITE",
                      "would_write": [{"evidence_id": r["evidence_id"], "status": r["status"],
                                       "claim": r["claim"][:100]} for r in written],
                      "skipped_duplicates": skipped, "same_claim_elsewhere": also})
                return

            backup_dir = matrix.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = backup_dir / f"evidence-matrix-{stamp}.csv"
            shutil.copy2(matrix, backup)

            buf = io.StringIO()
            w = csv.writer(buf, lineterminator=nl)
            for r in written:
                w.writerow([r[c] for c in COLUMNS])
            prefix = b"" if raw.endswith(b"\n") else nl.encode()
            with open(matrix, "ab") as fh:
                fh.write(prefix + buf.getvalue().encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())

            audit = matrix.parent / "evidence-matrix-audit.jsonl"
            with open(audit, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "agent": args.agent, "context": args.context,
                    "action": "append", "ids": [r["evidence_id"] for r in written],
                    "backup": backup.name}, ensure_ascii=False) + "\n")

            emit({"status": "APPENDED", "matrix": str(matrix), "backup": str(backup),
                  "written": [{"evidence_id": r["evidence_id"], "status": r["status"],
                               "claim": r["claim"][:100]} for r in written],
                  "skipped_duplicates": skipped, "same_claim_elsewhere": also})
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- main
def latest_reviews(matrix) -> dict:
    """evidence_id -> latest review record from evidence-reviews.jsonl (empty if none)."""
    log = matrix.parent / "evidence-reviews.jsonl"
    out = {}
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["evidence_id"].upper()] = rec
    return out


def with_review(row: dict, reviews: dict) -> dict:
    rec = reviews.get(row.get("evidence_id", "").upper())
    if rec:
        row = dict(row, review_state=rec["state"], reviewed_by=rec["by"], reviewed_at=rec["at"])
    return row


def cmd_review(args):
    _, matrix = resolve_paths(args)
    header, body, *_ = load(matrix)
    known = {r[0].strip().upper() for r in body if r}
    ids = [i.strip().upper() for i in args.ids]
    missing = [i for i in ids if i not in known]
    if missing:
        fail(f"unknown evidence_id(s): {', '.join(missing)}")
    log = matrix.parent / "evidence-reviews.jsonl"
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(log, "a", encoding="utf-8") as fh:
        for i in ids:
            fh.write(json.dumps({"evidence_id": i, "state": args.state, "by": args.by, "at": at,
                                 "note": args.note or ""}, ensure_ascii=False) + "\n")
    emit({"status": "OK", "reviewed": ids, "state": args.state, "log": str(log)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", help="workspace root (default: derived from this script's location)")
    ap.add_argument("--matrix", help="explicit matrix path (default: <workspace>/csa-work/evidence-matrix.csv)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lookup", help="find existing evidence for a question/claim")
    p.add_argument("query", help="short keyword phrase: topic + host/port/service names")
    p.add_argument("--area"); p.add_argument("--status", help="comma list, e.g. VERIFIED,INFERRED")
    p.add_argument("--host", help="substring that must appear in the row (host, port, file name)")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--min-score", type=float, default=0.25)
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("get", help="print rows by evidence_id")
    p.add_argument("ids", nargs="+")
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("verify"); p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("review", help="record a human review of rows (appends to evidence-reviews.jsonl; the CSV is not changed)")
    p.add_argument("ids", nargs="+")
    p.add_argument("--by", required=True)
    p.add_argument("--state", choices=["reviewed", "rejected"], default="reviewed")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("append", help="append new evidence rows (append-only)")
    p.add_argument("--agent", required=True, help="who is writing, e.g. csa-change-authoring-agent")
    p.add_argument("--context", default="", help="run context, e.g. 'Section 2 batch 1, S2-E3'")
    p.add_argument("--row-json", help="one JSON object or an array of objects")
    p.add_argument("--rows-file", help="path to a JSON file, or - for stdin")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-duplicate", action="store_true")
    p.add_argument("--allow-new-area", action="store_true")
    p.set_defaults(fn=cmd_append)

    args = ap.parse_args()
    try:
        args.fn(args)
    except FileNotFoundError as e:
        fail(f"file not found: {e.filename}")
    except ValueError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
