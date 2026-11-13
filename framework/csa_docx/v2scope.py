"""Deterministically rebuild application-scope metadata from current source proof."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .v2repo import Repo


def _register(project_root: Path) -> list[dict[str, str]]:
    source = project_root / "csa-work" / "hosts" / "hosts.csv"
    if not source.is_file():
        raise FileNotFoundError(f"missing source register: {source}")
    return list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))


def _proof(repo: Repo, owned: set[str], peers: set[str]) -> dict[str, list[str]]:
    """Return deterministic proof descriptions for peer endpoints."""
    proof = {host: [] for host in peers}
    for src, dst in repo.con.execute("SELECT src_host, dst_host FROM flow ORDER BY id"):
        if src in owned and dst in peers:
            proof[dst].append(f"flow:{src}->{dst}")
        if dst in owned and src in peers:
            proof[src].append(f"flow:{src}->{dst}")
    for host, provider in repo.con.execute(
            "SELECT host, provider_host FROM service WHERE provider_host IS NOT NULL AND provider_host != '' ORDER BY id"):
        if host in owned and provider in peers:
            proof[provider].append(f"service:{host}->{provider}")
        if provider in owned and host in peers:
            proof[host].append(f"service:{host}->{provider}")
    accepted = {row[0] for row in repo.con.execute(
        "SELECT id FROM evidence WHERE review_state != 'rejected' AND status IN ('VERIFIED','INFERRED','UNCONFIRMED','CONFLICTING')")}
    for src, dst, evidence_ids in repo.con.execute(
            "SELECT src, dst, evidence_ids FROM graph_edge WHERE kind='flow' ORDER BY edge_id"):
        src, dst = re.sub(r"^host/", "", src or ""), re.sub(r"^host/", "", dst or "")
        ids = [item.strip() for item in (evidence_ids or "").replace(";", ",").split(",") if item.strip() in accepted]
        if src in owned and dst in peers and ids:
            proof[dst].extend(f"evidence:{item}" for item in ids)
        if dst in owned and src in peers and ids:
            proof[src].extend(f"evidence:{item}" for item in ids)
    return {host: sorted(set(items)) for host, items in proof.items()}


def _report_path(v2_dir: Path, application_key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", application_key)
    return v2_dir / "scope-reports" / f"{safe}-scope.json"


def rebuild(project_root, v2_dir, application_key: str, dry_run: bool = False) -> dict:
    """Rebuild one application's scope without changing the global graph or V1 files."""
    if not application_key or not application_key.strip():
        return {"status": "ERROR", "error": "application_key is required"}
    root, v2 = Path(project_root), Path(v2_dir)
    try:
        rows = _register(root)
    except FileNotFoundError as exc:
        return {"status": "ERROR", "error": str(exc)}
    desired: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        host = (row.get("host") or "").strip()
        scope = (row.get("in_scope") or "").strip().lower()
        if not host:
            continue
        if scope in {"yes", "no"}:
            desired[host] = ("owned", scope, "v2:host-register; evidence-backed")
        elif scope == "peer":
            desired[host] = ("peer", scope, "v2:flow-service-evidence")

    repo = Repo(v2)
    try:
        statuses = {row[0]: row[1] for row in repo.con.execute("SELECT name, status FROM host")}
        owned = {host for host, (membership, _, _) in desired.items() if membership == "owned"}
        peers = {host for host, (membership, _, _) in desired.items() if membership == "peer"}
        proof = _proof(repo, owned, peers)
        active_owned = {host for host in owned if statuses.get(host, "active") == "active"}
        active_peers = {host for host in peers if statuses.get(host, "active") == "active" and proof[host]}
        excluded = []
        for host in sorted(peers):
            if host not in active_peers:
                reason = "host is retired" if statuses.get(host) == "retired" else "no current flow, service or accepted evidence proof"
                excluded.append({"host_name": host, "reason": reason, "proof": proof[host]})
        scope_rows = []
        for host in sorted(desired):
            membership, source_scope, source_ref = desired[host]
            active = host in active_owned or host in active_peers
            scope_rows.append({"host_name": host, "membership": membership, "active": active,
                               "basis": "; ".join(proof.get(host, [])) if membership == "peer" else f"register:in_scope={source_scope}",
                               "source_ref": source_ref, "proof": proof.get(host, [])})
        report = {"status": "DRY-RUN" if dry_run else "OK", "application_key": application_key,
                  "source": "csa-work/hosts/hosts.csv", "owned_count": len(active_owned),
                  "owned_register_rows": len(owned), "peer_candidates": len(peers),
                  "active_peer_count": len(active_peers), "active_peers": len(active_peers),
                  "excluded_peer_count": len(excluded),
                  "owned": [row for row in scope_rows if row["membership"] == "owned"],
                  "active_peer_rows": [row for row in scope_rows if row["membership"] == "peer" and row["active"]],
                  "excluded_peers": excluded}
        if dry_run:
            return report
        with repo.tx():
            repo.con.execute("UPDATE application_scope SET active=0, basis='scope-rebuild:retired' WHERE application_key=?",
                             (application_key,))
            for row in scope_rows:
                repo.application_scope.add(application_key, row["host_name"], row["membership"],
                                           basis=row["basis"], evidence_ids=",".join(
                                               item.removeprefix("evidence:") for item in row["proof"] if item.startswith("evidence:")),
                                           source_ref=row["source_ref"], review_state="proposed", active=row["active"])
                repo._audit("csa v2 scope-rebuild", "scope-rebuild", "application_scope",
                            f"{application_key}:{row['host_name']}", row["basis"] or "excluded")
        path = _report_path(v2, application_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = str(path)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report
    finally:
        repo.close()
