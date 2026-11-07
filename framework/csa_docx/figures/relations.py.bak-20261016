"""Service relationships for CSA figures: which host takes a service (time, DNS, ...) from which provider,
and on which side of the IT/OT line the provider sits. Read from the project's own evidence only.

Each relationship cites the evidence-matrix rows it came from. A relationship the evidence cannot name a
provider for is not created; the figure shows that as a gap instead.

    relations(work_dir, profile) -> {"time": [...], "dns": [...]}
    each: {"service", "consumer", "provider", "order", "state": "active" | "inactive", "evidence": [E-..], "text"}
    residency(provider, register, profile) -> ("it" | "ot" | "internet" | "unknown", reason)

Extractors are small and named per service. A service with no extractor yet returns nothing, and the
figure-need step reports it as "not built yet" rather than drawing an empty figure.
"""
from __future__ import annotations

import csv
import ipaddress
import re
from pathlib import Path

IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
HOSTLIKE = re.compile(r"\b([A-Z][A-Z0-9-]{5,30}\d)\b")          # captured host names: upper case ending in digits
FQDN = re.compile(r"\b([A-Za-z][A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){1,6})\b")


def _csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load(work_dir: Path) -> dict:
    """The evidence a figure may use: the evidence matrix and the host register."""
    matrix = _csv(work_dir / "evidence-matrix.csv")
    register = {r["host"]: r for r in _csv(work_dir / "hosts" / "hosts.csv")}
    facts = _csv(work_dir / "hosts" / "host_facts.csv")
    ip_name: dict[str, str] = {}
    for h, r in register.items():
        for ip in re.split(r"[;,\s]+", r.get("ips") or ""):
            if IPV4.fullmatch(ip or "") and not ip.endswith(".0"):
                ip_name.setdefault(ip, h)
    return {"matrix": matrix, "register": register, "ip_name": ip_name, "facts": facts}


def _short(name: str) -> str:
    return name.split(".")[0].upper() if not IPV4.fullmatch(name) else name


def _usable(row: dict) -> bool:
    return (row.get("status") or "").upper() not in ("REJECTED", "SUPERSEDED", "WITHDRAWN")


# ---------------------------------------------------------------- time
ACTIVE_PEER = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]+):\s*Active NTP peer\s+([A-Za-z0-9.-]+)", re.I)
PENDING_PEER = re.compile(r"^\s*([A-Za-z0-9.-]+)\s+is configured as a pending peer on\s+(.+?)\.", re.I)


def _time(ev: dict) -> list[dict]:
    out = []
    for r in ev["matrix"]:
        if not _usable(r):
            continue
        claim = r.get("claim") or ""
        m = ACTIVE_PEER.match(claim)
        if m:
            out.append({"service": "time", "consumer": m.group(1).upper(), "provider": _short(m.group(2)), "order": 1,
                        "state": "active", "evidence": [r["evidence_id"]], "text": claim})
            continue
        m = PENDING_PEER.match(claim)
        if m:
            hosts = HOSTLIKE.findall(m.group(2))
            for h in hosts:
                out.append({"service": "time", "consumer": h.upper(), "provider": m.group(1).lower(), "order": 2,
                            "state": "inactive", "evidence": [r["evidence_id"]], "text": claim})
    # a host whose time source is in its capture but in no matrix row: cite the capture file and line
    covered = {(r["consumer"], r["state"]) for r in out}
    for f in ev.get("facts", []):
        if f.get("attribute", "").strip().lower() == "time_status: source" and (f["host"].upper(), "active") not in covered:
            src = Path(f.get("source") or "").name
            out.append({"service": "time", "consumer": f["host"].upper(), "provider": _short(f["value"].strip()), "order": 1,
                        "state": "active", "evidence": [f"{src} line {f.get('line') or '?'}"],
                        "text": f"{f['host']}: time source {f['value']} ({src})"})
    return _dedupe(out)


# ---------------------------------------------------------------- DNS
DNS_ROW = re.compile(r"DNS servers?", re.I)


def _dns(ev: dict) -> list[dict]:
    out = []
    names = set(ev["register"])
    for r in ev["matrix"]:
        if not _usable(r):
            continue
        claim = r.get("claim") or ""
        if not DNS_ROW.search(claim):
            continue
        ips = IPV4.findall(claim)
        if not ips:
            continue
        cut = claim.find(ips[0])                      # the hosts are named before their DNS server addresses
        consumers = [h for h in HOSTLIKE.findall(claim[:cut]) if h in names]
        if not consumers:
            continue                                   # a summary row that names no host: not a relationship
        for c in consumers:
            for i, ip in enumerate(dict.fromkeys(ips), 1):
                out.append({"service": "dns", "consumer": c, "provider": ev["ip_name"].get(ip, ip), "order": i,
                            "state": "active", "evidence": [r["evidence_id"]], "text": claim})
    return _dedupe(out)


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in rows:
        k = (r["service"], r["consumer"], r["provider"], r["state"])
        if k in seen:
            seen[k]["evidence"] = sorted(set(seen[k]["evidence"]) | set(r["evidence"]))
            seen[k]["order"] = min(seen[k]["order"], r["order"])
        else:
            seen[k] = dict(r)
    return list(seen.values())


EXTRACTORS = {"time": _time, "dns": _dns}


def relations(work_dir: Path, services: list[str] | None = None, ev: dict | None = None) -> dict[str, list[dict]]:
    ev = ev or load(work_dir)
    return {s: f(ev) for s, f in EXTRACTORS.items() if services is None or s in services}


# ---------------------------------------------------------------- residency
def residency(provider: str, ev: dict, profile: dict) -> tuple[str, str]:
    """Which side a provider sits on, from the project's stated rule and the host register. Never guessed:
    a provider the rule does not cover is 'unknown'."""
    rule = (profile or {}).get("residency") or {}
    if IPV4.fullmatch(provider):
        try:
            if not ipaddress.ip_address(provider).is_private:
                return "internet", "Public address"
        except ValueError:
            pass
        return "unknown", "Address with no name in the evidence"
    reg = ev["register"].get(provider.upper())
    if reg is None:
        if "." in provider and not provider.lower().endswith(tuple(rule.get("it_domains", []))):
            return "internet", "Internet name"
        return "unknown", "Not in the host register"
    fqdn = (reg.get("fqdn") or "").lower()
    is_dc = "domain controller" in (reg.get("sources") or "").lower() or reg.get("ad_site")
    for d in rule.get("ot_domains", []):
        if fqdn.endswith(d.lower()):
            return "ot", f"Member of the OT domain {d}"
    if is_dc:
        for d in rule.get("it_domains", []):
            if fqdn.endswith(d.lower()):
                return "it", f"Domain controller of the enterprise domain {d}" + \
                    (f" ({', '.join(rule['evidence'])})" if rule.get("evidence") else "")
    return "unknown", "Residency not stated in the evidence"
