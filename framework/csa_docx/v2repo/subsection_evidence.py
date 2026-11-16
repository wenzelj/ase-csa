"""S624: a read-only, deterministic native V2 subsection evidence package.

The answer lane currently receives a matrix-shaped compatibility snapshot of the
store. This module gives it a package built natively from one selected
application store (`csa.sqlite`): evidence that fits the subsection contract,
the canonical scope projection (owned hosts plus qualifying peers), the
addresses / flows / services / graph edges that connect them, FTS source chunks
for confirmation, open and settled leads, and provenance, conflict and
superseded warnings.

The package is strictly read-only and deterministic: generation opens the store
read-only and derives every value from the store's own tables. A `revision`
fingerprint of the store and the `contract_version` are carried so a package
can be diffed against the store and contract it was built from. No V1 file is
read: a V2 route has no csa-work/ fallback (see `v2_access.route`).

Every fact carries its evidence IDs, source path/location, status, scope basis
and the retrieval reason it was included. Every returned item is a `fact` or is
explicitly `non-evidence`. Results are bounded by the requested caps and the
package records, without silently dropping required evidence, anything it did
not include: `counts` holds the true totals and `truncated` names each section
whose result was cut by a cap.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

from . import scope as _v2repo_scope
from .. import v2_access

PACKAGE_VERSION = "v2-subsection-evidence-v1"
DEFAULT_LIMITS = {
    "evidence": 48,
    "hosts": 48,
    "connections": 64,
    "chunks": 4,
    "leads": 48,
    "warnings": 16,
}
_EVIDENCE_RANK = {"VERIFIED": 0, "INFERRED": 1, "CONFLICTING": 2, "UNCONFIRMED": 3, "NOT_FOUND": 4}
_HOST = re.compile(r"\b[A-Z]{3,}\d{2,6}\b")


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("_", " ").replace("-", " ").split())


def _row(con, sql: str, *params) -> list[dict]:
    return [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]


def _prov(con, eid: str) -> tuple[str, list, list]:
    """(state, canonical paths, candidates) for one evidence row; a row with no
    resolvable source is `unresolved` (never `canonical`)."""
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_provenance'").fetchone():
        row = con.execute("SELECT state, canonical_paths, candidates FROM evidence_provenance WHERE evidence_id=?", (eid,)).fetchone()
        if row:
            return row[0], _split(row[1]), _split(row[2])
    r = con.execute("SELECT source_title, excerpt FROM evidence WHERE id=?", (eid,)).fetchone()
    if r and (r[0] or r[1]):
        return "unresolved", [r[0]] if r[0] else [], [r[0] or r[1] or ""]
    return "unresolved", [], []


def _split(raw) -> list:
    import json
    try:
        v = json.loads(raw or "[]")
        return [x for x in v if x]
    except Exception:
        return [x for x in (raw or "").split(";") if x]


def _scope_projection(con, application_key: str) -> dict:
    """The owned / peer / external identities of the projection, from
    `application_scope` rows."""
    owned, peers = [], []
    try:
        for row in _row(con,
                "SELECT host_name, membership FROM application_scope "
                "WHERE application_key=? AND active=1 AND review_state IN ('accepted','proposed') "
                "ORDER BY host_name", application_key):
            if row["membership"] == "owned":
                owned.append(row["host_name"])
            else:
                peers.append(row["host_name"])
    except Exception:
        pass
    # External endpoints are only visible when a flow connects them to this
    # application's owned or accepted peer hosts.  Do not scan every flow in
    # the store: that would leak another application's external endpoints.
    external = []
    try:
        for (endpoint,) in con.execute(
                "SELECT src_host FROM flow WHERE dst_host IN ("
                "SELECT host_name FROM application_scope WHERE application_key=? AND active=1 "
                "AND review_state IN ('accepted','proposed')) "
                "UNION SELECT dst_host FROM flow WHERE src_host IN ("
                "SELECT host_name FROM application_scope WHERE application_key=? AND active=1 "
                "AND review_state IN ('accepted','proposed')) ORDER BY 1",
                application_key, application_key):
            if endpoint not in owned and endpoint not in peers:
                if not _row(con, "SELECT 1 FROM host WHERE name=?", endpoint):
                    external.append(endpoint)
    except Exception:
        pass
    return {"owned": sorted(owned), "peers": sorted(peers), "external": sorted(external)}


def _bounded_scope(scope: dict, limit: int) -> tuple[dict, bool]:
    """Bound visible identities while retaining owned hosts before peers/endpoints."""
    limit = max(0, int(limit))
    ordered = [("owned", scope.get("owned", [])), ("peers", scope.get("peers", [])),
               ("external", scope.get("external", []))]
    remaining = limit
    bounded = {}
    for name, values in ordered:
        bounded[name] = list(values[:remaining])
        remaining = max(0, remaining - len(bounded[name]))
    return bounded, sum(len(v) for _, v in ordered) > limit


def _matches(text: str, term: str) -> bool:
    if not term or not term.strip():
        return True
    return term.lower() in (text or "").lower()


def build_package(db, *, subsection_key: str, application_key: str, question: str,
                  terms: list[str] | None = None, contract: dict | None = None,
                  limits: dict | None = None, evidence_ids: list[str] | None = None) -> dict:
    """Build one bounded, read-only native V2 package for ``subsection_key`` of ``application_key``.

    The package is read-only: it opens the store read-only and derives every
    value from the store's own tables. It is deterministic for the same store
    revision and options, and it never reads a legacy csa-work file."""
    if not (subsection_key or "").strip():
        raise ValueError("subsection_key is required")
    if not (application_key or "").strip():
        raise ValueError("application_key is required for a V2 package (scope cannot be omitted)")
    lim = {**DEFAULT_LIMITS, **dict(limits or {})}
    terms = [t for t in (terms or []) if t and t.strip()]
    contract = contract or {}
    contract_version = contract.get("contract_version") or ""
    requested_ids = {str(e).upper() for e in (evidence_ids or []) if str(e).strip()}
    areas = contract.get("body", {}).get("evidence", {}).get("areas") or []
    if isinstance(areas, str):
        areas = [areas]
    area = areas[0] if areas else (subsection_key or "")

    with closing(v2_access.connection(Path(db))) as con:
        # 1. evidence rows matching the subsection contract (question/area/claim), dedup by ID
        candidates = []
        seen_ids: set[str] = set()
        if _norm(subsection_key):
            for r in _row(con, "SELECT id, area, question, claim, status, source_title, page_or_location, "
                              "excerpt, review_state FROM evidence WHERE (question LIKE ? OR claim LIKE ? OR area LIKE ?) "
                              "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id",
                          f"%{subsection_key}%", f"%{subsection_key}%", f"%{subsection_key}%"):
                if r["id"] in seen_ids:
                    continue
                reason = "question-match" if _matches(r.get("question", ""), subsection_key) else (
                    "area-match" if _matches(r.get("area", ""), subsection_key) else "claim-match")
                candidates.append((r, reason))
                seen_ids.add(r["id"])
        for t in terms:
            for r in _row(con, "SELECT id, area, question, claim, status, source_title, page_or_location, "
                              "excerpt, review_state FROM evidence WHERE (claim LIKE ? OR question LIKE ?) "
                              "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id", f"%{t}%", f"%{t}%"):
                if r["id"] in seen_ids or r.get("review_state") == "rejected":
                    continue
                candidates.append((r, "term-match"))
                seen_ids.add(r["id"])
        for a in areas:
            for r in _row(con, "SELECT id, area, question, claim, status, source_title, page_or_location, "
                              "excerpt, review_state FROM evidence WHERE area = ? "
                              "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id", a):
                if r["id"] in seen_ids or r.get("review_state") == "rejected":
                    continue
                candidates.append((r, "area-match"))
                seen_ids.add(r["id"])

        # Card obligations may identify a relevant native evidence row whose
        # wording does not match the subsection title.  Fetch that row from
        # csa.sqlite directly; the database remains the authority and rejected
        # or missing IDs are simply not returned.
        if requested_ids:
            for start in range(0, len(requested_ids), 500):
                chunk = sorted(requested_ids)[start:start + 500]
                marks = ",".join("?" for _ in chunk)
                for r in _row(con, f"SELECT id, area, question, claim, status, source_title, page_or_location, "
                                  f"excerpt, review_state FROM evidence WHERE id IN ({marks}) "
                                  "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id", *chunk):
                    if r["id"] not in seen_ids:
                        candidates.append((r, "question-evidence"))
                        seen_ids.add(r["id"])

        def _ev_rank(pr):
            r, reason = pr
            return (_EVIDENCE_RANK.get(r.get("status", ""), 5), 0 if reason == "question-evidence" else
                    (1 if reason in ("question-match", "term-match", "area-match") else 2),
                    reason, (r.get("id") or "").lower())
        candidates.sort(key=_ev_rank)
        evidence_total = len(candidates)
        evidence = []
        for r, reason in candidates[:lim["evidence"]]:
            state, paths, cands = _prov(con, r["id"])
            evidence.append({
                "evidence_id": r["id"], "text": r.get("claim") or "",
                "source": r.get("source_title") or "", "location": r.get("page_or_location") or "",
                "status": r.get("status") or "", "review_state": r.get("review_state") or "",
                "basis": "stated" if state == "canonical" else state, "paths": paths, "candidates": cands,
                "reason": reason, "non_evidence": False,
            })

        # 2. canonical projection identities
        raw_scope = _scope_projection(con, application_key)
        scope, hosts_truncated = _bounded_scope(raw_scope, lim["hosts"])
        all_hosts = scope["owned"] + scope["peers"] + scope["external"]
        all_hosts_total = sum(len(v) for v in raw_scope.values())

        # 3. addresses / flows / services / graph edges for the visible hosts
        if all_hosts:
            ph = ",".join("?" * len(all_hosts))
            hosts2 = list(all_hosts) + list(all_hosts)
            addresses = _row(con, f"SELECT ip,scope,owner_host FROM address WHERE owner_host IN ({ph}) ORDER BY ip", *all_hosts)
            flows = _row(con, f"SELECT src_host,dst_host,port,protocol,purpose FROM flow WHERE src_host IN ({ph}) OR dst_host IN ({ph}) "
                             "ORDER BY src_host,dst_host,port", *hosts2)
            services = _row(con, f"SELECT host,provider_host,port,protocol,name,configured FROM service WHERE host IN ({ph}) "
                                f"OR provider_host IN ({ph}) ORDER BY host,provider_host", *hosts2)
            edges = _row(con, f"SELECT edge_id,src,dst,kind,evidence_ids FROM graph_edge WHERE src IN ({ph}) OR dst IN ({ph}) ORDER BY edge_id",
                         *hosts2)
        else:
            addresses = flows = services = edges = []
        for c in (addresses, flows, services, edges):
            c[:lim["connections"]]
        conn_total = len(addresses) + len(flows) + len(services) + len(edges)

        # 4. FTS source chunks for confirmation (LIKE-based, so it needs no FTS5)
        chunks = []
        chunks_total = 0
        if terms:
            or_terms = " OR ".join("text LIKE ?" for _ in terms)
            bind = tuple(f"%{t}%" for t in terms)
            chunks_total = int(con.execute(f"SELECT COUNT(*) FROM indexed_chunk WHERE {or_terms}",
                                           tuple(bind)).fetchone()[0])
            hits = _row(con, f"SELECT rel_path, heading, text FROM indexed_chunk WHERE {or_terms} ORDER BY id LIMIT ?",
                        *bind, lim["chunks"] * 2)
            for i, h in enumerate(hits):
                chunks.append({"id": f"C{i+1}", "source": h.get("rel_path") or "",
                               "where": h.get("heading") or "",
                               "excerpt": (h.get("text") or "")[:300], "non_evidence": True, "reason": "source-confirmation"})
                if len(chunks) >= lim["chunks"]:
                    break

        # 5. open leads and settled outcomes — use the section key and question text as OR terms
        leads: list[dict] = []
        lead_ids: set[str] = set()
        if subsection_key:
            for r in _row(con, "SELECT id,question,state,evidence_ids,searched_scope FROM lead "
                              "WHERE (question LIKE ? OR id LIKE ?) ORDER BY state,id",
                          f"%{subsection_key}%", f"%{subsection_key}%"):
                if r["id"] not in lead_ids:
                    leads.append(dict(r, non_evidence=True))
                    lead_ids.add(r["id"])
        if question:
            for r in _row(con, "SELECT id,question,state,evidence_ids,searched_scope FROM lead "
                              "WHERE question LIKE ? ORDER BY state,id",
                          f"%{question}%"):
                if r["id"] not in lead_ids:
                    leads.append(dict(r, non_evidence=True))
                    lead_ids.add(r["id"])
        leads_total = len(leads)
        leads = leads[:lim["leads"]]

        # 6. provenance, conflict and superseded warnings
        warnings = []
        for r in evidence:
            if r["basis"] in ("ambiguous", "unresolved"):
                warnings.append({"kind": "provenance", "evidence_id": r["evidence_id"], "note": "source is not canonical; do not rely on it as verified", "non_evidence": True})
        for r in evidence:
            if r["status"] == "CONFLICTING":
                warnings.append({"kind": "conflict", "evidence_id": r["evidence_id"], "note": "row is CONFLICTING; do not rely on it as verified", "non_evidence": True})
        for r in evidence:
            if r["status"] == "NOT_FOUND":
                warnings.append({"kind": "not_found", "evidence_id": r["evidence_id"], "note": "row is NOT_FOUND; raises the question, does not answer it", "non_evidence": True})
        # superseded: a VERIFIED row whose host is recorded with a different status by another row of the same area
        for r in evidence:
            if r["status"] != "VERIFIED":
                continue
            hostset = set(_HOST.findall(r["text"]))
            if not hostset:
                continue
            for s in _row(con, "SELECT id, status FROM evidence WHERE area = ? AND status != 'VERIFIED' ORDER BY id", area):
                other = _row(con, "SELECT claim FROM evidence WHERE id=?", s["id"])
                if other and hostset & set(_HOST.findall(other[0]["claim"])):
                    warnings.append({"kind": "superseded", "evidence_id": r["evidence_id"],
                                     "note": f"a row of the same area records shared host(s) with status {s['status']}", "non_evidence": True})
                    break
        warnings_total = len(warnings)
        warnings = warnings[:lim["warnings"]]

    return {
        "package_version": PACKAGE_VERSION,
        "section": subsection_key,
        "application_key": application_key,
        "question": question,
        "contract_version": contract_version,
        "terms_used": list(terms),
        "revision": v2_access.store_revision(Path(db)),
        "counts": {
            "evidence": evidence_total, "hosts": all_hosts_total, "connections": conn_total,
            "chunks": chunks_total, "leads": leads_total, "warnings": warnings_total,
        },
        "evidence": evidence,
        "hosts": scope,
        "connections": {
            "addresses": addresses[:lim["connections"]], "flows": flows[:lim["connections"]],
            "services": services[:lim["connections"]], "edges": edges[:lim["connections"]],
        },
        "chunks": chunks,
        "leads": leads,
        "warnings": warnings,
        "truncated": {
            "evidence": evidence_total > lim["evidence"], "hosts": hosts_truncated,
            "connections": conn_total > lim["connections"], "chunks": chunks_total > lim["chunks"],
            "leads": leads_total > lim["leads"], "warnings": warnings_total > lim["warnings"],
        },
        "more_available": bool(evidence_total > lim["evidence"] or hosts_truncated
                                or conn_total > lim["connections"] or chunks_total > lim["chunks"]
                                or leads_total > lim["leads"] or warnings_total > lim["warnings"]),
        "truncation_reasons": [name for name, truncated in (
            ("evidence_limit", evidence_total > lim["evidence"]),
            ("host_limit", hosts_truncated),
            ("connection_limit", conn_total > lim["connections"]),
            ("chunk_limit", chunks_total > lim["chunks"]),
            ("lead_limit", leads_total > lim["leads"]),
            ("warning_limit", warnings_total > lim["warnings"]),
        ) if truncated],
    }


# ---------------------------------------------------------------------------
# S625: scoped hybrid retrieval
# ---------------------------------------------------------------------------
def _host_from_text(text: str) -> set[str]:
    """Extract host-like tokens from free text (3+ uppercase letters + 2+ digits)."""
    return set(_HOST.findall(text or ""))


def _dedupe_evidence(raw: list[dict]) -> list[dict]:
    """Deduplicate evidence rows by text, retaining all evidence IDs for identical claims."""
    by_text: dict[str, dict] = {}
    for r in raw:
        key = (r.get("text") or "").strip()
        if key not in by_text:
            by_text[key] = dict(r, evidence_ids=[r["evidence_id"]])
        else:
            eid = r["evidence_id"]
            if eid not in by_text[key]["evidence_ids"]:
                by_text[key]["evidence_ids"].append(eid)
    return list(by_text.values())


def _resolve_address(con, endpoint: str) -> str:
    """Resolve an address to the registered host that owns it in the address table.
    Loopback, unspecified and link-local addresses are never resolved."""
    if not endpoint or not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", endpoint):
        return endpoint
    import ipaddress
    try:
        ip = ipaddress.ip_address(endpoint)
        if ip.is_loopback or ip.is_unspecified or ip.is_link_local:
            return endpoint
    except ValueError:
        return endpoint
    row = _row(con, "SELECT owner_host FROM address WHERE ip=? ORDER BY rowid", endpoint)
    return row[0]["owner_host"] if row else endpoint


def retrieve(db, *, subsection_key: str, application_key: str, question: str,
              terms: list[str] | None = None, hosts: list[str] | None = None,
              areas: list[str] | None = None, contract: dict | None = None,
              limits: dict | None = None) -> dict:
    """Complete scoped retrieval for one subsection of one application.

    Combines structured evidence rows, FTS chunks and graph context while
    preserving application boundaries. Every returned fact carries provenance,
    or is explicitly non-evidence. Rejected/unresolved evidence is never
    presented as verified. Results are stable for a given store revision.
    """
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    terms = [t for t in (terms or []) if t and t.strip()]
    hosts = [h for h in (hosts or []) if h and h.strip()]
    areas = [a for a in (areas or []) if a and a.strip()]
    contract = contract or {}
    contract_areas = contract.get("body", {}).get("evidence", {}).get("areas") or []
    if isinstance(contract_areas, str):
        contract_areas = [contract_areas]
    areas = list(dict.fromkeys(list(areas) + list(contract_areas)))  # dedupe, preserve order

    with closing(v2_access.connection(Path(db))) as con:
        raw_scope = _scope_projection(con, application_key)
        scope, hosts_truncated = _bounded_scope(raw_scope, lim["hosts"])
        visible_hosts = set(scope["owned"]) | set(scope["peers"]) | set(scope["external"])

        # ------------------------------------------------------------------
        # 1. Structured evidence: subsection, terms, hosts, areas
        # ------------------------------------------------------------------
        candidates: list[tuple[dict, str, str]] = []  # (row, reason, rank_key)
        seen: set[str] = set()

        def _add(row: dict, reason: str):
            rid = row["id"]
            if rid in seen:
                return
            seen.add(rid)
            status_r = _EVIDENCE_RANK.get(row["status"], 5)
            host_hits = len(_host_from_text(row.get("claim", "")) & visible_hosts)
            rank = (status_r, -host_hits, row["id"])
            candidates.append((row, reason, rank))

        # subsection key match
        if subsection_key:
            for r in _row(con,
                    "SELECT id, area, question, claim, status, source_title, page_or_location, "
                    "excerpt, review_state FROM evidence "
                    "WHERE (question LIKE ? OR claim LIKE ? OR area LIKE ?) "
                    "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id",
                    f"%{subsection_key}%", f"%{subsection_key}%", f"%{subsection_key}%"):
                rr = "question-match" if subsection_key.lower() in (r.get("question") or "").lower() else (
                     "area-match" if subsection_key.lower() in (r.get("area") or "").lower() else "claim-match")
                _add(r, rr)
        # term match
        for t in terms:
            for r in _row(con,
                    "SELECT id, area, question, claim, status, source_title, page_or_location, "
                    "excerpt, review_state FROM evidence "
                    "WHERE (claim LIKE ? OR question LIKE ?) "
                    "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id",
                    f"%{t}%", f"%{t}%"):
                _add(r, "term-match")
        # host match
        for h in hosts:
            for r in _row(con,
                    "SELECT id, area, question, claim, status, source_title, page_or_location, "
                    "excerpt, review_state FROM evidence "
                    "WHERE claim LIKE ? "
                    "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id",
                    f"%{h}%"):
                _add(r, "host-match")
        # area match
        for a in areas:
            for r in _row(con,
                    "SELECT id, area, question, claim, status, source_title, page_or_location, "
                    "excerpt, review_state FROM evidence "
                    "WHERE area = ? "
                    "AND (review_state IS NULL OR review_state IN ('proposed','accepted')) ORDER BY id",
                    a):
                _add(r, "area-match")

        candidates.sort(key=lambda c: c[2])
        total_evidence = len(candidates)
        evidence = []
        for row, reason, _rank in candidates[:lim["evidence"] * 3]:  # fetch extra for dedup headroom
            state, paths, cands = _prov(con, row["id"])
            basis = "stated" if state == "canonical" else state
            evidence.append({
                "evidence_id": row["id"], "text": row.get("claim") or "",
                "source": row.get("source_title") or "", "location": row.get("page_or_location") or "",
                "status": row.get("status") or "", "review_state": row.get("review_state") or "",
                "basis": basis, "paths": paths, "candidates": cands,
                "reason": reason, "non_evidence": False,
                "verified": row.get("status") == "VERIFIED" and row.get("review_state") != "rejected",
            })

        # Deduplicate identical-claim rows, retaining evidence IDs
        deduped = _dedupe_evidence(evidence)
        evidence_out = deduped[:lim["evidence"]]
        evidence_trunc = total_evidence > len(evidence_out)

        # ------------------------------------------------------------------
        # 2. FTS / LIKE chunks (source confirmation)
        # ------------------------------------------------------------------
        chunks = []
        chunks_total = 0
        search_terms = terms + ([h for h in hosts if h] if hosts else [])
        if subsection_key:
            search_terms.append(subsection_key)
        if search_terms:
            or_parts = " OR ".join("text LIKE ?" for _ in search_terms)
            bind = tuple(f"%{t}%" for t in search_terms)
            chunks_total = int(con.execute(f"SELECT COUNT(*) FROM indexed_chunk WHERE {or_parts}", bind).fetchone()[0])
            hits = _row(con,
                        f"SELECT rel_path, heading, text FROM indexed_chunk WHERE {or_parts} ORDER BY id LIMIT ?",
                        *bind, lim["chunks"] * 2)
            for i, h in enumerate(hits):
                chunks.append({
                    "id": f"C{i+1}", "source": h.get("rel_path") or "",
                    "where": h.get("heading") or "",
                    "excerpt": (h.get("text") or "")[:300],
                    "non_evidence": True, "reason": "source-confirmation",
                })
                if len(chunks) >= lim["chunks"]:
                    break
        chunks_trunc = chunks_total > len(chunks)

        # ------------------------------------------------------------------
        # 3. Addresses with V2 ownership resolution
        # ------------------------------------------------------------------
        addresses = []
        if visible_hosts:
            ph = ",".join("?" * len(visible_hosts))
            for r in _row(con,
                          f"SELECT ip,scope,owner_host FROM address WHERE owner_host IN ({ph}) ORDER BY ip",
                          *sorted(visible_hosts)):
                owner = r.get("owner_host") or ""
                # resolve the IP to confirm ownership
                resolved = _resolve_address(con, r.get("ip") or "")
                addresses.append({
                    "ip": r.get("ip") or "", "scope": r.get("scope") or "",
                    "owner_host": owner, "resolved_to": resolved,
                    "non_evidence": True, "reason": "scope-address",
                })
        addresses_out = addresses[:lim["connections"]]
        addresses_trunc = len(addresses) > lim["connections"]

        # ------------------------------------------------------------------
        # 4. Flows, services, graph edges
        # ------------------------------------------------------------------
        flows, services, edges = [], [], []
        if visible_hosts:
            ph = ",".join("?" * len(visible_hosts))
            hosts2 = list(sorted(visible_hosts)) * 2
            flows = _row(con,
                         f"SELECT src_host,dst_host,port,protocol,purpose FROM flow "
                         f"WHERE src_host IN ({ph}) OR dst_host IN ({ph}) "
                         "ORDER BY src_host,dst_host,port", *hosts2)
            services = _row(con,
                            f"SELECT host,provider_host,port,protocol,name,configured FROM service "
                            f"WHERE host IN ({ph}) OR provider_host IN ({ph}) "
                            "ORDER BY host,provider_host", *hosts2)
            edges = _row(con,
                         f"SELECT edge_id,src,dst,kind,evidence_ids FROM graph_edge "
                         f"WHERE src IN ({ph}) OR dst IN ({ph}) ORDER BY edge_id", *hosts2)

        for c in (flows, services, edges):
            for f in c:
                f["non_evidence"] = True
                f.setdefault("reason", "graph-edge" if "edge_id" in f else ("service" if "provider_host" in f else "flow"))
        connections_trunc = (len(flows) > lim["connections"] or
                             len(services) > lim["connections"] or
                             len(edges) > lim["connections"] or
                             addresses_trunc)
        flows = flows[:lim["connections"]]
        services = services[:lim["connections"]]
        edges = edges[:lim["connections"]]

        # ------------------------------------------------------------------
        # 5. Leads
        # ------------------------------------------------------------------
        leads = []
        lead_ids: set[str] = set()
        if subsection_key:
            for r in _row(con,
                          "SELECT id,question,state,evidence_ids,searched_scope FROM lead "
                          "WHERE (question LIKE ? OR id LIKE ?) ORDER BY state,id",
                          f"%{subsection_key}%", f"%{subsection_key}%"):
                if r["id"] not in lead_ids:
                    leads.append(dict(r, non_evidence=True, reason="lead"))
                    lead_ids.add(r["id"])
        if question:
            for r in _row(con,
                          "SELECT id,question,state,evidence_ids,searched_scope FROM lead "
                          "WHERE question LIKE ? ORDER BY state,id", f"%{question}%"):
                if r["id"] not in lead_ids:
                    leads.append(dict(r, non_evidence=True, reason="lead"))
                    lead_ids.add(r["id"])
        leads_total = len(leads)
        leads = leads[:lim["leads"]]
        leads_trunc = leads_total > lim["leads"]

        # ------------------------------------------------------------------
        # 6. Warnings: rejected, conflicting, superseded, unresolved provenance
        # ------------------------------------------------------------------
        warnings = []
        for f in evidence_out:
            if f["basis"] in ("ambiguous", "unresolved"):
                warnings.append({"kind": "provenance", "evidence_id": f["evidence_id"],
                                 "note": "source is not canonical; do not rely on it as verified",
                                 "non_evidence": True, "verified": False})
            if f["status"] == "CONFLICTING":
                warnings.append({"kind": "conflict", "evidence_id": f["evidence_id"],
                                 "note": "row is CONFLICTING; do not rely on it as verified",
                                 "non_evidence": True, "verified": False})
            if f["status"] == "NOT_FOUND":
                warnings.append({"kind": "not_found", "evidence_id": f["evidence_id"],
                                 "note": "row is NOT_FOUND; raises the question, does not answer it",
                                 "non_evidence": True, "verified": False})
            if f["review_state"] == "rejected":
                warnings.append({"kind": "rejected", "evidence_id": f["evidence_id"],
                                 "note": "row is rejected; not presented as verified",
                                 "non_evidence": True, "verified": False})
        # Superseded: VERIFIED row whose host appears in a CONFLICTING row of the same area
        if areas:
            area_str = areas[0]
            for f in evidence_out:
                if f["status"] != "VERIFIED":
                    continue
                hostset = _host_from_text(f["text"])
                if not hostset:
                    continue
                for s in _row(con, "SELECT id, status FROM evidence WHERE area = ? AND status != 'VERIFIED' ORDER BY id", area_str):
                    other = _row(con, "SELECT claim FROM evidence WHERE id=?", s["id"])
                    if other and hostset & _host_from_text(other[0]["claim"]):
                        warnings.append({"kind": "superseded", "evidence_id": f["evidence_id"],
                                         "note": f"a row of the same area records shared host(s) with status {s['status']}",
                                         "non_evidence": True, "verified": False})
                        break
        warnings_total = len(warnings)
        warnings = warnings[:lim["warnings"]]
        warnings_trunc = warnings_total > lim["warnings"]

    return {
        "package_version": PACKAGE_VERSION,
        "section": subsection_key,
        "application_key": application_key,
        "question": question,
        "terms_used": list(terms),
        "hosts_searched": list(hosts),
        "areas_requested": list(areas),
        "revision": v2_access.store_revision(Path(db)),
        "counts": {
            "evidence": total_evidence,
            "hosts": sum(len(v) for v in raw_scope.values()),
            "connections": len(flows) + len(services) + len(edges) + len(addresses),
            "chunks": chunks_total,
            "leads": leads_total,
            "warnings": warnings_total,
        },
        "evidence": evidence_out,
        "hosts": scope,
        "connections": {
            "addresses": addresses_out,
            "flows": flows,
            "services": services,
            "edges": edges,
        },
        "chunks": chunks,
        "leads": leads,
        "warnings": warnings,
        "truncated": {
            "evidence": evidence_trunc,
            "hosts": hosts_truncated,
            "connections": connections_trunc,
            "chunks": chunks_trunc,
            "leads": leads_trunc,
            "warnings": warnings_trunc,
        },
        "more_available": (evidence_trunc or chunks_trunc or connections_trunc or
                           leads_trunc or warnings_trunc or hosts_truncated),
        "truncation_reasons": [name for name, truncated in (
            ("evidence_limit", evidence_trunc), ("host_limit", hosts_truncated),
            ("connection_limit", connections_trunc), ("chunk_limit", chunks_trunc),
            ("lead_limit", leads_trunc), ("warning_limit", warnings_trunc),
        ) if truncated],
    }

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


def _scope_evidence(con, rows: list[dict], in_scope: set[str]) -> list[dict]:
    """Keep only evidence that cannot name a host outside this projection.

    Focused searches such as topic and source-path searches do not have a host
    predicate of their own.  Rejecting a row that names a known out-of-scope
    host prevents those searches from becoming an application boundary escape.
    Rows without a host identity remain eligible when the caller supplied an
    exact scoped source/query; they do not introduce a host by themselves.
    """
    all_hosts = {str(r[0]) for r in con.execute("SELECT name FROM host")}
    out = []
    for row in rows:
        text = " ".join(str(row.get(k) or "") for k in ("claim", "question", "excerpt"))
        named = {h for h in all_hosts if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(h)}(?![A-Za-z0-9_-])", text, re.I)}
        if named and not named <= in_scope:
            continue
        out.append(row)
    return out


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
    ev = _scope_evidence(con, ev, in_scope)
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
    combined = list(base.get("evidence", [])) + [f for f in evidence if f["evidence_id"] not in existing_ids]
    unique_added = len([f for f in evidence if f["evidence_id"] not in existing_ids])
    combined_total = int(base.get("counts", {}).get("evidence", len(base.get("evidence", [])))) + unique_added
    pkg["evidence"] = combined[:lim["evidence"]]
    pkg["expansion"] = expansion
    pkg["expansion_outcomes"] = outcomes
    pkg["conflict_disclosure_required"] = sorted(conflict_ids)
    pkg["not_found_disclosure_required"] = sorted(not_found_ids)
    pkg["counts"] = {
        "evidence": combined_total,
        "hosts": sum(len(v) for v in (base.get("hosts") or {}).values()),
        "connections": base.get("counts", {}).get("connections", 0),
        "chunks": base.get("counts", {}).get("chunks", 0),
        "leads": base.get("counts", {}).get("leads", 0),
        "warnings": base.get("counts", {}).get("warnings", 0),
    }
    pkg["truncated"] = {
        **base.get("truncated", {}),
        "evidence": bool(base.get("truncated", {}).get("evidence")) or combined_total > lim["evidence"],
    }
    pkg["more_available"] = bool(base.get("more_available") or pkg["truncated"]["evidence"])
    if pkg["truncated"]["evidence"] and "evidence_limit" not in base.get("truncation_reasons", []):
        pkg["truncation_reasons"] = list(base.get("truncation_reasons", [])) + ["evidence_limit"]
    pkg["package_version"] = PACKAGE_VERSION
    body = {k: v for k, v in pkg.items() if k not in ("revision", "package_hash", "context", "model_profile")}
    pkg["package_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]
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
            "package_hash": pkg.get("package_hash") or hashlib.sha256(
                json.dumps({k: v for k, v in pkg.items()
                            if k not in ("revision", "package_hash", "context", "model_profile")},
                           sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()[:16],
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
