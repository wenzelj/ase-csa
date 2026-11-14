"""Deterministically rebuild application-scope metadata from current V2 records (S605, S617).

Everything the rebuild reads is in `csa.sqlite`:

* ownership comes from `application_ownership`, the explicit and reviewable record of the
  hosts an application owns.  It is never inferred from a host name or a folder name, and no
  file below the legacy `csa-work/` tree is opened.  A store migrated before the ownership
  table existed holds its ownership as `application_scope` rows with `membership='owned'`;
  the first applied rebuild imports those rows into `application_ownership` (with review
  events) and a dry run reports them as not yet imported;
* a peer candidate is a registered host that already holds a peer scope row for the
  application, or that a current relationship links to an owned host;
* a peer is active only when a current flow, a service/provider relationship or a
  non-rejected source-backed evidence row links it to an owned host.

A dry run opens the database read-only and writes nothing.  An applied rebuild runs in one
repository transaction, which backs the database up first, and appends a review event per row.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .v2repo import DB_NAME, Repo
from .v2repo.graph import _LINK_IN, _LINK_OUT
from .v2repo.scope import _resolve_endpoint

SOURCE = "csa.sqlite application_ownership, application_scope, flow, service, evidence"
OWNERSHIP_REF = "v2:application_ownership"
PENDING_OWNERSHIP_REF = "v2:application_scope"
ACTOR = "csa v2 scope-rebuild"


def _table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _ownership(con, application_key: str) -> tuple[list[dict], bool]:
    """(ownership rows, imported) for an application.

    `imported` is False when the rows still live only in `application_scope` (a store migrated
    before `application_ownership` existed) and the next applied rebuild will import them."""
    cols = ("host_name", "source_ref", "evidence_ids", "review_state")
    if _table_exists(con, "application_ownership"):
        rows = [dict(zip(cols, row)) for row in con.execute(
            "SELECT host_name, source_ref, evidence_ids, review_state FROM application_ownership "
            "WHERE application_key=? ORDER BY host_name", (application_key,))]
        if rows:
            return rows, True
    rows = [dict(zip(cols, row)) for row in con.execute(
        "SELECT host_name, source_ref, evidence_ids, review_state FROM application_scope "
        "WHERE application_key=? AND membership='owned' ORDER BY host_name", (application_key,))]
    for row in rows:
        row["source_ref"] = f"{PENDING_OWNERSHIP_REF}/{application_key}/{row['host_name']}"
    return rows, False


def _proof(con, owned: set[str]) -> dict[str, list[str]]:
    """{host: proof} for every name a current V2 relationship links to an owned host.

    Proof is a flow row, a service/provider row, or a non-rejected evidence row that names its
    source and whose claim links the two hosts. Address peers are resolved to their registered
    owner, with the original address retained beside the proof entry."""
    proof: dict[str, list[str]] = {}

    def _add(a: str, b: str, text: str):
        for near, far in ((a, b), (b, a)):
            if near in owned and far not in owned:
                proof.setdefault(far, []).append(text)

    for src, dst in con.execute("SELECT src_host, dst_host FROM flow ORDER BY id"):
        _add(src, dst, f"flow:{src}->{dst}")
    for host, provider in con.execute(
            "SELECT host, provider_host FROM service WHERE provider_host IS NOT NULL AND provider_host != '' ORDER BY id"):
        _add(host, provider, f"service:{host}->{provider}")
    for eid, claim in con.execute(
            "SELECT id, claim FROM evidence WHERE review_state != 'rejected' AND claim IS NOT NULL "
            "AND source_title IS NOT NULL AND TRIM(source_title) != '' ORDER BY id"):
        m = _LINK_IN.match(claim) or _LINK_OUT.match(claim)
        if m and m[1] != m[2]:
            endpoints = (m[1], m[2])
            source, destination = (_resolve_endpoint(con, endpoint) for endpoint in endpoints)
            if source != destination:
                address = next((endpoint for endpoint, resolved in zip(endpoints, (source, destination))
                                if endpoint != resolved), None)
                suffix = f" ({address})" if address else ""
                _add(source, destination, f"evidence:{eid}{suffix}")
    return {host: sorted(set(items)) for host, items in proof.items()}


def _peer_refs(proof: list[str]) -> str:
    """The V2 records a peer row rests on, e.g. `v2:flow; v2:evidence`."""
    kinds = sorted({item.split(":", 1)[0] for item in proof})
    return "; ".join(f"v2:{kind}" for kind in kinds) or "v2:application_scope"


def _report_path(v2_dir: Path, application_key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", application_key)
    return v2_dir / "scope-reports" / f"{safe}-scope.json"


def _plan(con, application_key: str) -> dict:
    """Everything the rebuild decides, from one connection, without writing."""
    statuses = {row[0]: row[1] for row in con.execute("SELECT name, status FROM host")}
    ownership, imported = _ownership(con, application_key)
    owned = {row["host_name"]: row for row in ownership if row["review_state"] != "rejected"}
    rejected_ownership = sorted(row["host_name"] for row in ownership if row["review_state"] == "rejected")
    proof = _proof(con, set(owned))
    existing = {row[0]: {"membership": row[1], "review_state": row[2]} for row in con.execute(
        "SELECT host_name, membership, review_state FROM application_scope WHERE application_key=?", (application_key,))}
    candidates = {host for host, row in existing.items() if row["membership"] == "peer" and host not in owned}
    candidates |= {host for host in proof if host in statuses}       # a registered host with a current relationship
    candidates -= set(rejected_ownership)

    scope_rows, excluded = [], []
    for host in sorted(owned):
        active = statuses.get(host, "active") == "active"
        scope_rows.append({"host_name": host, "membership": "owned", "active": active,
                           "basis": f"ownership:{owned[host]['review_state']}",
                           "source_ref": OWNERSHIP_REF if imported else owned[host]["source_ref"],
                           "ownership_source_ref": owned[host]["source_ref"],
                           "evidence_ids": owned[host]["evidence_ids"] or "",
                           "review_state": owned[host]["review_state"], "proof": []})
    for host in sorted(candidates):
        items = proof.get(host, [])
        review_state = existing.get(host, {}).get("review_state", "proposed")
        reason = ""
        if statuses.get(host) == "retired":
            reason = "host is retired"
        elif review_state == "rejected":
            reason = "peer scope row was rejected in review"
        elif not items:
            reason = "no current flow, service or accepted evidence proof"
        scope_rows.append({"host_name": host, "membership": "peer", "active": not reason,
                           "basis": "; ".join(items), "source_ref": _peer_refs(items),
                           "evidence_ids": ",".join(i.removeprefix("evidence:") for i in items if i.startswith("evidence:")),
                           "review_state": review_state, "proof": items})
        if reason:
            excluded.append({"host_name": host, "reason": reason, "proof": items})
    classified = set(owned) | candidates | set(rejected_ownership)
    active_owned = [row for row in scope_rows if row["membership"] == "owned" and row["active"]]
    active_peers = [row for row in scope_rows if row["membership"] == "peer" and row["active"]]
    return {
        "ownership": ownership, "ownership_imported": imported, "scope_rows": scope_rows,
        "report": {
            "application_key": application_key, "source": SOURCE,
            "ownership_source": "application_ownership" if imported else
                                "application_scope owned rows (not yet imported into application_ownership)",
            "owned_count": len(active_owned), "owned_register_rows": len(owned),
            "peer_candidates": len(candidates), "active_peer_count": len(active_peers),
            "active_peers": len(active_peers), "excluded_peer_count": len(excluded),
            "owned": [row for row in scope_rows if row["membership"] == "owned"],
            "active_peer_rows": active_peers, "excluded_peers": excluded,
            "rejected_ownership": rejected_ownership,
            # registered hosts with no ownership, no peer scope row and no relationship: left unclassified
            "unclassified_hosts": sorted(host for host, status in statuses.items()
                                         if status == "active" and host not in classified),
        },
    }


def rebuild(project_root, v2_dir, application_key: str, dry_run: bool = False) -> dict:
    """Rebuild one application's scope from V2 records, without changing the global graph.

    `project_root` is accepted for existing callers and is not read: nothing below the legacy
    `csa-work/` tree is opened, created or required."""
    if not application_key or not application_key.strip():
        return {"status": "ERROR", "error": "application_key is required"}
    v2 = Path(v2_dir)
    db = v2 if v2.name == DB_NAME else v2 / DB_NAME
    no_ownership = {"status": "ERROR", "application_key": application_key, "source": SOURCE,
                    "error": f"no ownership is recorded in V2 for application '{application_key}'; record the owned "
                             "hosts in application_ownership (csa v2 ownership --add HOST --source-ref REF) first"}

    if dry_run:
        if not db.is_file():
            return no_ownership
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)       # read-only: a dry run writes nothing
        try:
            if not _table_exists(con, "application_scope"):
                return no_ownership
            plan = _plan(con, application_key)
        finally:
            con.close()
        if not plan["ownership"]:
            return no_ownership
        return {"status": "DRY-RUN", **plan["report"]}

    repo = Repo(db)
    try:
        plan = _plan(repo.con, application_key)
        if not plan["ownership"]:
            return no_ownership
        report = {"status": "OK", **plan["report"]}
        with repo.tx():
            if not plan["ownership_imported"]:
                for row in plan["ownership"]:                        # the one-time import, audited row by row
                    repo.application_ownership.add(application_key, row["host_name"], row["source_ref"],
                                                   evidence_ids=row["evidence_ids"],
                                                   review_state=row["review_state"], by=ACTOR)
                report["ownership_source"] = "application_ownership (imported from application_scope by this rebuild)"
                for row in plan["scope_rows"]:
                    if row["membership"] == "owned":
                        row["source_ref"] = OWNERSHIP_REF
            repo.con.execute("UPDATE application_scope SET active=0, basis='scope-rebuild:retired' WHERE application_key=?",
                             (application_key,))
            for row in plan["scope_rows"]:
                repo.application_scope.add(application_key, row["host_name"], row["membership"],
                                           basis=row["basis"], evidence_ids=row["evidence_ids"],
                                           source_ref=row["source_ref"], review_state=row["review_state"],
                                           active=row["active"])
                repo._audit(ACTOR, "scope-rebuild", "application_scope",
                            f"{application_key}:{row['host_name']}", row["basis"] or "excluded")
        path = _report_path(db.parent, application_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = str(path)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report
    finally:
        repo.close()
