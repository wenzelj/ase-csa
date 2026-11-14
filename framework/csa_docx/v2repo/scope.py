"""S592/S614: the canonical application-scoped projections of the v2 graph.

`graph.refresh()` keeps `graph_node` / `graph_edge` as the complete global
graph over the active hosts.  This module is the one read-only definition of
the three views every consumer (repository callers, the Evidence Browser,
System Explorer and the CSA figures) must share.  Nothing here deletes or
rewrites graph data, and nothing is copied between application stores.

The projection contract (`PROJECTION_CONTRACT`, version `CONTRACT_VERSION`):

`owned`
    Only the hosts the selected application owns: an `application_scope` row
    with `membership='owned'` that is active and not rejected, for a host that
    is not retired.  Edges are the global edges between two owned hosts.

`application`
    The owned hosts, plus two different kinds of connected endpoint:

    * a *scoped peer host* is a registered host (a row in `host`).  It is
      visible only when its `application_scope` row for this application has
      `membership='peer'`, is active and not rejected, the host is not
      retired, and a qualifying relationship links it to an owned host;
    * an *external endpoint* is not a registered host: an external IP address,
      a named endpoint, a provider endpoint or a service name.  It has no
      `application_scope` row and needs none.  It is visible when a qualifying
      relationship links it to an owned host.

    A qualifying relationship is a current flow, a service/provider
    relationship, or a non-rejected source-backed evidence row whose claim
    links the two ends.  A registered host with no active scope row for this
    application (an unlinked peer, another application's host, a retired
    host, a neighbour-only label) is never visible, whatever touches it.
    Edges are kept only when one end is an owned host and both ends are
    visible.

Address endpoints in a qualifying relationship are resolved to the first
registered owner in `address`, except for loopback, unspecified and
link-local addresses.  The owner's scope row then governs visibility; an
unowned address remains an external endpoint.

`global`
    The complete active graph exactly as `graph.refresh()` built it.  Scope
    metadata never changes it.

`owned` and `application` need an explicit registered application key; an
omitted key or a key with no scope rows is rejected.  Every projected edge
keeps its evidence IDs; scoped edges also carry the application key and the
record they were read from (`source`).
"""

from __future__ import annotations

import hashlib
import ipaddress

from .graph import _LINK_IN, _LINK_OUT

CONTRACT_VERSION = "v2-scope-1"
VIEWS = ("owned", "application", "global")

PROJECTION_CONTRACT = {
    "version": CONTRACT_VERSION,
    "views": {
        "owned": "Only active, non-rejected membership='owned' hosts of the application, "
                 "and the edges between them.",
        "application": "The owned hosts, plus scoped peer hosts and external endpoints that a "
                       "current flow, a service/provider relationship or a non-rejected "
                       "source-backed evidence row links to an owned host.",
        "global": "The complete active graph; never filtered by application scope.",
    },
    "application_key": "Required for 'owned' and 'application'; omitted or unknown keys are rejected.",
    "scoped_peer_host": "A registered host with an active, non-rejected membership='peer' scope row "
                        "and a qualifying relationship to an owned host.",
    "external_endpoint": "Not a registered host (external IP, named endpoint, provider endpoint or "
                         "service name); needs no scope row, only a qualifying relationship to an "
                         "owned host.",
    "address_resolution": "Resolve an address to its first address.owner_host except loopback, "
                          "unspecified and link-local addresses; the owner's scope row governs visibility.",
    "qualifying_relationships": ("flow", "service", "evidence"),
    "never_visible_in_application": ("rejected evidence", "retired hosts", "inactive scope rows",
                                     "rejected scope rows", "neighbour-only labels",
                                     "registered hosts without a scope row for the application"),
    "edge_provenance": ("evidence_ids", "application_key", "source"),
}

# what an external endpoint is, never a scoped peer host
EXTERNAL_CLASSES = ("external_ip", "named_endpoint", "provider_endpoint", "service_name")


def _scope_rows(repo, application_key: str) -> list[dict]:
    """All application-scope rows for a registered application key.

    The key is taken verbatim from the caller — it is never inferred from the
    working-directory name or a host name (S592).
    """
    if not application_key or not str(application_key).strip():
        raise ValueError("application_key is required for an application projection")
    return repo.application_scope.list_app_hosts(application_key=application_key)


def _retired_hosts(repo) -> set[str]:
    return {name for (name,) in repo.con.execute("SELECT name FROM host WHERE status = 'retired'")}


def _registered_hosts(repo) -> set[str]:
    """Every registered host, active or retired: none of them is an external endpoint."""
    return {name for (name,) in repo.con.execute("SELECT name FROM host")}


def _address_owners(con) -> dict[str, str]:
    """Return the first registered owner for each usable address."""
    owners = {}
    for address, owner in con.execute(
            "SELECT ip, owner_host FROM address WHERE owner_host IS NOT NULL ORDER BY rowid"):
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified or ip.is_link_local:
            continue
        owners.setdefault(address, owner)
    return owners


def _resolve_endpoint(con, endpoint: str) -> str:
    """Resolve a usable address to its first registered owner, if any."""
    return _address_owners(con).get(endpoint, endpoint)


def _active_scope(repo, application_key: str) -> dict[str, dict]:
    """Active, non-rejected scope rows of non-retired hosts, keyed by host name.

    `active` marks the relationship as currently valid, a `review_state` of
    `rejected` keeps retired evidence out of scoped views (S592), and a
    retired host is never part of a scoped view (S614).
    """
    retired = _retired_hosts(repo)
    out = {}
    for row in _scope_rows(repo, application_key):
        if not row["active"] or row["review_state"] == "rejected" or row["host_name"] in retired:
            continue
        out[row["host_name"]] = row
    return out


def _active_host_names(repo, application_key: str, membership: str) -> set[str]:
    return {name for name, row in _active_scope(repo, application_key).items()
            if row["membership"] == membership}


def _evidence_pairs(repo) -> list[tuple[str, str, str]]:
    """(source, destination, evidence ID) for every non-rejected source-backed link claim.

    Reuses `graph.py`'s link grammar so an evidence-backed link is the same
    whether it is read from `graph_edge` or recomputed here (S592).  A rejected
    row, or a row that names no source, is not a qualifying relationship.
    """
    out = []
    for (eid, claim) in repo.con.execute(
            "SELECT id, claim FROM evidence "
            "WHERE review_state != 'rejected' AND claim IS NOT NULL "
            "AND source_title IS NOT NULL AND TRIM(source_title) != '' ORDER BY id"):
        m = _LINK_IN.match(claim) or _LINK_OUT.match(claim)
        if m and m[1] != m[2]:
            source, destination = (_resolve_endpoint(repo.con, endpoint) for endpoint in (m[1], m[2]))
            if source != destination:
                out.append((source, destination, eid))
    return out


def _evidence_link(repo) -> dict[str, set[str]]:
    """Host pairs linked by a non-rejected source-backed evidence claim."""
    links: dict[str, set[str]] = {}
    for a, b, _eid in _evidence_pairs(repo):
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)
    return links


def _relationships(repo) -> list[tuple[str, str, str]]:
    """Every qualifying relationship as (end, other end, basis), in a stable order."""
    con = repo.con
    out = []
    for (src, dst) in con.execute("SELECT DISTINCT src_host, dst_host FROM flow ORDER BY src_host, dst_host"):
        if src != dst:
            out.append((src, dst, "flow"))
    for (client, provider) in con.execute(
            "SELECT DISTINCT host, provider_host FROM service "
            "WHERE provider_host IS NOT NULL AND provider_host != '' ORDER BY host, provider_host"):
        if client != provider:
            out.append((client, provider, "service"))
    for a, b, _eid in _evidence_pairs(repo):
        out.append((a, b, "evidence"))
    return out


def _linked_to_owned(repo, owned: set[str]) -> dict[str, list[str]]:
    """{name: bases} for every name a qualifying relationship links to an owned host."""
    linked: dict[str, list[str]] = {}
    for a, b, basis in _relationships(repo):
        for near, far in ((a, b), (b, a)):
            if near in owned and far not in owned:
                bases = linked.setdefault(far, [])
                if basis not in bases:
                    bases.append(basis)
    return linked


def _scoped_host_ids(repo, application_key: str) -> tuple[set[str], set[str]]:
    """Return (owned host IDs, active peer host IDs) for an application.

    An active peer is visible only when the scope metadata marks it active and
    non-rejected and a current flow, a service/provider relationship or a
    non-rejected source-backed evidence row links it to an owned host.
    Neighbour-only classifications never link hosts, so they cannot make a
    peer visible (S592).
    """
    owned = _active_host_names(repo, application_key, "owned")
    peers = _active_host_names(repo, application_key, "peer")
    if not owned:
        return set(), set()
    linked = _linked_to_owned(repo, owned)
    visible = {h for h in peers if linked.get(h)}
    return {f"host/{h}" for h in owned}, {f"host/{h}" for h in visible}


def application_hosts(repo, application_key: str) -> set[str]:
    """Active, non-rejected owned hosts and evidence-backed peers for an application."""
    owned, peers = _scoped_host_ids(repo, application_key)
    return owned | peers


def _require_known_key(repo, application_key: str | None, view: str) -> str:
    if not application_key or not str(application_key).strip():
        raise ValueError(f"application_key is required for the {view} view")
    if not _scope_rows(repo, application_key):
        raise ValueError(f"unknown application_key: {application_key}")
    return application_key


def _external_class(name: str, kind: str) -> str:
    """Which kind of external endpoint a node is; never a scoped peer host."""
    if kind == "service":
        return "service_name"
    try:
        ipaddress.ip_address(name.split("%")[0])
        return "external_ip"
    except ValueError:
        return "provider_endpoint" if kind == "provider" else "named_endpoint"


def _edge_id(src: str, dst: str, kind: str) -> str:
    """The same edge identity `graph.refresh()` gives a (source, destination, kind)."""
    return f"{kind}/{hashlib.sha1(f'{src}|{dst}|{kind}'.encode('utf-8')).hexdigest()[:12]}"


def scope_identities(repo, application_key: str) -> dict:
    """Who is visible for an application, by class, under the projection contract.

    Returns `owned` and `peers` (sorted `host/<name>` IDs) and `external`, one
    entry per external endpoint with its node ID, class (`EXTERNAL_CLASSES`)
    and the bases (`flow`, `service`, `evidence`) that link it to an owned
    host.  A scoped peer host is never listed as an external endpoint.
    """
    _require_known_key(repo, application_key, "application")
    owned_ids, peer_ids = _scoped_host_ids(repo, application_key)
    owned = {i.split("/", 1)[1] for i in owned_ids}
    registered = _registered_hosts(repo)
    scoped = {row["host_name"] for row in _scope_rows(repo, application_key)}
    kinds = {n["node_id"]: n["kind"] for n in repo.graph.nodes()}
    external: dict[str, dict] = {}

    def _external(node_id: str, name: str, kind: str, basis: str):
        entry = external.setdefault(node_id, {"node_id": node_id, "class": _external_class(name, kind), "basis": []})
        if basis not in entry["basis"]:
            entry["basis"].append(basis)

    for name, bases in _linked_to_owned(repo, owned).items():
        if name in registered or name in scoped:         # a registered or scoped host is governed by its scope row
            continue
        node_id = f"host/{name}"
        for basis in bases:
            _external(node_id, name, kinds.get(node_id, "endpoint"), basis)
    for edge in repo.graph.edges(kind="runs"):           # the service names an owned host runs
        if edge["src"] in owned_ids and edge["dst"].startswith("service/"):
            _external(edge["dst"], edge["dst"].split("/", 1)[1], "service", "service")
    return {"application_key": application_key, "owned": sorted(owned_ids), "peers": sorted(peer_ids),
            "external": [external[k] for k in sorted(external)]}


def projected_graph(repo, application_key: str | None = None, view: str = "application") -> dict:
    """Return a graph projection without mutating the repository.

    The three views follow `PROJECTION_CONTRACT` (see the module docstring).
    ``view='global'`` returns the complete graph of active hosts, unchanged
    regardless of application scope.  ``view='owned'`` and
    ``view='application'`` require a registered application key and keep node
    and edge provenance (including evidence IDs) from the global graph.
    Shared hosts are projected for every application that holds an active
    scope row for them (S592).  The result's ``scope`` lists the visible
    identities by class, so a scoped peer host is told apart from an external
    endpoint.
    """
    if view not in VIEWS:
        raise ValueError("view must be 'owned', 'application' or 'global'")

    nodes = repo.graph.nodes()
    edges = repo.graph.edges()
    if view == "global":
        return {"view": "global", "application_key": None, "contract": CONTRACT_VERSION,
                "nodes": nodes, "edges": edges,
                "scope": {"owned": [], "peers": [], "external": []}}

    ids = scope_identities(repo, _require_known_key(repo, application_key, view))
    owned = set(ids["owned"])
    if view == "owned":
        visible = set(owned)
        scope = {"owned": ids["owned"], "peers": [], "external": []}
    else:
        visible = owned | set(ids["peers"]) | {e["node_id"] for e in ids["external"]}
        scope = {"owned": ids["owned"], "peers": ids["peers"], "external": ids["external"]}

    def _keep(src: str, dst: str) -> bool:
        if view == "owned":
            return src in owned and dst in owned
        return (src in owned or dst in owned) and src in visible and dst in visible

    selected = {e["edge_id"]: {**e, "application_key": application_key, "source": "graph_edge"}
                for e in edges if _keep(e["src"], e["dst"])}
    selected_nodes = {n["node_id"]: n for n in nodes if n["node_id"] in visible}

    if view == "application":
        # `graph.refresh()` draws an evidence link only between two registered hosts, so an
        # external endpoint that only an evidence row links to an owned host is projected here.
        external = {e["node_id"] for e in ids["external"]}
        by_edge: dict[tuple[str, str], list[str]] = {}
        for a, b, eid in _evidence_pairs(repo):
            src, dst = f"host/{a}", f"host/{b}"
            if (src in visible and dst in visible and (src in owned or dst in owned)):
                by_edge.setdefault((src, dst), []).append(eid)
        for (src, dst), eids in sorted(by_edge.items()):
            edge_id = _edge_id(src, dst, "flow")
            edge = selected.get(edge_id)
            if edge is None:
                selected[edge_id] = {"edge_id": edge_id, "src": src, "dst": dst, "kind": "flow",
                                     "evidence_ids": ";".join(sorted(set(eids))),
                                     "application_key": application_key, "source": "evidence"}
            else:
                known = [x for x in (edge["evidence_ids"] or "").split(";") if x]
                edge["evidence_ids"] = ";".join(sorted(set(known) | set(eids)))
            for node_id in (src, dst):
                if node_id not in selected_nodes:
                    selected_nodes[node_id] = {"node_id": node_id, "label": node_id.split("/", 1)[1],
                                               "kind": "endpoint", "evidence_ids": ""}

    return {"view": view, "application_key": application_key, "contract": CONTRACT_VERSION,
            "nodes": [selected_nodes[k] for k in sorted(selected_nodes)],
            "edges": [selected[k] for k in sorted(selected)],
            "scope": scope}


# --------------------------------------------------------------------------- S616
# `csa graph` on a csa-work-v2 project.  Every action reads `csa.sqlite`; the legacy
# `graph/nodes.csv` and `graph/edges.csv` files are never opened, whatever they hold.

GRAPH_SOURCE = "csa.sqlite graph_node, graph_edge"
V2_GRAPH_ACTIONS = ("stats", "list", "get", "verify", "review")
V2_GRAPH_ERRORS = {
    "V2_GRAPH_COMMAND_UNAVAILABLE": "The graph action has no V2 implementation. The V2 graph is derived by "
                                    "graph.refresh(); legacy graph files are not read or written.",
    "V2_GRAPH_NOT_FOUND": "No graph node or edge with that ID exists in the selected view.",
    "V2_GRAPH_SCOPE_ERROR": "The view is not owned, application or global, or the application key is "
                            "missing or has no scope rows.",
    "V2_GRAPH_REVIEW_ERROR": "The review subject does not exist or the state is not accepted, reviewed "
                             "or rejected.",
}


def _graph_error(code: str, message: str) -> dict:
    return {"status": "ERROR", "code": code, "message": message, "source": GRAPH_SOURCE}


def _graph_options(rest: list[str]) -> tuple[list[str], str, str | None]:
    """Split `--view V` and `--application-key K` from the positional arguments."""
    args, view, key, i = [], "global", None, 0
    while i < len(rest):
        item = rest[i]
        if item in ("--view", "--application-key"):
            if i + 1 >= len(rest):
                raise ValueError(f"{item} needs a value")
            if item == "--view":
                view = rest[i + 1]
            else:
                key = rest[i + 1]
            i += 2
            continue
        if item.startswith("--view=") or item.startswith("--application-key="):
            name, value = item.split("=", 1)
            if name == "--view":
                view = value
            else:
                key = value
            i += 1
            continue
        args.append(item)
        i += 1
    return args, view, key


def _verify_projection(repo, projection: dict) -> dict:
    """The checks `graph.verify()` runs, on one projection: cited evidence exists, no dangling edge."""
    evidence = {row[0] for row in repo.con.execute("SELECT id FROM evidence")}
    node_ids = {node["node_id"] for node in projection["nodes"]}
    issues = []
    for row in projection["nodes"] + projection["edges"]:
        missing = sorted({x for x in str(row.get("evidence_ids") or "").split(";") if x} - evidence)
        if missing:
            issues.append({"id": row.get("node_id") or row.get("edge_id"), "missing": missing})
    for edge in projection["edges"]:
        if edge["src"] not in node_ids or edge["dst"] not in node_ids:
            issues.append({"id": edge["edge_id"], "error": "dangling graph endpoint"})
    return {"status": "OK" if not issues else "ERROR", "issues": issues,
            "nodes": len(projection["nodes"]), "edges": len(projection["edges"])}


def graph_command(repo, rest: list[str] | None = None, project_key: str | None = None) -> dict:
    """Run one `csa graph` action against the V2 repository and return its result dict.

    Actions (`V2_GRAPH_ACTIONS`): `stats` (the default), `list`, `get ID`, `verify` and
    `review ID STATE [note]`.  The read actions take `--view owned|application|global`
    (default `global`) and `--application-key KEY` (default: the project key) and follow the
    projection contract of `projected_graph`.  `review` runs in its own transaction and
    appends a review event.  Anything else returns one of the documented `V2_GRAPH_ERRORS`;
    no action ever falls back to the legacy graph CSV files.
    """
    try:
        args, view, key = _graph_options(list(rest or []))
    except ValueError as exc:
        return _graph_error("V2_GRAPH_SCOPE_ERROR", str(exc))
    action = args[0] if args else "stats"
    if action not in V2_GRAPH_ACTIONS:
        return _graph_error("V2_GRAPH_COMMAND_UNAVAILABLE",
                            f"graph action '{action}' has no V2 implementation; old graph files were not used")
    if action == "review":
        subject = args[1] if len(args) > 1 else ""
        state = args[2] if len(args) > 2 else ""
        try:
            with repo.tx():
                result = repo.graph.review(subject, state, actor="csa graph review", note=" ".join(args[3:]))
        except KeyError:
            return _graph_error("V2_GRAPH_REVIEW_ERROR", f"graph subject not found: {subject}")
        except ValueError as exc:
            return _graph_error("V2_GRAPH_REVIEW_ERROR", str(exc))
        return {**result, "source": GRAPH_SOURCE}

    try:
        projection = projected_graph(repo, None if view == "global" else (key or project_key), view=view)
    except ValueError as exc:
        return _graph_error("V2_GRAPH_SCOPE_ERROR", str(exc))
    nodes, edges = projection["nodes"], projection["edges"]
    base = {"status": "OK", "project": project_key, "view": projection["view"],
            "application_key": projection["application_key"]}
    if action == "stats":
        def counts(rows):
            kinds = sorted({row.get("kind") or "" for row in rows})
            return {kind: sum(1 for row in rows if (row.get("kind") or "") == kind) for kind in kinds}
        return {**base, "nodes": len(nodes), "edges": len(edges), "nodes_by_type": counts(nodes),
                "edges_by_relationship_type": counts(edges), "source": GRAPH_SOURCE}
    if action == "list":
        return {**base, "node_count": len(nodes), "edge_count": len(edges), "nodes": nodes, "edges": edges,
                "source": GRAPH_SOURCE}
    if action == "get":
        subject = args[1] if len(args) > 1 else ""
        row = next((n for n in nodes if n["node_id"] == subject), None) or \
            next((e for e in edges if e["edge_id"] == subject), None)
        if not row:
            return _graph_error("V2_GRAPH_NOT_FOUND", f"graph subject not found: {subject}")
        return {**base, "subject": row, "source": GRAPH_SOURCE}
    result = repo.graph.verify() if view == "global" else _verify_projection(repo, projection)
    return {**base, **result, "source": GRAPH_SOURCE + ", evidence"}
