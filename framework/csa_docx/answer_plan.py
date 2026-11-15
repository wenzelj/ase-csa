"""The requirement-answer plan of one subsection, and its checks.

`csa-work/convert/<N>/answer-plan.csv` says, for each fact of the previous assessment, which requirement
it answers, what is being stated, on what evidence scope, where in the subsection it goes, how far it is
trusted, how it was reworded and which gap it raises. The evidence agent writes it, the writer writes
from it, and the ledger checks it.

    python3 -m csa_docx.answer_plan <answer-plan.csv> --target 3.5 [--req SEP-DNS-01 ...] [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from csa_docx import targets  # noqa: E402

COLUMNS = ["legacy_ids", "req_id", "statement_type", "fact", "evidence_scope", "destination",
           "confidence", "transformation", "gap_generated"]

STATEMENT_TYPES = ("observed", "scope", "assessment", "gap", "consequence", "recommendation", "evidence-ref")
CONFIDENCE = ("high", "medium", "low", "n/a")

_DESTINATIONS = [re.compile(p) for p in (
    r"REQ SEP-[A-Z]+-\d+ / (?:Current State|Rating)",
    r"\d+\.\d+\.1 Discovery Information / .+",
    r"\d+\.\d+\.2 Drawbridge Impact",
    r"5\.\d .+",
    r"2\.1 Executive Summary",
    r"8 Discovery Required",
    r"MOVED \d+(?:\.\d+)?",
    r"roadmap(?: \(convert/parked\.md\))?",
    r"none",
)]
_GAP = re.compile(r"(DR-[A-Z]+-\d{2}) (.+)", re.DOTALL)
_ABSOLUTE = re.compile(r"\b(no [\w\- ]{0,40}(?:exists?|is present|in place)|does not exist|there is no)", re.IGNORECASE)
_SUBSECTION = re.compile(r"(\d+\.\d+)\.[12] ")
_NOT_IN_CSA = re.compile(r"(?:roadmap.*|none|MOVED .*)")

REQUIREMENT_MAP = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template"
                   / "references" / "requirement-map.csv")


class PlanRows(list):
    """The rows of a plan, with the CSV header it was read with."""
    columns: list[str] = COLUMNS


def load(path: Path | str) -> PlanRows:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = PlanRows({k: (v or "") for k, v in r.items() if k is not None} for r in reader)
        rows.columns = list(reader.fieldnames or [])
    return rows


def _valid_destination(dest: str) -> bool:
    return any(p.fullmatch(dest) for p in _DESTINATIONS)


def validate(rows, target: str, req_ids: list[str]) -> list[dict]:
    findings: list[dict] = []

    def add(level: str, code: str, n: int, message: str) -> None:
        findings.append({"level": level, "code": code, "row": n, "message": message})

    if list(getattr(rows, "columns", COLUMNS)) != COLUMNS:
        add("ERROR", "BAD_COLUMNS", 0, f"columns must be exactly: {', '.join(COLUMNS)}")
        return findings

    seen: dict[tuple[str, str], int] = {}
    answered: set[str] = set()
    rated: set[str] = set()
    for n, r in enumerate(rows, start=1):
        dest = r["destination"].strip()
        stype = r["statement_type"].strip()
        legacy = r["legacy_ids"].strip()
        bad = []
        if stype not in STATEMENT_TYPES:
            bad.append(f"statement_type {stype!r}")
        if r["confidence"].strip() not in CONFIDENCE:
            bad.append(f"confidence {r['confidence']!r}")
        if not _valid_destination(dest):
            bad.append(f"destination {dest!r}")
        gap = r["gap_generated"].strip()
        if gap and not _GAP.fullmatch(gap):
            bad.append(f"gap_generated {gap!r} (expected 'DR-XXX-01 <what to confirm>')")
        for b in bad:
            add("ERROR", "BAD_VALUE", n, f"bad {b}")

        if stype == "recommendation" and not _NOT_IN_CSA.fullmatch(dest):
            add("ERROR", "RECOMMENDATION_IN_CSA", n,
                "a recommendation never goes into a current-state field; use roadmap, none or MOVED")
        if (stype == "gap" or dest == "8 Discovery Required") and not gap:
            add("ERROR", "GAP_WITHOUT_DR", n, "a gap needs gap_generated: DR-XXX-01 <what to confirm>")

        is_req = dest.startswith("REQ ")
        is_discovery = bool(re.fullmatch(r"\d+\.\d+\.1 Discovery Information / .+", dest))
        if (is_req or is_discovery) and not r["evidence_scope"].strip():
            add("ERROR", "NO_SCOPE", n, "name the hosts and evidence type in evidence_scope")
        if (is_req or is_discovery) and _ABSOLUTE.search(r["fact"]) \
                and "qualify" not in r["transformation"] and "verified absence" not in r["transformation"]:
            add("ERROR", "ABSOLUTE_NOT_QUALIFIED", n,
                "an absolute ('no X exists') needs 'qualify' or 'verified absence' in transformation")

        if is_req:
            m = re.fullmatch(r"REQ (SEP-[A-Z]+-\d+) / (Current State|Rating)", dest)
            if m:
                (answered if m.group(2) == "Current State" else rated).add(m.group(1))
        sub = _SUBSECTION.match(dest)
        if sub and sub.group(1) != target:
            add("WARN", "OTHER_SUBSECTION", n, f"destination is in subsection {sub.group(1)}; use MOVED {sub.group(1)}")
        key = (legacy, dest)
        if legacy and key in seen:
            add("WARN", "DUPLICATE_ROW", n, f"same legacy_ids and destination as row {seen[key]}")
        seen.setdefault(key, n)

    for rid in req_ids:
        if rid not in answered:
            add("ERROR", "REQ_NOT_ANSWERED", 0, f"no 'REQ {rid} / Current State' row")
        if rid not in rated:
            add("ERROR", "REQ_NOT_RATED", 0, f"no 'REQ {rid} / Rating' row")
    return findings


def gaps(rows) -> list[dict]:
    out = []
    for r in rows:
        m = _GAP.fullmatch(r["gap_generated"].strip())
        if m:
            out.append({"dr_id": m.group(1), "text": m.group(2).strip(), "req_id": r["req_id"].strip(),
                        "fact": r["fact"], "evidence_scope": r["evidence_scope"]})
    return out


def requirement_ids(target: str, path: Path | None = None) -> list[str]:
    """Requirement IDs of the target's domain, from requirement-map.csv."""
    with Path(path or REQUIREMENT_MAP).open(newline="", encoding="utf-8") as fh:
        return [r["req_id"] for r in csv.DictReader(fh) if targets.requirement_in(r, target)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a requirement-answer plan.")
    ap.add_argument("plan", type=Path)
    ap.add_argument("--target", required=True)
    ap.add_argument("--req", action="append")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.plan.is_file():
        print(json.dumps({"status": "ERROR", "message": f"plan not found: {a.plan}"}))
        return 2
    req_ids = a.req or requirement_ids(a.target)
    findings = validate(load(a.plan), a.target, req_ids)
    errors = sum(f["level"] == "ERROR" for f in findings)
    warnings = len(findings) - errors
    if a.json:
        print(json.dumps({"status": "ERROR" if errors else "OK", "errors": errors, "warnings": warnings,
                          "findings": findings}, ensure_ascii=False))
    else:
        print(f"answer plan {a.plan.name} ({a.target}): {errors} error(s), {warnings} warning(s)")
        for f in findings:
            print(f"  {f['level']:<5} {f['code']:<24} row {f['row']:<3} {f['message']}")
    return 1 if errors else 0



# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# S627: focused evidence expansion and conflict handling
# ---------------------------------------------------------------------------
#
# The first package pass may be incomplete.  The answer agent can request one
# or more *focused* follow-up searches instead of guessing or receiving the
# entire database.  Every expansion stays inside the subsection and
# application scope that the first pass established: it may add no host, peer
# or external endpoint outside that projection, and index hits and leads never
# become verified evidence without source settlement.
#
# An expansion record carries the request, its query, result counts and the
# reason it was requested; a repeated empty request produces a *scoped gap*
# instead of a guessed answer.  Conflicts and NOT_FOUND outcomes are exposed
# as structured findings.  The run manifest is bounded: search history,
# package hash, database revision, scope, truncation reasons and the
# validation outcome all remain auditable from it.

EXPANSION_VERSION = "v2-expansion-v1"
MANIFEST_SEARCH_HISTORY_LIMIT = 12
_EXPANSION_KINDS = ("host", "address", "topic", "service", "source_path",
                    "graph_neighbours", "contradiction")

_EVIDENCE_SELECT = ("SELECT id, area, question, claim, status, source_title, "
                    "page_or_location, excerpt, review_state FROM evidence WHERE "
                    "{where} AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id")


def _evidence_where(*clauses) -> str:
    return " AND ".join(clauses)


def expansion_outcomes(evidence: list[dict]) -> list[dict]:
    """The structured conflict and NOT_FOUND outcomes of one evidence list.

    Every CONFLICTING or NOT_FOUND row is passed to the model as a disclosure
    requirement: it is never silently dropped or read as verified, and an
    answer that cites it without disclosing it fails validation."""
    out = []
    for f in evidence or []:
        status = f.get("status", "")
        if status not in ("CONFLICTING", "NOT_FOUND"):
            continue
        if status == "CONFLICTING":
            out.append({"kind": "conflict", "evidence_id": f.get("evidence_id", ""),
                        "status": status, "text": f.get("text", ""),
                        "requirement": "disclose the conflict before stating or rating it",
                        "non_evidence": False})
        else:
            out.append({"kind": "not_found", "evidence_id": f.get("evidence_id", ""),
                        "status": status, "text": f.get("text", ""),
                        "requirement": "state it as an evidenced absence; it raises the question, it does not answer it",
                        "non_evidence": False})
    return out


def _scope_hosts(con, application_key: str) -> set:
    raw = _scope_projection(con, application_key)
    return set(raw["owned"]) | set(raw["peers"]) | set(raw["external"])


def _expand_evidence(con, *, application_key: str, subsection_key: str,
                     kind: str, host: str = "", address: str = "",
                     terms: list[str] | None = None, service: str = "",
                     port: int | None = None, provider: str = "",
                     source_path: str = "", neighbour: str = "") -> tuple[list[dict], int, int]:
    """Rows relevant to one focused request, plus the true (evidence, connection) counts.

    The query is always anchored to this application's scope: a host or
    address request resolves the address to an in-scope owner first, and a
    service request is bound to an in-scope host or provider. Requests that
    resolve outside the projection return nothing: expansion cannot pull in an
    unrelated application's host or external endpoint."""
    in_scope = _scope_hosts(con, application_key)
    host = (host or "").strip()
    address = (address or "").strip()
    terms = [t for t in (terms or []) if (t or "").strip()]

    def ev_where(where: str, params: tuple) -> list[dict]:
        return _row(con, _EVIDENCE_SELECT.format(where=where), *params)

    if kind == "host":
        if host not in in_scope:
            return [], 0, 0
        ev = ev_where("claim LIKE ?", (f"%{host}%",))
        ph = ",".join("?" * max(1, len(in_scope)))
        binds = sorted(in_scope)
        conns = len(_row(con, f"SELECT 1 FROM address WHERE owner_host IN ({ph})", *binds))
        conns += len(_row(con, f"SELECT 1 FROM flow WHERE src_host IN ({ph}) OR dst_host IN ({ph})", *binds, *binds))
        conns += len(_row(con, f"SELECT 1 FROM service WHERE host IN ({ph}) OR provider_host IN ({ph})", *binds, *binds))
    elif kind == "address":
        owner = _resolve_address(con, address)
        if owner not in in_scope:
            return [], 0, 0
        ev = ev_where(_evidence_where("claim LIKE ?", "excerpt LIKE ?"), (f"%{address}%", f"%{address}%"))
        conns = len(_row(con, "SELECT 1 FROM address WHERE ip=? OR owner_host=?", address, owner))
        conns += len(_row(con, "SELECT 1 FROM flow WHERE src_host=? OR dst_host=?", owner, owner))
        conns += len(_row(con, "SELECT 1 FROM service WHERE host=? OR provider_host=?", owner, owner))
    elif kind == "service":
        has_query = bool((service or "").strip()) or port is not None or bool((provider or "").strip()) or bool(terms)
        if not has_query:
            return [], 0, 0
        host_ok = host if host in in_scope else ""
        prov_ok = provider if provider in in_scope else ""
        clauses, params = [], []
        if host_ok:
            clauses.append("claim LIKE ?"); params.append(f"%{host_ok}%")
        if prov_ok:
            clauses.append("claim LIKE ?"); params.append(f"%{prov_ok}%")
        if not clauses:
            clauses.append("claim LIKE ?"); params.append(f"%{service}%")
        if port is not None:
            clauses.append("claim LIKE ?"); params.append(f"%{port}%")
        for t in terms:
            clauses.append("claim LIKE ?"); params.append(f"%{t}%")
        ev = ev_where(_evidence_where(*clauses), tuple(params))
        ph = ",".join("?" * max(1, len(in_scope)))
        binds = sorted(in_scope)
        conns = len(_row(con, f"SELECT 1 FROM service WHERE host IN ({ph}) OR provider_host IN ({ph})",
                         *binds, *binds))
    elif kind == "topic":
        keys = terms or ([subsection_key] if subsection_key else [])
        if not keys:
            return [], 0, 0
        clauses = ["(claim LIKE ? OR question LIKE ?)"] * len(keys)
        params = [f"%{k}%" for k in keys]
        params = [p for k in keys for p in (f"%{k}%", f"%{k}%")]
        ev = ev_where(" OR ".join(clauses), tuple(params))
        conns = 0
    elif kind == "source_path":
        sp = (source_path or "").strip()
        if not sp:
            return [], 0, 0
        ev = ev_where(_evidence_where("source_title LIKE ?", "page_or_location LIKE ?"),
                      (f"%{sp}%", f"%{sp}%"))
        conns = len(_row(con, "SELECT 1 FROM indexed_file WHERE rel_path LIKE ?", f"%{sp}%"))
    elif kind == "graph_neighbours":
        nb = (neighbour or "").strip() or host
        if nb not in in_scope:
            return [], 0, 0
        ev = ev_where("claim LIKE ?", (f"%{nb}%",))
        ph = ",".join("?" * max(1, len(in_scope)))
        binds = sorted(in_scope)
        conns = len(_row(con, f"SELECT 1 FROM graph_edge WHERE (src=? OR dst=?) AND (src IN ({ph}) OR dst IN ({ph}))",
                         nb, nb, *binds, *binds))
        conns += len(_row(con, f"SELECT 1 FROM flow WHERE (src_host=? OR dst_host=?) AND (src_host IN ({ph}) OR dst_host IN ({ph}))",
                          nb, nb, *binds, *binds))
    else:  # contradiction: same subject, disagreeing status
        key = host or (terms[0] if terms else "")
        if not key:
            return [], 0, 0
        ev = ev_where("claim LIKE ?", (f"%{key}%",))
        statuses = {r["status"] for r in ev}
        if len(statuses) <= 1:
            ev = [r for r in ev if r["status"] in ("CONFLICTING", "NOT_FOUND")]
        conns = 0
    # de-duplicate by ID, keep first (stable) order, attach provenance
    seen: set[str] = set()
    out = []
    for r in ev:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        state, paths, cands = _prov(con, r["id"])
        out.append({
            "evidence_id": r["id"], "text": r.get("claim") or "",
            "source": r.get("source_title") or "", "location": r.get("page_or_location") or "",
            "status": r.get("status") or "", "review_state": r.get("review_state") or "",
            "basis": "stated" if state == "canonical" else state, "paths": paths, "candidates": cands,
            "reason": f"expansion-{kind}", "non_evidence": False,
            "verified": r.get("status") == "VERIFIED" and r.get("review_state") != "rejected",
        })
    return out, len(seen), conns


def expand_package(db, *, subsection_key: str, application_key: str, question: str,
                   kind: str, host: str = "", address: str = "",
                   terms: list[str] | None = None, service: str = "",
                   port: int | None = None, provider: str = "",
                   source_path: str = "", neighbour: str = "",
                   reason: str = "", base_package: dict | None = None,
                   limits: dict | None = None) -> dict:
    """One focused expansion search for ``subsection_key`` of ``application_key``.

    ``kind`` selects the bounded query (host, address, topic, service,
    source_path, graph_neighbours, contradiction); the remaining arguments are
    the query terms. The result is a full package: the same shape, limits,
    scope and truncation reporting as the first pass, plus ``expansion``
    (request, query, result counts, reason, outcomes) so the run manifest can
    carry the search history and audit the result."""
    if kind not in _EXPANSION_KINDS:
        raise ValueError(f"expansion kind must be one of {', '.join(_EXPANSION_KINDS)}, got {kind!r}")
    terms = [t for t in (terms or []) if t and t.strip()]
    base = base_package or build_package(db, subsection_key=subsection_key,
                                         application_key=application_key, question=question,
                                         terms=terms or None)
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    with closing(v2_access.connection(Path(db))) as con:
        ev, ev_total, conn_total = _expand_evidence(
            con, application_key=application_key, subsection_key=subsection_key,
            kind=kind, host=host, address=address, terms=terms, service=service,
            port=port, provider=provider, source_path=source_path, neighbour=neighbour)
    evidence = ev[:lim["evidence"]]
    outcomes = expansion_outcomes(evidence)
    conflict_ids = {o["evidence_id"] for o in outcomes if o["kind"] == "conflict"}
    not_found_ids = {o["evidence_id"] for o in outcomes if o["kind"] == "not_found"}
    scoped_gap = (not evidence) and (not outcomes) and (not base.get("evidence"))
    query = {k: v for k, v in (("kind", kind), ("host", host), ("address", address),
                               ("terms", terms), ("service", service), ("port", port),
                               ("provider", provider), ("source_path", source_path),
                               ("neighbour", neighbour)) if v not in ("", None, [])}
    expansion = {
        "version": EXPANSION_VERSION,
        "kind": kind,
        "query": query,
        "reason": (reason or "").strip() or f"focused-{kind}-search",
        "result_counts": {"evidence": ev_total, "connections": conn_total},
        "outcomes": outcomes,
        "scoped_gap": bool(scoped_gap),
        "gap": ({"subsection": subsection_key, "application_key": application_key,
                 "query": query, "note": "no evidence matched this scoped search; raise as a scoped gap, do not guess"}
                if scoped_gap else None),
    }
    pkg = dict(base)
    existing_ids = {f.get("evidence_id") for f in base.get("evidence", [])}
    pkg["evidence"] = list(base.get("evidence", [])) + [f for f in evidence if f["evidence_id"] not in existing_ids]
    pkg["expansion"] = expansion
    pkg["expansion_outcomes"] = outcomes
    pkg["conflict_disclosure_required"] = sorted(conflict_ids)
    pkg["not_found_disclosure_required"] = sorted(not_found_ids)
    pkg["counts"] = {
        "evidence": len(pkg["evidence"]),
        "hosts": sum(len(v) for v in (base.get("hosts") or {}).values()),
        "connections": base.get("counts", {}).get("connections", 0),
        "chunks": base.get("counts", {}).get("chunks", 0),
        "leads": base.get("counts", {}).get("leads", 0),
        "warnings": base.get("counts", {}).get("warnings", 0),
    }
    pkg["truncated"] = {
        **base.get("truncated", {}),
        "evidence": len(pkg["evidence"]) > lim["evidence"],
    }
    pkg["more_available"] = bool(base.get("more_available") or pkg["truncated"]["evidence"])
    if pkg["truncated"]["evidence"] and "evidence_limit" not in base.get("truncation_reasons", []):
        pkg["truncation_reasons"] = list(base.get("truncation_reasons", [])) + ["evidence_limit"]
    pkg["package_version"] = PACKAGE_VERSION
    return pkg


def _audit_expansion(exp: dict) -> dict:
    """One expansion entry for the bounded run-manifest search history."""
    e = exp.get("expansion") or {}
    return {
        "kind": e.get("kind"),
        "query": e.get("query"),
        "reason": e.get("reason"),
        "result_counts": e.get("result_counts"),
        "outcomes": e.get("outcomes"),
        "scoped_gap": e.get("scoped_gap"),
        "gap": e.get("gap"),
        "package_hash": exp.get("package_hash"),
        "truncated": exp.get("truncated"),
        "truncation_reasons": exp.get("truncation_reasons"),
        "more_available": exp.get("more_available"),
    }


def run_manifest(base_package: dict, expansions: list[dict] | None = None,
                 validation: dict | None = None, manifest: dict | None = None) -> dict:
    """The bounded, auditable run manifest for one V2 answer run.

    It carries the base package's hash, database revision, scope and
    truncation reasons, the bounded search history of every expansion (kind,
    query, result counts, reason, outcomes), and the validation outcome, so a
    run can be replayed and audited without re-running the searches."""
    manifest = dict(manifest or {})
    def _pkg_audit(pkg: dict) -> dict:
        return {
            "package_hash": pkg.get("package_hash") or _package_hash(pkg),
            "package_version": pkg.get("package_version") or PACKAGE_VERSION,
            "revision": pkg.get("revision"),
            "application_key": pkg.get("application_key"),
            "subsection": pkg.get("section"),
            "scope": pkg.get("hosts"),
            "truncated": pkg.get("truncated"),
            "truncation_reasons": pkg.get("truncation_reasons"),
            "more_available": pkg.get("more_available"),
        }
    history = [_audit_expansion(e) for e in (expansions or [])]
    return {
        "manifest_version": "v2-run-manifest-v1",
        "route": manifest.get("route", "v2-native"),
        "contract_version": manifest.get("contract_version") or base_package.get("contract_version") or "",
        "base": _pkg_audit(base_package),
        "expansions": history[:MANIFEST_SEARCH_HISTORY_LIMIT],
        "search_history_bounded": len(history) <= MANIFEST_SEARCH_HISTORY_LIMIT,
        "validation": validation,
    }


# ---------------------------------------------------------------------------
# S627: conflict / NOT_FOUND disclosure in the structured preflight
# ---------------------------------------------------------------------------

def conflict_disclosure_findings(sheet: dict[str, dict], card: dict, pkg: dict) -> list[dict]:
    """ERROR findings when a V2 sheet cites a CONFLICTING or NOT_FOUND row of
    its package without disclosing it (a QUESTION/Unknown line or an explicit
    disclosure of the conflict). Runs as part of the structured fact layer,
    before prose validation."""
    if not isinstance(pkg, dict):
        return []
    need = {str(x).upper() for x in (pkg.get("conflict_disclosure_required") or [])}
    need |= {str(x).upper() for x in (pkg.get("not_found_disclosure_required") or [])}
    if not need:
        return []
    _eid = re.compile(r"(?<![\w:-])E-\d+\b")
    out = []
    for qid, b in sheet.items():
        if qid.startswith("F"):
            continue
        cited = set()
        for fact in b.get("facts", []):
            cited |= {i.upper() for i in fact.get("ids", [])}
        for row in b.get("rows", []):
            cited |= {m.upper() for m in _eid.findall(" | ".join(str(c) for c in row))}
        for bullet in b.get("bullets", []):
            cited |= {m.upper() for m in _eid.findall(str(bullet))}
        disclosed = {m.upper() for u in (b.get("unknown") or []) for m in _eid.findall(str(u))}
        for eid in sorted(cited & need):
            if eid not in disclosed:
                out.append({"level": "ERROR", "code": "CONFLICT_NOT_DISCLOSED",
                            "question": qid,
                            "message": f"{eid} is CONFLICTING or NOT_FOUND in the package; "
                                       f"disclose it (QUESTION/Unknown) before stating or rating it"})
    return out


# ---------------------------------------------------------------------------

# S627: plan_context expansion + run-manifest composition
# ---------------------------------------------------------------------------

def plan_context(rows, card: dict, package: dict | None = None,
                 expansions: list[dict] | None = None,
                 validation: dict | None = None) -> dict:
    """One structured answer context for a subsection.

    ``rows`` is the answer plan for the subsection (``PlanRows`` or a list of
    dicts), ``card`` the section card, ``package`` the native V2 subsection
    evidence package (``v2repo.subsection_evidence.build_package``,
    ``retrieve`` or ``expand_package``), ``expansions`` the focused expansion
    packages of this run, and ``validation`` the structured validation
    outcome.  A V1 project or an explicitly marked compatibility run passes
    ``package=None`` and keeps the legacy CSV-only shape unchanged."""
    out: dict = {"route": "v2-native" if package is not None else "v1-native",
                 "contract_version": (package or {}).get("contract_version")
                 or (card.get("obligations") or {}).get("contract_version") or ""}
    if package is None:
        out["plan"] = [dict(r) for r in rows]
        return out
    allowed = set()
    for f in package.get("evidence", []):
        ids = f.get("evidence_ids") if isinstance(f, dict) else None
        if isinstance(ids, list):
            allowed |= {str(x).upper() for x in ids}
        elif isinstance(f, dict) and f.get("evidence_id"):
            allowed.add(str(f["evidence_id"]).upper())
    hosts = set()
    for k in ("owned", "peers", "external"):
        hosts.update(str(h).upper() for h in (package.get("hosts") or {}).get(k, []))
    findings = []
    for n, r in enumerate(rows, start=1):
        rr = dict(r)
        for i in ([x for x in str(rr.get("legacy_ids", "")).split() if x] or []):
            if i.upper() not in allowed and i.upper().startswith("E-"):
                findings.append({"level": "ERROR", "code": "UNKNOWN_EVIDENCE",
                                 "row": n, "message": f"{i} is not in the subsection evidence package"})
    out["plan"] = [dict(r) for r in rows]
    out["evidence_ids"] = sorted(allowed)
    out["hosts"] = sorted(hosts)
    out["package_hash"] = _package_hash(package)
    out["revision"] = package.get("revision")
    out["findings"] = findings
    if expansions is not None:
        out["expansions"] = [dict(e) for e in expansions]
    if expansions is not None or validation is not None:
        out["run_manifest"] = run_manifest(package, expansions=expansions or [],
                                          validation=validation,
                                          manifest={"route": out["route"],
                                                    "contract_version": out["contract_version"]})
    return out


def _package_hash(package: dict) -> str:
    """A stable content hash of the package body, independent of dict order."""
    import hashlib
    import json
    body = {k: v for k, v in package.items()
            if k not in ("revision", "package_hash", "context", "model_profile")}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    sys.exit(main())
