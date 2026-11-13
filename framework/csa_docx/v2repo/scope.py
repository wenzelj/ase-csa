"""S592: application-scoped v2 graph projections.

`graph.refresh()` keeps `graph_node` / `graph_edge` as the complete global
view over the active hosts.  This module is a read-only projection over that
global graph: for a registered application key it returns the owned hosts plus
the peer endpoints that a current flow, a service/provider relationship or a
non-rejected source-checked evidence row links to an owned host, where the
application-scope metadata marks the relationship active.  Nothing here
deletes or rewrites graph data.
"""

from __future__ import annotations

from .graph import _LINK_IN, _LINK_OUT


def _scope_rows(repo, application_key: str) -> list[dict]:
    """All application-scope rows for a registered application key.

    The key is taken verbatim from the caller — it is never inferred from the
    working-directory name or a host name (S592).
    """
    if not application_key or not str(application_key).strip():
        raise ValueError("application_key is required for an application projection")
    return repo.application_scope.list_app_hosts(application_key=application_key)


def _active_scope(repo, application_key: str) -> dict[str, dict]:
    """Active, non-rejected scope rows keyed by host name.

    `active` marks the relationship as currently valid and `review_state`
    anything other than `rejected` keeps retired evidence out of scoped views
    (S592).
    """
    out = {}
    for row in _scope_rows(repo, application_key):
        if not row["active"] or row["review_state"] == "rejected":
            continue
        out[row["host_name"]] = row
    return out


def _active_host_names(repo, application_key: str, membership: str) -> set[str]:
    return {name for name, row in _active_scope(repo, application_key).items()
            if row["membership"] == membership}


def _evidence_link(repo) -> dict[str, set[str]]:
    """Host pairs linked by a non-rejected source-checked evidence claim.

    Reuses `graph.py`'s link grammar so an evidence-backed link is the same
    whether it is read from `graph_edge` or recomputed here (S592).  Rejected
    rows are excluded.
    """
    links: dict[str, set[str]] = {}

    def _add(a: str, b: str):
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)

    for (eid, claim) in repo.con.execute(
            "SELECT id, claim FROM evidence "
            "WHERE review_state != 'rejected' AND claim IS NOT NULL ORDER BY id"):
        m = _LINK_IN.match(claim) or _LINK_OUT.match(claim)
        if m and m[1] != m[2]:
            _add(m[1], m[2])
    return links


def _scoped_host_ids(repo, application_key: str) -> tuple[set[str], set[str]]:
    """Return (owned host IDs, active peer host IDs) for an application.

    An active peer is visible only when the scope metadata marks it active and
    non-rejected and a current flow, a service/provider relationship or a
    non-rejected source-checked evidence row links it to an owned host.
    Neighbour-only classifications never link hosts, so they cannot make a
    peer visible (S592).
    """
    owned = _active_host_names(repo, application_key, "owned")
    peers = _active_host_names(repo, application_key, "peer")
    if not owned:
        return set(), set()
    con = repo.con
    linked: dict[str, list[str]] = {p: [] for p in peers}

    def _mark(host: str, basis: str):
        if host in linked:
            linked[host].append(basis)

    for (src, dst) in con.execute("SELECT src_host, dst_host FROM flow"):
        if src in owned and dst in peers:
            _mark(dst, "flow")
        if dst in owned and src in peers:
            _mark(src, "flow")

    for (client, provider) in con.execute(
            "SELECT host, provider_host FROM service WHERE provider_host IS NOT NULL AND provider_host != ''"):
        if client in owned and provider in peers:
            _mark(provider, "service")
        if provider in owned and client in peers:
            _mark(client, "service")

    for (a, b) in _evidence_link(repo).items():
        if a in owned and b in peers:
            _mark(b, "evidence")
        if b in owned and a in peers:
            _mark(a, "evidence")

    visible = {h for h, bases in linked.items() if bases}
    return {f"host/{h}" for h in owned}, {f"host/{h}" for h in visible}


def application_hosts(repo, application_key: str) -> set[str]:
    """Active, non-rejected owned hosts and evidence-backed peers for an application."""
    owned, peers = _scoped_host_ids(repo, application_key)
    return owned | peers


def projected_graph(repo, application_key: str | None = None, view: str = "application") -> dict:
    """Return a graph projection without mutating the repository.

    ``view='global'`` returns the complete graph of active hosts, unchanged
    regardless of application scope.  ``view='application'`` requires the
    registered application key and returns its owned hosts plus the
    evidence-backed active peers, keeping node and edge provenance (including
    evidence IDs) from the global graph.  Edges are kept only when both
    endpoints are included hosts, so service and provider context never
    leaks unrelated global graph nodes.  Shared hosts are projected for every
    application that holds an active scope row for them (S592).
    """
    if view not in {"application", "global"}:
        raise ValueError("view must be 'application' or 'global'")
    if view == "application" and not application_key:
        raise ValueError("application_key is required for the application view")

    nodes = repo.graph.nodes()
    edges = repo.graph.edges()
    if view == "global":
        return {
            "view": "global",
            "application_key": None,
            "nodes": nodes,
            "edges": edges,
        }

    owned, peers = _scoped_host_ids(repo, application_key)
    host_ids = owned | peers
    selected_edges = [edge for edge in edges
                      if edge["src"] in host_ids and edge["dst"] in host_ids]
    selected_nodes = [node for node in nodes if node["node_id"] in host_ids]
    return {
        "view": "application",
        "application_key": application_key,
        "nodes": selected_nodes,
        "edges": selected_edges,
    }
