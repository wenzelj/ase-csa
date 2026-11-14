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
                  limits: dict | None = None) -> dict:
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

        def _ev_rank(pr):
            r, reason = pr
            return (_EVIDENCE_RANK.get(r.get("status", ""), 5), 0 if reason in ("question-match", "term-match", "area-match") else 1,
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
