"""Data-flow inventory: one row per flow the captures show or the system's flow map declares.

Storage & Data Transfer, Network, Perimeter and Internet sections all ask the same things of a flow:
what moves, between which ends, in which zones, which side opens the connection, by which mechanism, and
whether anyone designed it. This module answers them from the captures, without a model, and writes
`csa-work/hosts/flows.csv`:

* observed flows come from each host's newest `23_process_connection_mapping` (local:port -> remote:port,
  process). The local port is a listener in `20_listening_ports` -> the peer opened the connection (inbound);
  otherwise the host opened it (outbound). Each flow is written from the side that opens it (src = initiator).
* declared flows come from the system's expected flow map (`02_*expected_flow_map`): CSID, source,
  destination, purpose and ports.
* an observed flow matching a declared one (source and destination hosts, a port the declaration names) is
  status `both`; the rest stay `observed` (nobody designed it on paper) or `declared` (not seen in the captures).
* zones come from zones.csv (zones.py); mechanism from the service port and process; `signature` from
  references/signal-signatures.json says what the process usually is (background, never evidence).

Every observed row keeps the capture lines it came from. Standard library only.

    python3 -m csa_docx.flows build --work-dir <work_dir>
    python3 -m csa_docx.flows show  --work-dir <work_dir> [--data] [--cross-zone] [--host H]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from csa_docx import host_settings, zones as zones_mod

SIGNATURES = Path(__file__).resolve().parents[2] / "references" / "signal-signatures.json"
FIELDS = ["flow_id", "status", "mechanism", "data", "src", "src_role", "src_zone", "src_zone_kind", "src_process",
          "dst", "dst_role", "dst_zone", "dst_zone_kind", "dst_process", "port", "cross_zone", "zones_reviewed",
          "declared_id", "declared_flow", "signature", "confirm", "connections", "sources", "excerpt"]

PORT_CLASS = {
    "445": "file share", "139": "file share", "2049": "file share",
    "20": "file transfer", "21": "file transfer", "22": "file transfer", "69": "file transfer", "989": "file transfer",
    "990": "file transfer", "115": "file transfer",
    "1433": "database", "1434": "database", "3306": "database", "5432": "database", "1521": "database", "27017": "database",
    "5022": "database replication",
    "25": "mail", "465": "mail", "587": "mail",
    "80": "web/API", "443": "web/API", "8080": "web/API", "8443": "web/API",
    "7000": "backup agent",
    "53": "name resolution", "88": "authentication", "389": "authentication", "636": "authentication",
    "3268": "authentication", "3269": "authentication", "123": "time", "135": "management", "5985": "remote administration",
    "5986": "remote administration", "3389": "remote administration", "5900": "remote administration",
    "5800": "remote administration", "3343": "cluster", "9997": "log forwarding",
    "8089": "log forwarding", "5723": "monitoring", "10123": "patch management", "8530": "patch management", "8531": "patch management",
}
DATA_MECHANISMS = {"file share", "file transfer", "database", "database replication", "mail", "web/API", "backup agent",
                   "message/API", "security agent telemetry"}
_MAP = re.compile(r"^\s*(\S+?):(\d+)\s*->\s*(\S+?):(\d+)\s+PID=(\d+)\s+PROC=(\S+)")
_LISTEN = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\d+)\s*$")
_HOST = re.compile(r"\b[A-Z][A-Z0-9]{5,}\d{2,3}\b")


def _skip(ip: str) -> bool:
    ip = ip.split("%")[0]
    return ip.startswith(("127.", "::1", "fe80", "169.254.", "0.0.0.0")) or ip in ("::", "[::]")


def signatures() -> list[dict]:
    try:
        return json.loads(SIGNATURES.read_text(encoding="utf-8")).get("signatures", [])
    except (OSError, ValueError):
        return []


def signature_for(process: str, port: str, sigs: list[dict]) -> dict | None:
    for s in sigs:
        if s.get("process") and not re.fullmatch(s["process"], process or "", re.I):
            continue
        if s.get("port") and not re.fullmatch(s["port"], str(port)):
            continue
        if s.get("process") or s.get("port"):
            return s
    return None


def mechanism(port: str, process: str, sig: dict | None) -> str:
    if sig and sig.get("mechanism"):
        return sig["mechanism"]
    return PORT_CLASS.get(str(port), "other")


def listeners(text: str) -> set[str]:
    out = set()
    for l in text.splitlines():
        m = _LISTEN.match(l)
        if m and not m.group(1).startswith("127."):
            out.add(m.group(2))
    return out


def observed(mapping: dict[str, dict], listening: dict[str, set], ip2host: dict[str, str]) -> list[dict]:
    """Observed flows from each host's process-connection mapping, written from the initiating side."""
    agg: dict[tuple, dict] = {}
    for host, cap in sorted(mapping.items()):
        lines = cap["text"].splitlines()
        lis = listening.get(host, set())
        for i, l in enumerate(lines):
            m = _MAP.match(l)
            if not m:
                continue
            lip, lp, rip, rp, _pid, proc = m.groups()
            if _skip(rip) or _skip(lip):
                continue
            peer = ip2host.get(rip.split("%")[0], rip.split("%")[0])
            if peer == host:
                continue                         # the host talking to itself on its own address
            if lp in lis:                        # the peer connected in to a port this host listens on
                src, dst, port, src_proc, dst_proc = peer, host, lp, "", proc
            else:
                src, dst, port, src_proc, dst_proc = host, peer, rp, proc, ""
            key = (src, dst, port)
            r = agg.setdefault(key, {"src": src, "dst": dst, "port": port, "src_process": src_proc, "dst_process": dst_proc,
                                     "connections": 0, "sources": [], "excerpt": l.strip()})
            r["connections"] += 1
            r["src_process"] = r["src_process"] or src_proc
            r["dst_process"] = r["dst_process"] or dst_proc
            cite = f"{cap['folder']}: {cap['fname']} line {cap['start'] + i}"
            if cite not in r["sources"] and len(r["sources"]) < 4:
                r["sources"].append(cite)
    return list(agg.values())


_NETSTAT = re.compile(r"^\s*TCP\s+(\S+):(\d+)\s+(\S+):(\d+)\s+(\S+)\s+(\d+)\s*$")
_LIVE = {"ESTABLISHED", "CLOSE_WAIT", "FIN_WAIT_1", "FIN_WAIT_2", "TIME_WAIT", "LAST_ACK", "CLOSING"}


def _image_names(text: str) -> dict[str, str]:
    """{pid: image name without .exe} from `tasklist /svc`."""
    out = {}
    for l in text.splitlines():
        m = re.match(r"^(\S.*?)\s+(\d+)\s", l)
        if m and not l.startswith(" "):
            out[m.group(2)] = re.sub(r"\.exe$", "", m.group(1).strip(), flags=re.I)
    return out


def sampled(samples: dict[str, dict], tasks: dict[str, dict], have: set[tuple]) -> list[dict]:
    """Outbound connections to public addresses in the netstat samples (25) that the process mapping (23) did not
    record. A connection only ever seen in SYN_SENT is 'attempted' (the host asked, no reply was seen); any
    established state makes it 'observed'."""
    import ipaddress
    agg: dict[tuple, dict] = {}
    for host, cap in sorted(samples.items()):
        names = _image_names((tasks.get(host) or {}).get("text", ""))
        for i, l in enumerate(cap["text"].splitlines()):
            m = _NETSTAT.match(l)
            if not m:
                continue
            _lip, _lp, rip, rp, state, pid = m.groups()
            try:
                if not ipaddress.ip_address(rip).is_global:
                    continue
            except ValueError:
                continue
            key = (host, rip, rp)
            if key in have:
                continue
            r = agg.setdefault(key, {"src": host, "dst": rip, "port": rp, "src_process": names.get(pid, ""),
                                     "dst_process": "", "connections": 0, "sources": [], "excerpt": l.strip(),
                                     "_states": set()})
            r["connections"] += 1
            r["_states"].add(state)
            r["src_process"] = r["src_process"] or names.get(pid, "")
            cite = f"{cap['folder']}: {cap['fname']} line {cap['start'] + i}"
            if cite not in r["sources"] and len(r["sources"]) < 4:
                r["sources"].append(cite)
    out = []
    for r in agg.values():
        r["status_hint"] = "observed" if r.pop("_states") & _LIVE else "attempted"
        out.append(r)
    return out


def declared(text: str) -> list[dict]:
    """CSID blocks of an expected flow map: {id, source, destination, flow, ports, risk, src_hosts, dst_hosts}."""
    out, cur = [], None
    for l in text.splitlines():
        m = re.match(r"^\s*(CSID|Source|Destination|Flow|Ports|OT35Risk)\s*:\s*(.*)$", l)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if k == "CSID":
            cur = {"id": v, "source": "", "destination": "", "flow": "", "ports": "", "risk": ""}
            out.append(cur)
        elif cur is not None:
            cur[{"Source": "source", "Destination": "destination", "Flow": "flow", "Ports": "ports", "OT35Risk": "risk"}[k]] = v
    for d in out:
        d["src_hosts"] = set(_HOST.findall(d["source"]))
        d["dst_hosts"] = set(_HOST.findall(d["destination"]))
        d["port_list"] = set(re.findall(r"\b\d{2,5}\b", d["ports"]))
        if re.search(r"\bSMB\b", d["ports"], re.I):
            d["port_list"].add("445")
        if re.search(r"\bRDP\b", d["ports"], re.I):
            d["port_list"].add("3389")
        if re.search(r"\bSQL\b", d["ports"], re.I):
            d["port_list"].add("1433")
    return out


def build(work_dir: Path, con=None) -> dict:
    work_dir = Path(work_dir)
    own = con is None
    if own:
        p = work_dir / "discovery-index.sqlite"
        if not p.is_file():
            return {"status": "ERROR", "message": f"no discovery index at {p}"}
        con = sqlite3.connect(str(p))
    try:
        mapping = host_settings.latest_texts(con, "%23_process_connection_mapping%")
        listen = {h: listeners(c["text"]) for h, c in host_settings.latest_texts(con, "%20_listening_ports%").items()}
        maps = host_settings.latest_texts(con, "%expected_flow_map%")
        samples = host_settings.latest_texts(con, "%25_netstat_tcp_samples%")
        tasks = host_settings.latest_texts(con, "%24_tasklist_services%")
    finally:
        if own:
            con.close()
    reg = {}
    hf = work_dir / "hosts" / "hosts.csv"
    if hf.is_file():
        for r in csv.DictReader(hf.open(encoding="utf-8")):
            reg[r["host"].upper()] = r
    ip2host = {ip: h for h, r in reg.items() for ip in (r.get("ips") or "").split(";") if ip}
    dcs = set()
    ff = work_dir / "hosts" / "host_facts.csv"
    if ff.is_file():
        dcs = {r["host"].upper() for r in csv.DictReader(ff.open(encoding="utf-8"))
               if r.get("attribute", "").startswith("domain_controllers")}
    z = zones_mod.for_project(work_dir)
    sigs = signatures()
    # ports the Remote Desktop service listens on (an alternate RDP port is remote administration, not "other")
    rdp_ports = set()
    sf = work_dir / "hosts" / "host_settings.csv"
    if sf.is_file():
        for r in csv.DictReader(sf.open(encoding="utf-8")):
            if r.get("attribute") == "admin.rdp_port":
                rdp_ports |= {x.strip() for x in r["value"].split(",") if x.strip().isdigit()}
    rows = observed(mapping, listen, ip2host)
    rows += sampled(samples, tasks, {(r["src"], r["dst"], r["port"]) for r in rows})
    decl_text = max(maps.values(), key=lambda c: c["folder"])["text"] if maps else ""
    decl = declared(decl_text)
    matched: set[str] = set()
    out = []
    for r in rows:
        proc = r["dst_process"] or r["src_process"]
        sig = signature_for(r["dst_process"], r["port"], sigs) or signature_for(r["src_process"], r["port"], sigs) \
            or signature_for(proc, "", sigs)
        mech = mechanism(r["port"], proc, sig)
        if str(r["port"]) in rdp_ports and mech in ("other", "management"):
            mech, sig = "remote administration", {"means": "Remote Desktop on the port the RDP service listens on",
                                                   "confirm": "who uses this RDP path and from where"}
        if r["dst"] in dcs and r["port"] in ("445", "139"):
            mech, sig = "directory (SYSVOL, Group Policy)", None    # a domain member reading policy, not a data transfer
        elif r["dst"] in dcs and mech == "other" and str(r["port"]).isdigit() and int(r["port"]) >= 49152:
            mech, sig = "directory (RPC)", {"means": "a domain member calling a domain controller on a dynamic RPC port",
                                            "confirm": ""}
        hint = r.pop("status_hint", "observed")
        d = next((d for d in decl if _matches(d, r)), None) if hint == "observed" else None
        if d:
            matched.add(d["id"])
        zs, zd = z.of(r["src"]), z.of(r["dst"])
        out.append({**r, "status": "both" if d else hint, "mechanism": mech, "data": "yes" if mech in DATA_MECHANISMS else "no",
                    "src_role": (reg.get(r["src"]) or {}).get("role", ""), "dst_role": (reg.get(r["dst"]) or {}).get("role", ""),
                    "src_zone": zs["zone"], "src_zone_kind": zs["kind"], "dst_zone": zd["zone"], "dst_zone_kind": zd["kind"],
                    "cross_zone": _cross(zs["kind"], zd["kind"]),
                    "zones_reviewed": "yes" if zs.get("reviewed") == "yes" and zd.get("reviewed") == "yes" else "no",
                    "declared_id": d["id"] if d else "", "declared_flow": d["flow"] if d else "",
                    "signature": (sig or {}).get("means", ""), "confirm": (sig or {}).get("confirm", ""),
                    "sources": "; ".join(r["sources"])})
    for d in decl:
        if d["id"] in matched:
            continue
        port = next(iter(sorted(d["port_list"])), "")
        mech = PORT_CLASS.get(port, "other") if port else "other"
        if re.search(r"azure|internet|service bus|https", d["flow"] + d["destination"], re.I):
            mech = "message/API" if mech in ("other", "web/API") else mech
        src = ", ".join(sorted(d["src_hosts"])) or d["source"]
        dst = ", ".join(sorted(d["dst_hosts"])) or d["destination"]
        zs, zd = _zone_of_list(z, d["src_hosts"]), _zone_of_list(z, d["dst_hosts"])
        out.append({"status": "declared", "mechanism": mech, "data": "yes" if mech in DATA_MECHANISMS else "no",
                    "src": src, "dst": dst, "port": d["ports"], "src_process": "", "dst_process": "",
                    "src_role": "", "dst_role": "", "src_zone": zs["zone"], "src_zone_kind": zs["kind"],
                    "dst_zone": zd["zone"], "dst_zone_kind": zd["kind"], "cross_zone": _cross(zs["kind"], zd["kind"]),
                    "zones_reviewed": "no", "declared_id": d["id"], "declared_flow": d["flow"], "signature": "", "confirm": "",
                    "connections": 0, "sources": f"{max(maps.values(), key=lambda c: c['folder'])['folder']}: "
                                               f"{max(maps.values(), key=lambda c: c['folder'])['fname']}" if maps else "",
                    "excerpt": f"CSID        : {d['id']}"})
    out.sort(key=lambda r: (r["status"] == "declared", r["mechanism"], r["src"], r["dst"], str(r["port"])))
    for n, r in enumerate(out, 1):
        r["flow_id"] = f"F{n:03d}"
    f = work_dir / "hosts" / "flows.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return {"status": "OK", "flows": len(out), "observed": sum(r["status"] != "declared" for r in out),
            "declared_only": sum(r["status"] == "declared" for r in out),
            "data_flows": sum(r["data"] == "yes" for r in out),
            "cross_zone": sum(r["cross_zone"] == "yes" for r in out), "zones_file": zones_mod.path(work_dir).is_file(),
            "out": str(f)}


def _matches(d: dict, r: dict) -> bool:
    """An observed flow matches a declared one: both named ends match, and where a declaration names an end
    only by description ("Internet / Azure", "IT SOE Workstation") the port must match."""
    if not d["src_hosts"] and not d["dst_hosts"]:
        return False
    src_ok = r["src"] in d["src_hosts"] if d["src_hosts"] else True
    dst_ok = r["dst"] in d["dst_hosts"] if d["dst_hosts"] else True
    if not (src_ok and dst_ok):
        return False
    if d["src_hosts"] and d["dst_hosts"]:
        return r["port"] in d["port_list"] or not d["port_list"]
    return r["port"] in d["port_list"]


def _zone_of_list(z, hosts: set) -> dict:
    if not hosts:
        return {"zone": "", "kind": "unknown"}
    rules = [z.of(h) for h in sorted(hosts)]
    kinds = {r["kind"] for r in rules}
    return {"zone": ", ".join(dict.fromkeys(r["zone"] for r in rules)), "kind": kinds.pop() if len(kinds) == 1 else "unknown"}


def _cross(a: str, b: str) -> str:
    """yes when the two ends sit in different kinds of zone (OT/IT/internet/...), unknown when either is not recorded."""
    if "unknown" in (a, b):
        return "unknown"
    return "no" if a == b else "yes"


def groups(rows: list[dict]) -> list[dict]:
    """Flows grouped for reading: flows of one mechanism and port to the same far end merge their sources
    ("ROTPRDCLU101, ROTPRDCLU102 -> 10.40.254.6"); a source talking to many ends of one mechanism and port merges
    its destinations ("IPTPRDAPP137 -> 34.120.2.104, 34.132.184.13 ..."). Declared-only flows stay one per CSID.
    Each group: {mechanism, port, status, srcs, dsts, src_zones, dst_zones, cross_zone, flows, signature, confirm,
    declared_id, declared_flow}."""
    by_dst: dict[tuple, list[dict]] = {}
    out = []
    attempted: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["status"] == "declared":
            out.append(_group([r]))
            continue
        if r["status"] == "attempted":                 # unanswered requests: one row per mechanism and port
            attempted.setdefault((r["mechanism"], r["port"]), []).append(r)
            continue
        by_dst.setdefault((r["mechanism"], r["port"], r["dst"], r["status"]), []).append(r)
    singles: dict[tuple, list[dict]] = {}
    for k, rs in by_dst.items():
        if len(rs) > 1:
            out.append(_group(rs))
        else:
            r = rs[0]
            singles.setdefault((r["mechanism"], r["port"], r["src"], r["status"]), []).append(r)
    out += [_group(rs) for rs in singles.values()]
    out += [_group(rs) for rs in attempted.values()]
    order = {"yes": 0, "unknown": 1, "no": 2}
    out.sort(key=lambda g: (g["status"] == "declared", order.get(g["cross_zone"], 3), g["mechanism"], g["srcs"][0]))
    return out


def _group(rs: list[dict]) -> dict:
    cz = {r["cross_zone"] for r in rs}
    return {"mechanism": rs[0]["mechanism"], "port": rs[0]["port"], "status": rs[0]["status"],
            "srcs": list(dict.fromkeys(r["src"] for r in rs)), "dsts": list(dict.fromkeys(r["dst"] for r in rs)),
            "src_zones": list(dict.fromkeys(r["src_zone"] for r in rs if r["src_zone"])),
            "dst_zones": list(dict.fromkeys(r["dst_zone"] for r in rs if r["dst_zone"])),
            "cross_zone": "yes" if "yes" in cz else "unknown" if "unknown" in cz else "no",
            "flows": rs, "signature": rs[0].get("signature", ""), "confirm": rs[0].get("confirm", ""),
            "declared_id": rs[0].get("declared_id", ""), "declared_flow": rs[0].get("declared_flow", ""),
            "process": rs[0].get("dst_process") or rs[0].get("src_process") or ""}


def load(work_dir: Path) -> list[dict]:
    f = Path(work_dir) / "hosts" / "flows.csv"
    return list(csv.DictReader(f.open(encoding="utf-8"))) if f.is_file() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build"); s.add_argument("--work-dir", type=Path, required=True)
    s = sub.add_parser("show"); s.add_argument("--work-dir", type=Path, required=True)
    s.add_argument("--data", action="store_true"); s.add_argument("--cross-zone", action="store_true"); s.add_argument("--host")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = build(a.work_dir)
        print(json.dumps(out, indent=1))
        return 0 if out["status"] == "OK" else 1
    for r in load(a.work_dir):
        if a.data and r["data"] != "yes":
            continue
        if a.cross_zone and r["cross_zone"] != "yes":
            continue
        if a.host and a.host.upper() not in (r["src"] + " " + r["dst"]).upper():
            continue
        print(f"{r['flow_id']} {r['status']:8} {r['mechanism']:22} {r['src']} ({r['src_zone']}) -> {r['dst']} ({r['dst_zone']}) "
              f":{r['port']} {r['src_process'] or r['dst_process']} {'CROSS' if r['cross_zone'] == 'yes' else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def select(rows: list[dict], flt: dict, register: set[str] | None = None) -> list[dict]:
    """The flows a profile or frame asks for. Keys (all optional, all must hold): data, status, mechanisms,
    exclude_mechanisms, cross_zone, dst_zones (a zone name contains one of these), direction ("inbound": the far
    end is not in the host register and the near end is; "outbound": the reverse), any_of (a list of these
    filters, at least one must hold)."""
    def one(r: dict, f: dict) -> bool:
        if f.get("data") and r["data"] != "yes":
            return False
        if f.get("status") and r["status"] not in f["status"]:
            return False
        if f.get("mechanisms") and r["mechanism"] not in f["mechanisms"]:
            return False
        if f.get("exclude_mechanisms") and r["mechanism"] in f["exclude_mechanisms"]:
            return False
        if f.get("cross_zone") and r["cross_zone"] not in f["cross_zone"]:
            return False
        if f.get("dst_zones") and not any(z.lower() in (r.get("dst_zone") or "").lower() for z in f["dst_zones"]):
            return False
        if f.get("direction") and register is not None:
            src_in = all(x.strip().upper() in register for x in r["src"].split(",") if x.strip())
            dst_in = all(x.strip().upper() in register for x in r["dst"].split(",") if x.strip())
            if f["direction"] == "inbound" and not (dst_in and not src_in):
                return False
            if f["direction"] == "outbound" and not (src_in and not dst_in):
                return False
        if f.get("any_of") and not any(one(r, g) for g in f["any_of"]):
            return False
        return True
    return [r for r in rows if one(r, flt)]
