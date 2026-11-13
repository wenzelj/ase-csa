"""Application-scoped projections of the shared V2 graph (S592).

The graph tables remain global and derived.  This module only selects a view over
those tables; it never deletes or rewrites graph data.
"""

from __future__ import annotations


def _host_name(node_id: str) -> str | None:
    return node_id.removeprefix("host/") if node_id.startswith("host/") else None


def application_hosts(repo, application_key: str) -> set[str]:
    """Return active, non-rejected owned hosts and qualified peers for an application."""
    rows = repo.application_scope.list_app_hosts(application_key=application_key, active=True)
    return {
        row["host_name"] for row in rows
        if row["review_state"] != "rejected"
    }


def projected_graph(repo, application_key: str | None = None, view: str = "application") -> dict:
    """Return a graph projection without mutating the repository.

    ``view='global'`` returns the complete graph.  ``view='application'`` requires
    an application key and returns its owned hosts plus active, evidence-backed
    peers recorded in ``application_scope``.  Non-host nodes are retained only
    when attached to an included host, preserving service/provider context.
    """
    if view not in {"application", "global"}:
        raise ValueError("view must be 'application' or 'global'")
    if view == "application" and not application_key:
        raise ValueError("application_key is required for application view")

    rows = repo.graph.nodes()
    edges = repo.graph.edges()
    if view == "global":
        allowed = None
    else:
        allowed_hosts = {f"host/{name}" for name in application_hosts(repo, application_key)}
        allowed = set(allowed_hosts)
        # Include service/provider/endpoint nodes only when an edge touches an
        # application host. This prevents unrelated global graph nodes leaking in.
        for edge in edges:
            if edge["src"] in allowed_hosts or edge["dst"] in allowed_hosts:
                for node_id in (edge["src"], edge["dst"]):
                    if not node_id.startswith("host/") or node_id in allowed_hosts:
                        allowed.add(node_id)

    selected_edges = [edge for edge in edges if allowed is None or
                      (edge["src"] in allowed and edge["dst"] in allowed)]
    selected_ids = {node["node_id"] for node in rows} if allowed is None else allowed
    selected_nodes = [node for node in rows if node["node_id"] in selected_ids]
    return {
        "view": view,
        "application_key": application_key,
        "nodes": selected_nodes,
        "edges": selected_edges,
    }
