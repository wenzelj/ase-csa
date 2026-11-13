"""Read-only portfolio graph assembled from registered application stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _read_project(project: dict[str, str]) -> dict[str, Any]:
    work = Path(project.get("work_dir", "")).expanduser()
    db = work / "csa.sqlite"
    if not db.is_file():
        return {"key": project.get("key", ""), "label": project.get("label", ""),
                "state": "missing-store", "hosts": [], "edges": []}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            scope = [dict(row) for row in con.execute(
                "SELECT application_key,host_name,membership,review_state,active "
                "FROM application_scope WHERE active=1 AND review_state != 'rejected'")]
            if not scope:
                return {"key": project.get("key", ""), "label": project.get("label", ""),
                        "state": "missing-scope", "hosts": [], "edges": []}
            names = {row["host_name"] for row in scope}
            hosts = {row["name"]: dict(row) for row in con.execute(
                "SELECT name,role,site FROM host WHERE status='active' AND name IN ({})".format(
                    ",".join("?" for _ in names)), tuple(names))} if names else {}
            edges = [dict(row) for row in con.execute(
                "SELECT src,dst,kind,evidence_ids FROM graph_edge WHERE kind='flow'")]
            return {"key": project.get("key", ""), "label": project.get("label", ""),
                    "state": "ok", "scope": scope, "hosts": hosts, "edges": edges}
    except (sqlite3.Error, OSError) as exc:
        if isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc).lower():
            return {"key": project.get("key", ""), "label": project.get("label", ""),
                    "state": "missing-scope", "hosts": [], "edges": []}
        return {"key": project.get("key", ""), "label": project.get("label", ""),
                "state": "unavailable", "error": str(exc), "hosts": [], "edges": []}


def build(projects: list[dict[str, str]]) -> dict[str, Any]:
    """Aggregate only scope-qualified hosts and graph edges from registered stores."""
    stores = [_read_project(project) for project in projects]
    owners: dict[str, list[str]] = {}
    for store in stores:
        for row in store.get("scope", []):
            if row["membership"] == "owned":
                owners.setdefault(row["host_name"], []).append(store["key"])

    def node_id(project_key: str, host: str) -> str:
        candidates = owners.get(host, [])
        return f"{candidates[0]}::{host}" if len(candidates) == 1 else f"{project_key}::{host}"

    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}
    states = []
    for store in stores:
        states.append({"application_key": store["key"], "label": store["label"], "state": store["state"]})
        if store["state"] != "ok":
            continue
        scope_by_host = {row["host_name"]: row for row in store["scope"]}
        for host, details in store["hosts"].items():
            row = scope_by_host.get(host)
            if not row:
                continue
            nid = node_id(store["key"], host)
            nodes.setdefault(nid, {"id": nid, "label": host, "kind": "captured",
                                   "role": details.get("role") or "", "site": details.get("site") or "",
                                   "application_key": store["key"], "application_label": store["label"],
                                   "membership": row["membership"], "project_key": store["key"]})
        for edge in store["edges"]:
            src = (edge["src"] or "").removeprefix("host/")
            dst = (edge["dst"] or "").removeprefix("host/")
            if src not in scope_by_host or dst not in scope_by_host:
                continue
            s, t = node_id(store["key"], src), node_id(store["key"], dst)
            key = (s, t, edge["kind"])
            item = edges.setdefault(key, {"s": s, "t": t, "kind": edge["kind"],
                                          "ids": [], "source_projects": []})
            item["ids"] = sorted(set(item["ids"] + [x for x in (edge["evidence_ids"] or "").split(";") if x]))
            if store["key"] not in item["source_projects"]:
                item["source_projects"].append(store["key"])
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "applications": states,
            "partial": any(item["state"] != "ok" for item in states),
            "source": "registered csa-work-v2 stores opened read-only"}
