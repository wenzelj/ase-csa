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
          query: str = "", kind: str = "", include_retired: bool = False) -> dict[str, Any]:
    """Assemble the inventory read model. Read-only: nothing under the project is written.

    ``kind`` narrows the response to one group (``application_hosts``, ``devices``,
    ``unidentified``, ``conflicts`` or "" for all); ``query`` filters that group's rows by name,
    role, site, type or address; ``page``/``per_page`` paginate. Every group carries its own
    ``items``, ``total``, ``page`` and ``per_page``; ``sources`` lists the files that existed.

    ``include_retired`` adds retired register devices to the ``devices`` group (``active`` false, no
    aliases, nothing derived from observations) and a ``retired_devices`` count; ``counts`` still
    counts active devices only."""
    _framework(agents)
    from csa_docx import evidence_digest, evidence_live

    reg_rows = _rows(work_dir / "hosts" / "hosts.csv")
    reg = {r["host"].strip().upper(): r for r in reg_rows if (r.get("host") or "").strip()}
    matrix = work_dir / "evidence-matrix.csv"
    live = evidence_live.read(matrix) if matrix.is_file() else []
    link_rows = _rows(work_dir / "hosts" / "host_links.csv")
    svc_rows = _rows(work_dir / "hosts" / "host_services.csv")
    addr_rows = _rows(work_dir / "hosts" / "addresses.csv")
    all_dev_rows = _rows(work_dir / "hosts" / "connected_devices.csv")
    dev_rows = [r for r in all_dev_rows if (r.get("active") or "true").strip().lower() in ("true", "1", "yes")]
    retired_rows = [r for r in all_dev_rows if r not in dev_rows]
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
    for d in sorted(dev_rows + (retired_rows if include_retired else []), key=lambda x: x.get("device_id", "")):
        dev_id = (d.get("device_id") or "").strip()
        register = {"revision": (d.get("revision") or "").strip(), "provenance": (d.get("provenance") or "").strip(),
                    "reviewer": (d.get("reviewer") or "").strip(), "recorded": (d.get("recorded") or "").strip()}
        if d in retired_rows:
            # a retired identification keeps its register row only: no aliases, no connections inferred from it
            devices.append({
                "id": dev_id, "name": (d.get("name") or "").strip(), "kind": "connected_device", "active": False,
                "type": (d.get("device_type") or "").strip(), "role": (d.get("role") or "").strip(),
                "owner": (d.get("owner") or "").strip(), "site": (d.get("site_zone") or "").strip(),
                "state": (d.get("identification_state") or "").strip(),
                "classification": (d.get("classification") or "").strip(),
                "relationship": (d.get("relationship") or "").strip(), "aliases": [],
                "connected_application_hosts": [], "direction": [], "ports": [], "processes": [],
                "observation_type": [], "source": (d.get("provenance") or "hosts/connected_devices.csv").strip(),
                "evidence": [], **register})
            continue
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
            "active": True, **register,
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
    counts = {k: len(v) for k, v in groups.items()}
    counts["devices"] = len([d for d in devices if d["active"]])
    extra = {"retired_devices": len(retired_rows)} if include_retired else {}
    return {"groups": out, "counts": counts, "sources": sources, **extra,
            "matrix_rows": len(live),
            "note": "Observed connections, configured services and documented dependencies are recorded "
                    "distinctly; none of them implies a migration dependency."}


# ---------------------------------------------------------------------------------------------
# Editing the durable connected-device register (S539 store) and the alias reconciliation preview.
#
# Every mutation goes through ``csa_docx.connected_devices``, which writes only the register
# (``connected_devices.csv``, ``device_addresses.csv``), its audit log and timestamped backups of
# those files. Nothing here touches generated host CSVs, captures, the evidence matrix, the graph
# or a DOCX, and a ``confirmed`` device never adds an evidence row: confirmation is recorded as
# provenance on the register row only.
# ---------------------------------------------------------------------------------------------
import re as _re

REGISTER_FILES = ("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl")
SCOPE_FILES = ("host_scope.csv", "device-audit.jsonl")
_ISO_DATE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEVICE_FIELDS = ("name", "device_type", "role", "owner", "site_zone", "relationship", "classification",
                  "identification_state", "provenance", "reviewer")


class AssetError(Exception):
    """A rejected edit: ``status`` is the HTTP status the routes return, ``code`` a stable machine label."""

    def __init__(self, status: int, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _store(agents: Path):
    _framework(agents)
    from csa_docx import connected_devices
    return connected_devices


def _root(project_root: Path, work_dir: Path) -> Path:
    if Path(work_dir).resolve() != (Path(project_root) / "csa-work").resolve():
        raise AssetError(409, "The connected-device register lives in <project_root>/csa-work; this project's "
                              "work folder is elsewhere, so editing is not available.", "unsupported_layout")
    return Path(project_root)


def _translate(error: ValueError) -> AssetError:
    text = str(error)
    low = text.lower()
    if low.startswith("stale preview"):
        return AssetError(409, text, "stale_preview")
    if low.startswith("blocked:"):
        return AssetError(409, text[len("blocked:"):].strip(), "scope_conflict")
    if low.startswith("unknown conversion"):
        return AssetError(404, text, "not_found")
    if "stale revision" in low or "already an active alias" in low or "already attached" in low:
        return AssetError(409, text, "conflict")
    if low.startswith("unknown device"):
        return AssetError(404, text, "not_found")
    if "retired" in low and "restore" in low:
        return AssetError(409, text, "retired")
    if "not attached" in low:
        return AssetError(404, text, "not_found")
    return AssetError(422, text, "invalid")


def _expected(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text.isdigit():
        raise AssetError(422, "expected_revision is required (the revision the editor last read)", "revision_required")
    return text


def _confirmation(payload: dict, existing_provenance: str = "") -> str:
    """Provenance text for a ``confirmed`` device: a cited source, or a dated owner confirmation."""
    source = str(payload.get("source") or "").strip()
    when = str(payload.get("owner_confirmed_on") or "").strip()
    if when and not _ISO_DATE.match(when):
        raise AssetError(422, "owner_confirmed_on must be a date written YYYY-MM-DD", "invalid_date")
    if not source and not when:
        raise AssetError(422, "A confirmed device needs a cited source (`source`) or a dated owner "
                              "confirmation (`owner_confirmed_on`, YYYY-MM-DD).", "confirmation_required")
    parts = [str(payload.get("provenance") or existing_provenance or "").strip()]
    if source:
        parts.append(f"source: {source}")
    if when:
        parts.append(f"owner confirmed {when}")
    return "; ".join(p for p in parts if p)


def _register_hosts(work_dir: Path) -> dict[str, dict]:
    """Normalised IP / FQDN / host name -> register host row, for every host in the register."""
    owners: dict[str, dict] = {}
    for r in _rows(work_dir / "hosts" / "hosts.csv"):
        host = (r.get("host") or "").strip()
        if not host:
            continue
        for x in _split(r.get("ips", "")) + [host]:
            n = _norm(x) or _norm(x.lower())
            if n:
                owners.setdefault(n, r)
    return owners


def _active_aliases(work_dir: Path) -> dict[str, list[str]]:
    """Normalised alias -> the active devices that claim it (more than one means the register is ambiguous)."""
    devices = {r.get("device_id", "") for r in _rows(work_dir / "hosts" / "connected_devices.csv")
               if (r.get("active") or "").lower() == "true"}
    out: dict[str, list[str]] = defaultdict(list)
    for r in _rows(work_dir / "hosts" / "device_addresses.csv"):
        n = _norm(r.get("normalized", ""))
        if n and (r.get("active") or "").lower() == "true" and r.get("device_id") in devices \
                and r["device_id"] not in out[n]:
            out[n].append(r["device_id"])
    return dict(out)


def _normalise(agents: Path, address: str) -> str:
    try:
        return _store(agents)._normalize_address(address)
    except ValueError as exc:
        raise AssetError(422, str(exc), "invalid_address") from exc


def _check_free(work_dir: Path, agents: Path, address: str, device_id: str | None) -> str:
    """The normalised address, or a rejection when a register host or another active device already owns it."""
    n = _normalise(agents, address)
    host = _register_hosts(work_dir).get(n)
    if host:
        raise AssetError(409, f"{n} is claimed by register host {host.get('host', '').strip()}; an application "
                              "host's address cannot become a connected-device alias.", "host_owned")
    others = [o for o in _active_aliases(work_dir).get(n, []) if o != device_id]
    if others:
        raise AssetError(409, f"{n} is already an active alias of {', '.join(others)}.", "alias_claimed")
    return n


def reconcile_preview(work_dir: Path, agents: Path, *, device_id: str = "", add: list[str] | None = None,
                      remove: list[str] | None = None) -> dict[str, Any]:
    """Read-only before/after: what each address resolves to now, and after the proposed alias change.

    Nothing is written. ``add`` addresses that a register host or another device owns come back
    ``blocked`` with the reason; ``remove`` addresses fall back to what the captures say (an
    unidentified address) or to nothing."""
    hosts = _register_hosts(work_dir)
    aliases = _active_aliases(work_dir)
    unidentified = {_norm(r.get("address", "")) for r in _rows(work_dir / "hosts" / "addresses.csv")}
    names = {r.get("device_id", ""): r.get("name", "") for r in _rows(work_dir / "hosts" / "connected_devices.csv")}
    target = device_id.strip()
    if target and target not in {k for k, _ in names.items()}:
        raise AssetError(404, f"unknown device: {target}", "not_found")

    def resolve(n: str, gain: set[str], lose: set[str]) -> dict[str, str]:
        if n in hosts:
            return {"resolves_to": "application_host", "id": hosts[n].get("host", "").strip(), "name": hosts[n].get("host", "").strip()}
        owners = list(aliases.get(n, []))
        if n in gain and (target or "(new device)") not in owners:
            owners.append(target or "(new device)")
        if n in lose:
            owners = [o for o in owners if o != target]
        if len(owners) > 1:
            return {"resolves_to": "ambiguous", "id": ", ".join(sorted(owners)), "name": ""}
        if owners:
            return {"resolves_to": "connected_device", "id": owners[0], "name": names.get(owners[0], "")}
        if n in unidentified:
            return {"resolves_to": "unidentified_address", "id": n, "name": ""}
        return {"resolves_to": "nothing_recorded", "id": "", "name": ""}

    out, any_blocked = [], False
    requests = [("add", a) for a in (add or [])] + [("remove", a) for a in (remove or [])]
    for action, raw in requests:
        item: dict[str, Any] = {"action": action, "address": raw, "normalized": "", "status": "ready", "reasons": []}
        try:
            n = _normalise(agents, raw)
        except AssetError as exc:
            item.update(status="blocked", reasons=[exc.message], before=None, after=None)
            out.append(item); any_blocked = True
            continue
        item["normalized"] = n
        before = resolve(n, set(), set())
        if action == "add":
            if n in hosts:
                item["reasons"].append(f"claimed by register host {hosts[n].get('host', '').strip()}")
            elif [o for o in aliases.get(n, []) if o != target]:
                item["reasons"].append("already an active alias of " + ", ".join(o for o in aliases[n] if o != target))
            elif target and target in aliases.get(n, []):
                item["reasons"].append("already an active alias of this device")
            after = resolve(n, {n}, set()) if not item["reasons"] else before
        else:
            if not target or target not in aliases.get(n, []):
                item["reasons"].append("not an active alias of this device")
            after = resolve(n, set(), {n}) if not item["reasons"] else before
        item.update(before=before, after=after)
        if item["reasons"]:
            item["status"] = "blocked"; any_blocked = True
        out.append(item)
    return {"device_id": target, "changes": out, "blocked": any_blocked, "writes": [],
            "note": "Preview only: nothing was written. Aliases match exactly (normalised IP or FQDN)."}


def _device_view(agents: Path, project_root: Path, device_id: str) -> dict:
    cd = _store(agents)
    try:
        device = cd.get_device(project_root, device_id, include_retired=True)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {**device, "aliases": [a for a in cd.list_addresses(project_root, device_id)]}


def _clean(values: dict) -> dict:
    return {k: str(values[k]).strip() for k in _DEVICE_FIELDS if k in values and values[k] is not None}


def create_device(project_root: Path, work_dir: Path, agents: Path, payload: dict) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    values = _clean(payload)
    if str(values.get("identification_state") or "") == "confirmed":
        values["provenance"] = _confirmation({**payload, "provenance": values.get("provenance", "")})
    values.setdefault("provenance", "Evidence Browser entry")
    if not values["provenance"]:
        values["provenance"] = "Evidence Browser entry"
    addresses = [str(a) for a in (payload.get("addresses") or [])]
    seen: set[str] = set()
    for a in addresses:
        n = _check_free(work_dir, agents, a, None)
        if n in seen:
            raise AssetError(422, f"{n} is listed twice", "duplicate_address")
        seen.add(n)
    try:
        result = cd.create_device(root, name=str(payload.get("name") or ""), values=values,
                                  reviewer=str(payload.get("reviewer") or ""), addresses=addresses or None)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "device": _device_view(agents, root, result["device_id"]), "writes": list(REGISTER_FILES)}


def patch_device(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    expected = _expected(payload.get("expected_revision"))
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise AssetError(422, "changes must be a non-empty object", "invalid")
    changes = {k: ("" if v is None else v) for k, v in changes.items()}
    existing = _device_view(agents, root, device_id)
    if changes.get("identification_state") == "confirmed" and existing.get("identification_state") != "confirmed":
        changes["provenance"] = _confirmation({**payload, "provenance": changes.get("provenance", "")}, existing.get("provenance", ""))
    if payload.get("reviewer") and "reviewer" not in changes:
        changes["reviewer"] = str(payload["reviewer"])
    try:
        cd.edit_device(root, device_id, changes=changes, expected_revision=expected)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "device": _device_view(agents, root, device_id), "writes": list(REGISTER_FILES)}


def _check_revision(agents: Path, root: Path, device_id: str, expected: str) -> dict:
    device = _device_view(agents, root, device_id)
    if str(device.get("revision")) != expected:
        raise AssetError(409, f"stale revision: expected {expected}, current {device.get('revision')}", "conflict")
    return device


def add_alias(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    _check_revision(agents, root, device_id, _expected(payload.get("expected_revision")))
    n = _check_free(work_dir, agents, str(payload.get("address") or ""), device_id)
    if device_id in _active_aliases(work_dir).get(n, []):
        raise AssetError(409, f"{n} is already an active alias of this device.", "alias_claimed")
    try:
        cd.add_address(root, device_id, str(payload.get("address") or ""), source=str(payload.get("source") or ""),
                       first_seen=str(payload.get("first_seen") or ""), last_seen=str(payload.get("last_seen") or ""))
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "device": _device_view(agents, root, device_id), "writes": list(REGISTER_FILES)}


def remove_alias(project_root: Path, work_dir: Path, agents: Path, device_id: str, address: str, expected_revision: Any) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    _check_revision(agents, root, device_id, _expected(expected_revision))
    try:
        cd.remove_address(root, device_id, address)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "device": _device_view(agents, root, device_id), "writes": list(REGISTER_FILES)}


def set_active(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict, *, retire: bool) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    _check_revision(agents, root, device_id, _expected(payload.get("expected_revision")))
    reviewer = str(payload.get("reviewer") or "")
    try:
        (cd.retire_device if retire else cd.restore_device)(root, device_id, reviewer=reviewer)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "device": _device_view(agents, root, device_id), "writes": list(REGISTER_FILES)}


def convert_preview(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict) -> dict[str, Any]:
    """Read-only plan for making a device an application host (a BLOCKED plan is still a normal answer)."""
    root, cd = _root(project_root, work_dir), _store(agents)
    try:
        return cd.scope_plan(root, device_id, host_name=str(payload.get("host_name") or ""),
                             source=str(payload.get("source") or ""), operator=str(payload.get("operator") or ""))
    except ValueError as exc:
        raise _translate(exc) from exc


def convert_apply(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict) -> dict[str, Any]:
    """Record the conversion. Needs the previewed plan's ``preview_id``, the device revision and an explicit ``confirm``."""
    root, cd = _root(project_root, work_dir), _store(agents)
    expected = _expected(payload.get("expected_revision"))
    if payload.get("confirm") is not True:
        raise AssetError(422, "confirm must be true: converting a device to an application host is a deliberate decision", "confirmation_required")
    if not str(payload.get("preview_id") or "").strip():
        raise AssetError(422, "preview_id is required: preview the conversion first", "preview_required")
    try:
        result = cd.convert_to_host(root, device_id, host_name=str(payload.get("host_name") or ""),
                                    source=str(payload.get("source") or ""), operator=str(payload.get("operator") or ""),
                                    preview_id=str(payload["preview_id"]), expected_revision=expected)
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "decision": result["decision"], "rebuild_required": True, "message": result["message"],
            "writes": list(SCOPE_FILES)}


def convert_reverse(project_root: Path, work_dir: Path, agents: Path, device_id: str, payload: dict) -> dict[str, Any]:
    root, cd = _root(project_root, work_dir), _store(agents)
    try:
        result = cd.reverse_conversion(root, device_id, operator=str(payload.get("operator") or ""),
                                       reason=str(payload.get("reason") or ""))
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"status": "OK", "decision": result["decision"], "rebuild_required": True, "message": result["message"],
            "writes": list(SCOPE_FILES)}
