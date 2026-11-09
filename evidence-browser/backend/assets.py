"""Asset inventory read model for the Evidence Workspace: what a project's evidence names as
hosts, devices and addresses, and which of them are still unresolved.

Read-only: it assembles four inventory views (application hosts, connected devices,
unidentified addresses, conflicts) from what the project already records --

* ``hosts/hosts.csv``            the host register (in-scope application hosts and peers)
* ``hosts/addresses.csv``        addresses no register host owns
* ``hosts/host_links.csv``       captured host-to-host connections (established sessions)
* ``hosts/host_services.csv``    configured services (DNS / time servers each host points at)
* ``evidence-matrix.csv``        VERIFIED connection rows (the live observation rows) and
                                 every VERIFIED row that names an asset (evidence links)
* the S539 register              ``hosts/connected_devices.csv`` + ``hosts/device_addresses.csv``
                                 (durable connected-device decisions, independent of rebuilds)

Nothing is inferred. The observation kinds stay distinct and none of them implies a migration
dependency: a captured connection (host_links rows, matrix link-grammar rows) is what was seen,
a configured service (host_services row) is what a host is set to use, and a documented
dependency is a VERIFIED matrix row written in the dependency grammar. Aliases match a device
exactly (normalised IP or FQDN); an address claimed by more than one device, claimed by a device
while a register host owns it, or owned by no one stays a conflict or an unidentified address --
it is never resolved by guess.
"""
from __future__ import annotations

import csv
import ipaddress
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _framework(agents: Path) -> None:
    fw = str(agents / "framework")
    if fw not in sys.path:
        sys.path.insert(0, fw)


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(fh)]


def _norm(value: str) -> str:
    """Normalise an alias (IP or FQDN) for exact matching, or "" when it is neither."""
    text = str(value or "").strip().lower()
    if text.endswith("."):
        text = text[:-1]
    if not text:
        return ""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    if text == "localhost":
        return text
    parts = text.split(".")
    if len(parts) < 2 or any(len(p) > 63 for p in parts):
        return ""
    if not all(p and all(c.isalnum() or c == "-" for c in p) for p in parts):
        return ""
    return text


def _split(value: str, sep: str = ";") -> list[str]:
    return [x.strip() for x in str(value or "").split(sep) if x.strip()]


def _listed(r: dict) -> bool:
    """A captured host, or one the project's inventory lists (every other register entry is a peer or another application's)."""
    scope = (r.get("in_scope") or "").strip().lower()
    return scope not in ("peer", "no") and not scope.startswith("system:")


def _page(items: list, page: int, per_page: int, query: str) -> list:
    query = (query or "").strip().lower()
    if query:
        items = [i for i in items if query in " ".join(
            str(i.get(k) or "") for k in ("id", "name", "role", "site", "kind", "type",
                                         "address", "identification_state", "classification")).lower()]
    per_page = max(1, per_page)
    start = max(0, (max(1, page) - 1) * per_page)
    return items[start:start + per_page]


def _link_evidence(live: list[dict], host_keys: set[str] | None = None) -> dict[str, list[dict]]:
    """VERIFIED matrix rows that mention a register host or a normalised address, by key.

    Host keys are matched exactly (upper-case); a normalised IP or FQDN found in the row text
    also links. The same row may link several assets; rejected rows draw no link."""
    host_keys = host_keys or set()
    out: dict[str, list[dict]] = defaultdict(list)
    for r in live:
        if (r.get("status") or "").upper() != "VERIFIED":
            continue
        eid = (r.get("evidence_id") or "").strip()
        text = f"{r.get('claim', '')} {r.get('evidence_excerpt', '')}"
        if not eid or not text.strip():
            continue
        record = {"evidence_id": eid, "claim": (r.get("claim") or "").strip()}
        # exact host-name matches
        for h in host_keys:
            if h in text.upper():
                out[h].append(dict(record))
        # normalised IP / FQDN matches
        for word in text.replace(",", " ").replace(";", " ").replace("(", " ").replace(")", " ").split():
            n = _norm(word)
            if n and n not in host_keys:
                out.setdefault(n, [])
                if all(e["evidence_id"] != eid for e in out[n]):
                    out[n].append(dict(record))
    return out


def _evidence(map_: dict[str, list[dict]], *keys: str) -> list[dict]:
    seen, out = set(), []
    for k in keys:
        for e in map_.get(k.upper(), []):
            if e["evidence_id"] not in seen:
                seen.add(e["evidence_id"])
                out.append(e)
    return sorted(out, key=lambda e: e["evidence_id"])


def build(work_dir: Path, agents: Path, *, page: int = 1, per_page: int = 50,
          query: str = "", kind: str = "") -> dict[str, Any]:
    """Assemble the inventory read model. Read-only: nothing under the project is written.

    ``kind`` narrows the response to one group (``application_hosts``, ``devices``,
    ``unidentified``, ``conflicts`` or "" for all); ``query`` filters that group's rows by name,
    role, site, type or address; ``page``/``per_page`` paginate. Every group carries its own
    ``items``, ``total``, ``page`` and ``per_page``; ``sources`` lists the files that existed."""
    _framework(agents)
    from csa_docx import evidence_digest, evidence_live

    reg_rows = _rows(work_dir / "hosts" / "hosts.csv")
    reg = {r["host"].strip().upper(): r for r in reg_rows if (r.get("host") or "").strip()}
    matrix = work_dir / "evidence-matrix.csv"
    live = evidence_live.read(matrix) if matrix.is_file() else []
    link_rows = _rows(work_dir / "hosts" / "host_links.csv")
    svc_rows = _rows(work_dir / "hosts" / "host_services.csv")
    addr_rows = _rows(work_dir / "hosts" / "addresses.csv")
    dev_rows = [r for r in _rows(work_dir / "hosts" / "connected_devices.csv")
                if (r.get("active") or "true").strip().lower() in ("true", "1", "yes")]
    alias_rows = [r for r in _rows(work_dir / "hosts" / "device_addresses.csv")
                  if (r.get("active") or "true").strip().lower() in ("true", "1", "yes")]

    # matrix-derived facts, keyed by host (upper name) or normalised address ----------------
    host_keys = {(r.get("host") or "").strip().upper() for r in reg_rows}
    hosts_dir = work_dir / "hosts"
    present = [n for n in ("hosts.csv", "host_links.csv", "host_services.csv", "addresses.csv",
                           "connected_devices.csv", "device_addresses.csv") if (hosts_dir / n).is_file()]
    sources = ["hosts/" + n for n in present]
    if matrix.is_file():
        sources.append("evidence-matrix.csv")

    dep_links = evidence_digest.links(live, {h: r for h, r in reg.items()})
    mention = _link_evidence(live, host_keys)

    def ev(*keys: str) -> list[dict]:
        return _evidence(mention, *keys)

    host_ips: dict[str, str] = {}        # normalised ip -> host name
    for h, r in reg.items():
        for x in _split(r.get("ips", "")):
            n = _norm(x)
            if n:
                host_ips.setdefault(n, h)

    # --- application hosts ---------------------------------------------------------
    hosts = []
    for h in sorted(reg):
        r = reg[h]
        if not _listed(r):
            continue
        ips = _split(r.get("ips", ""))
        links = [l for l in link_rows
                 if h in ((l.get("src_host") or "").upper(), (l.get("dst_host") or "").upper())]
        services = [s for s in svc_rows if h == (s.get("client_host") or "").upper()]
        deps = sorted({f"{l['dir']} {l['host']} -> {l['peer']}:{l['port']}" for l in dep_links
                       if l["host"].upper() == h or l["peer"].upper() == h})
        hosts.append({
            "id": h, "name": h, "kind": "application_host",
            "aliases": sorted({_norm(x) for x in ips + [h.lower()] if _norm(x)}),
            "role": (r.get("role") or "").strip(), "site": (r.get("site") or r.get("ad_site") or "").strip(),
            "state": "captured" if (r.get("capture") or "").strip() else "not captured",
            "in_scope": (r.get("in_scope") or "").strip(),
            "services": [{"service": s.get("service", ""), "server_host": s.get("server_host", ""),
                          "server_ip": s.get("server_ip", ""), "preference": s.get("preference", ""),
                          "source": s.get("source", "")} for s in services],
            "observed_connections": [
                {"src": l.get("src_host", ""), "dst": l.get("dst_host", ""),
                 "dst_port": l.get("dst_port", ""), "connections": l.get("connections", ""),
                 "basis": l.get("basis", ""), "source": l.get("source", "")} for l in links],
            "documented_dependencies": deps,
            "evidence": ev(h, *ips),
        })

    # --- connected devices (S539 register) ------------------------------------------
    aliases_by_device: dict[str, list[dict]] = defaultdict(list)
    for a in alias_rows:
        aliases_by_device[a.get("device_id", "")].append({
            "address": a.get("address", ""), "normalized": a.get("normalized", ""),
            "address_type": a.get("address_type", ""), "source": a.get("source", "")})
    claimed = {_norm(a["normalized"]): a.get("device_id", "") for a in alias_rows
               if _norm(a["normalized"])}

    devices = []
    for d in sorted(dev_rows, key=lambda x: x.get("device_id", "")):
        dev_id = (d.get("device_id") or "").strip()
        dev_aliases = aliases_by_device.get(dev_id, [])
        keys = {_norm(a["normalized"]) for a in dev_aliases if _norm(a["normalized"])}
        name_n = _norm(d.get("name", ""))
        if name_n:
            keys.add(name_n)
        # exact-match only: an application host is connected when one of its register IPs or its
        # name is exactly one of the device's active aliases
        connected = sorted({h for h in reg if _listed(reg[h]) and keys & ({n for n in (_norm(x) for x in _split(reg[h].get("ips", ""))) if n} | ({_norm(reg[h]["host"].lower())} if _norm(reg[h]["host"].lower()) else set()))})
        dep_hits = [l for l in dep_links if _norm(l["peer"]) in keys or l["peer"].upper() in keys]
        svc_hits = [s for s in svc_rows
                    if _norm(s.get("server_ip", "")) in keys and _norm(s.get("server_ip", ""))
                    or _norm((s.get("server_host") or "").lower()) in keys and _norm((s.get("server_host") or "").lower())]
        # A captured connection links to a device when the destination resolves to one of
        # the device's aliases (either the dst_host name or the register IP it owns).
        def _dst_matches(dst: str) -> bool:
            dn = _norm(dst)
            if dn and dn in keys:
                return True
            dn_lower = _norm(dst.lower())
            if dn_lower and dn_lower in keys:
                return True
            # dst_host is a register host name: check its IPs
            r = reg.get(dst.upper())
            if r:
                return bool(keys & {n for n in (_norm(x) for x in _split(r.get("ips", ""))) if n})
            return False
        link_hits = [l for l in link_rows if _dst_matches((l.get("dst_host") or "").strip())]
        observation_type = []
        if link_hits or dep_hits:
            observation_type.append("captured_connection")
        if svc_hits:
            observation_type.append("configured_service")
        if dep_hits:
            observation_type.append("documented_dependency")
        devices.append({
            "id": dev_id, "name": (d.get("name") or "").strip(), "kind": "connected_device",
            "type": (d.get("device_type") or "").strip(), "role": (d.get("role") or "").strip(),
            "owner": (d.get("owner") or "").strip(), "site": (d.get("site_zone") or "").strip(),
            "state": (d.get("identification_state") or "").strip(),
            "classification": (d.get("classification") or "").strip(),
            "relationship": (d.get("relationship") or "").strip(),
            "aliases": [a["address"] for a in dev_aliases],
            "connected_application_hosts": connected,
            "direction": sorted({l["dir"] for l in dep_hits}),
            "ports": sorted({l["port"] for l in dep_hits}, key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0)),
            "processes": sorted({l["proc"] for l in dep_hits}),
            "observation_type": observation_type,
            "source": (d.get("provenance") or "hosts/connected_devices.csv").strip(),
            "evidence": ev(d.get("name", ""), *[_norm(a["normalized"]) for a in dev_aliases]),
        })

    # --- unidentified addresses -------------------------------------------------------
    unidentified = []
    for a in sorted(addr_rows, key=lambda r: r.get("address", "")):
        addr = (a.get("address") or "").strip()
        if not addr:
            continue
        n = _norm(addr)
        unidentified.append({
            "id": n or addr, "address": addr, "kind": "unidentified_address",
            "type": a.get("kind") or "",
            "claimed_by_device": claimed.get(n, ""),
            "seen_from": _split(a.get("seen_from", "")),
            "directions": _split(a.get("directions", "")),
            "ports": _split(a.get("ports", "")),
            "processes": _split(a.get("processes", "")),
            "sessions": a.get("sessions") or "",
            "source": "hosts/addresses.csv",
            "evidence": ev(n, *_split(a.get("evidence_ids", ""))),
        })

    # --- conflicts ---------------------------------------------------------------------
    # ambiguous: one exact alias claimed by more than one active device
    owners: dict[str, list[str]] = defaultdict(list)
    for a in alias_rows:
        n = _norm(a.get("normalized", ""))
        if n:
            owners[n].append(a.get("device_id", ""))
    conflicts = []
    for n in sorted(owners):
        devs = sorted(set(owners[n]))
        if len(devs) > 1:
            conflicts.append({"id": n, "address": n, "kind": "ambiguous_alias", "claimed_by": devs,
                              "source": "hosts/device_addresses.csv", "evidence": ev(n)})
        elif n in host_ips:
            conflicts.append({"id": n, "address": n, "kind": "host_owned_alias",
                              "host": host_ips[n], "claimed_by": devs,
                              "source": "hosts/hosts.csv", "evidence": ev(n, host_ips[n])})

    groups = {"application_hosts": hosts, "devices": devices,
              "unidentified": unidentified, "conflicts": conflicts}
    if kind:
        if kind not in groups:
            raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(groups)}")
        out = {kind: {"items": _page(groups[kind], page, per_page, query),
                      "total": len(groups[kind]), "page": max(1, page), "per_page": per_page}}
    else:
        out = {k: {"items": _page(v, page, per_page, query),
                   "total": len(v), "page": max(1, page), "per_page": per_page} for k, v in groups.items()}
    return {"groups": out, "counts": {k: len(v) for k, v in groups.items()}, "sources": sources,
            "matrix_rows": len(live),
            "note": "Observed connections, configured services and documented dependencies are recorded "
                    "distinctly; none of them implies a migration dependency."}
