#!/usr/bin/env python3
"""Host-outward evidence profiling for CSA projects (stdlib only, Python 3.8+).

Start from one known host and look outwards: what it is, what it runs, what it
listens on, who connects to it (inbound) and what it connects to (outbound).
Every link comes from the host's own capture files, never from prior knowledge.

  python3 host_profile.py --workspace <project_root> list
  python3 host_profile.py --workspace <project_root> profile ROTPRDLOG102 [--json]
  python3 host_profile.py --workspace <project_root> profile --all
  python3 host_profile.py --workspace <project_root> record ROTPRDLOG102 --agent <name> [--dry-run]
  python3 host_profile.py --workspace <project_root> record --all --agent <name>

profile  writes csa-work/hosts/cards/<HOST>.md (the host's full picture) and prints it.
record   appends VERIFIED matrix rows (one per role fact and one per peer link, each quoting
         the exact capture line) through evidence_matrix.py, then the host and peer nodes
         and the link edges through graph_store.py. Re-running is safe: duplicates are skipped.

Direction rule: a connection whose local port is one the host listens on is INBOUND
(the peer is a client of this host); any other connection is OUTBOUND.
Peer names come only from captured name resolution (hosts/hosts.csv, 48A, 41, 03 time
status); an address with no captured name stays an address and is listed as unresolved.
"""
import argparse, csv, json, os, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
AGENTS = HERE.parents[3]                       # .../.agents
EM = AGENTS / "skills/csa-evidence-matrix/scripts/evidence_matrix.py"
GS = AGENTS / "skills/csa-evidence-matrix/scripts/graph_store.py"
PROJECTS = AGENTS / "csa-context/PROJECTS.yaml"
CAP_RE = re.compile(r"^(?P<prefix>[A-Z0-9]+)_discovery_(?P<host>[A-Z0-9-]+)_(?P<ts>\d{8}T\d{6}Z)$")
CONN_RE = re.compile(r"^\s*(\S+):(\d+)\s*->\s*(\S+):(\d+)\s+PID=(\d+)\s+PROC=(\S+)")
NETSTAT_RE = re.compile(r"^\s*TCP\s+(\S+):(\d+)\s+(\S+):(\d+)\s+(\S+)\s+(\d+)")
LISTEN_RE = re.compile(r"^\s*(\d+)\s+PID=(\d+)\s+(\S+)")


def fail(msg, **kw):
    print(json.dumps({"status": "ERROR", "error": msg, **kw}, indent=2)); sys.exit(2)


def project_for(workspace):
    """Return (key, project_root, source_set) from PROJECTS.yaml for this workspace."""
    if not PROJECTS.is_file():
        fail("PROJECTS.yaml not found")
    text = PROJECTS.read_text(encoding="utf-8")
    ws = Path(workspace).resolve()
    for block in re.split(r"\n\s*- key:\s*", text)[1:]:
        key = block.split("\n", 1)[0].strip()
        def val(name):
            m = re.search(rf"^\s*{name}:\s*\"?([^\"\n]+)\"?", block, re.M)
            return m.group(1).strip() if m else ""
        root = val("project_root")
        # the registry holds macOS paths; match on the trailing folder names
        if root and (Path(root).name == ws.name and Path(root).parent.name == ws.parent.name):
            src = val("default_source_set")
            rel = os.path.relpath(src, root) if src else ""
            return key, ws, (ws / rel).resolve() if rel else None
    fail("WORKSPACE_NOT_REGISTERED", workspace=str(ws))


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []


def captures(source_set):
    """Latest capture directory per host (a capture must hold a listener or connection file)."""
    best = {}
    for root, dirs, files in os.walk(source_set):
        m = CAP_RE.match(Path(root).name)
        if not m or not ({"10_listeners_by_process.txt", "23_process_connection_mapping.txt"} & set(files)):
            continue
        h = m["host"]
        if h not in best or m["ts"] > best[h][0]:
            best[h] = (m["ts"], Path(root))
    return {h: v[1] for h, v in best.items()}


def is_local(ip):
    """Loopback, unspecified and IPv6 link-local (cluster heartbeat) addresses are not peers."""
    return ip.startswith(("127.", "::1", "0.0.0.0", "[::", "::", "fe80:", "[fe80:")) or ip in ("*", "::")


def name_map(ws, caps):
    """address -> (name, basis). Only names a capture or the host register records."""
    names = {}
    reg = ws / "csa-work/hosts/hosts.csv"
    if reg.is_file():
        for r in csv.DictReader(open(reg, encoding="utf-8-sig")):
            for ip in (r.get("ips") or "").split(";"):
                ip = ip.strip()
                if ip and not ip.endswith(".0") and not ip.startswith("169.254."):
                    names.setdefault(ip, (r["host"], "hosts/hosts.csv"))
    for h, d in caps.items():
        for line in read(d / "12_ip_interface_config.txt"):
            m = re.match(r"\s*IPAddress\s*:\s*(\d+\.\d+\.\d+\.\d+)", line)
            if m and not is_local(m[1]) and not m[1].startswith("169.254."):
                names[m[1]] = (h, f"{d.name}/12_ip_interface_config.txt")
        for fn in ("48A_reveloc_known_host_ip_map.txt", "41_dns_query_tests.txt", "48_dns_resolution_validation.txt"):
            for line in read(d / fn):
                m = re.match(r"\s*([A-Za-z][\w.-]+)\s+A\s+(\d+\.\d+\.\d+\.\d+)\s*$", line) or \
                    re.match(r"\s*([A-Za-z][\w.-]+)\s+(\d+\.\d+\.\d+\.\d+)\s+A\s*$", line)
                # skip localhost and the domain name itself (it resolves to every domain controller)
                if m and m[1].lower() != "localhost" and not re.match(r"^[a-z]+\.[a-z]+\.[a-z]+\.[a-z]+$", m[1].lower()):
                    names.setdefault(m[2], (m[1].split(".")[0].upper(), f"{d.name}/{fn}"))
        src = None
        for line in read(d / "03_time_status.txt"):
            m = re.match(r"\s*Source:\s*(\S+)", line)
            if m: src = m[1].split(".")[0].upper()
            m = re.search(r"source IP:\s*(\d+\.\d+\.\d+\.\d+)", line)
            if m and src and not src.startswith(("LOCAL", "FREE")):
                names.setdefault(m[1], (src, f"{d.name}/03_time_status.txt"))
    return names


def listeners(d):
    out = defaultdict(set)
    for line in read(d / "10_listeners_by_process.txt"):
        m = LISTEN_RE.match(line)
        if m: out[int(m[1])].add(m[3])
    return out


def pid_names(d):
    pn = {}
    for line in read(d / "23_process_connection_mapping.txt"):
        m = CONN_RE.match(line)
        if m: pn[m[5]] = m[6]
    for line in read(d / "10_listeners_by_process.txt"):
        m = LISTEN_RE.match(line)
        if m: pn.setdefault(m[2], m[3])
    for line in read(d / "24_tasklist_services.txt"):
        m = re.match(r"(\S+?)(?:\.exe)?\s+(\d+)\s", line)
        if m: pn.setdefault(m[2], m[1])
    return pn


def services(d):
    """Running services (32_services_inventory blocks) and application matches (32A/32B)."""
    svc, cur = [], {}
    for line in read(d / "32_services_inventory.txt") + [""]:
        m = re.match(r"\s*(\w+)\s*:\s*(.*)$", line)
        if m:
            cur[m[1]] = m[2].strip()
            if m[1] == "DisplayName": cur["_line"] = line.strip()
        elif cur:
            svc.append(cur); cur = {}
    apps = []
    for line in read(d / "32B_reveloc_installed_software_matches.txt"):
        m = re.match(r"\s*DisplayName\s*:\s*(.+)$", line)
        if m: apps.append((m[1].strip(), line.strip()))
    return svc, apps


def profile(ws, host, caps, names):
    if host not in caps:
        fail("NO_CAPTURE", host=host, captured=sorted(caps))
    d = caps[host]
    lis = listeners(d)
    pn = pid_names(d)
    links = {}                                   # (dir, peer_ip, port, proc) -> info
    own_ips = set()
    def add(direction, lip, lport, rip, rport, proc, state, line, fname):
        own_ips.add(lip)
        port = lport if direction == "inbound" else rport
        # an outbound port in the dynamic range on a peer we hold no capture for is an RPC
        # endpoint-mapper style port: group it so one peer does not fan out into many rows
        if direction == "outbound" and port >= 49152 and names.get(rip, (None,))[0] not in caps:
            port = "dynamic"
        k = (direction, rip, port, proc)
        e = links.setdefault(k, {"direction": direction, "peer_ip": rip, "port": port, "process": proc,
                                 "states": set(), "count": 0, "line": line.strip(), "file": fname})
        e["states"].add(state); e["count"] += 1
    for line in read(d / "23_process_connection_mapping.txt"):
        m = CONN_RE.match(line)
        if not m or is_local(m[1]) or is_local(m[3]):
            continue
        lp, rp = int(m[2]), int(m[4])
        add("inbound" if lp in lis else "outbound", m[1], lp, m[3], rp, m[6], "ESTABLISHED", line,
            "23_process_connection_mapping.txt")
    seen = {(k[0], k[1], k[2]) for k in links}
    for line in read(d / "25_netstat_tcp_samples.txt"):
        m = NETSTAT_RE.match(line)
        if not m or m[5] == "LISTENING" or is_local(m[1]) or is_local(m[3]):
            continue
        lp, rp = int(m[2]), int(m[4])
        direction = "inbound" if lp in lis else "outbound"
        port = lp if direction == "inbound" else rp
        if direction == "outbound" and port >= 49152 and names.get(m[3], (None,))[0] not in caps:
            port = "dynamic"
        if (direction, m[3], port) in seen:
            continue                                  # already known from the process mapping
        seen.add((direction, m[3], port))
        add(direction, m[1], lp, m[3], rp, pn.get(m[6], "closed" if m[6] == "0" else f"PID {m[6]}"), m[5], line, "25_netstat_tcp_samples.txt")
    # what the peer runs on that port, when the peer is itself captured
    for k in [k for k, e in links.items() if e["peer_ip"] in own_ips or names.get(e["peer_ip"], (None,))[0] == host]:
        del links[k]                             # the host talking to its own address is not a peer link
    for e in links.values():
        peer = names.get(e["peer_ip"], (None, None))[0]
        e["peer"] = peer
        e["peer_basis"] = names.get(e["peer_ip"], (None, None))[1]
        e["peer_service"] = ""
        if peer in caps and e["direction"] == "outbound" and isinstance(e["port"], int):
            pl = listeners(caps[peer]).get(e["port"])
            if pl: e["peer_service"] = "/".join(sorted(pl))
        e["states"] = sorted(e["states"])
    svc, apps = services(d)
    running = [s for s in svc if s.get("State", "Running") == "Running" or "PathName" in s]
    nonwin = [s for s in running if s.get("PathName") and "\\windows\\" not in s["PathName"].lower()]
    return {"host": host, "capture": d.name, "capture_dir": str(d), "own_ips": sorted(own_ips),
            "listening": {p: sorted(v) for p, v in sorted(lis.items())},
            "applications": [a[0] for a in apps], "app_lines": apps,
            "non_windows_services": [{"name": s.get("Name"), "display": s.get("DisplayName"),
                                      "path": s.get("PathName"), "line": s.get("_line", "")} for s in nonwin],
            "links": sorted(links.values(), key=lambda e: (e["direction"], e["peer"] or "~", e["peer_ip"], str(e["port"]))),
            "capture_files": sorted(p.name for p in d.iterdir())}


def card_md(p):
    L = [f"# {p['host']}", "", f"Capture: `{p['capture']}`  ", f"Addresses seen: {', '.join(p['own_ips']) or 'none'}", ""]
    L += ["## What it does", ""]
    for a in p["applications"]: L.append(f"- Application: {a}")
    for s in p["non_windows_services"]: L.append(f"- Service: {s['display']} (`{s['name']}`) - {s['path']}")
    if not p["applications"] and not p["non_windows_services"]: L.append("- No non-Windows service or application match captured.")
    L += ["", "## Listening", "", "| Port | Process |", "| --- | --- |"]
    L += [f"| {k} | {', '.join(v)} |" for k, v in p["listening"].items()]
    for title, d in (("Inbound - who connects to it", "inbound"), ("Outbound - what it connects to", "outbound")):
        L += ["", f"## {title}", "", "| Peer | Address | Port | Local process | Peer service | State | Seen |", "| --- | --- | --- | --- | --- | --- | --- |"]
        rows = [e for e in p["links"] if e["direction"] == d]
        L += [f"| {e['peer'] or '**unresolved**'} | {e['peer_ip']} | {e['port']} | {e['process']} | {e['peer_service']} | {'/'.join(e['states'])} | {e['count']} |" for e in rows] or ["| none captured | | | | | | |"]
    unres = sorted({e["peer_ip"] for e in p["links"] if not e["peer"]})
    expected = ["10_listeners_by_process.txt", "23_process_connection_mapping.txt", "33_firewall_rules.txt",
                "59_gpresult_computer.txt", "66_scheduled_tasks.txt", "68_certificates_localmachine_my.txt", "73_system_events.txt"]
    missing = [f for f in expected if f not in p["capture_files"]]
    L += ["", "## Open questions", ""]
    if unres: L.append(f"- Name not captured for: {', '.join(unres)} (Resolve-DnsName -Type PTR on each).")
    if missing: L.append(f"- Capture incomplete; missing: {', '.join(missing)}.")
    L.append("- Connection samples are a short window; periodic or batch peers may be absent.")
    return "\n".join(L) + "\n"


def run(cmd, payload):
    env = dict(os.environ, CSA_NO_GRAPH_SYNC="1")   # this script writes the graph itself; sync once at the end
    r = subprocess.run([sys.executable, *map(str, cmd)], input=None if payload is None else json.dumps(payload), capture_output=True, text=True, env=env)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR", "stdout": r.stdout[-800:], "stderr": r.stderr[-800:]}


def matrix_rows(ws):
    p = ws / "csa-work/evidence-matrix.csv"
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if p.is_file() else []


def record(ws, key, p, agent, dry):
    src = f"{p['capture']}: "
    rows = []
    ver = f"capture {p['capture'].rsplit('_', 1)[-1]}"
    def chunks(items, limit=1000):
        """Split (name, line) pairs so each row's claim and excerpt stay inside the matrix limits."""
        out, cur, size = [], [], 0
        for it in items:
            if cur and size + len(it[1]) + 3 > limit:
                out.append(cur); cur, size = [], 0
            cur.append(it); size += len(it[1]) + 3
        return out + ([cur] if cur else [])
    apps = [a for a in p["app_lines"] if not re.search(r"Hotfix|Update for|Security Update|\bKB\d|Language Pack|Redistributable", a[0], re.I)]
    for part in chunks(apps):
        rows.append({"csa_area": "general_asset_inventory", "question": f"What does {p['host']} run?",
                     "claim": f"{p['host']} has these application packages installed: " + "; ".join(a[0] for a in part) + ".",
                     "status": "VERIFIED", "source_title": src + "32B_reveloc_installed_software_matches.txt",
                     "source_version": ver, "section": "3.1 General / Asset Inventory",
                     "page_or_location": "32B, DisplayName lines", "evidence_excerpt": " | ".join(a[1] for a in part),
                     "confidence": "high", "review_state": "pending"})
    svc = [(f"{s['display']} ({s['name']})", s["line"]) for s in p["non_windows_services"] if s["line"] and not re.search(
        r"Edge|Google|Chrome|VMware|VM3D|Media Player|Bonjour|Policy Platform", s["display"] or "")]
    for part in chunks(svc):
        rows.append({"csa_area": "general_asset_inventory", "question": f"What does {p['host']} run?",
                     "claim": f"{p['host']} runs these non-Windows services: " + "; ".join(x[0] for x in part) + ".",
                     "status": "VERIFIED", "source_title": src + "32_services_inventory.txt", "source_version": ver,
                     "section": "3.1 General / Asset Inventory", "page_or_location": "32, service DisplayName lines",
                     "evidence_excerpt": " | ".join(x[1] for x in part), "confidence": "high", "review_state": "pending"})
    nfacts = len(rows)
    for e in p["links"]:
        peer = f"{e['peer']} ({e['peer_ip']})" if e["peer"] else f"{e['peer_ip']} (name not captured)"
        state = "established" if "ESTABLISHED" in e["states"] else "attempted (" + "/".join(e["states"]) + ")"
        if e["direction"] == "inbound":
            claim = f"{peer} has an {state} connection to {p['host']} on port {e['port']}, served by {e['process']} on {p['host']}."
            q = f"What connects to {p['host']}?"
        else:
            svc = f" ({e['peer_service']} on {e['peer']})" if e["peer_service"] else ""
            claim = f"{p['host']} has an {state} connection from {e['process']} to {peer} on {'a dynamic (49152+) port' if e['port'] == 'dynamic' else 'port ' + str(e['port'])}{svc}."
            q = f"What does {p['host']} connect to?"
        rows.append({"csa_area": "network_and_connectivity", "question": q, "claim": claim, "status": "VERIFIED",
                     "source_title": src + e["file"], "source_version": f"capture {p['capture'].rsplit('_', 1)[-1]}",
                     "section": "3.6 Network / Segmentation", "page_or_location": f"{e['file']}, {e['count']} sample(s)",
                     "evidence_excerpt": e["line"], "confidence": "high",
                     "gap_or_action": "" if e["peer"] else f"Name of {e['peer_ip']} not captured; resolve it.",
                     "review_state": "pending"})
    known_areas = {r["csa_area"] for r in matrix_rows(ws)}
    extra = ["--allow-new-area"] if "general_asset_inventory" not in known_areas else []
    res = run([EM, "--workspace", ws, "append", "--agent", agent, "--context", f"host-profile {p['host']}",
               "--rows-file", "-", *extra, *(["--dry-run"] if dry else [])], rows)
    if res.get("status") == "ERROR" and "rejected" in res:
        # sources outside the discovery index cannot be source-checked; keep the exact quote and retry
        res = run([EM, "--workspace", ws, "append", "--agent", agent, "--context", f"host-profile {p['host']}",
                   "--rows-file", "-", "--no-source-check", *extra, *(["--dry-run"] if dry else [])], rows)
    out = {"matrix": {k: res.get(k) for k in ("status", "written", "skipped_duplicates", "would_write", "error", "rejected") if res.get(k)}}
    if dry or res.get("status") == "ERROR":
        return out
    # graph: map each claim back to its E-id (new or pre-existing duplicate)
    by_claim = {r["claim"]: r["evidence_id"] for r in matrix_rows(ws)}
    eid = lambda c: by_claim.get(c, "")
    nodes_p = ws / "csa-work/graph/nodes.csv"
    nodes = list(csv.DictReader(open(nodes_p, encoding="utf-8-sig"))) if nodes_p.is_file() else []
    def node_for(label_key):
        for n in nodes:
            if n["label"].split(" ")[0] == label_key:
                return n["node_id"]
    host_ids = [eid(r["claim"]) for r in rows if eid(r["claim"])]
    want = {}
    if not node_for(p["host"]):
        role = "; ".join(p["applications"][:2])
        want[p["host"]] = {"domain": "3.6 Network / Segmentation", "label": f"{p['host']} ({role})" if role else p["host"],
                           "node_type": "host", "purdue_level": "n/a", "zone": "", "evidence_ids": ";".join(host_ids[:6]),
                           "confidence": "high", "review_state": "pending"}
    for r, e in zip(rows[nfacts:], p["links"]):
        k = e["peer"] or e["peer_ip"]
        if not node_for(k) and k not in want:
            want[k] = {"domain": "3.6 Network / Segmentation", "label": k if e["peer"] else f"{k} (name not captured)",
                       "node_type": "host", "purdue_level": "n/a", "zone": "", "evidence_ids": eid(r["claim"]),
                       "confidence": "high" if e["peer"] else "medium", "review_state": "pending"}
    if want:
        out["nodes"] = run([GS, "--workspace", ws, "append-node", "--agent", agent, "--context",
                            f"host-profile {p['host']}", "--rows-file", "-"], list(want.values())).get("status")
        nodes = list(csv.DictReader(open(nodes_p, encoding="utf-8-sig")))
    edges_p = ws / "csa-work/graph/edges.csv"
    have = {(x["source_node_id"], x["target_node_id"], x["evidence_ids"]) for x in csv.DictReader(open(edges_p, encoding="utf-8-sig"))} if edges_p.is_file() else set()
    me = node_for(p["host"])
    edges = []
    for r, e in zip(rows[nfacts:], p["links"]):
        other = node_for(e["peer"] or e["peer_ip"]); ev = eid(r["claim"])
        if not (me and other and ev) or me == other:
            continue
        s, t = (other, me) if e["direction"] == "inbound" else (me, other)
        if (s, t, ev) in have:
            continue
        rel = "remote-access" if e["port"] in (3389, 5985, 5986, 22) else "data-flow"
        edges.append({"domain": "3.6 Network / Segmentation", "source_node_id": s, "target_node_id": t,
                      "relationship_type": rel, "evidence_ids": ev,
                      "confidence": "high" if "ESTABLISHED" in e["states"] else "medium", "review_state": "pending"})
    if edges:
        out["edges"] = run([GS, "--workspace", ws, "append-edge", "--agent", agent, "--context",
                            f"host-profile {p['host']}", "--rows-file", "-"], edges).get("status")
    out["edges_new"] = len(edges)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("profile", "record"):
        s = sub.add_parser(c); s.add_argument("host", nargs="?"); s.add_argument("--all", action="store_true")
        s.add_argument("--json", action="store_true")
        if c == "record":
            s.add_argument("--agent", required=True); s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    key, ws, source_set = project_for(a.workspace)
    if not source_set or not source_set.is_dir():
        fail("default_source_set not found", source_set=str(source_set))
    caps = captures(source_set)
    if a.cmd == "list":
        print(json.dumps({"project": key, "captured_hosts": {h: d.name for h, d in sorted(caps.items())}}, indent=2)); return
    hosts = sorted(caps) if a.all else [a.host.upper()] if a.host else fail("give a HOST or --all")
    names = name_map(ws, caps)
    cards = ws / "csa-work/hosts/cards"; cards.mkdir(parents=True, exist_ok=True)
    results = {}
    for h in hosts:
        p = profile(ws, h, caps, names)
        (cards / f"{h}.md").write_text(card_md(p), encoding="utf-8")
        if a.cmd == "profile":
            if a.json: results[h] = {k: v for k, v in p.items() if k not in ("app_lines", "capture_files")}
            elif not a.all: print(card_md(p))
            else: results[h] = {"inbound": sum(e["direction"] == "inbound" for e in p["links"]),
                                "outbound": sum(e["direction"] == "outbound" for e in p["links"]),
                                "unresolved": len({e["peer_ip"] for e in p["links"] if not e["peer"]})}
        else:
            results[h] = record(ws, key, p, a.agent, a.dry_run)
    if a.cmd == "record" and not a.dry_run and not os.environ.get("CSA_NO_GRAPH_SYNC"):
        # prune removed evidence, graph other link rows and rebuild the host index
        sync = run([GS.with_name("graph_sync.py"), "--workspace", ws, "--no-captures"], None)
        results["_graph_sync"] = {k: sync.get(k) for k in ("status", "edges_from_rows", "prune", "hosts_index")}
    if results:
        print(json.dumps(results, indent=2, default=list))


if __name__ == "__main__":
    main()
