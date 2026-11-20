"""Recover explicit network structure from verified V2 evidence.

This is deliberately conservative: it imports only concrete host/IP bindings,
listeners, configured DNS/NTP dependencies, and point-to-point connections with
an explicit remote address and port. Ambiguous literals remain evidence only.
"""
from __future__ import annotations

import re
from pathlib import Path

from .v2repo import Repo
import csa_docx.v2repo.graph  # register r.graph

IP = r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"


def repair(db: str | Path) -> dict:
    r = Repo(db)
    con = r.con
    hosts = {x[0] for x in con.execute("SELECT name FROM host")}
    addresses = {x[0]: x[2] for x in con.execute("SELECT ip, scope, owner_host FROM address")}
    counts = {"addresses_added": 0, "services_added": 0, "flows_added": 0}

    def host_in(text):
        found = [h for h in hosts if h.lower() in (text or "").lower()]
        return max(found, key=len) if found else None

    def endpoint(ip):
        return addresses.get(ip) or ip

    def ensure_host(name, note):
        if name not in hosts:
            r.hosts.create(name, role="Observed network endpoint", actor="csa-structured-repair", note=note)
            hosts.add(name)

    with r.tx():
        evidence = con.execute("SELECT id, claim, source_title FROM evidence WHERE status='VERIFIED'").fetchall()

        # Explicit host/IP bindings.
        for eid, claim, source in evidence:
            host = host_in(claim) or host_in(source)
            if not host:
                continue
            ips = []
            for pattern in (rf"\bat\s+({IP})", rf"IPv4 address(?:es)?\s+({IP})",
                            rf"interface address\s+({IP})", rf"host at\s+({IP})"):
                ips += re.findall(pattern, claim or "", re.I)
            for ip in dict.fromkeys(ips):
                if ip in {"127.0.0.1", "0.0.0.0", "255.255.255.255"}:
                    continue
                if ip in addresses and addresses[ip] not in (None, host):
                    continue
                if ip not in addresses:
                    con.execute("INSERT INTO address(ip, scope, owner_host) VALUES (?, ?, ?)",
                                (ip, "evidence-derived", host))
                    addresses[ip] = host
                    counts["addresses_added"] += 1
                    r._audit("csa-structured-repair", "address.evidence_import", "address", ip,
                             f"evidence={eid}; source={source}")

        port_names = {53: "dns", 80: "http", 123: "ntp", 135: "rpc", 139: "netbios-session",
                      443: "https", 445: "smb", 502: "modbus", 102: "iso-tsap", 161: "snmp",
                      514: "syslog", 20000: "dnp3", 2404: "iec-104", 3389: "rdp", 5481: "geoscada",
                      5723: "healthservice", 5985: "winrm", 8080: "http-alt", 8089: "splunk"}

        # Explicit listeners become host -> service records.
        listener_sql = ("SELECT id, claim, source_title FROM evidence WHERE status='VERIFIED' "
                        "AND (lower(claim) LIKE '%listens on port%' OR lower(claim) LIKE '%listens on ports%')")
        for eid, claim, source in con.execute(listener_sql):
            host = host_in(claim) or host_in(source)
            if not host:
                continue
            protocol = "udp" if re.search(r"\bUDP\b", claim, re.I) else ("tcp" if re.search(r"\bTCP\b", claim, re.I) else None)
            match = re.search(r"listens on ports?\s+(.+?)(?:\.|$)", claim, re.I)
            if not match:
                continue
            ports = {int(x) for x in re.findall(r"(?<!\d)(\d{1,5})(?!\d)", match.group(1)) if 1 <= int(x) <= 65535}
            process = (re.search(r"\b(?:The|A|An)\s+([A-Za-z][A-Za-z0-9_-]*)\s+process", claim) or [None, "listener"])[1].lower()
            for port in ports:
                name = port_names.get(port, process if process != "listener" else f"listener:{port}")
                if con.execute("SELECT 1 FROM service WHERE host=? AND port=? AND protocol IS ? AND name=?",
                               (host, port, protocol, name)).fetchone():
                    continue
                con.execute("INSERT INTO service(host, provider_host, port, protocol, name, configured) VALUES (?, ?, ?, ?, ?, 0)",
                            (host, None, port, protocol, name))
                r._audit("csa-structured-repair", "service.evidence_import", "service", f"{host}/{name}",
                         f"evidence={eid}; source={source}")
                counts["services_added"] += 1

        # Configured DNS and NTP dependencies become service records.
        for eid, claim, source in evidence:
            host = host_in(claim) or host_in(source)
            if not host:
                continue
            if re.search(r"\bDNS servers?\b", claim, re.I):
                for ip in dict.fromkeys(re.findall(IP, claim)):
                    if not con.execute("SELECT 1 FROM service WHERE host=? AND provider_host=? AND port=53 AND protocol='udp' AND name='dns'", (host, ip)).fetchone():
                        con.execute("INSERT INTO service(host, provider_host, port, protocol, name, configured) VALUES (?, ?, 53, 'udp', 'dns', 1)", (host, ip))
                        r._audit("csa-structured-repair", "service.evidence_import", "service", f"{host}/dns", f"evidence={eid}; provider={ip}; source={source}")
                        counts["services_added"] += 1
            if re.search(r"\bNTP peer\b|\bconfigured .*NTP\b", claim, re.I):
                match = re.search(r"(?:on|for)\s+([A-Za-z][A-Za-z0-9_.-]+)", claim, re.I)
                provider = match.group(1) if match else None
                if provider and provider.lower() not in {"host", "the"} and not con.execute("SELECT 1 FROM service WHERE host=? AND provider_host=? AND port=123 AND protocol='udp' AND name='ntp'", (host, provider)).fetchone():
                    con.execute("INSERT INTO service(host, provider_host, port, protocol, name, configured) VALUES (?, ?, 123, 'udp', 'ntp', 1)", (host, provider))
                    r._audit("csa-structured-repair", "service.evidence_import", "service", f"{host}/ntp", f"evidence={eid}; provider={provider}; source={source}")
                    counts["services_added"] += 1

        # Concrete point-to-point connections. Keep evidence IDs in purpose for graph provenance.
        flows = {}
        for eid, claim, source in evidence:
            if not re.search(r"\b(connection|connections|connect)\b", claim or "", re.I):
                continue
            host = host_in(claim) or host_in(source)
            if not host:
                continue
            protocol = "udp" if re.search(r"\bUDP\b", claim, re.I) else "tcp"
            state = "attempted" if re.search(r"\battempted\b", claim, re.I) else "established"
            matches = [(m.group(1), int(m.group(2))) for m in re.finditer(
                rf"\bto\s+({IP})(?::|\s+on\s+(?:remote\s+)?port\s+|\s+port\s+)(\d{{1,5}})", claim, re.I)]
            if not matches:
                peer = re.search(r"connections from\s+(.+?)\s+to\s+.+?\s+on (?:local )?(?:TCP|UDP) port\s+(\d+)", claim, re.I)
                if peer:
                    for ip in re.findall(IP, peer.group(1)):
                        key = (endpoint(ip), host, int(peer.group(2)), protocol)
                        flows.setdefault(key, [[], state])[0].append(eid)
                continue
            for ip, port in matches:
                if 1 <= port <= 65535 and endpoint(ip) != host:
                    key = (host, endpoint(ip), port, protocol)
                    flows.setdefault(key, [[], state])[0].append(eid)
        for (src, dst, port, protocol), (ids, state) in flows.items():
            ensure_host(src, f"flow source; evidence={ids[0]}")
            ensure_host(dst, f"flow endpoint; evidence={ids[0]}")
            if con.execute("SELECT 1 FROM flow WHERE src_host=? AND dst_host=? AND port=? AND protocol=?", (src, dst, port, protocol)).fetchone():
                continue
            purpose = f"evidence-derived:{state}; evidence=" + ",".join(sorted(set(ids)))
            con.execute("INSERT INTO flow(src_host, dst_host, port, protocol, purpose) VALUES (?, ?, ?, ?, ?)", (src, dst, port, protocol, purpose))
            r._audit("csa-structured-repair", "flow.evidence_import", "flow", f"{src}->{dst}:{port}/{protocol}", f"evidence={','.join(sorted(set(ids)))}")
            counts["flows_added"] += 1

        # The registered key is traction-scada; merge the historical display-case variant.
        for table in ("application_scope", "application_ownership"):
            cols = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
            rows = con.execute(f"SELECT * FROM {table} WHERE application_key='Traction Scada'").fetchall()
            marks = ",".join("?" for _ in cols)
            for row in rows:
                data = dict(zip(cols, row)); data["application_key"] = "traction-scada"
                con.execute(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})", [data[c] for c in cols])
            con.execute(f"DELETE FROM {table} WHERE application_key='Traction Scada'")
            r._audit("csa-structured-repair", "scope.key_normalize", table, "Traction Scada", f"canonical=traction-scada; rows={len(rows)}")

        counts["graph"] = r.graph.refresh(actor="csa-structured-repair")
    r.close()
    return counts


if __name__ == "__main__":
    import json
    print(json.dumps(repair(Path("Traction Scada/csa-work-v2/csa.sqlite")), default=str))
