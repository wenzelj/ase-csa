"""Host-centred view of a project's evidence.

Everything in a CSA is about the system, its applications and the machines it
runs on. Source files are organised however their authors chose (a workbook row
per MECM collection, a sheet per agent, one capture folder per host), and the
source's own row or collection ID must never become the subject. This module
turns the discovery index into three host-keyed files under
``<work_dir>/hosts/``:

* ``hosts.csv``       the host register: one row per machine (name, FQDN, IPs,
                      OU, in scope, system/role/site from ``roles.csv``,
                      capture, sources that name it).
* ``host_facts.csv``  one row per (host, attribute, value) found in any indexed
                      workbook or document row that names the host, plus key
                      capture facts, each with its source file, table and line.
* ``host_links.csv``  host-to-host connections from the captures' established
                      connections, remote addresses resolved to register hosts;
                      kept only where the destination listens on the port (or has
                      no capture, marked as not verified).
* ``evidence_hosts.csv`` evidence_id -> hosts, derived from each matrix row's text
                      (the append-only matrix is not changed).

``roles.csv`` (project data, editable) maps host-name patterns to
system/role/site. Standard library only.

    python3 -m csa_docx.hostmodel build  --work-dir <work_dir>
    python3 -m csa_docx.hostmodel list   --work-dir <work_dir> [--system UTC] [--json]
    python3 -m csa_docx.hostmodel show   --work-dir <work_dir> HOST [--json]
    python3 -m csa_docx.hostmodel links  --work-dir <work_dir> [HOST] [--json]
    python3 -m csa_docx.hostmodel group  --work-dir <work_dir> --attr A [--attr B ...] [--system ...] [--json]
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

DNS_TABLES = ("dns_resolution_validation", "dns_query_tests", "utc_integration_validation", "iccp_target_resolution")
NAME_COLUMNS = ("ComputerName", "DeviceName", "Name", "Host", "MachineName", "Computer", "Hostname")
CAPTURE_FACT_TABLES = {
    "host_summary": ("Caption", "Version", "BuildNumber", "LastBootUpTime"),
    "windows_update_config": ("WUServer", "NoAutoUpdate", "DisableWindowsUpdateAccess"),
    "sccm_mecm_check": ("ClientVersion",),
    "time_status": ("Source",),
}
TOKEN_SPLIT = re.compile(r"[\n,;]+")
SLASH_RE = re.compile(r"^(.*?\D)(\d+)((?:\s*/\s*\d+)+)$")
RANGE_RE = re.compile(r"^(.*?\D)(\d+)\s*-\s*(\d+)$")
NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9-]{2,30}$")


def expand_hosts(text: str) -> list[str]:
    """Split a cell into host tokens, expanding the shorthand used in workbooks:
    'CONTROLLER70 / 73 / 76' and 'VPCOSEW10TCS101 - 108'."""
    out = []
    for part in TOKEN_SPLIT.split(str(text or "")):
        part = part.strip()
        if not part:
            continue
        m = SLASH_RE.match(part)
        if m:
            out += [m[1] + n for n in [m[2]] + re.findall(r"\d+", m[3])]
            continue
        m = RANGE_RE.match(part)
        if m and int(m[3]) >= int(m[2]) and int(m[3]) - int(m[2]) < 500:
            w = len(m[2])
            out += [f"{m[1]}{n:0{w}d}" for n in range(int(m[2]), int(m[3]) + 1)]
            continue
        out.append(part)
    return out


def _value(col: str, val) -> str:
    v = re.sub(r"\s*\n\s*", " ", str(val)).strip()
    if re.search(r"date|time", col, re.I) and re.fullmatch(r"\d{5}(\.\d+)?", v) and 20000 < float(v) < 80000:
        v = (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d %H:%M").replace(" 00:00", "")
    return v[:400]


def _db(work_dir: Path) -> sqlite3.Connection:
    p = work_dir / "discovery-index.sqlite"
    if not p.is_file():
        raise SystemExit(f"no discovery index at {p}; run `csa index build` first")
    return sqlite3.connect(str(p))


def _rows(con, where: str, args=()):
    q = ("select f.rel_path, f.host, r.table_name, r.line_no, r.data from rows r join files f using(file_id) "
         "left join captures c on c.capture_id = f.capture_id "
         f"where f.status='indexed' and (c.superseded_by is null) and ({where})")
    for rel, host, table, line, data in con.execute(q, args):
        try:
            yield rel, host, table, line, json.loads(data)
        except (TypeError, ValueError):
            continue


def _roles(work_dir: Path) -> list[dict]:
    """roles.csv rows: kind (process | name | collection), match, system, role, site, basis, reviewed.

    system_project match = key of another project in PROJECTS.yaml whose application belongs to the
               same system: its hosts name this project's links (in_scope "system: <key>").
    inventory  match = index table name of the project's computer inventory (e.g.
               tcs_computers/tcs_computers); role = its host-name column (default ComputerName).
    listening  match = TCP port the captured host listens on (listening_ports): evidence-based,
               for module ports that identify a role.
    service    match = text in the name or display name of a Windows service running on the host
               (services_inventory): evidence-based.
    process    match = executable name seen running on the host (24_tasklist_services.txt):
               evidence-based, wins over everything else.
    subnet     match = CIDR; a host with an address in it gets that site (evidence-based);
               a host-name site that differs is recorded as a conflict.
    collection match = text in the host's MECM Target Collection name: flags a site
               conflict when it differs from the site given by other rules; never sets it.
    name_source match = regular expression on an indexed file's path whose lines pairing an address
               with one host name are trusted to name that address (design docs, DNS tests).
    name       match = regular expression on the host name: fallback, used only when no
               evidence gives the value, and reported as such."""
    p = work_dir / "hosts" / "roles.csv"
    if not p.is_file():
        return []
    out = []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            kind, match = (r.get("kind") or "").strip().lower(), (r.get("match") or "").strip()
            if kind and match and not kind.startswith("#"):
                out.append({"kind": kind, "match": match, **{k: (r.get(k) or "").strip()
                            for k in ("system", "role", "site", "basis", "reviewed")}})
    return out


def _processes(work_dir: Path, con) -> dict[str, tuple[set, str]]:
    """host -> (lower-case executable names, relative path of the process list) for current captures."""
    root = work_dir.parent
    out = {}
    for host, folder in con.execute("select host, folder from captures where superseded_by is null and archived = 0"):
        p = root / folder / "24_tasklist_services.txt"
        if host and p.is_file():
            exes = {m[1].lower() for m in (re.match(r'^\s*"?([^",\s]+\.exe)', l, re.I)
                                            for l in p.read_text(errors="ignore").splitlines()) if m}
            out[host.upper()] = (exes, f"{folder}/24_tasklist_services.txt")
    return out


def _project_work_dir(key: str) -> Path | None:
    """work_dir of a project in csa-context/PROJECTS.yaml (or $CSA_PROJECTS_FILE)."""
    import os
    reg = Path(os.environ["CSA_PROJECTS_FILE"]) if os.environ.get("CSA_PROJECTS_FILE") \
        else Path(__file__).resolve().parents[2] / "csa-context" / "PROJECTS.yaml"
    if not reg.is_file():
        return None
    cur = {}
    for line in reg.read_text(encoding="utf-8").splitlines() + ["- key: END"]:
        st = line.strip()
        if st.startswith("- key:"):
            if cur.get("key") == key and cur.get("work_dir"):
                return Path(cur["work_dir"])
            cur = {}
            st = st[2:]
        if ":" in st:
            k, _, v = st.partition(":")
            cur[k.strip()] = v.strip().strip('"').strip("'")
    return None


IP_RE = re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])")
FQDN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9-]{2,30})\.(?:[A-Za-z0-9-]+\.){1,5}[A-Za-z]{2,}\b")
HOSTTOK_RE = re.compile(r"\b([A-Z][A-Z0-9-]*\d[A-Z0-9-]*)\b")


def name_addresses(con, ips: set, known: dict, trusted: list | None = None) -> dict:
    """Names for unknown addresses, taken only where the source puts them side by side:
    a text line holding the address and exactly one host name (an FQDN, or an upper-case
    token with a digit) once the line's other addresses' own hosts are set aside.
    Lines from a reviewed name_source file (roles.csv) are taken as they stand and win over
    other sources; elsewhere a name offered for 3+ addresses is treated as the log's writer.
    Returns {ip: {"name", "cite", "conflict"}}. Nothing is guessed from subnets."""
    trusted = [re.compile(t, re.I) for t in (trusted or [])]
    tfound = defaultdict(lambda: defaultdict(set))
    found = defaultdict(lambda: defaultdict(set))
    for ip in ips:
        q = ("select f.rel_path, m.line_start, cc.c0 from chunks_content cc join chunk_map m on m.chunk_id = cc.id "
             "join files f on f.file_id = m.file_id where cc.c0 like ?")
        for rel, start, text in con.execute(q, (f"%{ip}%",)):
            for n, line in enumerate(text.splitlines()):
                if ip not in IP_RE.findall(line):
                    continue
                others = {known.get(x) for x in IP_RE.findall(line) if x != ip}
                names = {m.upper() for m in FQDN_RE.findall(line)}
                if not names:
                    names = {m for m in HOSTTOK_RE.findall(line) if len(m) >= 6 and not re.fullmatch(r"[A-F0-9-]+", m)}
                names -= {o for o in others if o}
                names = {x for x in names if NAME_OK.match(x)}
                if len(names) == 1:
                    name, cite = names.pop(), f"{Path(rel).name} line {(start or 0) + n}"
                    (tfound if any(t.search(rel) for t in trusted) else found)[ip][name].add(cite)
    # a name offered for 3+ different addresses is a log or report source (e.g. the firewall
    # that wrote the line), not the address's host
    spread = Counter(n for cands in found.values() for n in cands)
    out = {}
    for ip, cands in tfound.items():
        name = max(cands, key=lambda k: len(cands[k]))
        out[ip] = {"name": name, "cite": sorted(cands[name])[0], "conflict": sorted(k for k in cands if k != name)}
    for ip, cands in found.items():
        if ip in out:
            continue
        keep = {n: c for n, c in cands.items() if spread[n] < 3 and not n.startswith("IDX-")}
        if len(keep) == 1:
            name, cites = next(iter(keep.items()))
            out[ip] = {"name": name, "cite": sorted(cites)[0], "conflict": []}
        elif keep:
            out[ip] = {"name": None, "ambiguous": sorted(keep)}
    return out


def build(work_dir: Path) -> dict:
    con = _db(work_dir)
    reg: dict[str, dict] = {}

    def entry(name: str) -> dict:
        key = name.strip().upper()
        return reg.setdefault(key, {"host": key, "fqdn": "", "ips": set(), "ou": "", "in_scope": "",
                                    "system": "", "role": "", "site": "", "capture": "", "sources": set(),
                                    "listening": set(), "captured_in": "",
                                    "system_source": "", "role_source": "", "site_source": "", "conflicts": []})

    # 1. register from the project's inventory tables (roles.csv kind=inventory:
    #    match = table name, role = name column; other columns FQDN / IP Addresses / OUPath / In Scope)
    rules = _roles(work_dir)
    for inv in (r for r in rules if r["kind"] == "inventory"):
        col = inv["role"] or "ComputerName"
        for rel, _h, _t, _l, d in _rows(con, "r.table_name = ?", (inv["match"],)):
            name = (d.get(col) or "").strip()
            if not NAME_OK.match(name):
                continue
            e = entry(name)
            e["fqdn"] = e["fqdn"] or (d.get("FQDN") or "")
            e["ips"].update(x.strip().strip("{}") for x in re.split(r"[,;\s]+", str(d.get("IP Addresses") or d.get("IPAddress") or "")) if x.strip().strip("{}"))
            e["ou"] = e["ou"] or (d.get("OUPath") or "")
            e["in_scope"] = e["in_scope"] or (d.get("In Scope") or "")
            e["sources"].add(Path(rel).name)
    # 2. captures
    for host, cap in con.execute("select host, folder from captures where superseded_by is null and archived = 0"):
        if host:
            e = entry(host)
            e["capture"] = Path(cap).name
            e["sources"].add("capture")
    for rel, host, _t, _l, d in _rows(con, "r.table_name = 'ip_route' and f.host is not null"):
        ip = (d.get("IPv4Address") or "").strip().strip("{}")
        if host and ip:
            entry(host)["ips"].add(ip)
    # 2a. a captured host's own addresses also show as LocalAddress on its sessions and listeners
    for t in ("established_connections_raw", "listening_ports"):
        for rel, host, _t, _l, d in _rows(con, "r.table_name = ? and f.host is not null", (t,)):
            ip = str(d.get("LocalAddress") or "").strip()
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and not ip.startswith(("127.", "0.", "169.254.")):
                entry(host)["ips"].add(ip)
    # 2c. peers named with their address in evidence-matrix claims: "NAME (10.1.2.3)", "NAME at 10.1.2.3",
    #     "10.1.2.3 (NAME)", "10.1.2.3 as NAME". Source is the evidence ID.
    mpath = work_dir / "evidence-matrix.csv"
    if mpath.is_file():
        pair = re.compile(r"\b([A-Z][A-Z0-9-]{4,30})\s*(?:\(|at\s+|on\s+|=\s*)(\d+\.\d+\.\d+\.\d+)\b"
                          r"|\b(\d+\.\d+\.\d+\.\d+)\s*(?:\(|\bas\s+)([A-Za-z][A-Za-z0-9-]{4,30})\b")
        with mpath.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("review_state") or "") == "rejected" or r.get("status") not in ("VERIFIED",):
                    continue
                for m in pair.finditer(r.get("claim") or ""):
                    name, ip = (m[1], m[2]) if m[1] else (m[4], m[3])
                    if not re.search(r"\d", name) or ip.startswith(("127.", "0.", "169.254.")):
                        continue       # host names here carry a number; skips words like "SCADA (10.x)"
                    e = entry(name)
                    if not e["capture"] and not e["in_scope"]:
                        e["in_scope"] = "peer"
                    e["ips"].add(ip)
                    e["sources"].add(r["evidence_id"])
    # 2d. hosts of the other applications in the same system (roles.csv kind=system_project,
    #     match = project key in PROJECTS.yaml): read from that project's hosts/hosts.csv
    #     (captured or inventory hosts only, not its peers). Their in_scope is kept as-is for
    #     their own project; here they are marked "system: <key>" so they name links but are
    #     not listed as this project's hosts.
    for sp in (r for r in rules if r["kind"] == "system_project"):
        other = _project_work_dir(sp["match"])
        p2 = other / "hosts" / "hosts.csv" if other else None
        if not p2 or not p2.is_file():
            continue
        with p2.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                scope = (r.get("in_scope") or "").lower()
                if scope.startswith("system:") or (r["host"] in reg and reg[r["host"]]["capture"]):
                    continue
                if scope == "peer":
                    e = entry(r["host"])
                    e["in_scope"] = e["in_scope"] or "peer"
                    e["ips"].update(x for x in r["ips"].split(";") if x)
                    e["sources"].add(f"project {sp['match']} (peer)")
                    continue
                e = entry(r["host"])
                e["in_scope"] = e["in_scope"] or f"system: {sp['match']}"
                e["ips"].update(x for x in r["ips"].split(";") if x)
                e["listening"].update(x for x in (r.get("listening") or "").split(";") if x)
                if r.get("capture") and not r.get("captured_in"):
                    e["captured_in"] = sp["match"]       # captured in the sibling project
                for k in ("system", "role", "site"):
                    if r.get(k) and not e[k]:
                        e[k], e[f"{k}_source"] = r[k], f"project {sp['match']}: {r.get(k + '_source', '')}"
                e["sources"].add(f"project {sp['match']}")
    # 2b. peers: names the captures resolved in DNS tests (not captured, not in the inventory)
    for t in DNS_TABLES:
        for rel, host, _t, _l, d in _rows(con, "r.table_name = ? and f.host is not null", (t,)):
            name, ip = str(d.get("Name") or d.get("Target") or "").strip(), str(d.get("IPAddress") or "").strip()
            short = name.split(".")[0]
            if not NAME_OK.match(short) or short.upper() == "LOCALHOST" or not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                continue
            e = entry(short)
            if not e["capture"] and "capture" not in e["sources"] and not e["in_scope"]:
                e["in_scope"] = "peer"
            e["fqdn"] = e["fqdn"] or (name if "." in name else "")
            e["ips"].add(ip)
            e["sources"].add(f"DNS test on {host}")
    known = set(reg)

    # 3. facts from every non-capture row that names a known host
    facts = []
    for rel, fhost, table, line, d in _rows(con, "f.host is null or f.host = ''"):
        named = {}
        for col, val in d.items():
            toks = [t.upper() for t in expand_hosts(val) if t.upper() in known]
            if toks:
                named[col] = toks
        if not named:
            continue
        hosts = sorted({h for v in named.values() for h in v})
        if len(hosts) > 300:
            continue
        for col, val in d.items():
            if col in named or val in (None, ""):
                continue
            v = _value(col, val)
            for h in hosts:
                facts.append({"host": h, "attribute": f"{table.split('/')[-1]}: {col}", "value": v,
                              "record": f"{Path(rel).name}#{table.split('/')[-1]}#{line}",
                              "listed_as": ";".join(c for c, t in named.items() if h in t),
                              "source": rel, "table": table, "line": line})
        for h in hosts:
            reg[h]["sources"].add(Path(rel).name)
    # 4. key capture facts
    for table, cols in CAPTURE_FACT_TABLES.items():
        for rel, host, t, line, d in _rows(con, "r.table_name = ? and f.host is not null", (table,)):
            for c in cols:
                if d.get(c) not in (None, ""):
                    facts.append({"host": host.upper(), "attribute": f"{table}: {c}", "value": _value(c, d[c]),
                                  "record": f"{Path(rel).parent.name}#{table}#{line}",
                                  "listed_as": "capture", "source": rel, "table": t, "line": line})
    # 5. host-to-host links from established connections
    ip2host = {}
    for h, e in reg.items():
        for ip in e["ips"]:
            ip2host.setdefault(ip, h)
    unknown = set()
    for rel, host, t, line, d in _rows(con, "r.table_name = 'established_connections_raw' and f.host is not null"):
        ra = str(d.get("RemoteAddress") or "").strip()
        if IP_RE.fullmatch(ra) and ra not in ip2host and not ra.startswith(("127.", "0.", "169.254.")):
            unknown.add(ra)
    ambiguous = {}
    for ip, hit in name_addresses(con, unknown, ip2host,
            [r["match"] for r in _roles(work_dir) if r["kind"] == "name_source" and r["reviewed"].lower() == "yes"]).items():
        if not hit.get("name"):
            ambiguous[ip] = hit["ambiguous"]
            continue
        e = entry(hit["name"])
        if not e["in_scope"] and not e["capture"]:
            e["in_scope"] = "peer"
        e["ips"].add(ip)
        e["sources"].add(f"address {ip} named in {hit['cite']}")
        if hit["conflict"]:
            e["conflicts"].append(f"name: {ip} is also named {', '.join(hit['conflict'][:3])} elsewhere")
        ip2host.setdefault(ip, hit["name"])
    listening = defaultdict(set)
    for rel, host, t, line, d in _rows(con, "r.table_name = 'listening_ports' and f.host is not null"):
        if d.get("LocalPort"):
            listening[host.upper()].add(str(d["LocalPort"]).strip())
    for h, ports in listening.items():
        if h in reg:
            reg[h]["listening"] |= ports
    for h, e in reg.items():
        if e["captured_in"] and not e["capture"]:
            listening[h] |= e["listening"]           # ports proven by the sibling project's capture
    captured = {h for h, e in reg.items() if e["capture"]}
    elsewhere = {h: e["captured_in"] for h, e in reg.items() if e["captured_in"] and not e["capture"]}
    links = Counter()
    lsrc = {}
    served = set()
    for rel, host, t, line, d in _rows(con, "r.table_name = 'established_connections_raw' and f.host is not null"):
        ra, rp = (d.get("RemoteAddress") or "").strip(), (d.get("RemotePort") or "").strip()
        try:
            if ipaddress.ip_address(ra).is_loopback:
                continue
        except ValueError:
            continue
        dst = ip2host.get(ra)
        lp = str(d.get("LocalPort") or "").strip()
        if dst and dst != host.upper():
            if lp and lp in listening[host.upper()] and dst not in captured:
                # incoming session: the captured host is the server; record client -> server
                k = (dst, host.upper(), lp)
                links[k] += 1
                lsrc.setdefault(k, f"{rel} line {line}")
                served.add(k)
                continue
            if (dst in captured or dst in elsewhere) and rp not in listening[dst]:
                continue                     # the other end of a session seen from the server side
            k = (host.upper(), dst, rp)
            links[k] += 1
            lsrc.setdefault(k, f"{rel} line {line}")
    # 6. classification: evidence first (running module), then host-name patterns as an unreviewed
    #    fallback; MECM collection names only flag site conflicts. Every value says where it came from.
    procs = _processes(work_dir, con)
    colls = defaultdict(set)
    for f in facts:
        if f["attribute"].endswith("Target Collection"):
            colls[f["host"]].add(f["value"])
    running = defaultdict(set)
    for rel, host, t, line, d in _rows(con, "r.table_name = 'services_inventory' and f.host is not null"):
        if str(d.get("State") or "").lower() == "running":
            running[host.upper()].add((str(d.get("Name") or "") + " | " + str(d.get("DisplayName") or "")).lower())
    for h, e in reg.items():
        for r in (r for r in rules if r["kind"] == "listening"):
            if r["match"] in e["listening"] and e["capture"]:
                for k in ("system", "role"):
                    if r[k] and not e[k]:
                        e[k], e[f"{k}_source"] = r[k], f"evidence: listens on TCP/{r['match']} (listening_ports)"
        for r in (r for r in rules if r["kind"] == "service"):
            if any(r["match"].lower() in sv for sv in running.get(h, ())):
                for k in ("system", "role"):
                    if r[k] and not e[k]:
                        e[k], e[f"{k}_source"] = r[k], f"evidence: service '{r['match']}' running (services_inventory)"
    for h, e in reg.items():
        exes, plist = procs.get(h, (set(), ""))
        for r in (r for r in rules if r["kind"] == "process"):
            if r["match"].lower() in exes:
                for k in ("system", "role"):
                    if r[k] and not e[k]:
                        e[k], e[f"{k}_source"] = r[k], f"evidence: {r['match']} running ({plist})"
        nets = set()
        for r in (r for r in rules if r["kind"] == "subnet" and r["site"]):
            try:
                net = ipaddress.ip_network(r["match"], strict=False)
            except ValueError:
                continue
            for ip in e["ips"]:
                try:
                    if ipaddress.ip_address(ip.strip("{} ")) in net:
                        nets.add((r["site"], r["match"]))
                except ValueError:
                    pass
        if len({n[0] for n in nets}) == 1:
            site, cidr = sorted(nets)[0]
            e["site"], e["site_source"] = site, f"evidence: address on {cidr}"
        elif nets:
            e["conflicts"].append("site: addresses on " + ", ".join(f"{c} ({s})" for s, c in sorted(nets)))
        for r in (r for r in rules if r["kind"] == "name"):
            if re.search(r["match"], h, re.I):
                if r["site"] and e["site"] and e["site"] != r["site"] and e["site_source"].startswith("evidence"):
                    e["conflicts"].append(f"site: {e['site_source'].split(' (')[0]} gives {e['site']}, host name says {r['site']}")
                tag = f"name pattern {r['match']}" + ("" if r["reviewed"].lower() in ("yes", "y") else " (unreviewed)")
                for k in ("system", "role", "site"):
                    if k == "role" and r[k] and e[k] and r[k] != e[k] and r[k].startswith(e[k]) \
                            and e["role_source"].startswith("evidence"):
                        # the host name only adds a qualifier (e.g. "(UAT)") to an evidence-based role
                        e[k], e["role_source"] = r[k], e["role_source"] + f"; qualifier from {tag}"
                        continue
                    if not r[k] or e[k]:
                        continue
                    if k == "role" and (h in procs or h in running) and any(
                            x["kind"] in ("process", "service", "listening") and x["system"] == r["system"] for x in rules):
                        continue      # the host's own process list does not show the module: role stays unknown
                    e[k], e[f"{k}_source"] = r[k], tag
        # MECM collection names flag a site conflict; they are not site evidence
        csites = {r["site"] for r in rules if r["kind"] == "collection" and r["site"]
                  for c in colls[h] if r["match"].lower() in c.lower()}
        for cs in sorted(csites):
            if e["site"] and cs != e["site"]:
                e["conflicts"].append(f"site: MECM collection name suggests {cs}, "
                                      f"{e['site_source'].split(' (')[0]} says {e['site']}")
        if h in procs and not e["role_source"].startswith("evidence"):
            e["conflicts"].append("role: process list captured but no known module running")

    out = work_dir / "hosts"
    out.mkdir(exist_ok=True)
    with (out / "hosts.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "in_scope", "system", "role", "site", "system_source", "role_source", "site_source",
                    "conflicts", "fqdn", "ips", "ou", "capture", "captured_in", "listening", "sources"])
        for h in sorted(reg):
            e = reg[h]
            w.writerow([h, e["in_scope"], e["system"], e["role"], e["site"], e["system_source"], e["role_source"],
                        e["site_source"], " | ".join(e["conflicts"]), e["fqdn"], ";".join(sorted(e["ips"])),
                        e["ou"], e["capture"], e["captured_in"],
                        ";".join(sorted(e["listening"], key=lambda x: int(x) if x.isdigit() else 0)),
                        ";".join(sorted(e["sources"]))])
    with (out / "host_facts.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["host", "attribute", "value", "record", "listed_as", "source", "table", "line"])
        w.writeheader()
        seen = set()
        for f in sorted(facts, key=lambda x: (x["host"], x["attribute"], x["value"])):
            k = (f["host"], f["attribute"], f["value"])   # copies of one workbook in several folders
            if k not in seen:          # the same workbook exists in two folders
                seen.add(k)
                w.writerow(f)
    with (out / "host_links.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["src_host", "dst_host", "dst_port", "connections", "basis", "source"])
        for (s, d_, p), n in sorted(links.items()):
            basis = ("dst listens on port" if d_ in captured else
                     f"dst listens on port (captured in project {elsewhere[d_]})" if d_ in elsewhere else
                     "dst listens on port (seen from the server's capture)" if (s, d_, p) in served else
                     "dst not captured; port not verified")
            w.writerow([s, d_, p, n, basis, lsrc[(s, d_, p)]])
    ev = link_evidence(work_dir, set(reg))
    return {"status": "OK", "hosts": len(reg), "with_capture": sum(1 for e in reg.values() if e["capture"]),
            "facts": len(seen), "links": len(links), "unclassified": sum(1 for e in reg.values() if not e["system"]),
            "role_from_evidence": sum(1 for e in reg.values() if e["role_source"].startswith("evidence")),
            "role_from_name_only": sum(1 for e in reg.values() if e["role"] and not e["role_source"].startswith("evidence")),
            "conflicts": {h: e["conflicts"] for h, e in reg.items() if e["conflicts"]},
            "evidence_rows": ev["rows"], "evidence_without_host": ev["without_host"],
            "addresses_named": sum(1 for e in reg.values() if any(x.startswith("address ") for x in e["sources"])),
            "addresses_ambiguous": ambiguous,
            "out": str(out)}


def link_evidence(work_dir: Path, known: set[str]) -> dict:
    """Derived link table evidence_id -> hosts, read from each matrix row's text (shorthand
    expanded). The matrix itself is append-only and is not changed. A row naming no register
    host is subject_type 'system' (system-wide or not yet host-attributed)."""
    m = work_dir / "evidence-matrix.csv"
    out, none = [], 0
    if m.is_file():
        with m.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                text = " ".join(r.get(k) or "" for k in ("claim", "evidence_excerpt", "page_or_location", "question"))
                toks = set()
                for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,30}(?:\s*/\s*\d+)*(?:\s*-\s*\d+)?", text):
                    toks.update(t.upper() for t in expand_hosts(w))
                hosts = sorted(toks & known)
                none += not hosts
                out.append({"evidence_id": r["evidence_id"], "subject_type": "host" if hosts else "system",
                            "hosts": ";".join(hosts), "status": r.get("status", ""),
                            "review_state": r.get("review_state", ""), "question": (r.get("question") or "")[:160]})
    (work_dir / "hosts").mkdir(exist_ok=True)
    with (work_dir / "hosts" / "evidence_hosts.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["evidence_id", "subject_type", "hosts", "status", "review_state", "question"])
        w.writeheader()
        w.writerows(out)
    return {"rows": len(out), "without_host": none}


def _read(work_dir: Path, name: str) -> list[dict]:
    p = work_dir / "hosts" / name
    if not p.is_file():
        raise SystemExit(f"{p} missing; run `csa hosts build` first")
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def show(work_dir: Path, host: str) -> dict:
    h = host.strip().upper()
    reg = [r for r in _read(work_dir, "hosts.csv") if r["host"] == h]
    if not reg:
        return {"status": "NOT_FOUND", "host": h}
    facts = [f for f in _read(work_dir, "host_facts.csv") if f["host"] == h]
    links = [l for l in _read(work_dir, "host_links.csv") if h in (l["src_host"], l["dst_host"])]
    ev = [e for e in _read(work_dir, "evidence_hosts.csv") if h in e["hosts"].split(";")]
    return {"status": "OK", "host": reg[0], "evidence": ev, "links": links, "facts": facts}


def _attr_match(want: str, attribute: str) -> bool:
    """`want` names a source column (e.g. "Software Update Group"); a host_facts attribute is
    "<sheet or table>: <column>". Compare with the column only, so a sheet called
    "software update groups" does not make every one of its columns match."""
    col = attribute.split(": ", 1)[-1]
    return want.strip().lower() == col.strip().lower()


def _in_scope(r: dict) -> bool:
    """In scope unless the inventory says No, or the host is only a peer named in a DNS test
    (captured hosts missing from the inventory stay in)."""
    v = (r.get("in_scope") or "").strip().lower()
    return v not in ("no", "peer") and not v.startswith("system:")


def group(work_dir: Path, attrs: list[str], system: str | None = None, all_hosts: bool = False) -> list[dict]:
    """Group hosts that share the same values for the given source columns (exact column name). The unit of the result is a set of hosts, never a source row."""
    reg = {r["host"]: r for r in _read(work_dir, "hosts.csv")}
    vals = defaultdict(lambda: defaultdict(set))
    for f in _read(work_dir, "host_facts.csv"):
        for a in attrs:
            if _attr_match(a, f["attribute"]):
                vals[f["host"]][a].add(f["value"])
    groups = defaultdict(list)
    for h, r in reg.items():
        if system and r["system"].lower() != system.lower():
            continue
        if not all_hosts and not _in_scope(r):
            continue
        key = tuple(" / ".join(sorted(vals[h][a])) or "not recorded" for a in attrs)
        groups[key].append(h)
    return [{"hosts": sorted(v), **dict(zip(attrs, k))} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix" / "scripts"


def _script(name: str, workspace: Path, *args, payload=None) -> dict:
    import subprocess
    cmd = [sys.executable, str(SCRIPTS / name), "--workspace", str(workspace), *args]
    if payload is not None:
        cmd += ["--rows-file", "-"]
    r = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise SystemExit(f"{name} {' '.join(args)} failed:\n{r.stdout[-800:]}{r.stderr[-800:]}")
    if out.get("status") == "ERROR":
        raise SystemExit(f"{name} {' '.join(args)} refused: {json.dumps(out)[:1500]}")
    return out


def to_graph(work_dir: Path, workspace: Path, domain: str = "3.6 Network / Segmentation", dry_run: bool = False,
             all_hosts: bool = False, fix: bool = False) -> dict:
    """Put the verified host-to-host links into the evidence matrix and the graph store.

    One evidence row per source host (the sessions its capture shows, destinations that
    listen on the port), one host node per host (an existing node whose label starts with
    the host name is reused), one data-flow edge per (source, destination). Re-running adds
    only what is missing. Links to hosts without a capture are left out: their port is not
    verified."""
    reg = {r["host"]: r for r in _read(work_dir, "hosts.csv")}
    scope = {h for h, r in reg.items() if all_hosts or _in_scope(r)
             or (r.get("in_scope") or "").lower().startswith("system:")}   # same system, other application
    links = [l for l in _read(work_dir, "host_links.csv") if l["basis"].startswith("dst listens")
             and l["src_host"] in scope and l["dst_host"] in scope]
    by_src = defaultdict(list)
    for l in links:
        by_src[l["src_host"]].append(l)
    def desc(h):
        r = reg.get(h, {})
        role = r.get("role") if (r.get("role_source") or "").startswith("evidence") else ""
        site = r.get("site") if (r.get("site_source") or "").startswith("evidence") else ""
        return ", ".join(x for x in (role, site) if x)
    label = lambda h: f"{h} ({desc(h)})" if desc(h) else h

    # 1. evidence rows. An edge may only cite a row whose claim names its destination, so a
    #    source host gets a further row when later-verified links are not in its earlier rows.
    matrix = work_dir / "evidence-matrix.csv"
    claims = defaultdict(list)            # src -> [(evidence_id, claim)]
    qpat = re.compile(r"^Which captured hosts does (\S+) hold established sessions to\?")
    with matrix.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            m = qpat.match(r.get("question") or "")
            if m and (r.get("review_state") or "") != "rejected":
                claims[m[1]].append((r["evidence_id"], r.get("claim") or ""))
    def cover(src, dst):
        return next((e for e, c in claims[src] if re.search(rf"\b{re.escape(dst)}\b on TCP/", c)), None)
    rows = []
    for src, ls in sorted(by_src.items()):
        new = [l for l in ls if not cover(src, l["dst_host"])]
        if not new:
            continue
        parts = sorted({f"{l['dst_host']} on TCP/{l['dst_port']}" for l in new})
        cap = Path(new[0]["source"].split(" line ")[0]).parent.name
        q = f"Which captured hosts does {src} hold established sessions to?" + ("" if not claims[src] else " (further verified links)")
        rows.append({"csa_area": "network_and_connectivity", "question": q,
                     "claim": f"{src} holds established sessions to {', '.join(parts)}; each destination listens on that port "
                              f"({'; '.join(sorted({l['basis'].replace('dst listens on port', '').strip(' ()') or 'own capture' for l in new}))}).",
                     "status": "VERIFIED", "source_title": "21_established_connections_raw.txt; 20_listening_ports.txt",
                     "source_version": cap, "section": "established connections", "page_or_location": new[0]["source"],
                     "evidence_excerpt": "; ".join(f"{l['dst_host']}:{l['dst_port']} ({l['source'].split('/')[-1]})" for l in new)[:1200],
                     "confidence": "high", "gap_or_action": "Sessions at capture time only; not a full flow record."})
    res = {"evidence_new": len(rows)}
    if rows:
        out = _script("evidence_matrix.py", workspace, "append", "--agent", "csa-hosts", "--context", "csa hosts graph",
                      *(["--dry-run"] if dry_run else []), payload=rows)
        written = out.get("written") or out.get("would_write") or out.get("appended") or []
        for row, w in zip(rows, written):
            src = row["question"].split(" does ")[1].split(" hold")[0]
            claims[src].append((w.get("evidence_id"), row["claim"]))
    ev_of = {src: [e for e, _ in claims[src]] for src in claims}
    # 2. nodes
    gdir = work_dir / "graph"
    nodes = list(csv.DictReader((gdir / "nodes.csv").open(encoding="utf-8-sig"))) if (gdir / "nodes.csv").is_file() else []
    gstate = {}
    if (gdir / "graph-reviews.jsonl").is_file():
        for ln in (gdir / "graph-reviews.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln); gstate[r["id"]] = r["state"]
            except (ValueError, KeyError):
                pass
    gone = {n["node_id"] for n in nodes if gstate.get(n["node_id"]) == "rejected"}
    nodes = [n for n in nodes if n["node_id"] not in gone]
    node_of = {}
    for n in nodes:
        first = re.split(r"[\s(]", n["label"].strip(), 1)[0].upper()
        if n["node_type"] == "host" and first in reg:
            node_of.setdefault(first, n["node_id"])
    need = sorted({h for l in links for h in (l["src_host"], l["dst_host"])} - set(node_of))
    new_nodes = [{"domain": domain, "label": label(h), "node_type": "host", "purdue_level": "n/a",
                  "zone": "OT" if reg.get(h, {}).get("system") else "",
                  "evidence_ids": ";".join(sorted({cover(l["src_host"], l["dst_host"]) for l in links
                                                   if h in (l["src_host"], l["dst_host"]) and cover(l["src_host"], l["dst_host"])})),
                  "confidence": "high"} for h in need]
    new_nodes = [n for n in new_nodes if n["evidence_ids"]]
    res["nodes_new"] = len(new_nodes)
    if new_nodes and not dry_run:
        out = _script("graph_store.py", workspace, "append-node", "--agent", "csa-hosts", "--context", "csa hosts graph", payload=new_nodes)
        for n, w in zip(new_nodes, out.get("written") or out.get("appended") or []):
            node_of[re.split(r"[\s(]", n["label"], 1)[0]] = w["node_id"]
    # 3. edges
    edges = [e for e in (list(csv.DictReader((gdir / "edges.csv").open(encoding="utf-8-sig"))) if (gdir / "edges.csv").is_file() else [])
             if gstate.get(e["edge_id"]) != "rejected" and e["source_node_id"] not in gone and e["target_node_id"] not in gone]
    have_e = {(e["source_node_id"], e["target_node_id"], e["relationship_type"]) for e in edges}
    pairs = defaultdict(set)
    for l in links:
        pairs[(l["src_host"], l["dst_host"])].add(l["dst_port"])
    new_edges = []
    for (s_, d_), ports in sorted(pairs.items()):
        a, b = node_of.get(s_), node_of.get(d_)
        e_id = cover(s_, d_)
        if a and b and (a, b, "data-flow") not in have_e and e_id:
            new_edges.append({"domain": domain, "source_node_id": a, "target_node_id": b, "relationship_type": "data-flow",
                              "evidence_ids": e_id, "confidence": "high"})
    res["edges_new"] = len(new_edges)
    label_of = {v: k for k, v in node_of.items()}
    ev_text = {e: c for src in claims for e, c in claims[src]}
    audit = work_dir / "graph-audit.jsonl"
    ours = set()
    if audit.is_file():
        for ln in audit.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(ln)
            except ValueError:
                continue
            if a.get("agent") == "csa-hosts":
                ours.update(a.get("ids") or [])
    res["nodes_with_stale_label"] = [n["node_id"] for n in nodes if n["node_id"] in ours and label_of.get(n["node_id"])
                                     and n["label"] != label(label_of[n["node_id"]])]
    # only hosts the inventory marks In Scope: No; evidence-named peers and hosts of sibling
    # applications (IAMPS, OTIS, TOS ...) are valid endpoints on this project's diagrams
    excluded = {h for h, r in reg.items() if (r.get("in_scope") or "").strip().lower() == "no"}
    res["nodes_out_of_scope"] = [n["node_id"] for n in nodes if label_of.get(n["node_id"])
                                 and label_of[n["node_id"]] in excluded]
    res["edges_citing_wrong_evidence"] = [
        e["edge_id"] for e in edges if e["relationship_type"] == "data-flow"
        and label_of.get(e["target_node_id"]) and all(
            not re.search(rf"\b{re.escape(label_of[e['target_node_id']])}\b", ev_text.get(x, label_of[e["target_node_id"]]))
            for x in e["evidence_ids"].split(";") if x)]
    if new_edges and not dry_run:
        _script("graph_store.py", workspace, "append-edge", "--agent", "csa-hosts", "--context", "csa hosts graph", payload=new_edges)
    bad_e = [e for e in res["edges_citing_wrong_evidence"] if e in ours]
    bad_n = [n for n in res["nodes_with_stale_label"] + res["nodes_out_of_scope"] if n in ours]
    if fix and not dry_run and (bad_e or bad_n):
        for ids, why in ((bad_n, "label or scope no longer matches the host register (csa hosts)"),
                         (bad_e, "cited evidence does not name the destination host")):
            if ids:
                _script("graph_store.py", workspace, "review", *sorted(set(ids)), "--state", "rejected",
                        "--by", "csa hosts graph --fix", "--note", why)
        again = to_graph(work_dir, workspace, domain, dry_run=False, all_hosts=all_hosts, fix=False)
        res["fixed"] = {"rejected_nodes": sorted(set(bad_n)), "rejected_edges": sorted(set(bad_e)),
                        "re_added": {k: again[k] for k in ("evidence_new", "nodes_new", "edges_new")},
                        "left": {k: again[k] for k in ("nodes_with_stale_label", "nodes_out_of_scope",
                                                        "edges_citing_wrong_evidence")}}
    res["status"] = "DRY_RUN" if dry_run else "OK"
    return res


def unresolved(work_dir: Path, top: int = 40) -> list[dict]:
    """Remote endpoints in the captures' sessions whose address is not any register host's:
    the peers still to be named from evidence (e.g. a matrix row 'NAME (address)')."""
    con = _db(work_dir)
    known = {ip for r in _read(work_dir, "hosts.csv") for ip in r["ips"].split(";") if ip}
    seen = defaultdict(lambda: {"ports": set(), "from": set(), "sessions": 0})
    for rel, host, t, line, d in _rows(con, "r.table_name = 'established_connections_raw' and f.host is not null"):
        ra = str(d.get("RemoteAddress") or "").strip()
        if not ra or ra in known or ":" in ra or ra.startswith(("127.", "0.", "169.254.")):
            continue
        s = seen[ra]
        s["ports"].add(str(d.get("RemotePort"))); s["from"].add(host.upper()); s["sessions"] += 1
    out = [{"address": a, "sessions": v["sessions"], "ports": ";".join(sorted(v["ports"], key=lambda x: int(x) if x.isdigit() else 0)[:8]),
            "from_hosts": ";".join(sorted(v["from"]))} for a, v in seen.items()]
    return sorted(out, key=lambda x: -x["sessions"])[:top]


def system_layer(work_dir: Path, name: str, own_key: str) -> dict:
    """Merge this project's and its sibling projects' (roles.csv kind=system_project) host
    registers and links into .agents/csa-context/systems/<name>/: one view of the whole system,
    every row tagged with the project whose evidence it came from. Derived; rebuilt each run."""
    members = [(own_key, work_dir)] + [(r["match"], _project_work_dir(r["match"]))
                                       for r in _roles(work_dir) if r["kind"] == "system_project"]
    out = Path(__file__).resolve().parents[2] / "csa-context" / "systems" / name
    out.mkdir(parents=True, exist_ok=True)
    hosts, links = {}, {}
    for key, wd in members:
        if not wd or not (wd / "hosts" / "hosts.csv").is_file():
            continue
        for r in _read(wd, "hosts.csv"):
            if (r["in_scope"] or "").lower().startswith("system:") or r["in_scope"] == "peer":
                continue                            # each host comes from the project that owns it
            cur = hosts.get(r["host"])
            if cur is None or (r["capture"] and not cur["capture"]):
                hosts[r["host"]] = {**r, "project": key}
        for l in _read(wd, "host_links.csv"):
            k = (l["src_host"], l["dst_host"], l["dst_port"])
            if k not in links or (links[k]["basis"].startswith("dst not") and not l["basis"].startswith("dst not")):
                links[k] = {**l, "project": key}
    with (out / "hosts.csv").open("w", encoding="utf-8", newline="") as fh:
        cols = ["host", "project", "in_scope", "system", "role", "site", "role_source", "site_source", "ips",
                "capture", "listening"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(hosts[h] for h in sorted(hosts))
    with (out / "host_links.csv").open("w", encoding="utf-8", newline="") as fh:
        cols = ["src_host", "dst_host", "dst_port", "connections", "basis", "project", "source"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(links[k] for k in sorted(links))
    cross = [l for l in links.values() if hosts.get(l["src_host"], {}).get("project") != hosts.get(l["dst_host"], {}).get("project")
             and l["src_host"] in hosts and l["dst_host"] in hosts]
    return {"status": "OK", "system": name, "members": [k for k, _ in members], "hosts": len(hosts),
            "links": len(links), "cross_application_links": len(cross), "out": str(out)}


def group_evidence(work_dir: Path, workspace: Path, attrs: list[str], system: str | None = None,
                   question: str = "", dry_run: bool = False) -> dict:
    """One evidence row per group of in-scope hosts that share the same values for `attrs`
    (substring match on host_facts attributes). The claim is about the hosts; the source's own
    row or collection keys appear only in page_or_location, with every file and line cited."""
    facts = _read(work_dir, "host_facts.csv")
    groups = group(work_dir, attrs, system)
    cite = defaultdict(set)
    for f in facts:
        if any(_attr_match(a, f["attribute"]) for a in attrs):
            cite[f["host"]].add(f"{Path(f['source']).name} {f['table'].split('/')[-1]} line {f['line']}")
    rows = []
    for g in groups:
        if all(g[a] == "not recorded" for a in attrs):
            continue
        hosts = g["hosts"]
        values = "; ".join(f"{a}: {g[a]}" for a in attrs)
        where = sorted(set().union(*[cite[h] for h in hosts]))
        rows.append({"csa_area": "infrastructure_and_hosting",
                     "question": question or f"Which {', '.join(attrs)} apply to which hosts?",
                     "claim": f"{', '.join(hosts)} share {values}."[:1500],
                     "status": "VERIFIED", "source_title": "; ".join(sorted({w.split(' ')[0] for w in where}))[:300],
                     "source_version": "", "section": ", ".join(attrs)[:200],
                     "page_or_location": "; ".join(where)[:1400],
                     "evidence_excerpt": values[:1200], "confidence": "medium",
                     "gap_or_action": "Grouped by host from the source rows (csa hosts evidence)."})
    if not rows:
        return {"status": "NOTHING", "groups": 0}
    out = _script("evidence_matrix.py", workspace, "append", "--agent", "csa-hosts", "--context",
                  "csa hosts evidence: " + ", ".join(attrs), *(["--dry-run"] if dry_run else []), payload=rows)
    written = out.get("written") or out.get("would_write") or []
    return {"status": "DRY_RUN" if dry_run else "OK", "rows": [
        {"evidence_id": w.get("evidence_id"), "hosts": len(r["claim"].split(" share ")[0].split(", ")),
         "claim": r["claim"][:160]} for r, w in zip(rows, written)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="csa hosts", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["build", "list", "show", "links", "group", "graph", "unresolved", "system", "evidence"])
    ap.add_argument("--question", default="")
    ap.add_argument("--name", default="system", help="system layer name (system command)")
    ap.add_argument("--project-key", default="")
    ap.add_argument("--workspace", help="project root (graph: where the matrix and graph store live)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fix", action="store_true", help="graph: reject stale/out-of-scope/mis-cited items csa hosts created, then re-add them")
    ap.add_argument("host", nargs="?")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--system")
    ap.add_argument("--attr", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="include hosts the inventory marks In Scope: No")
    a = ap.parse_args(argv)
    wd = Path(a.work_dir)
    if a.cmd == "build":
        res = build(wd)
    elif a.cmd == "evidence":
        if not a.attr:
            ap.error("evidence needs at least one --attr")
        res = group_evidence(wd, Path(a.workspace or wd.parent), a.attr, a.system, a.question, a.dry_run)
    elif a.cmd == "system":
        res = system_layer(wd, a.name, a.project_key or wd.parent.name)
    elif a.cmd == "unresolved":
        res = unresolved(wd)
    elif a.cmd == "graph":
        res = to_graph(wd, Path(a.workspace or wd.parent), dry_run=a.dry_run, all_hosts=a.all, fix=a.fix)
    elif a.cmd == "list":
        res = [r for r in _read(wd, "hosts.csv") if (not a.system or r["system"].lower() == a.system.lower())
               and (a.all or _in_scope(r))]
    elif a.cmd == "show":
        if not a.host:
            ap.error("show needs HOST")
        res = show(wd, a.host)
    elif a.cmd == "links":
        scope = {r["host"] for r in _read(wd, "hosts.csv") if a.all or _in_scope(r)}
        res = [l for l in _read(wd, "host_links.csv") if (not a.host or a.host.upper() in (l["src_host"], l["dst_host"]))
               and (a.host or (l["src_host"] in scope and l["dst_host"] in scope))]
    else:
        if not a.attr:
            ap.error("group needs at least one --attr")
        res = group(wd, a.attr, a.system, a.all)
    if a.json or a.cmd in ("build", "show", "group", "graph", "system", "evidence"):
        print(json.dumps(res, indent=1, default=list))
    else:
        for r in res:
            print("  ".join(f"{v}" for v in r.values()))
    return 0 if not (isinstance(res, dict) and res.get("status") == "NOT_FOUND") else 1


if __name__ == "__main__":
    sys.exit(main())
