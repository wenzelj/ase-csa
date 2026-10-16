"""Per-host settings read from the discovery captures, one value per (host, attribute).

The topic tables (topic_tables.py) describe the system per role group, so they need the settings a
section topic is about as values, not sentences: which time source a host follows, its fallback peers
and their state, how often it polls, its stratum; which DNS servers it asks first and second. This
module reads them from the captures and writes ``<work_dir>/hosts/host_settings.csv``:

    host, topic, attribute, value, capture, source, excerpt

Every value carries its capture file and line, so a table cell traces back to the capture. Only the
newest capture of a host counts. Standard library only.

    python3 -m csa_docx.host_settings build --work-dir <work_dir>
    python3 -m csa_docx.host_settings show  --work-dir <work_dir> [--topic time] [HOST]
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

FIELDS = ["host", "topic", "attribute", "value", "capture", "source", "excerpt"]
CAPTURE_FOLDER_RE = re.compile(r"^(?P<prefix>[A-Za-z0-9]+)_discovery_(?P<host>[A-Za-z0-9-]+)_(?P<ts>\d{8}T\d{6}Z)$")
_STRATUM = re.compile(r"^\s*Stratum:\s*(\d+)")
_REF = re.compile(r"^\s*ReferenceId:.*?\(source IP:\s*(\d{1,3}(?:\.\d{1,3}){3})\)")
_SOURCE = re.compile(r"^\s*Source:\s*(\S+)\s*$")
_POLL = re.compile(r"^\s*Poll Interval:\s*\d+\s*\((\d+)s\)")
_PEER = re.compile(r"^\s*Peer:\s*(\S+)\s*$")
_STATE = re.compile(r"^\s*State:\s*(\S+)")
_SHORT = re.compile(r"^[A-Za-z][A-Za-z0-9-]{2,30}$")


def _capture(rel: str):
    folder = Path(rel).parent.name
    m = CAPTURE_FOLDER_RE.match(folder)
    return (m["host"].upper(), folder, m["ts"]) if m else (None, None, None)


def _short(name: str) -> str:
    """ROTPRDSRV122.internal.qr.com.au -> ROTPRDSRV122; time.windows.com stays as it is (not a host name)."""
    name = name.split(",")[0].strip()
    first = name.split(".")[0]
    if _SHORT.match(first) and re.search(r"\d", first):
        return first.upper()
    return name


def seconds(n: int) -> str:
    return f"{n:,} s"


def time_settings(text: str) -> list[tuple[str, str, int]]:
    """(attribute, value, line offset) from one `w32tm /query /status` + `/query /peers` output.

    Attributes: time.service, time.stratum (the host's own), time.source (``NAME (IP)``),
    time.source_stratum (the active peer's), time.poll (the host's poll interval), time.fallback
    (every configured peer that is not the active source, with its state; ``None`` when there is none).
    Text that is not w32tm output gives []."""
    lines = text.splitlines()
    if not any("Leap Indicator:" in x for x in lines) or not any(_STRATUM.match(x) for x in lines):
        return []
    out: list[tuple[str, str, int]] = []
    peers_at = next((i for i, x in enumerate(lines) if x.strip().startswith("#Peers")), len(lines))
    ref_ip, source, src_line = "", "", -1
    for i, x in enumerate(lines[:peers_at]):
        if (m := _STRATUM.match(x)) and not any(a == "time.stratum" for a, _, _ in out):
            out.append(("time.stratum", m[1], i))
        elif m := _REF.match(x):
            ref_ip = m[1]
        elif m := _SOURCE.match(x):
            source, src_line = m[1], i
        elif m := _POLL.match(x):
            out.append(("time.poll", seconds(int(m[1])), i))
    first = next((i for i, x in enumerate(lines) if "Leap Indicator:" in x), 0)
    out.append(("time.service", "Windows Time Service", first))
    if source:
        name = _short(source)
        out.append(("time.source", f"{name} ({ref_ip})" if ref_ip and name != ref_ip else name, src_line))
    peers: list[dict] = []
    for i in range(peers_at, len(lines)):
        if m := _PEER.match(lines[i]):
            peers.append({"name": m[1].split(",")[0], "line": i, "state": "", "stratum": ""})
        elif peers and (m := _STATE.match(lines[i])) and not peers[-1]["state"]:
            peers[-1]["state"] = m[1].lower()
        elif peers and (m := _STRATUM.match(lines[i])) and not peers[-1]["stratum"]:
            peers[-1]["stratum"] = m[1]
    active = [p for p in peers if source and p["name"].lower() == source.lower()]
    if active and active[0]["stratum"]:
        out.append(("time.source_stratum", active[0]["stratum"], active[0]["line"]))
    others = [p for p in peers if p not in active]
    if peers_at < len(lines):
        if others:
            out.append(("time.fallback", ", ".join(f"{_short(p['name'])} ({p['state'] or 'state not shown'})" for p in others),
                        others[0]["line"]))
        else:
            out.append(("time.fallback", "None", peers_at))
    return out


def from_chunks(records) -> list[dict]:
    """host_settings rows from capture chunks ``[(rel_path, line_start, text)]`` (time status files).
    Per host only the newest capture counts; a file split over several chunks is read in order."""
    best: dict[tuple, tuple] = {}
    chunks: dict[str, list] = defaultdict(list)
    for rel, start, text in records:
        host, folder, ts = _capture(rel)
        if not host or "time_status" not in Path(rel).name:
            continue
        chunks[rel].append((start or 0, text or ""))
        k = (host, Path(rel).name)
        if k not in best or ts > best[k][0]:
            best[k] = (ts, rel, folder)
    out = []
    for (host, fname) in sorted(best):
        _ts, rel, folder = best[(host, fname)]
        parts = sorted(chunks[rel])
        start = parts[0][0]
        text = "\n".join(t for _, t in parts)
        lines = text.splitlines()
        for attr, value, off in time_settings(text):
            out.append({"host": host, "topic": "time", "attribute": attr, "value": value, "capture": folder,
                        "source": f"{folder}/{fname} line {start + off}",
                        "excerpt": lines[off].strip() if 0 <= off < len(lines) else ""})
    return out


def from_services(rows: list[dict]) -> list[dict]:
    """dns.primary / dns.secondary from host_services.csv rows (resolver captures, preference 1 and 2)."""
    out = []
    for r in rows:
        if r.get("service") != "dns" or str(r.get("preference")) not in ("1", "2"):
            continue
        ip, name = r.get("server_ip", ""), (r.get("server_host") or "").upper()
        out.append({"host": r["client_host"], "topic": "dns",
                    "attribute": "dns.primary" if str(r["preference"]) == "1" else "dns.secondary",
                    "value": f"{name} ({ip})" if name else ip, "capture": r.get("capture", ""),
                    "source": r.get("source", ""), "excerpt": r.get("excerpt", "")})
    return out


def latest_texts(con, like: str, keep_empty: bool = False) -> dict[str, dict]:
    """{HOST: {"folder", "fname", "start", "text"}} for the newest capture per host of the files whose path
    matches ``like`` (SQL LIKE, e.g. '%23_process_connection_mapping%'); a file split over chunks is joined.
    An empty file counts only with ``keep_empty`` (an empty group-membership listing means no members; an empty
    services listing means the capture failed)."""
    try:
        rows = con.execute(
            "select f.rel_path, m.line_start, cc.c0 from files f "
            "left join chunk_map m on m.file_id = coalesce(f.dup_of, f.file_id) left join chunks_content cc on cc.id = m.chunk_id "
            "where f.status in ('indexed', 'duplicate') and (f.archived = 0 or f.archived is null) and f.rel_path like ?",
            (like,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    chunks: dict[str, list] = defaultdict(list)
    best: dict[str, tuple] = {}
    for rel, start, text in rows:
        host, folder, ts = _capture(rel)
        if not host:
            continue
        chunks[rel].append((start or 0, text or ""))
        if host not in best or ts > best[host][0]:
            best[host] = (ts, rel, folder)
    out = {}
    for host, (_ts, rel, folder) in best.items():
        parts = sorted(chunks[rel])
        text = "\n".join(t for _, t in parts)
        if text.strip() or keep_empty:
            out[host] = {"folder": folder, "fname": Path(rel).name, "start": parts[0][0], "text": text}
    return out


_DB_SERVICE = re.compile(r"^\s*(MSSQL\$\S+|MSSQLSERVER|MySQL\S*|postgresql\S*|OracleService\S*)\s+(.+?)\s+Running\b", re.I)
_DEFAULT_SHARE = re.compile(r"^(?:[A-Z]\$|ADMIN\$|IPC\$|print\$)$", re.I)
TRANSFER_TOOLS = re.compile(r"\b(WinSCP|FileZilla|Tftpd\d*|SolarWinds TFTP|PuTTY|SuperPuTTY|ExtraPuTTY|Cyberduck|rclone|AzCopy|"
                            r"Core ?FTP|SmartFTP|Bitvise|MobaXterm|TeraCopy|GoodSync|Syncthing|Dropbox|Google Drive|Box Drive)\b", re.I)
_REMOVABLE = re.compile(r"Removable (?:Storage|Disks?)|RemovableStorageDevices|Deny_All|CD and DVD|WPD Devices", re.I)


def _row(host, attr, value, cap, off, lines, topic):
    excerpt = " | ".join(lines[o].strip() for o in (off if isinstance(off, list) else [off]) if 0 <= o < len(lines)) if off != [] else ""
    first = off[0] if isinstance(off, list) and off else (off if not isinstance(off, list) else 0)
    return {"host": host, "topic": topic, "attribute": attr, "value": value, "capture": cap["folder"],
            "source": f"{cap['folder']}/{cap['fname']} line {cap['start'] + first}" if excerpt else f"{cap['folder']}/{cap['fname']}",
            "excerpt": excerpt}


def storage_settings(caps: dict[str, dict[str, dict]]) -> list[dict]:
    """storage.* and transfer.* rows. ``caps`` maps a capture kind to latest_texts() output:
    services (32_services_inventory), sql (52_*sql*), shares (42_local_shares), software (67_installed_software),
    gpo (61_gpresult_verbose), proxy (15_proxy_configuration). An absence keeps an empty excerpt: it is a
    searched-and-not-found fact, never a quoted one."""
    out = []
    hosts = sorted({h for k in caps.values() for h in k})
    for h in hosts:
        found, offs, cap0 = [], [], None
        for kind in ("sql", "services"):
            cap = caps.get(kind, {}).get(h)
            if not cap:
                continue
            lines = cap["text"].splitlines()
            for i, l in enumerate(lines):
                m = _DB_SERVICE.match(l)
                if m and m.group(2).strip() not in found:
                    found.append(m.group(2).strip()); offs.append(i); cap0 = cap0 or (cap, lines)
            if found:
                break
        if not found and (caps.get("sql", {}).get(h) or caps.get("services", {}).get(h)):
            cap = caps.get("sql", {}).get(h) or caps.get("services", {}).get(h)
            out.append(_row(h, "storage.database", "None found", cap, [], cap["text"].splitlines(), "storage"))
        if found and cap0:
            sql = caps.get("sql", {}).get(h)
            ags = []
            if sql:
                ags = sorted({l.strip() for l in sql["text"].splitlines() if l.strip().endswith("_AG")})
            out.append(_row(h, "storage.database", ", ".join(found) + (f"; availability group {', '.join(ags)}" if ags else ""),
                            cap0[0], offs, cap0[1], "storage"))
        cap = caps.get("shares", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            names = [(i, l.split(":", 1)[1].strip()) for i, l in enumerate(lines) if re.match(r"^\s*Name\s*:", l)]
            paths = {i: l.split(":", 1)[1].strip() for i, l in enumerate(lines) if re.match(r"^\s*Path\s*:", l)}
            extra = [(i, n) for i, n in names if not _DEFAULT_SHARE.match(n)]
            if extra:
                val = ", ".join(f"{n} ({paths.get(i + 1, '')})".replace(" ()", "") for i, n in extra)
                out.append(_row(h, "storage.shares", val, cap, [i for i, _ in extra], lines, "storage"))
            elif names:
                out.append(_row(h, "storage.shares", "Default and administrative shares only", cap,
                                [i for i, _ in names], lines, "storage"))
        cap = caps.get("software", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            hits = [(i, re.sub(r"^\s*DisplayName\s*:\s*", "", l).strip()) for i, l in enumerate(lines)
                    if re.match(r"^\s*DisplayName\s*:", l) and TRANSFER_TOOLS.search(l)]
            if hits:
                out.append(_row(h, "transfer.tools", ", ".join(dict.fromkeys(n for _, n in hits)), cap, [i for i, _ in hits], lines, "transfer"))
            else:
                out.append(_row(h, "transfer.tools", "None found", cap, [], lines, "transfer"))
        cap = caps.get("gpo", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            hits = [i for i, l in enumerate(lines) if _REMOVABLE.search(l)]
            if hits:
                out.append(_row(h, "transfer.removable", "; ".join(lines[i].strip() for i in hits[:3]), cap, hits[:3], lines, "transfer"))
            else:
                out.append(_row(h, "transfer.removable", "Not set in applied Group Policy", cap, [], lines, "transfer"))
        cap = caps.get("proxy", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            i = next((i for i, l in enumerate(lines) if "Direct access (no proxy server)" in l), None)
            j = next((i for i, l in enumerate(lines) if re.search(r"Proxy Server\(s\)\s*:", l)), None)
            if j is not None:
                out.append(_row(h, "transfer.proxy", lines[j].split(":", 1)[1].strip(), cap, j, lines, "transfer"))
            elif i is not None:
                out.append(_row(h, "transfer.proxy", "Direct, no WinHTTP proxy", cap, i, lines, "transfer"))
    return out


CATALOGUE = Path(__file__).resolve().parents[2] / "references" / "product-catalogue.json"
_APPCONTROL = re.compile(r"AppLocker|Software Restriction Polic|Application Control Polic|Code Integrity|WDAC", re.I)


def catalogue() -> dict:
    try:
        return json.loads(CATALOGUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"categories": {}, "products": []}


def service_blocks(text: str) -> list[dict]:
    """Win32_Service blocks (Name / DisplayName / State / StartMode / StartName / PathName), each with the line
    offset of every field so a value can be quoted from the capture."""
    out, cur = [], None
    for i, l in enumerate(text.splitlines()):
        m = re.match(r"^\s*(Name|DisplayName|State|StartMode|StartName|PathName)\s*:\s*(.*?)\s*$", l)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if k == "Name":
            cur = {"Name": v, "_lines": {"Name": i}}
            out.append(cur)
        elif cur is not None and k not in cur:
            cur[k] = v
            cur["_lines"][k] = i
    return out


def _product_match(p: dict, b: dict) -> bool:
    if p.get("state") and (b.get("State") or "").lower() != p["state"].lower():
        return False
    for key, field in (("service", "Name"), ("display", "DisplayName"), ("path", "PathName")):
        if p.get(key) and re.search(p[key], b.get(field) or "", re.I):
            return True
    return False


def agent_settings(caps: dict[str, dict[str, dict]], cat: dict | None = None) -> list[dict]:
    """agent.<category> rows (products found, from the services capture, else installed software), agent.backup_account
    (the account each backup service runs as) and appcontrol.policy (Group Policy). Absent categories are recorded as
    'None found' with no quote when the services capture exists."""
    cat = cat or catalogue()
    prods = cat.get("products", [])
    out = []
    hosts = sorted(set(caps.get("services", {})) | set(caps.get("software", {})))
    for h in hosts:
        scap, wcap = caps.get("services", {}).get(h), caps.get("software", {}).get(h)
        blocks = service_blocks(scap["text"]) if scap else []
        slines = scap["text"].splitlines() if scap else []
        wl = wcap["text"].splitlines() if wcap else []
        soft = [(i, re.sub(r"^\s*DisplayName\s*:\s*", "", l).strip()) for i, l in enumerate(wl) if re.match(r"^\s*DisplayName\s*:", l)]
        for category in cat.get("categories", {}):
            found, offs, accounts, acc_offs = [], [], [], []
            for p in (x for x in prods if x["category"] == category):
                hits = [b for b in blocks if _product_match(p, b)]
                if not hits:
                    continue
                # one entry per product: running if any of its services runs, else the first service's state
                run = [b for b in hits if (b.get("State") or "").lower() == "running"]
                b0 = (run or hits)[0]
                state, mode = (b0.get("State") or "").lower(), (b0.get("StartMode") or "").lower()
                found.append(p["product"] + ("" if run else f" ({', '.join(x for x in (state, mode) if x)})"))
                offs += [b["_lines"]["Name"] for b in hits]
                if category == "backup":
                    for b in hits:
                        if b.get("StartName"):
                            accounts.append(f"{b.get('DisplayName') or b['Name']}: {b['StartName']}")
                            acc_offs.append(b["_lines"].get("StartName", b["_lines"]["Name"]))
            if found:
                out.append(_row(h, f"agent.{category}", ", ".join(found), scap, offs, slines, "agents"))
                if accounts:
                    out.append(_row(h, "agent.backup_account", "; ".join(accounts), scap, acc_offs, slines, "agents"))
                continue
            hits = [(i, n) for p in prods if p["category"] == category and p.get("software")
                    for i, n in soft if re.search(p["software"], n, re.I)]
            if hits:
                out.append(_row(h, f"agent.{category}", ", ".join(dict.fromkeys(n for _, n in hits)), wcap,
                                [i for i, _ in hits], wl, "agents"))
            elif scap:
                out.append(_row(h, f"agent.{category}", "None found", scap, [], slines, "agents"))
                if category == "backup":
                    out.append(_row(h, "agent.backup_account", "No backup service", scap, [], slines, "agents"))
        gcap = caps.get("gpo", {}).get(h)
        if gcap:
            gl = gcap["text"].splitlines()
            hits = [i for i, l in enumerate(gl) if _APPCONTROL.search(l)]
            out.append(_row(h, "appcontrol.policy", "; ".join(gl[i].strip() for i in hits[:3]) if hits
                            else "Not set in applied Group Policy", gcap, hits[:3], gl, "agents"))
    return out


AGENT_CAPTURES = {"services": "%32_services_inventory%", "software": "%67_installed_software%", "gpo": "%61_gpresult_verbose%"}


# ---- identity and admin access (3.2, 3.8, 3.16) -------------------------------------------------------------
_BUILTIN_ACCOUNT = re.compile(r"^\s*(LocalSystem|NT AUTHORITY\\.*|NT SERVICE\\.*|\.?\\?LocalService|\.?\\?NetworkService)?\s*$", re.I)
ADMIN_PORTS = {"3389": "RDP 3389", "5985": "WinRM 5985", "5986": "WinRM 5986 (HTTPS)", "22": "SSH 22", "23": "Telnet 23",
               "5900": "VNC 5900", "5800": "VNC 5800"}
_LISTEN_LINE = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\d+)\s*$")


def _list(xs: list[str]) -> str:
    """'a', 'a and b', 'a, b and c' (a value inside a cell; the top-level list separator stays ', ')."""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def member_table(text: str) -> list[tuple[int, str, str, str]]:
    """Rows of a fixed-width PowerShell table (Get-LocalGroupMember): [(line, Name, ObjectClass, PrincipalSource)].
    Columns come from the dash underline, so a name with single spaces ('Aurizon Server MOE Administrators')
    keeps every word and never takes the next column."""
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if re.match(r"^\s*-{3,}(\s+-{3,})+\s*$", l):
            spans = [m.span() for m in re.finditer(r"-+", l)]
            out = []
            for j in range(i + 1, len(lines)):
                row = lines[j]
                if not row.strip():
                    continue
                cells = []
                for k, (s, _e) in enumerate(spans):
                    end = spans[k + 1][0] if k + 1 < len(spans) else len(row)
                    cells.append(row[s:end].strip())
                cells += [""] * (3 - len(cells))
                out.append((j, cells[0], cells[1], cells[2]))
            return out
    return []


def _member_name(name: str, host: str, source: str) -> str:
    """'ROKPRDOPS110\\casuser' (local) -> 'casuser (local)'; domain names stay as captured."""
    pre, _, rest = name.partition("\\")
    if rest and (pre.upper() == host.upper() or source.lower() == "local"):
        return f"{rest} (local)"
    return name


def local_users(text: str) -> list[tuple[int, str]]:
    """Enabled local accounts from Get-LocalUser blocks: [(Name line, name)]."""
    out, cur = [], None
    for i, l in enumerate(text.splitlines()):
        m = re.match(r"^\s*(Name|Enabled)\s*:\s*(.*?)\s*$", l)
        if not m:
            continue
        if m.group(1) == "Name":
            cur = (i, m.group(2))
        elif cur and m.group(2).lower() == "true":
            out.append(cur)
            cur = None
    return out


_DOMAIN_LINE = re.compile(r"^\s*(\S+)\s+(True|False)\s*$")


_ADMIN_SERVICES = {"TermService": "RDP", "sshd": "SSH", "FreeSSHDService": "SSH", "OpenSSHd": "SSH",
                   "uvnc_service": "VNC", "tvnserver": "VNC", "vncserver": "VNC", "WinRM": "WinRM"}
_ADMIN_PORT_PROTO = {"3389": "RDP", "5985": "WinRM", "5986": "WinRM", "22": "SSH", "23": "Telnet", "5900": "VNC", "5800": "VNC"}


def service_pids(text: str) -> dict[str, list[str]]:
    """{pid: [service names]} from `tasklist /svc` (24_tasklist_services); a wrapped service list continues on
    lines that carry no image name or PID."""
    out: dict[str, list[str]] = {}
    last = None
    for l in text.splitlines():
        m = re.match(r"^(\S.*?)\s+(\d+)\s+(.*?)\s*$", l)
        if m and not l.startswith(" "):
            last = m.group(2)
            out[last] = [x.strip() for x in m.group(3).split(",") if x.strip() and x.strip() != "N/A"]
        elif last and l.startswith(" ") and l.strip() and not l.strip().startswith("="):
            out[last] += [x.strip() for x in l.split(",") if x.strip()]
    return out


def admin_listeners(lines: list[str], tasks: dict[str, list[str]]) -> list[tuple[str, str, int]]:
    """[(protocol, port, line)] of remote administration listeners in 20_listening_ports: by the owning service
    (TermService on any port is RDP, so an alternate RDP port is found) and by well-known port."""
    out = []
    for i, l in enumerate(lines):
        m = _LISTEN_LINE.match(l)
        if not m or m.group(1).startswith("127.") or m.group(1) == "::1":
            continue
        port, pid = m.group(2), m.group(3)
        proto = next((_ADMIN_SERVICES[s_] for s_ in tasks.get(pid, []) if s_ in _ADMIN_SERVICES), None)
        proto = proto or _ADMIN_PORT_PROTO.get(port)
        if proto and (proto != "WinRM" or port in ("5985", "5986")):
            out.append((proto, port, i))
    return out


def identity_settings(caps: dict[str, dict[str, dict]]) -> list[dict]:
    """identity.* and admin.* rows. ``caps`` maps a kind to latest_texts() output: auth (54_auth_configs),
    kerberos (56_kerberos_ticket_detail), users (44_local_users), admins (46_local_admins_membership),
    rdp (47_remote_desktop_users_membership), services (32_services_inventory), listen (20_listening_ports).
    A capture that holds no entry gives 'None found', 'None enabled' or 'No members' with no quote."""
    out = []
    hosts = sorted({h for k in caps.values() for h in k})
    for h in hosts:
        cap = caps.get("auth", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            j = next((i for i, l in enumerate(lines) if _DOMAIN_LINE.match(l)), None)
            if j is not None:
                dom, member = _DOMAIN_LINE.match(lines[j]).groups()
                out.append(_row(h, "identity.domain", dom if member == "True" else f"Workgroup {dom}", cap, j, lines, "identity"))
        kcap = caps.get("kerberos", {}).get(h) or cap
        if kcap:
            lines = kcap["text"].splitlines()
            kdc = [(i, _short(l.split(":", 1)[1].strip())) for i, l in enumerate(lines) if re.match(r"^\s*Kdc Called:", l)]
            enc = [(i, l.split(":", 1)[1].strip()) for i, l in enumerate(lines) if re.match(r"^\s*KerbTicket Encryption Type:", l)]
            if kdc:
                names = list(dict.fromkeys(n for _, n in kdc))
                out.append(_row(h, "identity.kdc", ", ".join(names), kcap,
                                [next(i for i, n in kdc if n == x) for x in names], lines, "identity"))
            else:
                out.append(_row(h, "identity.kdc", "No Kerberos tickets in capture", kcap, [], lines, "identity"))
            if enc:
                types = list(dict.fromkeys(re.sub(r"-CTS-HMAC-SHA1-96$", "", t) for _, t in enc))
                out.append(_row(h, "identity.kerberos", ", ".join(types), kcap,
                                [next(i for i, t in enc if t.startswith(x)) for x in types], lines, "identity"))
        cap = caps.get("users", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            u = local_users(cap["text"])
            out.append(_row(h, "identity.local_users", ", ".join(n for _, n in u) if u else "None enabled", cap,
                            [i for i, _ in u], lines, "identity"))
        cap = caps.get("services", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            acc: dict[str, list] = {}
            for b in service_blocks(cap["text"]):
                sn = b.get("StartName", "")
                if sn and not _BUILTIN_ACCOUNT.match(sn):
                    acc.setdefault(sn, []).append(b)
            if acc:
                val = ", ".join(f"{a} ({_list([x['Name'] for x in bs[:3]] + (['others'] if len(bs) > 3 else []))})"
                                for a, bs in acc.items())
                offs = [b["_lines"].get("StartName", b["_lines"]["Name"]) for bs in acc.values() for b in bs[:3]]
                out.append(_row(h, "identity.service_accounts", val, cap, offs, lines, "identity"))
            else:
                out.append(_row(h, "identity.service_accounts", "Built-in accounts only", cap, [], lines, "identity"))
        for kind, attr in (("admins", "admin.local_admins"), ("rdp", "admin.rdp_users")):
            cap = caps.get(kind, {}).get(h)
            if not cap:
                continue
            lines = cap["text"].splitlines()
            rows = member_table(cap["text"])
            out.append(_row(h, attr, ", ".join(_member_name(n, h, s) for _, n, _c, s in rows) if rows else "No members", cap,
                            [i for i, *_ in rows], lines, "admin"))
        cap = caps.get("listen", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            tasks = service_pids((caps.get("tasks", {}).get(h) or {}).get("text", ""))
            found = admin_listeners(lines, tasks)
            order = ["RDP", "WinRM", "SSH", "Telnet", "VNC"]
            byproto: dict[str, list[str]] = {}
            offs = []
            for proto, port, off in sorted(found, key=lambda x: (order.index(x[0]), int(x[1]))):
                if port not in byproto.setdefault(proto, []):
                    byproto[proto].append(port)
                    offs.append(off)
            val = ", ".join(f"{k} {_list(v)}" for k, v in byproto.items())
            out.append(_row(h, "admin.listeners", val or "None found", cap, offs, lines, "admin"))
            rdp = [(port, off) for proto, port, off in found if proto == "RDP"]
            if rdp:
                ports = list(dict.fromkeys(p_ for p_, _ in rdp))
                out.append(_row(h, "admin.rdp_port", ", ".join(ports), cap,
                                [next(o for p_, o in rdp if p_ == x) for x in ports], lines, "admin"))
            elif tasks:
                out.append(_row(h, "admin.rdp_port", "Not listening", cap, [], lines, "admin"))
    return out


IDENTITY_CAPTURES = {"auth": "%54_auth_configs%", "kerberos": "%56_kerberos_ticket_detail%", "users": "%44_local_users%",
                     "admins": "%46_local_admins_membership%", "rdp": "%47_remote_desktop_users_membership%",
                     "services": "%32_services_inventory%", "listen": "%20_listening_ports%",
                     "tasks": "%24_tasklist_services%"}


# ---- platform and patch facts (3.1, 3.10, 3.15) ------------------------------------------------------------
LIFECYCLE = Path(__file__).resolve().parents[2] / "references" / "os-lifecycle.json"
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(\d{1,2})-([A-Za-z]{3})-(\d{2,4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_HOTFIX = re.compile(r"\b(KB\d{6,8})\b")


def lifecycle() -> list[dict]:
    try:
        return json.loads(LIFECYCLE.read_text(encoding="utf-8")).get("products", [])
    except (OSError, ValueError):
        return []


def hotfix_dates(text: str) -> list[tuple[int, str, tuple[int, int, int]]]:
    """[(line, KB, (year, month, day))] from a Get-HotFix listing. The day/month order of slash dates is worked out
    for the whole file (a first number over 12 means day first, a second number over 12 means month first; with
    neither, day first as Australian hosts write it). '03-Jun-26' and '2026-06-03' are read as they are."""
    rows = []
    for i, l in enumerate(text.splitlines()):
        kb, d = _HOTFIX.search(l), _DATE.search(l)
        if kb and d:
            rows.append((i, kb.group(1), d))
    slash = [d for _, _, d in rows if d.group(1)]
    month_first = any(int(d.group(2)) > 12 for d in slash) and not any(int(d.group(1)) > 12 for d in slash)
    out, seen = [], set()
    for i, kb, d in rows:
        if d.group(1):
            a, b, y = int(d.group(1)), int(d.group(2)), int(d.group(3))
            day, mon = (b, a) if month_first else (a, b)
        elif d.group(4):
            day, mon, y = int(d.group(4)), _MONTHS.get(d.group(5).lower(), 0), int(d.group(6))
            y += 2000 if y < 100 else 0
        else:
            y, mon, day = int(d.group(7)), int(d.group(8)), int(d.group(9))
        if 1 <= mon <= 12 and 1 <= day <= 31 and (kb, y, mon, day) not in seen:
            seen.add((kb, y, mon, day))
            out.append((i, kb, (y, mon, day)))
    return out


def _kv(lines: list[str], key: str) -> tuple[int, str] | None:
    for i, l in enumerate(lines):
        m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", l)
        if m:
            return i, m.group(1)
    return None


def platform_settings(caps: dict[str, dict[str, dict]], life: list[dict] | None = None) -> list[dict]:
    """platform.* and patch.* rows. ``caps``: summary (00_host_summary), wu (70_windows_update_config),
    hotfix (71_installed_hotfixes), mecm (72_sccm_mecm_check)."""
    life = lifecycle() if life is None else life
    out = []
    hosts = sorted({h for k in caps.values() for h in k})
    for h in hosts:
        cap = caps.get("summary", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            cp, bn = _kv(lines, "Caption"), _kv(lines, "BuildNumber")
            if cp:
                os_ = re.sub(r"^Microsoft\s+", "", cp[1])
                out.append(_row(h, "platform.os", os_ + (f" (build {bn[1]})" if bn else ""), cap,
                                [cp[0]] + ([bn[0]] if bn else []), lines, "platform"))
                p = next((x for x in life if x["match"].lower() in os_.lower()), None)
                if p:
                    out.append(_row(h, "platform.support", f"Extended support to {p['extended_end']}", cap, cp[0], lines, "platform"))
            mf, md = _kv(lines, "Manufacturer"), _kv(lines, "Model")
            if mf:
                mfr, model = mf[1], (md[1] if md else "")
                if re.search(r"VMware", mfr, re.I):
                    val = "VMware virtual machine"
                elif re.search(r"Microsoft", mfr, re.I) and re.search(r"Virtual", model, re.I):
                    val = "Hyper-V virtual machine"
                elif re.search(r"QEMU|KVM|Xen|innotek|VirtualBox|Nutanix", mfr + model, re.I):
                    val = f"Virtual machine ({mfr} {model})".strip()
                else:
                    maker = re.sub(r",? Inc\.?$", "", mfr)
                    val = f"Physical, {maker} {model}".strip()
                out.append(_row(h, "platform.hardware", val, cap, [mf[0]] + ([md[0]] if md else []), lines, "platform"))
        cap = caps.get("hotfix", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            hf = hotfix_dates(cap["text"])
            if hf:
                i, kb, (y, m, d) = max(hf, key=lambda x: x[2])
                out.append(_row(h, "patch.latest", f"{kb} on {d:02d}/{m:02d}/{y}", cap, i, lines, "patch"))
            else:
                out.append(_row(h, "patch.latest", "None found", cap, [], lines, "patch"))
        cap = caps.get("wu", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            ws, na = _kv(lines, "WUServer"), _kv(lines, "NoAutoUpdate")
            if ws and ws[1]:
                m = re.match(r"^\w+://([^/:]+)(?::(\d+))?", ws[1])
                host_, port = (_short(m.group(1)), m.group(2)) if m else (ws[1], None)
                out.append(_row(h, "patch.source", f"WSUS on {host_}" + (f" port {port}" if port else ""), cap, ws[0], lines, "patch"))
            else:
                out.append(_row(h, "patch.source", "No WSUS policy (Windows Update)", cap, [], lines, "patch"))
            if na:
                out.append(_row(h, "patch.auto", "Automatic Updates off" if na[1] == "1" else "Automatic Updates on",
                                cap, na[0], lines, "patch"))
        cap = caps.get("mecm", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            cv = _kv(lines, "ClientVersion")
            run = next((i for i, l in enumerate(lines) if re.match(r"^\s*Running\s+ccmexec\b", l, re.I)), None)
            if cv and cv[1]:
                out.append(_row(h, "patch.client", f"MECM client {cv[1]}" + ("" if run is not None else " (service not running)"),
                                cap, [x for x in (run, cv[0]) if x is not None], lines, "patch"))
            else:
                out.append(_row(h, "patch.client", "None found", cap, [], lines, "patch"))
    return out


PLATFORM_CAPTURES = {"summary": "%00_host_summary%", "wu": "%70_windows_update_config%", "hotfix": "%71_installed_hotfixes%",
                     "mecm": "%72_sccm_mecm_check%"}


# ---- network placement and host firewall (3.6, 3.13, 3.17) --------------------------------------------------
_CORE_PROCS = {"system", "svchost", "lsass", "wininit", "services", "spoolsv"}
_CORE_PORTS = {"80", "135", "139", "443", "445", "3387", "5985", "5986", "8005", "47001"}
_BUILTIN_RULE = re.compile(
    r"^@\{|-In\)\s*$|\(In\)\s*$|^(Cortana|Desktop App Web Viewer|Failover Cluster|File and Printer Sharing|SMB Witness|"
    r"Windows Backup|TargetMgr Service|Remote Desktop|Windows Remote Management|Core Networking|Network Discovery|"
    r"Microsoft Edge|Captive Portal|Windows Defender|Windows Management Instrumentation|Remote Service Management|"
    r"Remote Event Log|Remote Scheduled Tasks|Remote Volume Management|DFS |Distributed Transaction|iSCSI|"
    r"Key Management|Netlogon|Performance Logs|Routing and Remote|Secure Socket Tunneling|SNMP Trap|"
    r"Virtual Machine Monitoring|Windows Firewall Remote|Windows Media|Wireless|AllJoyn|BranchCache|Cast to Device|"
    r"Connected Devices|Delivery Optimization|DIAL protocol|mDNS|Microsoft Media Foundation|Proximity|Shell Input|"
    r"Software Load Balancer|Wi-Fi|Work or school|Your account|Email and accounts|Windows Shell Experience|Xbox|"
    r"Feedback Hub|Windows Collaboration|Windows Peer to Peer|Hyper-V|Cloud Identity|Microsoft Photos|Get Help|"
    r"Windows Calculator|Windows Camera|Microsoft Store|Start|Narrator|Cloud Experience|Windows Security)", re.I)


def net_settings(caps: dict[str, dict[str, dict]], zone_of=None) -> list[dict]:
    """net.address (IPv4 with prefix, link-local and loopback left out), net.zone (zones.csv, when given) and
    net.gateway (default route). ``caps``: ipcfg (12_ip_interface_config), routes (11_ip_route)."""
    out = []
    for h in sorted({h for k in caps.values() for h in k}):
        cap = caps.get("ipcfg", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            addrs = []
            for i, l in enumerate(lines):
                m = re.match(r"^\s*IPAddress\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})\s*$", l)
                if not m or m.group(1).startswith(("169.254.", "127.")):
                    continue
                pl = next((re.match(r"^\s*PrefixLength\s*:\s*(\d+)", x) for x in lines[i + 1:i + 3]
                           if re.match(r"^\s*PrefixLength\s*:", x)), None)
                addrs.append((i, m.group(1) + (f"/{pl.group(1)}" if pl else "")))
            if addrs:
                out.append(_row(h, "net.address", ", ".join(dict.fromkeys(a for _, a in addrs)), cap,
                                [i for i, _ in addrs], lines, "network"))
                if zone_of:
                    z = zone_of(addrs[0][1].split("/")[0])
                    if z:
                        out.append(_row(h, "net.zone", z, cap, addrs[0][0], lines, "network"))
        cap = caps.get("routes", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            j = next((i for i, l in enumerate(lines) if re.match(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+\d", l)), None)
            if j is not None:
                out.append(_row(h, "net.gateway", lines[j].split()[2], cap, j, lines, "network"))
    return out


def _blocks_kv(text: str) -> list[dict]:
    out, cur = [], {}
    for i, l in enumerate(text.splitlines()):
        m = re.match(r"^\s*([A-Za-z]+)\s*:\s*(.*?)\s*$", l)
        if not m:
            if cur:
                out.append(cur)
                cur = {}
            continue
        if m.group(1) in cur:
            out.append(cur)
            cur = {}
        cur[m.group(1)] = m.group(2)
        cur.setdefault("_line", i)
    if cur:
        out.append(cur)
    return out


def firewall_settings(caps: dict[str, dict[str, dict]]) -> list[dict]:
    """fw.profiles (31), fw.custom_inbound (enabled inbound Allow rules that are not stock Windows rules, 33) and
    fw.exposed (what listens on every interface, 20 with process names from 10 and services from 24). Windows'
    own processes count only on their well-known ports; dynamic ports from 49152 up are left out, except RDP."""
    out = []
    for h in sorted({h for k in caps.values() for h in k}):
        cap = caps.get("profiles", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            rows = []
            for i, l in enumerate(lines):
                m = re.match(r"^\s*(Domain|Private|Public)\s+(True|False)\s+(\S+)\s+(\S+)\s*$", l)
                if m:
                    rows.append((i, *m.groups()))
            if rows:
                off = [r[1] for r in rows if r[2] == "False"]
                ins, outs = {r[3] for r in rows}, {r[4] for r in rows}
                state = "On for all profiles" if not off else ("Off for all profiles" if len(off) == len(rows)
                                                               else f"Off for {_list(off)}")
                acts = []
                for name, vals in (("inbound", ins), ("outbound", outs)):
                    v = vals.pop() if len(vals) == 1 else "mixed"
                    acts.append(f"{name} {'not configured' if v == 'NotConfigured' else v.lower()}")
                defaults = "default actions not set" if acts == ["inbound not configured", "outbound not configured"] \
                    else f"default {acts[0]}, {acts[1]}"
                out.append(_row(h, "fw.profiles", f"{state}, {defaults}", cap,
                                [r[0] for r in rows], lines, "firewall"))
        cap = caps.get("rules", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            names: dict[str, int] = {}
            for b in _blocks_kv(cap["text"]):
                n = b.get("DisplayName", "")
                if (b.get("Enabled") == "True" and b.get("Direction") == "Inbound" and b.get("Action") == "Allow"
                        and n and not _BUILTIN_RULE.search(n)):
                    names.setdefault(n, b["_line"])
            out.append(_row(h, "fw.custom_inbound", ", ".join(names) if names else "None found", cap,
                            list(names.values()), lines, "firewall"))
        cap = caps.get("listen", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            procs = {}
            for l in (caps.get("procs", {}).get(h) or {}).get("text", "").splitlines():
                m = re.match(r"^\s*\d+\s+PID=(\d+)\s+(\S+)", l)
                if m:
                    procs[m.group(1)] = m.group(2)
            tasks = service_pids((caps.get("tasks", {}).get(h) or {}).get("text", ""))
            core: dict[str, int] = {}
            apps: dict[str, list] = {}
            for i, l in enumerate(lines):
                m = _LISTEN_LINE.match(l)
                if not m or m.group(1) not in ("0.0.0.0", "::"):
                    continue
                port, pid = m.group(2), m.group(3)
                name = procs.get(pid, "")
                if "TermService" in tasks.get(pid, []):
                    core.setdefault(f"{port} (RDP)", i)
                elif int(port) >= 49152:
                    continue
                elif name.lower() in _CORE_PROCS or not name:
                    if port in _CORE_PORTS:
                        core.setdefault(f"{port} ({name or 'Windows'})", i)
                else:
                    if port not in [p_ for p_, _ in apps.setdefault(name, [])]:
                        apps[name].append((port, i))
            items = sorted(core.items(), key=lambda kv: int(kv[0].split()[0]))
            for name, ps in sorted(apps.items(), key=lambda kv: int(kv[1][0][0])):
                ports = sorted((p_ for p_, _ in ps), key=int)
                shown = ports[:3] + (["others"] if len(ports) > 3 else [])
                items.append((f"{name} ({_list(shown)})", ps[0][1]))
            out.append(_row(h, "fw.exposed", ", ".join(k for k, _ in items) or "None found", cap,
                            [i for _, i in items], lines, "firewall"))
    return out


NET_CAPTURES = {"ipcfg": "%12_ip_interface_config%", "routes": "%11_ip_route%"}
FIREWALL_CAPTURES = {"profiles": "%31_firewall_profiles%", "rules": "%33_firewall_rules%", "listen": "%20_listening_ports%",
                     "procs": "%10_listeners_by_process%", "tasks": "%24_tasklist_services%"}


# ---- certificates (3.3) -------------------------------------------------------------------------------------
PUBLIC_ROOTS = Path(__file__).resolve().parents[2] / "references" / "public-roots.json"
_CLUSTER_ROOT = re.compile(r"^ClusInfraCert_|^CLIUSR$", re.I)


def _public_roots() -> re.Pattern:
    try:
        pats = json.loads(PUBLIC_ROOTS.read_text(encoding="utf-8")).get("patterns", [])
    except (OSError, ValueError):
        pats = []
    return re.compile("|".join(f"(?:{p})" for p in pats) or r"(?!x)x", re.I)


def _dn(dn: str, key: str) -> str:
    m = re.search(rf"(?:^|,\s*){key}=(\"[^\"]*\"|[^,]+)", dn or "")
    return m.group(1).strip().strip('"') if m else ""


def cert_blocks(text: str) -> list[dict]:
    """Get-ChildItem Cert:\\ blocks (Subject, Issuer, NotBefore, NotAfter, Thumbprint, HasPrivateKey), each with
    the line of every field."""
    out, cur = [], None
    for i, l in enumerate(text.splitlines()):
        m = re.match(r"^\s*(Subject|Issuer|NotBefore|NotAfter|Thumbprint|HasPrivateKey)\s*:\s*(.*?)\s*$", l)
        if not m:
            continue
        if m.group(1) == "Subject" or cur is None:
            cur = {"_lines": {}}
            out.append(cur)
        cur[m.group(1)] = m.group(2)
        cur["_lines"][m.group(1)] = i
    return out


def _dates(values: list[str]) -> list[tuple[int, int, int] | None]:
    """(y, m, d) for each value; the day/month order of slash dates is worked out over the whole list, as for hotfixes."""
    fake = "\n".join(f"KB{1000000 + i} {v}" for i, v in enumerate(values))      # one KB per line: no de-duplication
    got = {i: d for i, _kb, d in hotfix_dates(fake)}
    return [got.get(i) for i in range(len(values))]


def cert_settings(caps: dict[str, dict[str, dict]]) -> list[dict]:
    """cert.machine (the host's own certificate with a private key: issuer and expiry), cert.other (other
    certificates in the machine store; the failover cluster's own CLIUSR certificates are named once; expired at
    capture is said) and cert.private_roots (Trusted Root entries that are not public roots, cluster roots left out).
    ``caps``: my (68_certificates_localmachine_my), root (69_certificates_localmachine_root)."""
    public = _public_roots()
    out = []
    for h in sorted({h for k in caps.values() for h in k}):
        cap = caps.get("my", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            m_ = CAPTURE_FOLDER_RE.match(cap["folder"])
            at = (int(m_.group("ts")[:4]), int(m_.group("ts")[4:6]), int(m_.group("ts")[6:8])) if m_ else None
            certs = cert_blocks(cap["text"])
            ends = _dates([c.get("NotAfter", "") for c in certs])
            mine, other, cluster = [], [], []
            for c, end in zip(certs, ends):
                cn = _dn(c.get("Subject", ""), "CN") or c.get("Subject", "")
                issuer = _dn(c.get("Issuer", ""), "CN") or _dn(c.get("Issuer", ""), "O") or c.get("Issuer", "")
                when = f"{end[2]:02d}/{end[1]:02d}/{end[0]}" if end else c.get("NotAfter", "")
                expired = bool(end and at and end < at)
                line = c["_lines"].get("NotAfter", c["_lines"].get("Subject", 0))
                if cn.split(".")[0].upper() == h.upper() and c.get("HasPrivateKey", "").lower() == "true":
                    mine.append((f"{issuer}, {'expired' if expired else 'expires'} {when}", [c["_lines"]["Subject"], line]))
                elif _CLUSTER_ROOT.match(cn):
                    cluster.append(line)
                else:
                    other.append((f"{cn} from {issuer}, {'expired' if expired else 'expires'} {when}", [c["_lines"]["Subject"], line]))
            out.append(_row(h, "cert.machine", ", ".join(v for v, _ in mine) or "None found", cap,
                            [o for _, offs in mine for o in offs], lines, "certificates"))
            items = [v for v, _ in other] + (["CLIUSR (failover cluster, self-signed)"] if cluster else [])
            offs = [o for _, os_ in other for o in os_] + cluster[:1]
            out.append(_row(h, "cert.other", ", ".join(items) or "None found", cap, offs, lines, "certificates"))
        cap = caps.get("root", {}).get(h)
        if cap:
            lines = cap["text"].splitlines()
            priv: dict[str, int] = {}
            for c in cert_blocks(cap["text"]):
                subj = c.get("Subject", "")
                name = _dn(subj, "CN") or _dn(subj, "OU") or _dn(subj, "O") or subj
                probe = " ".join(x for x in (name, _dn(subj, "O"), _dn(subj, "OU"), subj) if x)
                if not name or _CLUSTER_ROOT.match(name) or public.search(probe):
                    continue
                priv.setdefault(name, c["_lines"]["Subject"])
            names = sorted(priv, key=str.lower)
            out.append(_row(h, "cert.private_roots", ", ".join(names) or "None found", cap,
                            [priv[n] for n in names], lines, "certificates"))
    return out


CERT_CAPTURES = {"my": "%68_certificates_localmachine_my%", "root": "%69_certificates_localmachine_root%"}


STORAGE_CAPTURES = {"services": "%32_services_inventory%", "sql": "%sql_cluster_evidence%", "shares": "%42_local_shares%",
                    "software": "%67_installed_software%", "gpo": "%61_gpresult_verbose%", "proxy": "%15_proxy_configuration%"}


def write(work_dir: Path, rows: list[dict]) -> Path:
    out = Path(work_dir) / "hosts" / "host_settings.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["host"], x["topic"], x["attribute"])):
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return out


def _time_chunks(con) -> list:
    try:
        return con.execute(
            "select f.rel_path, m.line_start, cc.c0 from files f "
            "join chunk_map m on m.file_id = coalesce(f.dup_of, f.file_id) join chunks_content cc on cc.id = m.chunk_id "
            "where f.status in ('indexed', 'duplicate') and (f.archived = 0 or f.archived is null) "
            "and f.rel_path like '%time_status%'").fetchall()
    except sqlite3.OperationalError:
        return []


def build(work_dir: Path, con=None, services: list[dict] | None = None) -> dict:
    """Write host_settings.csv. ``hostmodel.build`` passes its index connection and service rows;
    run on its own, it opens the discovery index and reads hosts/host_services.csv."""
    work_dir = Path(work_dir)
    own = con is None
    if own:
        p = work_dir / "discovery-index.sqlite"
        if not p.is_file():
            return {"status": "ERROR", "message": f"no discovery index at {p}; run `csa index build` first"}
        con = sqlite3.connect(str(p))
    try:
        rows = from_chunks(_time_chunks(con))
        rows += storage_settings({k: latest_texts(con, like) for k, like in STORAGE_CAPTURES.items()})
        rows += agent_settings({k: latest_texts(con, like) for k, like in AGENT_CAPTURES.items()})
        rows += identity_settings({k: latest_texts(con, like, keep_empty=k in ("admins", "rdp"))
                                   for k, like in IDENTITY_CAPTURES.items()})
        rows += platform_settings({k: latest_texts(con, like) for k, like in PLATFORM_CAPTURES.items()})
        try:
            from csa_docx import zones as zones_mod
            zs = zones_mod.for_project(work_dir)
            zone_of = lambda ip: zs.of(ip).get("zone", "")    # noqa: E731
        except Exception:                                      # zones are optional
            zone_of = None
        rows += net_settings({k: latest_texts(con, like) for k, like in NET_CAPTURES.items()}, zone_of)
        rows += firewall_settings({k: latest_texts(con, like) for k, like in FIREWALL_CAPTURES.items()})
        rows += cert_settings({k: latest_texts(con, like) for k, like in CERT_CAPTURES.items()})
    finally:
        if own:
            con.close()
    if services is None:
        sf = work_dir / "hosts" / "host_services.csv"
        services = list(csv.DictReader(sf.open(encoding="utf-8"))) if sf.is_file() else []
    rows += from_services(services)
    out = write(work_dir, rows)
    return {"status": "OK", "rows": len(rows), "hosts": len({r["host"] for r in rows}), "out": str(out)}


def load(work_dir: Path, merge_isolation: bool = True) -> dict[str, dict[str, dict]]:
    """{HOST: {attribute: row}} from host_settings.csv ({} when it does not exist), with the isolation matrix
    (hosts/isolation.csv, iso.* attributes) merged in when it exists."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    files = [Path(work_dir) / "hosts" / "host_settings.csv"]
    if merge_isolation:
        files.append(Path(work_dir) / "hosts" / "isolation.csv")
    for f in files:
        if f.is_file():
            for r in csv.DictReader(f.open(encoding="utf-8")):
                out[r["host"].upper()][r["attribute"]] = r
    return dict(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build"); s.add_argument("--work-dir", type=Path, required=True)
    s = sub.add_parser("show"); s.add_argument("--work-dir", type=Path, required=True)
    s.add_argument("--topic", default=""); s.add_argument("host", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = build(a.work_dir)
    else:
        data = load(a.work_dir)
        out = {h: {k: v["value"] for k, v in attrs.items() if not a.topic or v["topic"] == a.topic}
               for h, attrs in sorted(data.items()) if not a.host or h == a.host.upper()}
    print(json.dumps(out, indent=1))
    return 0 if not isinstance(out, dict) or out.get("status", "OK") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
