"""S584: `r.graph` — the graph as a derived view over the core tables.

`refresh()` drops and rebuilds `graph_node`, `graph_edge`, `alias` and `entity` from
`host`, `address`, `service`, `flow` and `evidence` (and the discovery index mirror),
inside one transaction, and appends one `review_event` row with the counts. The derived
tables are read-only at the API level: any write to them outside `refresh()` raises
`RuntimeError`, enforced by a `_GuardedConnection` proxy over the Repo's sqlite3
connection for the Repo's lifetime.

The link grammar that turns an evidence `claim` into an edge is reused from
`graph_sync.py` (the "A ... has an ... connection to B on ..." / "A has an ... connection
from P to B ..." pair); the entity extraction is imported from `index_entities.py`.
Neither is re-implemented here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

# graph_sync.py's link grammar, reused — never re-implemented (S584).
# `IN` / `OUT` are local names inside `graph_sync.main`, so the patterns are extracted
# verbatim from the module's source text and compiled here (same file, same patterns).
_GS_SCRIPT = (Path(__file__).resolve().parents[3] / "skills" / "csa-evidence-matrix"
              / "scripts" / "graph_sync.py")
_GRAMMAR_RE = re.compile(r'^\s*(IN|OUT)\s*=\s*re\.compile\(r"([^"]+)"\)\s*$', re.M)


def _link_grammars():
    text = _GS_SCRIPT.read_text(encoding="utf-8")
    m_in = next((m for m in _GRAMMAR_RE.finditer(text) if m.group(1) == "IN"), None)
    m_out = next((m for m in _GRAMMAR_RE.finditer(text) if m.group(1) == "OUT"), None)
    if not m_in or not m_out:
        raise RuntimeError(f"link grammar not found in {str(_GS_SCRIPT)!r}")
    return re.compile(m_in.group(2)), re.compile(m_out.group(2))


_LINK_IN, _LINK_OUT = _link_grammars()

# index_entities.py's extraction, imported — never re-implemented (S584).
_IE_SCRIPT = (Path(__file__).resolve().parents[3] / "skills" / "csa-discovery-index"
              / "scripts" / "index_entities.py")


def _load_ie():
    spec = importlib.util.spec_from_file_location("_csa_v2repo_index_entities", _IE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _IE = _load_ie()
except Exception:
    _IE = None

DERIVED_TABLES = ("graph_node", "graph_edge", "alias", "entity")
_WRITE_HEADS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "DROP", "ALTER")
_TABLE_RE = re.compile(
    r"\s*(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|DROP\s+TABLE|ALTER\s+TABLE)"
    r"\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.I)


class _DerivedGuard:
    """Refuses any write to the derived tables outside a `refresh()` call.

    `check(stmt)` raises `RuntimeError` for INSERT / UPDATE / DELETE / REPLACE /
    DROP / ALTER on a derived table (`graph_node`, `graph_edge`, `alias`, `entity`)
    while `refresh()` is not running. `_GuardedConnection` calls `check()` before
    forwarding `execute` / `executemany` to sqlite3.
    """

    def __init__(self):
        self._active = False

    def check(self, stmt: str) -> None:
        if self._active or not stmt:
            return
        head = stmt.lstrip().split(None, 1)
        if not head or head[0].upper() not in _WRITE_HEADS:
            return
        m = _TABLE_RE.match(stmt)
        if m and m.group(1).lower() in DERIVED_TABLES:
            raise RuntimeError(
                f"derived table {m.group(1)!r} is read-only — it is rebuilt by "
                "`r.graph.refresh()`, never written directly"
            )


class _GuardedConnection:
    """Thin proxy over `sqlite3.Connection` that checks every `execute` / `executemany`
    against the `_DerivedGuard` before forwarding to the real connection.

    All other attributes and methods are passed through unchanged.
    """

    def __init__(self, real: "sqlite3.Connection", guard: "_DerivedGuard"):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_guard", guard)

    def execute(self, stmt, *args, **kwargs):
        self._guard.check(stmt)
        return self._real.execute(stmt, *args, **kwargs)

    def executemany(self, stmt, seq, *args, **kwargs):
        self._guard.check(stmt)
        return self._real.executemany(stmt, seq, *args, **kwargs)

    def executescript(self, script, *args, **kwargs):
        return self._real.executescript(script, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


class Graph:
    """`r.graph` — read-only views `nodes()` / `edges()` plus the `refresh()` rebuild.

    `refresh()` must be called inside `with r.tx():`; it rebuilds all four derived
    tables from the core tables in a deterministic (order-independent) way and appends
    one `review_event` row: `action='graph.refresh'`, `subject_type='graph'`,
    `note='<counts>'`.

    The derived tables are read-only at the API level: `graph.py` patches the
    `Repo` class once at import time to wrap its `con` property with a
    `_GuardedConnection` proxy that runs `_DerivedGuard.check` on every
    `execute` / `executemany` before forwarding to the raw connection, so any
    write to `graph_node`, `graph_edge`, `alias`, or `entity` outside
    `refresh()` raises `RuntimeError`. `refresh()` itself uses the unguarded
    raw connection (`repo.raw_con`).
    """

    def __init__(self, repo: "Repo"):
        self._repo = repo
        self._guard = _DerivedGuard()

    # --------------------------------------------------------------- derived build
    # --------------------------------------------------------------- derived build
    def _host_nodes(self, con) -> list[tuple[str, str, str]]:
        """One node per active host: (node_id, label, evidence_ids)."""
        out = []
        for name, role, site in con.execute(
                "SELECT name, role, site FROM host WHERE status='active' ORDER BY name"):
            label = name
            parts = [p for p in (role, site) if p]
            if parts:
                label += f" ({', '.join(parts)})"
            out.append((f"host/{name}", label, ""))
        return out

    def _flow_endpoint_nodes(self, con, host_names: set[str]) -> list[tuple[str, str, str]]:
        """One node per distinct flow endpoint not already a host (UNION de-duplicates)."""
        out = []
        for (ep,) in con.execute("SELECT src_host FROM flow UNION SELECT dst_host FROM flow"):
            if ep in host_names:
                continue
            out.append((f"host/{ep}", ep, ""))
        return out

    def _build_nodes(self, con):
        hosts = self._host_nodes(con)
        host_names = {h[0].split("/", 1)[1] for h in hosts}
        rows = [(node_id, label, "host", evid) for node_id, label, evid in hosts]
        for (sname,) in con.execute(
                "SELECT DISTINCT name FROM service WHERE name IS NOT NULL AND name != '' ORDER BY name"):
            rows.append((f"service/{sname}", sname, "service", ""))
        for node_id, label, evid in self._flow_endpoint_nodes(con, host_names):
            rows.append((node_id, label, "endpoint", evid))
        return rows

    def _build_edges(self, con):
        def _edge_id(src, dst, kind):
            h = hashlib.sha1(f"{src}|{dst}|{kind}".encode("utf-8")).hexdigest()[:12]
            return f"{kind}/{h}"

        # (src_node, dst_node, kind) -> semicolon-joined evidence IDs (deduplicated, sorted)
        evid: dict[tuple[str, str, str], list[str]] = {}

        def _add(src, dst, kind, eid=None):
            evid.setdefault((src, dst, kind), [])
            if eid and eid not in evid[(src, dst, kind)]:
                evid[(src, dst, kind)].append(eid)

        # flow: host -> host, kind='flow'
        for src, dst in con.execute("SELECT DISTINCT src_host, dst_host FROM flow ORDER BY src_host, dst_host"):
            if src == dst:
                continue
            _add(f"host/{src}", f"host/{dst}", "flow")

        # service: host -> service, kind='runs'
        for host, name in con.execute(
                "SELECT DISTINCT host, name FROM service WHERE name IS NOT NULL AND name != '' "
                "ORDER BY host, name"):
            _add(f"host/{host}", f"service/{name}", "runs")

        # evidence link rows: reuse graph_sync.py's grammar (IN / OUT patterns)
        host_names = {h[0].split("/", 1)[1] for h in self._host_nodes(con)}
        for eid, claim in con.execute(
                "SELECT id, claim FROM evidence WHERE review_state != 'rejected' AND claim IS NOT NULL ORDER BY id"):
            m = _LINK_IN.match(claim) or _LINK_OUT.match(claim)
            if not m or m[1] not in host_names or m[2] not in host_names or m[1] == m[2]:
                continue
            _add(f"host/{m[1]}", f"host/{m[2]}", "flow", eid)

        return [
            (_edge_id(src, dst, kind), src, dst, kind, ";".join(sorted(eids)))
            for (src, dst, kind), eids in sorted(evid.items())
        ]

    def _build_alias(self, con):
        rows = []
        for (hname,) in con.execute("SELECT name FROM host ORDER BY name"):
            rows.append((hname, "host", hname, None))
        for ip, scope, owner in con.execute("SELECT ip, scope, owner_host FROM address ORDER BY ip"):
            if owner:
                rows.append((ip, "host", owner, scope))
        return rows

    def _build_entity(self, con):
        rows = []
        for (path,) in con.execute("SELECT rel_path FROM indexed_file ORDER BY rel_path"):
            for (text,) in con.execute(
                    "SELECT text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (path,)):
                if _IE is None or not text:
                    continue
                seen = set()
                for _line_no, kind, _value, norm in _IE.extract_text(text.splitlines()):
                    if (kind, norm) in seen:
                        continue
                    seen.add((kind, norm))
                    rows.append((kind, norm, path))
        return rows

    def refresh(self, actor=None):
        """Drop and rebuild `graph_node`, `graph_edge`, `alias` and `entity` from the core
        tables, then append one `review_event` row. Call inside `with r.tx():`."""
        r = self._repo
        r._require_tx()
        con = r.raw_con
        self._guard._active = True
        try:
            nodes = self._build_nodes(con)
            edges = self._build_edges(con)
            alias = self._build_alias(con)
            entity = self._build_entity(con)
            con.execute("DELETE FROM graph_node")
            con.executemany("INSERT INTO graph_node (node_id, label, kind, evidence_ids) VALUES (?, ?, ?, ?)", nodes)
            con.execute("DELETE FROM graph_edge")
            con.executemany("INSERT INTO graph_edge (edge_id, src, dst, kind, evidence_ids) VALUES (?, ?, ?, ?, ?)", edges)
            con.execute("DELETE FROM alias")
            con.executemany("INSERT INTO alias (alias, subject_type, subject_id, scope) VALUES (?, ?, ?, ?)", alias)
            con.execute("DELETE FROM entity")
            con.executemany("INSERT INTO entity (kind, norm, file_ref) VALUES (?, ?, ?)", entity)
        finally:
            self._guard._active = False
        counts = {"graph_node": len(nodes), "graph_edge": len(edges),
                  "alias": len(alias), "entity": len(entity)}
        note = " ".join(f"{k}={v}" for k, v in counts.items())
        r._audit(actor, "graph.refresh", "graph", "graph", note)
        return {**counts, "note": note}

    # ------------------------------------------------------------- read-only views
    def nodes(self, host=None, kind=None):
        r = self._repo
        sql = "SELECT node_id, label, kind, evidence_ids FROM graph_node"
        where, params = [], []
        if host is not None:
            where.append("node_id = ?"); params.append(f"host/{host}")
        if kind is not None:
            where.append("kind = ?"); params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY node_id"
        return [dict(zip(("node_id", "label", "kind", "evidence_ids"), row))
                for row in r.con.execute(sql, params).fetchall()]

    def edges(self, src=None, dst=None, kind=None):
        r = self._repo
        sql = "SELECT edge_id, src, dst, kind, evidence_ids FROM graph_edge"
        where, params = [], []
        if src is not None:
            where.append("src = ?"); params.append(src)
        if dst is not None:
            where.append("dst = ?"); params.append(dst)
        if kind is not None:
            where.append("kind = ?"); params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY edge_id"
        return [dict(zip(("edge_id", "src", "dst", "kind", "evidence_ids"), row))
                for row in r.con.execute(sql, params).fetchall()]

# ---------------------------------------------------------------------------
# Wire the guard into Repo without modifying `__init__.py`.
#
# `sqlite3.Connection` instances do not allow arbitrary attribute assignment,
# so the guard state is kept in a module-level dict keyed by `id(raw)`.
#
# We replace the `Repo.con` class property with a new property that returns a
# `_GuardedConnection` proxy. The raw connection is exposed as `Repo.raw_con`.
# `Repo.graph` is added as an instance attribute on first access via
# `Repo.__getattr__`.
# ---------------------------------------------------------------------------

_STATE: dict[int, dict] = {}


def _state(raw) -> dict:
    key = id(raw)
    if key not in _STATE:
        _STATE[key] = {"guard": _DerivedGuard(), "proxy": None}
    return _STATE[key]


def _patch_repo():
    from . import Repo as _Repo

    if getattr(_Repo, "_v2repo_graph_patched", False):
        return

    original_con = _Repo.con
    original_getattr = getattr(_Repo, "__getattr__", None)

    def _guarded_con(self):
        raw = original_con.fget(self)
        st = _state(raw)
        if st["proxy"] is None:
            st["proxy"] = _GuardedConnection(raw, st["guard"])
        return st["proxy"]

    def _raw_con(self):
        return original_con.fget(self)

    def _getattr(self, name):
        if name == "graph":
            g = Graph(self)
            self.graph = g
            self._graph_guard = g._guard
            return g
        if name == "raw_con":
            return _raw_con(self)
        if name == "_con_proxy":
            return _guarded_con(self)
        if original_getattr is not None:
            return original_getattr(self, name)
        raise AttributeError(name)

    _Repo.con = property(_guarded_con)
    _Repo.__getattr__ = _getattr
    _Repo._v2repo_graph_patched = True


_patch_repo()
