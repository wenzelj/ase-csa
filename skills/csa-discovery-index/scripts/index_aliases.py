"""Aliases for the CSA discovery index: which names, full names and addresses belong to which host, built from the
index's entities and the project's host register. Derived data: rebuilt from scratch on every call, never edited.

Basis, strongest first:
  own-capture   an address (or the name) on the capture the host itself produced
  register      a row of the host register (hosts.csv), which carries the scope: system, sibling or neighbour
  paired-row    a name and an address in one row of a structured table
  paired-line   one name and one or more addresses (at most MAX_PAIRING_ADDRESSES) on one line of text
A name paired with PAIRING_SPREAD or more different addresses is the writer of a log, not a host. An address that
maps to two hosts is marked ``ambiguous`` and is never used to expand a search.
Standard library only."""
import re
from collections import defaultdict

MAX_PAIRING_ADDRESSES = 3
PAIRING_SPREAD = 3
OWN_ADDRESS_TABLES = ("ip_interface_config",)
NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9-]{2,30}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS aliases(
  alias_id INTEGER PRIMARY KEY, host TEXT, kind TEXT, value TEXT, norm TEXT, scope TEXT, basis TEXT,
  confidence TEXT, file_id INTEGER, line_no INTEGER, ambiguous INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS aliases_norm ON aliases(kind, norm);
CREATE INDEX IF NOT EXISTS aliases_host ON aliases(host);
"""


def register_scope(sources: str, in_scope: str = "") -> str:
    """The scope a register row carries, from the sources and in_scope hostmodel records for it."""
    s = (sources or "").lower()
    if "neighbour:" in s:
        return "neighbour"
    if "project " in s or (in_scope or "").lower().startswith("system:"):
        return "sibling"
    return "external" if (in_scope or "").lower() == "peer" else "system"


def load_register(work_dir) -> list[dict]:
    """The host register (<work_dir>/hosts/hosts.csv) as [{host, fqdn, ips, sources, in_scope}]; empty without it."""
    import csv
    from pathlib import Path
    f = Path(work_dir) / "hosts" / "hosts.csv"
    if not f.is_file():
        return []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        return [{"host": r["host"], "fqdn": r.get("fqdn", ""), "ips": [x for x in (r.get("ips") or "").split(";") if x],
                 "sources": r.get("sources", ""), "in_scope": r.get("in_scope", "")}
                for r in csv.DictReader(fh) if r.get("host")]


def _short(name: str) -> str:
    return name.split(".")[0].upper()


def build_aliases(con, register: list[dict] | None = None) -> int:
    """Rebuild ``aliases`` from ``entities`` and ``register`` ([{host, fqdn, ips, sources}]); returns the row count."""
    con.executescript(SCHEMA)
    con.execute("DELETE FROM aliases")
    reg_scope = {r["host"].upper(): register_scope(r.get("sources", ""), r.get("in_scope", "")) for r in register or []}
    captured = {h.upper() for (h,) in con.execute("SELECT DISTINCT host FROM files WHERE host IS NOT NULL AND host<>''")}
    out: list[tuple] = []     # host, kind, value, norm, basis, confidence, file_id, line_no

    # own-capture: the host's name, and the addresses and full name on its own capture
    for h in captured:
        out.append((h, "name", h, h, "own-capture", "high", None, None))
    ph = ",".join("?" * len(OWN_ADDRESS_TABLES))
    for host, val, norm, fid, ln in con.execute(
            "SELECT host, value, norm, file_id, line_no FROM entities WHERE kind='address' AND source='row' AND host<>'' "
            f"AND file_id IN (SELECT file_id FROM rows WHERE table_name IN ({ph}))", OWN_ADDRESS_TABLES):
        out.append((host.upper(), "address", val, norm, "own-capture", "high", fid, ln))
    for host, val, norm, fid, ln in con.execute("SELECT host, value, norm, file_id, line_no FROM entities WHERE kind='fqdn' AND host<>''"):
        if _short(norm) == host.upper():
            out.append((host.upper(), "fqdn", val, norm, "own-capture", "high", fid, ln))

    # paired: one name, a few addresses, one line or one table row
    by_line = defaultdict(lambda: {"address": [], "name": [], "src": set()})
    for kind, val, norm, fid, ln, src in con.execute(
            "SELECT kind, value, norm, file_id, line_no, source FROM entities WHERE kind IN ('address','fqdn','host')"):
        e = by_line[(fid, ln)]
        e["src"].add(src)
        if kind == "address":
            e["address"].append((val, norm))
        else:
            name = _short(norm) if kind == "fqdn" else norm
            if NAME_OK.match(name):
                e["name"].append((name, val, norm if kind == "fqdn" else None))
    pairs = []
    for (fid, ln), e in by_line.items():
        names = {n[0] for n in e["name"]}
        if len(names) != 1 or not e["address"] or len(e["address"]) > MAX_PAIRING_ADDRESSES:
            continue
        name = next(iter(names))
        row = e["src"] == {"row"}
        for val, norm in e["address"]:
            pairs.append((name, "address", val, norm, "paired-row" if row else "paired-line", "high" if row else "medium", fid, ln))
        for _n, val, full in e["name"]:
            if full:
                pairs.append((name, "fqdn", val, full, "paired-row" if row else "paired-line", "high" if row else "medium", fid, ln))
    spread = defaultdict(set)
    for p in pairs:
        if p[1] == "address":
            spread[p[0]].add(p[3])
    out += [p for p in pairs if len(spread[p[0]]) < PAIRING_SPREAD or p[4] == "paired-row"]

    # the register: identity and scope
    rows = []
    for r in register or []:
        h = r["host"].upper()
        rows.append((h, "name", r["host"], h, "register", "high", None, None))
        if r.get("fqdn"):
            rows.append((h, "fqdn", r["fqdn"], r["fqdn"].lower(), "register", "high", None, None))
        for ip in r.get("ips") or []:
            rows.append((h, "address", ip, ip, "register", "high", None, None))
    out += rows

    seen, final = set(), []
    for host, kind, val, norm, basis, conf, fid, ln in out:
        key = (host, kind, norm, basis)
        if key in seen:
            continue
        seen.add(key)
        scope = reg_scope.get(host) or ("system" if host in captured else "external")
        final.append((host, kind, val, norm, scope, basis, conf, fid, ln))
    con.executemany("INSERT INTO aliases(host, kind, value, norm, scope, basis, confidence, file_id, line_no) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", final)
    con.execute("UPDATE aliases SET ambiguous=1 WHERE kind='address' AND norm IN "
                "(SELECT norm FROM aliases WHERE kind='address' GROUP BY norm HAVING COUNT(DISTINCT host)>1)")
    return len(final)
