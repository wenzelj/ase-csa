"""Question-aware evidence digests for section cards.

Each card question gets an *evidence need*, worked out from its kind (from the template table) and its
wording, narrowed by the section's subject:

  inventory     host table / "inventory, role, location"   -> per-host summary (role, applications)
  dependencies  "dependencies, connect, interface, external" -> grouped connection table (graph links)
  isolation     "Drawbridge, isolation, fallback"            -> the connection table, enterprise/external peers only
  observed      observation tables and other requirements    -> section rows, plus the section-filtered
                                                                connection table when the section has a subject filter
  default       anything else                                -> section rows only (today's behaviour), flagged

Digests are built only from VERIFIED matrix rows in the host-profile link grammar and the host register;
every line carries the E-ids it rests on, so the writer can cite what it reads. A peer's zone is never
guessed: it comes from the host register (captured system host, domain controller, named peer) or from the
address itself (public address); anything else is "unnamed internal address".

A per-question override is read from the scope map / spec part as `evidence_need:`; the rules apply otherwise.
"""
from __future__ import annotations

import csv
import ipaddress
import re
from collections import defaultdict
from pathlib import Path

NEEDS = ("inventory", "dependencies", "isolation", "observed", "default")

_DEP = re.compile(r"\b(dependenc\w*|depend\w*|connect\w*|interface\w*|external|integrat\w*|data flows?|communicat\w*)\b", re.I)
_ISO = re.compile(r"\b(drawbridge|isolat\w*|fallback|disconnect\w*)\b", re.I)
_INV = re.compile(r"\b(inventory|asset|role|location)\b", re.I)

# section subject -> which links belong to it (local process / port). None = every link.
SUBJECTS = [
    (re.compile(r"monitor|logging|siem|log ?server|syslog", re.I),
     re.compile(r"HealthService|MonitoringHost|splunk|CSFalcon|MsSense|Sense|nxlog|winlogbeat", re.I), {5723, 9997, 8089, 514, 6514}),
    (re.compile(r"\bdns\b|name resolution", re.I), None, {53}),
    (re.compile(r"time", re.I), re.compile(r"w32time", re.I), {123}),
    (re.compile(r"identity|authentication|directory", re.I), re.compile(r"lsass", re.I), {88, 389, 636, 3268, 3269, 464}),
    (re.compile(r"backup|recovery|storage", re.I), re.compile(r"agentService|vflragentd|ddboost|avagent", re.I), {445, 2049, 7000, 9613}),
    (re.compile(r"patch|lifecycle|update", re.I), re.compile(r"CcmExec|wuauserv|EdgeUpdate|updater", re.I), {8530, 8531, 10123}),
    (re.compile(r"security control|endpoint|antivirus", re.I), re.compile(r"CSFalcon|MsSense|Sense|MsMpEng", re.I), set()),
    (re.compile(r"remote access|jump", re.I), re.compile(r"mstsc|TermService", re.I), {3389, 5985, 5986, 22}),
]

_IN = re.compile(r"^(?P<peer>\S+) (?:\((?P<pip>[^)]*)\) )?has an (?P<state>.*?)connection to (?P<host>\S+) on port (?P<port>\d+), served by (?P<proc>\S+)")
_OUT = re.compile(r"^(?P<host>\S+) has an (?P<state>.*?)connection from (?P<proc>\S+) to (?P<peer>\S+) (?:\((?P<pip>[^)]*)\) )?on "
                  r"(?:port (?P<port>\d+)|a dynamic)(?: \((?P<psvc>[^)]*)\))?")


def need_for(q: dict, node: dict, override: str | None = None) -> str:
    if override in NEEDS:
        return override
    text = q.get("text", "")
    cols = " ".join(q.get("columns") or [])
    if q["kind"] == "register" and re.search(r"\bhost", cols + " " + text, re.I):
        return "inventory"
    if _ISO.search(text):
        return "isolation"
    if q["kind"] == "requirement" and re.search(r"\binventory\b", text, re.I):
        return "inventory"                     # an inventory requirement may also name dependencies
    if _DEP.search(text):
        return "dependencies"
    if q["kind"] == "requirement" and _INV.search(text):
        return "inventory"
    if q["kind"] in ("observation", "requirement", "findings"):
        return "observed"
    return "default"


def subject_section(title: str):
    for sect, _, _ in SUBJECTS:
        if sect.search(title):
            return sect
    return None


def subject_filter(title: str):
    """(process regex, ports) for the section, or None when every link belongs to it."""
    for sect, proc, ports in SUBJECTS:
        if sect.search(title):
            return proc, ports
    return None


def _register(workspace: Path) -> dict:
    p = Path(workspace) / "csa-work" / "hosts" / "hosts.csv"
    if not p.is_file():
        return {}
    from csa_docx import modelstore
    return {r["host"].strip(): r for r in modelstore.read_csv(p)}


def _zone(peer: str, reg: dict) -> str:
    r = reg.get(peer)
    if r:
        if (r.get("in_scope") or "").strip() != "peer" and (r.get("capture") or "").strip():
            return "this system (captured)"
        if "domain controller" in (r.get("sources") or "").lower():
            return "enterprise directory (domain controller)"
        if (r.get("system") or "").strip():
            return f"{r['system']} host, not captured"
        return "named host, role not recorded"
    try:
        ip = ipaddress.ip_address(peer.split("%")[0])
        return "unnamed internal address" if ip.is_private else "public address (internet / cloud)"
    except ValueError:
        return "named host, role not recorded"


def ip_owners(reg: dict | None) -> dict[str, str]:
    """{address: register host} for every address a register host lists."""
    out: dict[str, str] = {}
    for h, r in (reg or {}).items():
        for ip in (r.get("ips") or "").split(";"):
            ip = ip.strip()
            if ip and not ip.startswith(("127.", "0.", "169.254.")):
                out.setdefault(ip, h)
    return out


def links(rows: list[dict], reg: dict | None = None) -> list[dict]:
    """Connection rows in host_profile's link grammar. With the host register, a peer the capture saw only as
    an address is named by the register host that now owns it (peer_ip keeps the address)."""
    owner = ip_owners(reg)
    out = []
    for r in rows:
        if r.get("status") != "VERIFIED" or r.get("csa_area") != "network_and_connectivity" \
                or (r.get("review_state") or "").lower() == "rejected":
            continue
        c = r.get("claim", "")
        m = _IN.match(c)
        if m:
            out.append({"dir": "inbound", "host": m["host"], "peer": owner.get(m["peer"], m["peer"]), "peer_ip": m["peer"]
                        if m["peer"] in owner else (m["pip"] or ""), "port": m["port"], "proc": m["proc"],
                        "state": m["state"].strip(), "id": r["evidence_id"], "psvc": ""})
            continue
        m = _OUT.match(c)
        if m:
            out.append({"dir": "outbound", "host": m["host"], "peer": owner.get(m["peer"], m["peer"]),
                        "peer_ip": m["peer"] if m["peer"] in owner else (m["pip"] or ""), "port": m["port"] or "dynamic",
                        "proc": m["proc"], "state": m["state"].strip(), "id": r["evidence_id"], "psvc": m["psvc"] or ""})
    return out


def _keep(l: dict, flt) -> bool:
    if flt is None:
        return True
    proc, ports = flt
    return bool((proc and proc.search(l["proc"] + " " + l["psvc"])) or (l["port"].isdigit() and int(l["port"]) in ports))


def dependency_table(rows: list[dict], workspace: Path, flt=None, external_only: bool = False, limit: int = 40) -> tuple[list[str], set[str]]:
    reg = _register(workspace)
    groups: dict[tuple, dict] = {}
    for l in links(rows, reg):
        if not _keep(l, flt):
            continue
        zone = _zone(l["peer"], reg)
        if external_only and zone == "this system (captured)":
            continue
        k = (l["dir"], l["peer"], l["port"])
        g = groups.setdefault(k, {"zone": zone, "hosts": set(), "procs": set(), "ids": [], "states": set(), "psvc": set()})
        g["hosts"].add(l["host"]); g["procs"].add(l["proc"]); g["ids"].append(l["id"]); g["states"].add(l["state"])
        if l["psvc"]:
            g["psvc"].add(l["psvc"])
    if not groups:
        return [], set()
    # the long tail: public addresses collapse per direction and port, and single-host links to unnamed
    # internal addresses collapse per host, so the table stays readable without dropping any E-id
    merged: dict[tuple, dict] = {}
    for (d, peer, port), g in list(groups.items()):
        if g["zone"].startswith("public"):
            key = (d, f"public internet addresses", port)
        elif g["zone"] == "unnamed internal address" and len(g["hosts"]) == 1:
            key = (d, f"other unnamed addresses from {next(iter(g['hosts']))}", "various")
        else:
            continue
        m = merged.setdefault(key, {"zone": g["zone"] if "public" in g["zone"] else "unnamed internal address",
                                    "hosts": set(), "procs": set(), "ids": [], "states": set(), "psvc": set(), "peers": []})
        m["hosts"] |= g["hosts"]; m["procs"] |= g["procs"]; m["ids"] += g["ids"]; m["states"] |= g["states"]
        m["peers"].append(peer if key[2] != "various" else f"{peer}:{port}")
        del groups[(d, peer, port)]
    for (d, label, port), m in merged.items():
        n = len(set(m["peers"]))
        shown = ", ".join(sorted(set(m["peers"]))[:5]) + (f" +{n - 5}" if n > 5 else "")
        groups[(d, f"{label} ({n}: {shown})", port)] = m
    order = sorted(groups.items(), key=lambda kv: (kv[0][0] != "outbound", -len(kv[1]["hosts"]), kv[0][1]))
    lines = ["| Direction | Peer | Zone (from the host register or address) | Port | Process | Hosts | Seen as | Evidence |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    ids: set[str] = set()
    for (d, peer, port), g in order[:limit]:
        hosts = sorted(g["hosts"])
        hs = f"{len(hosts)}: {', '.join(hosts)}"
        proc = ", ".join(sorted(g["procs"])) + (f" (peer runs {', '.join(sorted(g['psvc']))})" if g["psvc"] else "")
        seen = "established" if any(s.startswith("established") for s in g["states"]) else "attempted only"
        lines.append(f"| {d} | {peer} | {g['zone']} | {port} | {proc} | {hs} | {seen} | {', '.join(g['ids'])} |")
        ids.update(g["ids"])
    if len(order) > limit:
        lines.append(f"| ... | {len(order) - limit} more peer/port groups not shown | | | | | | |")
    return lines, ids


_GENERIC_PKG = re.compile(r"ODBC|OLE DB|Native Client|Visual C\+\+|Redistributable|\.NET|Runtime|Driver|Batch Parser|"
                          r"Common Files|Connection Info|Shared|Setup|Support Files|Language|XEvent|Diagnostics|Management Objects|"
                          r"VSS Writer|Browser for SQL|Installer|Edge|Google|Chrome|VMware|Update|Hotfix|Workbench|Connector|"
                          r"Management Studio|Policies|Configuration Checker|SQL Server \d{4} (?!\(64)", re.I)
_GENERIC_SVC = re.compile(r"CrowdStrike|Flexera|Microsoft Monitoring|PowerProtect|Cohesity|Dell VM|VMware|Windows Defender|"
                          r"Edge|Google|Bonjour|Policy Platform|Media Player|Cisco Secure Workload|cats|DSM SA|Splunk|SQL Server VSS|"
                          r"SQL Server CEIP|SQL Server Agent|SQL Server Browser|SQL Full-text|Launchpad", re.I)


def host_summary(rows: list[dict], workspace: Path, match=None, max_items: int = 6) -> tuple[list[str], set[str]]:
    """One line per captured host: role, its distinctive applications and services, and every E-id behind them.
    Generic packages (drivers, runtimes, agents present everywhere) are left out of the line; the full lists are
    on the host card (csa-work/hosts/cards/<HOST>.md). With `match`, only hosts whose role or software matches."""
    reg = _register(workspace)
    apps: dict[str, list[str]] = defaultdict(list)
    svcs: dict[str, list[str]] = defaultdict(list)
    ids_by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.get("status") != "VERIFIED" or r.get("csa_area") != "general_asset_inventory":
            continue
        h = r.get("claim", "").split(" ", 1)[0]
        body = re.sub(r"^\S+ (has these application packages installed|runs these non-Windows services): ", "", r["claim"]).rstrip(".")
        items = [x.strip() for x in body.split(";") if x.strip()]
        (apps if "application packages" in r["claim"] else svcs)[h].extend(items)
        ids_by[h].append(r["evidence_id"])
    lines, ids = [], set()
    for h in sorted(ids_by):
        role = (reg.get(h, {}).get("role") or "").strip() or "role not recorded"
        site = (reg.get(h, {}).get("site") or "").strip()
        a = list(dict.fromkeys(x for x in apps[h] if not _GENERIC_PKG.search(x)))
        sv = list(dict.fromkeys(re.sub(r" \([^)]*\)$", "", x) for x in svcs[h] if not _GENERIC_SVC.search(x)))
        if match is not None and not (match.search(role) or any(match.search(x) for x in apps[h])):
            continue
        dist = list(dict.fromkeys(a + sv))
        more = len(dist) - max_items
        what = "; ".join(dist[:max_items]) + (f"; +{more} more on the host card" if more > 0 else "") if dist else "no distinctive software"
        lines.append(f"- {h} ({role}{'; ' + site if site else ''}): {what} ({', '.join(ids_by[h])})")
        ids.update(ids_by[h])
    return lines, ids


CAVEAT = ("Connections were sampled over a short window per host (about 30 seconds), so a peer that connects "
          "occasionally can be missing: never write that these are all the dependencies. 'Attempted only' means the "
          "connection was not established when sampled. An unnamed address stays an address; say its name was not captured.")


# a row that states what something needs: a declared dependency, a required service, an application path or a
# recorded flow or conduit between named parts (not run notes, inventories or settings that merely mention a register)
_DECLARED = re.compile(r"\b(declares? (?:the |a )?dependenc\w*|OT dependency|required before migration|application path|"
                       r"records? (?:an? |the )?(?:\w+ )?(?:flow|conduit|path)\b|depends? on)", re.I)
_PREVIOUS = re.compile(r"Current_State_Assessment|NetSeg_Current", re.I)


def declared_dependencies(rows: list[dict], workspace: Path | None, limit: int = 10) -> tuple[list[str], set[str]]:
    """VERIFIED rows that declare what a function needs (flow map, system matrix, dependency summaries), newest
    sources first: captures and supplied documents before the previous assessment. One line per row, with its ID."""
    picked = []
    for r in rows:
        if r.get("status") != "VERIFIED" or not _DECLARED.search(r.get("claim", "")):
            continue
        prev = bool(_PREVIOUS.search(r.get("source_title", "")))
        hosts = len(set(re.findall(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b", r.get("claim", ""))))
        picked.append((prev, -hosts, r["evidence_id"], r))
    picked.sort(key=lambda t: t[:3])
    lines, ids = [], set()
    for _, _, eid, r in picked[:limit]:
        lines.append(f"- {eid}: {' '.join(r['claim'].split())[:320]}")
        ids.add(eid)
    return lines, ids


def digest(q: dict, need: str, node: dict, rows: list[dict], workspace: Path | None) -> dict:
    """{"need", "blocks": [[line, ...], ...], "ids"} for one question. The card shows each block once and
    refers back to it from later questions."""
    if not workspace:
        return {"need": need, "blocks": [], "ids": []}
    flt = subject_filter(node["title"])
    sect = subject_section(node["title"])
    blocks: list[list[str]] = []
    ids: set[str] = set()
    if need == "inventory":
        l, i = host_summary(rows, workspace)
        if l:
            blocks.append(["Per-host summary (role from the host register; distinctive software from the captures; "
                           "full lists on the host cards):"] + l)
            ids |= i
    if need == "observed" and sect is not None:
        l, i = host_summary(rows, workspace, match=sect)
        if l:
            blocks.append(["Hosts whose role or software is this section's subject:"] + l)
            ids |= i
    if need in ("dependencies", "isolation", "observed") or (need == "inventory" and _DEP.search(q.get("text", ""))):
        # one table per card: the isolation question reads the same table (rows whose zone is not
        # "this system" are what an isolation event cuts), so the card prints it once
        l, i = dependency_table(rows, workspace, flt)
        if l:
            title = "Connections for this section's subject:" if flt else "Connections of the captured hosts:"
            blocks.append([title, ""] + l + ["", CAVEAT])
            ids |= i
        if need == "isolation" and l:
            blocks.append(["For this question: every connection row whose zone is not 'this system (captured)' is a "
                           "peer an isolation event would cut. Say what each lost peer provides only where the evidence names it."])
    if need == "isolation":
        l, i = declared_dependencies(rows, workspace)
        if l:
            blocks.append(["Declared dependencies and flows (what each function of the system needs, from the flow map, "
                           "system matrix and dependency summaries). Use them to say which functions an isolation event "
                           "stops: a function stops when something it needs is cut, and only where these rows name the need:"] + l)
            ids |= i
    return {"need": need, "blocks": blocks, "ids": sorted(ids)}
