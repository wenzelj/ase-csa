"""Deterministically rebuild application-scope metadata from the source register."""

from __future__ import annotations

import csv
from pathlib import Path

from .v2repo import Repo


def rebuild(project_root, v2_dir, application_key: str, dry_run: bool = False) -> dict:
    root = Path(project_root)
    source = root / "csa-work" / "hosts" / "hosts.csv"
    if not source.is_file():
        return {"status": "ERROR", "error": f"missing source register: {source}"}
    rows = list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))
    desired = {}
    for row in rows:
        host = (row.get("host") or "").strip()
        scope = (row.get("in_scope") or "").strip().lower()
        if host and scope in {"yes", "no", "peer"}:
            desired[host] = ("owned" if scope in {"yes", "no"} else "peer", scope)
    repo = Repo(v2_dir)
    try:
        con = repo.con
        active_peers = set()
        for src, dst in con.execute("SELECT src_host, dst_host FROM flow"):
            if desired.get(src, (None,))[0] == "owned" and desired.get(dst, (None,))[0] == "peer":
                active_peers.add(dst)
            if desired.get(dst, (None,))[0] == "owned" and desired.get(src, (None,))[0] == "peer":
                active_peers.add(src)
        for client, provider in con.execute("SELECT host, provider_host FROM service WHERE provider_host IS NOT NULL"):
            if desired.get(client, (None,))[0] == "owned" and desired.get(provider, (None,))[0] == "peer":
                active_peers.add(provider)
            if desired.get(provider, (None,))[0] == "owned" and desired.get(client, (None,))[0] == "peer":
                active_peers.add(client)
        result = {"status": "DRY-RUN" if dry_run else "OK", "application_key": application_key,
                  "owned": sum(kind == "owned" for kind, _ in desired.values()),
                  "peers": sum(kind == "peer" for kind, _ in desired.values()),
                  "active_peers": len(active_peers)}
        if dry_run:
            return result
        with repo.tx():
            con = repo.con
            con.execute("UPDATE application_scope SET active=0, basis='scope-rebuild:retired' "
                        "WHERE application_key=?", (application_key,))
            for host, (membership, scope) in desired.items():
                active = membership == "owned" or host in active_peers
                con.execute(
                    "INSERT INTO application_scope (application_key,host_name,membership,basis,source_ref,review_state,active) "
                    "VALUES (?,?,?,?,?,'proposed',?) ON CONFLICT(application_key,host_name) DO UPDATE SET "
                    "membership=excluded.membership,basis=excluded.basis,source_ref=excluded.source_ref,active=excluded.active",
                    (application_key, host, membership,
                     f"scope-rebuild:in_scope={scope}", "hosts/hosts.csv", int(active)))
        return result
    finally:
        repo.close()
