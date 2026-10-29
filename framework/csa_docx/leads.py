"""Append-only discovery leads for CSA gap lookup and settlement.

Search hits are not evidence.  This store keeps the exact question and source
identity until a reviewer reads the original source and either links the lead
to evidence, records that it is not an answer, or retires it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

from csa_docx import tools

MAX_EXCERPT = 1200
MAX_FIELD = 1500
STATES = {"open", "not_an_answer", "resolved", "retired"}
_ID = re.compile(r"L-(\d{6,})$")
_EVIDENCE_ID = re.compile(r"E-\d+$", re.I)
_SECRET = re.compile(
    r"(?i)\b(pass(word|wd)?|pwd|secret|api[_-]?key|access[_-]?key|token|private[_-]?key)\b\s*[:=]\s*\S+"
)


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace(workspace: str | Path) -> Path:
    value = Path(workspace).expanduser().resolve()
    error = tools._check_workspace_registered(value)
    if error:
        raise ValueError(error["message"])
    return value


def _paths(workspace: str | Path) -> tuple[Path, Path, Path, Path]:
    ws = _workspace(workspace)
    intake = ws / "csa-work" / "intake"
    return ws, intake / "leads.jsonl", intake / "leads-reviews.jsonl", intake / ".leads.lock"


def _fingerprint(question: str, dr_id: str = "") -> str:
    # The DR identifier is part of the question identity: two active cards may ask the
    # same words independently and must be retired/settled independently.
    normal = re.sub(r"\s+", " ", f"{dr_id}\n{question or ''}").strip().casefold()
    return "sha256:" + hashlib.sha256(normal.encode("utf-8")).hexdigest()


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> tuple[list[dict], list[dict], int]:
    """Return records, parse errors and the byte offset after the last valid line."""
    if not path.is_file():
        return [], [], 0
    raw = path.read_bytes()
    records: list[dict] = []
    errors: list[dict] = []
    offset = 0
    valid_end = 0
    lines = raw.splitlines(keepends=True)
    for number, data in enumerate(lines, 1):
        offset += len(data)
        try:
            value = json.loads(data.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append({"line": number, "error": str(exc), "truncated": number == len(lines) and not raw.endswith(b"\n")})
            continue
        records.append(value)
        valid_end = offset
    return records, errors, valid_end


def _recover_interrupted_tail(path: Path) -> tuple[list[dict], list[dict]]:
    records, errors, valid_end = _read_jsonl(path)
    if not errors:
        return records, []
    if len(errors) == 1 and errors[0]["truncated"]:
        with path.open("r+b") as fh:
            fh.truncate(valid_end)
            fh.flush()
            os.fsync(fh.fileno())
        return records, errors
    raise ValueError(f"malformed JSONL in {path}: {errors}")


def _append(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = b""
    if path.is_file() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        prefix = b"\n"
    payload = prefix + b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for r in records)
    with path.open("ab") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())


def _identity(record: dict) -> tuple[str, str, str, str]:
    return (
        record["question_fingerprint"],
        str(record.get("rel_path") or record["source_ref"]),
        str(record.get("source_version") or record["excerpt_hash"]),
        str(record.get("page_or_location") or ""),
    )


def _validate_hit(hit: dict, *, migration: bool) -> None:
    if not isinstance(hit, dict):
        raise ValueError("each hit must be an object")
    source_ref = hit.get("source_ref") or hit.get("source_title")
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("source_ref is required")
    rel_path = hit.get("rel_path")
    if not migration and (not isinstance(rel_path, str) or not rel_path.strip()):
        raise ValueError("rel_path is required for new leads")
    if migration and rel_path is not None and not isinstance(rel_path, str):
        raise ValueError("rel_path must be a string or null")
    excerpt = hit.get("evidence_excerpt", hit.get("excerpt", ""))
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise ValueError("excerpt is required")
    if len(excerpt) > MAX_EXCERPT:
        raise ValueError(f"excerpt is {len(excerpt)} chars; keep <= {MAX_EXCERPT}")
    terms = hit.get("terms", [])
    if not isinstance(terms, list) or not all(isinstance(x, str) for x in terms):
        raise ValueError("terms must be a list of strings")
    for name in ("source_title", "source_ref", "source_version", "source_class", "page_or_location"):
        value = hit.get(name, "") or ""
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        if len(value) > MAX_FIELD:
            raise ValueError(f"{name} is too long ({len(value)} chars)")
    for name, value in (("source_ref", source_ref), ("excerpt", excerpt), ("source_title", hit.get("source_title", ""))):
        if _SECRET.search(value or ""):
            raise ValueError(f"{name} looks like it contains a credential/secret value")


def _overlay(leads: list[dict], reviews: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for item in reviews:
        latest[str(item.get("lead_id", "")).upper()] = item
    out = []
    for item in leads:
        row = dict(item)
        review_rec = latest.get(str(row.get("lead_id", "")).upper())
        if review_rec:
            row["state"] = review_rec.get("state", "open")
            row["review"] = review_rec
        else:
            row["state"] = "open"
        out.append(row)
    return sorted(out, key=lambda r: int(_ID.fullmatch(r.get("lead_id", "")).group(1)) if _ID.fullmatch(r.get("lead_id", "")) else 10**18)


def add_leads(workspace: str | Path, dr_id: str, qid: str, question: str, hits: list[dict], *, migration: bool = False) -> list[str]:
    """Append new identities and return the existing/new lead ID for every hit."""
    if not dr_id or not qid or not question.strip():
        raise ValueError("dr_id, qid and question are required")
    if not isinstance(hits, list):
        raise ValueError("hits must be a list")
    for item in hits:
        _validate_hit(item, migration=migration)
    _, lead_path, review_path, lock_path = _paths(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            existing, _ = _recover_interrupted_tail(lead_path)
            reviews, review_errors, _ = _read_jsonl(review_path)
            if review_errors:
                raise ValueError(f"malformed JSONL in {review_path}: {review_errors}")
            by_identity = {_identity(r): r for r in existing}
            top = max((int(m.group(1)) for r in existing if (m := _ID.fullmatch(str(r.get("lead_id", ""))))), default=0)
            now = _utc()
            added: list[dict] = []
            ids: list[str] = []
            question_fp = _fingerprint(question, dr_id)
            for hit in hits:
                excerpt = hit.get("evidence_excerpt", hit.get("excerpt", ""))
                record = {
                    "lead_id": "",
                    "dr_id": dr_id,
                    "qid": qid,
                    "question": question,
                    "question_fingerprint": question_fp,
                    "source_title": hit.get("source_title") or hit.get("source_ref"),
                    "source_ref": hit.get("source_ref") or hit.get("source_title"),
                    "rel_path": hit.get("rel_path"),
                    "source_version": hit.get("source_version", ""),
                    "source_class": hit.get("source_class", ""),
                    "page_or_location": hit.get("page_or_location", ""),
                    "excerpt": excerpt,
                    "excerpt_hash": _digest(excerpt),
                    "terms": list(hit.get("terms", [])),
                    "found_at": hit.get("found_at") or now,
                }
                if hit.get("legacy_evidence_ids"):
                    record["legacy_evidence_ids"] = sorted({str(x).upper() for x in hit["legacy_evidence_ids"]})
                prior = by_identity.get(_identity(record))
                if prior:
                    ids.append(prior["lead_id"])
                    continue
                top += 1
                record["lead_id"] = f"L-{top:06d}"
                by_identity[_identity(record)] = record
                added.append(record)
                ids.append(record["lead_id"])
            _append(lead_path, added)
            return ids
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _records(workspace: str | Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    _, lead_path, review_path, _ = _paths(workspace)
    lead_rows, lead_errors, _ = _read_jsonl(lead_path)
    review_rows, review_errors, _ = _read_jsonl(review_path)
    return lead_rows, review_rows, lead_errors, review_errors


def open_leads(workspace: str | Path, dr_id: str | None = None) -> list[dict]:
    lead_rows, review_rows, lead_errors, review_errors = _records(workspace)
    if lead_errors or review_errors:
        raise ValueError(f"malformed lead store: {lead_errors + review_errors}")
    return [r for r in _overlay(lead_rows, review_rows) if r["state"] == "open" and (dr_id is None or r.get("dr_id") == dr_id)]


def already_read(workspace: str | Path, dr_id: str) -> set[str]:
    lead_rows, review_rows, lead_errors, review_errors = _records(workspace)
    if lead_errors or review_errors:
        raise ValueError(f"malformed lead store: {lead_errors + review_errors}")
    return {
        str(r.get("rel_path") or r.get("source_ref"))
        for r in _overlay(lead_rows, review_rows)
        if r.get("dr_id") == dr_id and r["state"] != "open"
    }


def _known_evidence(workspace: Path) -> set[str]:
    matrix = workspace / "csa-work" / "evidence-matrix.csv"
    if not matrix.is_file():
        return set()
    with matrix.open(encoding="utf-8-sig", newline="") as fh:
        return {str(r.get("evidence_id", "")).upper() for r in csv.DictReader(fh) if r.get("evidence_id")}


def _lead_record_error(record: dict) -> str | None:
    required_strings = ("lead_id", "dr_id", "qid", "question", "question_fingerprint", "source_title",
                        "source_ref", "source_version", "source_class", "page_or_location", "excerpt",
                        "excerpt_hash", "found_at")
    if any(not isinstance(record.get(name), str) for name in required_strings):
        return "required lead fields must be strings"
    if not _ID.fullmatch(record["lead_id"]):
        return "invalid lead_id"
    if not record["dr_id"] or not record["qid"] or not record["question"] or not record["source_ref"]:
        return "required lead fields are empty"
    if not record["question_fingerprint"].startswith("sha256:") or not record["excerpt_hash"].startswith("sha256:"):
        return "invalid content hash"
    if record.get("rel_path") is not None and not isinstance(record.get("rel_path"), str):
        return "rel_path must be a string or null"
    if not isinstance(record.get("terms"), list) or not all(isinstance(x, str) for x in record["terms"]):
        return "terms must be a list of strings"
    legacy = record.get("legacy_evidence_ids", [])
    if not isinstance(legacy, list) or not all(isinstance(x, str) and _EVIDENCE_ID.fullmatch(x) for x in legacy):
        return "legacy_evidence_ids must contain E-IDs"
    if len(record["excerpt"]) > MAX_EXCERPT:
        return "excerpt is too long"
    if any(len(record.get(name, "")) > MAX_FIELD for name in
           ("source_title", "source_ref", "source_version", "source_class", "page_or_location")):
        return "source field is too long"
    return None


def _review_record_error(record: dict) -> str | None:
    if not isinstance(record.get("lead_id"), str) or not _ID.fullmatch(record["lead_id"]):
        return "invalid lead_id"
    if record.get("state") not in STATES:
        return "invalid state"
    if not all(isinstance(record.get(name), str) and record.get(name) for name in ("by", "at")):
        return "reviewer and timestamp are required"
    if not isinstance(record.get("note", ""), str):
        return "note must be a string"
    evidence = record.get("evidence_ids", [])
    if not isinstance(evidence, list) or not all(isinstance(x, str) and _EVIDENCE_ID.fullmatch(x) for x in evidence):
        return "evidence_ids must contain E-IDs"
    if record["state"] == "resolved" and not evidence:
        return "resolved review requires evidence_ids"
    if record["state"] != "resolved" and evidence:
        return "only resolved reviews may contain evidence_ids"
    if record["state"] == "retired" and not record.get("note", "").strip():
        return "retired review requires a note"
    return None


def review(workspace: str | Path, lead_ids: list[str], state: str, by: str, note: str, evidence_ids: list[str] | None = None) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(sorted(STATES))}")
    if not by.strip():
        raise ValueError("reviewer is required")
    ids = list(dict.fromkeys(str(x).upper() for x in lead_ids))
    ws, lead_path, review_path, lock_path = _paths(workspace)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            lead_rows, lead_errors, _ = _read_jsonl(lead_path)
            review_rows, review_errors, _ = _read_jsonl(review_path)
            if lead_errors or review_errors:
                raise ValueError(f"malformed lead store: {lead_errors + review_errors}")
            known = {str(r.get("lead_id", "")).upper() for r in lead_rows}
            missing = [x for x in ids if x not in known]
            if missing:
                raise ValueError("unknown lead ID(s): " + ", ".join(missing))
            overlaid = {r["lead_id"]: r for r in _overlay(lead_rows, review_rows)}
            current = {lead_id: row["state"] for lead_id, row in overlaid.items()}
            if state == "open" and any(current.get(x) != "open" for x in ids) and not note.strip():
                raise ValueError("reopening a lead requires an explicit note")
            if state == "retired" and not note.strip():
                raise ValueError("retired leads require an explicit note")
            evidence = sorted({str(x).upper() for x in (evidence_ids or [])})
            if state == "resolved" and not evidence:
                raise ValueError("resolved leads require evidence_ids")
            if state != "resolved" and evidence:
                raise ValueError("evidence_ids are only valid for resolved leads")
            bad_format = [x for x in evidence if not _EVIDENCE_ID.fullmatch(x)]
            unknown = [x for x in evidence if x not in _known_evidence(ws)]
            if bad_format or unknown:
                raise ValueError("unknown evidence ID(s): " + ", ".join(sorted(set(bad_format + unknown))))
            reused = []
            write_ids = []
            for lead_id in ids:
                prior = overlaid[lead_id].get("review", {})
                if (current.get(lead_id) == state and sorted(prior.get("evidence_ids", [])) == evidence
                        and str(prior.get("note", "")) == (note or "")):
                    reused.append(lead_id)
                else:
                    write_ids.append(lead_id)
            at = _utc()
            rows = [{"lead_id": x, "state": state, "evidence_ids": evidence, "by": by, "at": at, "note": note or ""} for x in write_ids]
            _append(review_path, rows)
            return {"status": "OK", "reviewed": write_ids, "reused": reused, "state": state,
                    "evidence_ids": evidence, "log": str(review_path)}
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def verify(workspace: str | Path) -> dict:
    ws, lead_path, review_path, _ = _paths(workspace)
    lead_rows, lead_errors, _ = _read_jsonl(lead_path)
    review_rows, review_errors, _ = _read_jsonl(review_path)
    ids = [str(r.get("lead_id", "")).upper() for r in lead_rows]
    duplicate_ids = sorted({x for x in ids if ids.count(x) > 1})
    known = set(ids)
    unknown_reviews = sorted({str(r.get("lead_id", "")).upper() for r in review_rows if str(r.get("lead_id", "")).upper() not in known})
    evidence = _known_evidence(ws)
    bad_links = []
    for r in review_rows:
        if r.get("state") == "resolved":
            bad = sorted({str(x).upper() for x in r.get("evidence_ids", []) if str(x).upper() not in evidence})
            if bad:
                bad_links.append({"lead_id": str(r.get("lead_id", "")).upper(), "evidence_ids": bad})
    bad_records = [{"lead_id": str(r.get("lead_id", "")) or "(missing)", "error": error}
                   for r in lead_rows if (error := _lead_record_error(r))]
    invalid_reviews = [{"lead_id": str(r.get("lead_id", "")) or "(missing)", "error": error}
                       for r in review_rows if (error := _review_record_error(r))]
    errors = lead_errors + review_errors
    out = {
        "status": "OK" if not (errors or duplicate_ids or unknown_reviews or bad_links or bad_records or invalid_reviews) else "ERROR",
        "leads": len(lead_rows),
        "reviews": len(review_rows),
        "states": {},
        "duplicate_ids": duplicate_ids,
        "unknown_review_leads": unknown_reviews,
        "bad_evidence_links": bad_links,
        "bad_records": bad_records,
        "invalid_reviews": invalid_reviews,
        "malformed_lines": [e["line"] for e in errors if not e.get("truncated")],
        "truncated_lines": [e["line"] for e in errors if e.get("truncated")],
        "paths": {"leads": str(lead_path), "reviews": str(review_path)},
    }
    if not errors:
        for r in _overlay(lead_rows, review_rows):
            out["states"][r["state"]] = out["states"].get(r["state"], 0) + 1
    return out


_LEGACY_CLAIM = re.compile(r"^Possible answer to (DR-[A-Za-z0-9_.-]+):")
_NON_ANSWER = re.compile(r"\b(?:does not|do not|did not|not an answer|not capture|doesn't|is not an answer)\b", re.I)
_MIGRATED = re.compile(r"migrated to lead (L-\d+); not an evidence row", re.I)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _evidence_rows(workspace: Path) -> list[dict]:
    path = workspace / "csa-work" / "evidence-matrix.csv"
    if not path.is_file():
        raise ValueError(f"evidence matrix is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _latest_evidence_reviews(workspace: Path) -> dict[str, dict]:
    path = workspace / "csa-work" / "evidence-reviews.jsonl"
    latest: dict[str, dict] = {}
    if not path.is_file():
        return latest
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"malformed evidence review at line {number}: {exc}") from exc
        latest[str(rec.get("evidence_id", "")).upper()] = rec
    return latest


def _indexed_paths(workspace: Path) -> list[str]:
    db = workspace / "csa-work" / "discovery-index.sqlite"
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [str(row[0]).replace("\\", "/") for row in con.execute("SELECT rel_path FROM files ORDER BY file_id")]
    finally:
        con.close()


def _resolve_rel_path(source_ref: str, indexed: list[str]) -> tuple[str | None, str | None]:
    source = (source_ref or "").strip().replace("\\", "/").removeprefix("./")
    if not source:
        return None, "missing source_ref"
    exact = [p for p in indexed if p.casefold() == source.casefold()]
    if len(exact) == 1:
        return exact[0], None
    # An explicit project-relative path is durable as written. Do not rebind a retired
    # project's path to a current file merely because the trailing filename matches.
    if "/" in source:
        return None, "explicit source path is not present in the discovery index"
    # Source titles may prefix a capture name with a colon. Match the longest path-like suffix first.
    suffixes = [source]
    if ": " in source:
        suffixes.append(source.split(": ", 1)[-1])
    names = re.findall(r"[^/:]+\.(?:txt|csv|xlsx|docx|doc|pdf|md|log|json|xml|ps1|pptx)\b", source, re.I)
    suffixes.extend(names)
    matches = []
    for suffix in sorted(set(suffixes), key=len, reverse=True):
        found = [p for p in indexed if p.casefold().endswith(suffix.casefold())]
        if len(found) == 1:
            return found[0], None
        matches.extend(found)
    matches = sorted(set(matches))
    if len(matches) > 1:
        captures = re.findall(r"[A-Za-z0-9-]+_\d{8}T\d{6}Z", source)
        scoped = [p for p in matches if any(c.casefold() in p.casefold() for c in captures)]
        if len(scoped) == 1:
            return scoped[0], None
        return None, f"ambiguous indexed source ({len(matches)} matches)"
    return None, "source not found in discovery index"


def _legacy_classification(row: dict, latest: dict[str, dict], known_evidence: set[str], migrated: dict[str, dict]) -> tuple[str, list[str], str | None]:
    evidence_id = str(row.get("evidence_id", "")).upper()
    rec = latest.get(evidence_id)
    if rec and _MIGRATED.search(str(rec.get("note", ""))) and evidence_id in migrated:
        lead = migrated[evidence_id]
        return lead["state"], list((lead.get("review") or {}).get("evidence_ids", [])), None
    state = str((rec or {}).get("state") or row.get("review_state") or "pending").lower()
    note = str((rec or {}).get("note") or "")
    if state in ("", "pending"):
        return "open", [], None
    if state == "rejected":
        return "not_an_answer", [], None
    if state in ("reviewed", "accepted"):
        if re.search(r"\bsettled by\b", note, re.I):
            ids = sorted(set(re.findall(r"E-\d+", note, re.I)))
            missing = [item.upper() for item in ids if item.upper() not in known_evidence]
            if not ids or missing:
                return "needs_manual_classification", [], f"settlement note has missing/unknown evidence IDs: {missing or ids}"
            return "resolved", [item.upper() for item in ids], None
        if _NON_ANSWER.search(note):
            return "not_an_answer", [], None
    return "needs_manual_classification", [], f"unclassified review state/note: {state}: {note[:160]}"


def _migration_plan(workspace: Path) -> dict:
    rows = _evidence_rows(workspace)
    latest = _latest_evidence_reviews(workspace)
    known_evidence = {str(r.get("evidence_id", "")).upper() for r in rows}
    candidates = [r for r in rows if r.get("csa_area") == "gap_lookup" and r.get("status") == "UNCONFIRMED"
                  and _LEGACY_CLAIM.match(r.get("claim", ""))]
    indexed = _indexed_paths(workspace)
    lead_rows, review_rows, lead_errors, review_errors = _records(workspace)
    if lead_errors or review_errors:
        raise ValueError(f"malformed lead store: {lead_errors + review_errors}")
    overlaid = _overlay(lead_rows, review_rows)
    migrated: dict[str, dict] = {}
    for lead in overlaid:
        for evidence_id in lead.get("legacy_evidence_ids", []):
            migrated[str(evidence_id).upper()] = lead
    existing_by_identity = {_identity(r): r for r in lead_rows}
    top = max((int(m.group(1)) for r in lead_rows if (m := _ID.fullmatch(str(r.get("lead_id", ""))))), default=0)
    warnings = []
    manual: list[str] = []
    prepared = []
    state_by_evidence: dict[str, tuple[str, tuple[str, ...]]] = {}
    prior_by_evidence: dict[str, dict | None] = {}
    for row in sorted(candidates, key=lambda r: int(str(r["evidence_id"]).split("-")[1])):
        evidence_id = str(row["evidence_id"]).upper()
        match = _LEGACY_CLAIM.match(row.get("claim", ""))
        dr_id = match.group(1)
        question = re.sub(rf"^{re.escape(dr_id)}:\s*", "", row.get("question", "")).strip() or row.get("question", "").strip()
        rel_path, warning = _resolve_rel_path(row.get("source_title", ""), indexed)
        if warning:
            warnings.append({"evidence_id": evidence_id, "source_ref": row.get("source_title", ""), "warning": warning})
        excerpt = row.get("evidence_excerpt", "") or row.get("claim", "")
        hit = {"source_title": row.get("source_title", ""), "source_ref": row.get("source_title", ""),
               "rel_path": rel_path, "source_version": row.get("source_version", ""),
               "source_class": "capture" if re.search(r"_\d{8}T\d{6}Z", row.get("source_title", "")) else "document",
               "page_or_location": row.get("page_or_location", ""), "evidence_excerpt": excerpt[:MAX_EXCERPT],
               "terms": [], "legacy_evidence_ids": [evidence_id]}
        record = {"question_fingerprint": _fingerprint(question, dr_id), "rel_path": rel_path,
                  "source_ref": hit["source_ref"], "source_version": hit["source_version"],
                  "excerpt_hash": _digest(hit["evidence_excerpt"]), "page_or_location": hit["page_or_location"]}
        state, evidence_ids, reason = _legacy_classification(row, latest, known_evidence, migrated)
        if state == "needs_manual_classification":
            manual.append(evidence_id)
        state_by_evidence[evidence_id] = (state, tuple(evidence_ids))
        prior_by_evidence[evidence_id] = latest.get(evidence_id)
        prepared.append({"row": row, "evidence_id": evidence_id, "dr_id": dr_id,
                         "qid": dr_id.rsplit("-", 1)[-1], "question": question, "hit": hit,
                         "identity": _identity(record),
                         # The historical writer's only stable duplicate key was the
                         # matrix tuple below. Keep that migration concern separate
                         # from the richer identity used for all new leads.
                         "legacy_identity": (dr_id, row.get("source_title", ""),
                                             row.get("page_or_location", "")),
                         "reason": reason})
    groups: dict[tuple, list[dict]] = {}
    for item in prepared:
        groups.setdefault(item["legacy_identity"], []).append(item)
    specs = []
    mapping = []
    duplicate_groups = []
    states: dict[str, int] = {}
    for _legacy_identity, items in sorted(groups.items(), key=lambda pair: int(pair[1][0]["evidence_id"].split("-")[1])):
        group_states = {state_by_evidence[x["evidence_id"]] for x in items}
        if len(group_states) != 1:
            manual.extend(x["evidence_id"] for x in items)
            state, evidence_ids = "needs_manual_classification", ()
        else:
            state, evidence_ids = next(iter(group_states))
        prior_leads = {migrated[x["evidence_id"]]["lead_id"] for x in items
                       if x["evidence_id"] in migrated}
        if len(prior_leads) > 1:
            manual.extend(x["evidence_id"] for x in items)
        prior = (next(migrated[x["evidence_id"]] for x in items
                      if x["evidence_id"] in migrated)
                 if len(prior_leads) == 1 else None)
        if prior is None:
            prior = existing_by_identity.get(items[0]["identity"])
        if prior:
            lead_id = prior["lead_id"]
        else:
            top += 1
            lead_id = f"L-{top:06d}"
        legacy_ids = [x["evidence_id"] for x in items]
        hit = dict(items[0]["hit"], legacy_evidence_ids=legacy_ids)
        spec = {"lead_id": lead_id, "dr_id": items[0]["dr_id"], "qid": items[0]["qid"], "question": items[0]["question"],
                "hit": hit, "state": state, "evidence_ids": list(evidence_ids), "legacy_evidence_ids": legacy_ids}
        specs.append(spec)
        states[state] = states.get(state, 0) + 1
        mapping.extend({"evidence_id": item["evidence_id"], "lead_id": lead_id} for item in items)
        if len(items) > 1:
            duplicate_groups.append({"lead_id": lead_id, "evidence_ids": legacy_ids})
    return {"rows": rows, "candidates": candidates, "specs": specs, "mapping": mapping,
            "duplicate_groups": duplicate_groups, "source_warnings": warnings,
            "needs_manual_classification": sorted(set(manual), key=lambda x: int(x.split("-")[1])),
            "prior_reviews": prior_by_evidence, "states": states}


def _migration_public(plan: dict, status: str) -> dict:
    return {"status": status, "counts": {"matrix_rows": len(plan["rows"]), "candidate_rows": len(plan["candidates"]),
            "leads": len(plan["specs"]), "duplicates_collapsed": len(plan["candidates"]) - len(plan["specs"]),
            "states": plan["states"]}, "mapping": plan["mapping"], "duplicate_groups": plan["duplicate_groups"],
            "source_warnings": plan["source_warnings"],
            "needs_manual_classification": plan["needs_manual_classification"],
            "baseline_comparison": {"plan_candidate_rows": 1517, "plan_leads": 1506, "plan_not_found": 347}}


def migrate(workspace: str | Path, *, apply: bool = False) -> dict:
    ws = _workspace(workspace)
    try:
        plan = _migration_plan(ws)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "ERROR", "message": str(exc)}
    public = _migration_public(plan, "DRY_RUN")
    if plan["needs_manual_classification"]:
        return {**public, "status": "ERROR", "message": "reviewed candidates need manual classification"}
    if any(not item["hit"].get("source_ref") for item in plan["specs"]):
        return {**public, "status": "ERROR", "message": "one or more candidates lack a durable source_ref"}
    if not apply:
        return public
    migration_lock = ws / "csa-work" / "intake" / ".lead-migration.lock"
    migration_lock.parent.mkdir(parents=True, exist_ok=True)
    with migration_lock.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            plan = _migration_plan(ws)
            public = _migration_public(plan, "DRY_RUN")
            if plan["needs_manual_classification"]:
                return {**public, "status": "ERROR", "message": "review state changed before apply"}
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = ws / "csa-work" / "backups" / f"lead-migration-{stamp}"
            backup_dir.mkdir(parents=True, exist_ok=False)
            work = ws / "csa-work"
            source_files = [work / "intake" / "leads.jsonl", work / "intake" / "leads-reviews.jsonl",
                            work / "evidence-reviews.jsonl"]
            backups = {}
            pre_hashes = {}
            for path in source_files:
                pre_hashes[str(path)] = _sha256(path)
                if path.is_file():
                    target = backup_dir / path.name
                    shutil.copy2(path, target)
                    backups[path.name] = str(target)
                else:
                    backups[path.name] = None
            matrix = work / "evidence-matrix.csv"
            matrix_hash = _sha256(matrix)
            actual_mapping = []
            for spec in plan["specs"]:
                got = add_leads(ws, spec["dr_id"], spec["qid"], spec["question"], [spec["hit"]], migration=True)
                if got != [spec["lead_id"]]:
                    return {**public, "status": "ERROR", "message": f"lead allocation drift for {spec['legacy_evidence_ids']}: {got}"}
                actual_mapping.extend({"evidence_id": eid, "lead_id": got[0]} for eid in spec["legacy_evidence_ids"])
                note = "migrated legacy gap-lookup candidates: " + ", ".join(spec["legacy_evidence_ids"])
                review(ws, got, spec["state"], "lead migration", note, spec["evidence_ids"])
            checked = verify(ws)
            if checked["status"] != "OK" or len(actual_mapping) != len(plan["candidates"]):
                return {**public, "status": "ERROR", "message": "lead verification or candidate mapping failed", "verify": checked}
            tombstones = []
            latest_now = _latest_evidence_reviews(ws)
            at = _utc()
            for item in actual_mapping:
                note = f"migrated to lead {item['lead_id']}; not an evidence row"
                prior = latest_now.get(item["evidence_id"], {})
                if prior.get("state") == "rejected" and prior.get("note") == note:
                    continue
                tombstones.append({"evidence_id": item["evidence_id"], "state": "rejected", "by": "lead migration",
                                   "at": at, "note": note})
            _append(work / "evidence-reviews.jsonl", tombstones)
            if _sha256(matrix) != matrix_hash:
                return {**public, "status": "ERROR", "message": "evidence matrix changed during migration"}
            manifest = {"schema_version": 1, "action": "leads-out-of-evidence-matrix", "created_at": at,
                        "workspace": str(ws), "matrix_sha256": matrix_hash, "counts": public["counts"],
                        "mapping": actual_mapping, "duplicate_groups": plan["duplicate_groups"],
                        "source_warnings": plan["source_warnings"], "prior_evidence_reviews": plan["prior_reviews"],
                        "backups": backups, "pre_hashes": pre_hashes,
                        "post_hashes": {str(path): _sha256(path) for path in source_files},
                        "lead_ids": sorted({x["lead_id"] for x in actual_mapping})}
            manifest_path = work / "intake" / f"lead-migration-{stamp}.json"
            temp = manifest_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temp, manifest_path)
            return {**public, "status": "OK", "manifest": str(manifest_path), "backup_dir": str(backup_dir),
                    "verify": checked, "tombstones_appended": len(tombstones)}
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def rollback(workspace: str | Path, manifest: str | Path, *, apply: bool = False) -> dict:
    ws = _workspace(workspace)
    path = Path(manifest).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "ERROR", "message": f"cannot read migration manifest: {exc}"}
    if data.get("schema_version") != 1 or data.get("workspace") != str(ws):
        return {"status": "ERROR", "message": "manifest schema/workspace does not match"}
    mappings = data.get("mapping", [])
    lead_ids = sorted({str(item.get("lead_id", "")) for item in mappings if item.get("lead_id")})
    out = {"status": "DRY_RUN", "manifest": str(path), "restore_evidence_reviews": len(mappings),
           "retire_leads": len(lead_ids), "matrix_sha256": data.get("matrix_sha256")}
    if not apply:
        return out
    lock_path = ws / "csa-work" / "intake" / ".lead-migration.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if _sha256(ws / "csa-work" / "evidence-matrix.csv") != data.get("matrix_sha256"):
                return {**out, "status": "ERROR", "message": "matrix hash differs from the migration manifest"}
            at = _utc()
            restore = []
            prior = data.get("prior_evidence_reviews", {})
            for item in mappings:
                evidence_id = item["evidence_id"]
                old = prior.get(evidence_id) or {}
                restore.append({"evidence_id": evidence_id, "state": old.get("state") or "pending",
                                "by": "lead migration rollback", "at": at,
                                "note": f"rollback of {path.name}; prior note: {old.get('note', '')}"[:600]})
            _append(ws / "csa-work" / "evidence-reviews.jsonl", restore)
            review(ws, lead_ids, "retired", "lead migration rollback", f"rolled back by {path.name}")
            checked = verify(ws)
            return {**out, "status": "OK" if checked["status"] == "OK" else "ERROR", "verify": checked}
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _list(workspace: Path, dr_id: str | None, state: str | None) -> dict:
    lead_rows, review_rows, lead_errors, review_errors = _records(workspace)
    if lead_errors or review_errors:
        raise ValueError(f"malformed lead store: {lead_errors + review_errors}")
    rows = _overlay(lead_rows, review_rows)
    if dr_id:
        rows = [r for r in rows if r.get("dr_id") == dr_id]
    if state:
        rows = [r for r in rows if r.get("state") == state]
    return {"status": "OK", "count": len(rows), "leads": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage append-only CSA discovery leads.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("list")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--dr")
    p.add_argument("--state", choices=sorted(STATES))
    p = sub.add_parser("review")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("lead_ids", nargs="+")
    p.add_argument("--state", choices=sorted(STATES), required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--evidence", action="append", default=[])
    p = sub.add_parser("verify")
    p.add_argument("--workspace", type=Path, required=True)
    for action in ("migrate", "rollback"):
        p = sub.add_parser(action)
        p.add_argument("--workspace", type=Path, required=True)
        p.add_argument("--apply", action="store_true")
        if action == "rollback":
            p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            result = _list(args.workspace, args.dr, args.state)
        elif args.action == "review":
            result = review(args.workspace, args.lead_ids, args.state, args.by, args.note, args.evidence)
        elif args.action == "verify":
            result = verify(args.workspace)
        elif args.action == "migrate":
            result = migrate(args.workspace, apply=args.apply)
        elif args.action == "rollback":
            result = rollback(args.workspace, args.manifest, apply=args.apply)
        else:
            raise ValueError(f"unsupported action: {args.action}")
    except (OSError, ValueError) as exc:
        result = {"status": "ERROR", "message": str(exc)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"OK", "DRY_RUN"} else 2


if __name__ == "__main__":
    sys.exit(main())
