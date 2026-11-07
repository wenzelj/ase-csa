"""The endpoint register: one row per end of a flow, in csa-work/hosts/endpoints.csv.

What an endpoint is and which zone it sits in was held in five places that never
synced (hosts/zones.csv, the "Likely ..." hints in hosts/unrecorded-peers.csv,
parts.json `assign`, the figure code and the evidence rows that resolve a peer).
This module merges them into one register, one row per endpoint (system host or
peer), with a confidence and a basis for each field:

    end,name,zone,confidence,basis,evidence,reviewed
    MOTPRDPDM101,Mackay Dell PowerProtect Data Manager,,observed,gap lookup evidence,E-1547,no
    ROTPRDREV102,OT Reveloc Server,OT Rockhampton,observed,"register role; site Rockhampton in the register",,no
    10.40.254.6,Dell PowerProtect Data Manager server,,likely,unrecorded-peer hint,,,no

Sources, in this order (a later source fills only what is still empty, and never
overrides a reviewed row):

1. the existing endpoints.csv rows with reviewed=yes, kept as they are;
2. register hosts (hosts.csv): name = role, confidence = observed;
3. the zone zones.for_project(work_dir) gives the host or address;
4. a register host with no zone from 3, an in-scope role and a site gets the
   zone "OT <site>" when zones.csv has an ot zone of exactly that name (basis
   "site <site> in the register"); a step-3 zone that disagrees with the site's
   OT zone is kept and listed as a conflict;
5. parts.json `assign` entries: name = the assigned part, confidence = documented;
6. VERIFIED gap_lookup evidence rows whose question ends in "zone and
   operational role of <end>" (E-1547 style): the name is the claim text after
   the first " is the " / " is a " up to the first comma or full stop, with any
   leading "internal address of <host>, the " removed; an <end> that a register
   host carries in its ips is written against that host name;
7. peer hints in hosts/unrecorded-peers.csv: the role text without "Likely " and
   without anything from ", confirm" on; confidence = likely.

    python3 -m csa_docx.endpoints build  --work-dir <work_dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from csa_docx import zones

FIELDS = ["end", "name", "zone", "confidence", "basis", "evidence", "reviewed"]
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def path(work_dir: Path) -> Path:
    return Path(work_dir) / "hosts" / "endpoints.csv"


def _csv(work_dir: Path, *parts: str) -> list[dict]:
    p = Path(work_dir).joinpath(*parts)
    if not p.is_file():
        return []
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def _register(work_dir: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """({HOST: row} of hosts.csv, {IP: HOST} for its addresses)."""
    reg: dict[str, dict] = {}
    ip2host: dict[str, str] = {}
    for r in _csv(work_dir, "hosts", "hosts.csv"):
        h = (r.get("host") or "").strip().upper()
        if not h:
            continue
        e = reg.setdefault(h, {})
        for k, v in r.items():
            if v not in (None, "") and not e.get(k):
                e[k] = v
        for ip in (r.get("ips") or "").split(";"):
            ip = ip.strip()
            if IP_RE.match(ip):
                ip2host.setdefault(ip, h)
    return reg, ip2host


def _evidence_names(work_dir: Path) -> dict[str, tuple[str, str]]:
    """{end (as the question names it): (name, evidence_id)} from VERIFIED gap_lookup rows
    whose question ends in "zone and operational role of <end>" (E-1547 style)."""
    out: dict[str, tuple[str, str]] = {}
    from csa_docx import evidence_live
    for r in evidence_live.read(Path(work_dir) / "evidence-matrix.csv", drop_rejected=True):
        if (r.get("csa_area") or "") != "gap_lookup" or (r.get("status") or "") != "VERIFIED":
            continue
        q = (r.get("question") or "").strip()
        i = q.rfind("zone and operational role of ")
        if i < 0:
            continue
        end = q[i + len("zone and operational role of "):].strip().rstrip("?").strip()
        if not end or " " in end:
            continue
        m = re.search(r"\bis (a|the) ", r.get("claim") or "")
        if not m:
            continue
        rest = r["claim"][m.end():]
        rest = re.sub(r"\binternal address of [A-Za-z][A-Za-z0-9.-]*,\s*the\s*", "", rest)
        rest = re.sub(r"\binternal name [A-Za-z][A-Za-z0-9.-]*\s*\([^)]*\)\s*(?:\([^)]*\))?,\s*the\s*", "", rest)
        name = re.split(r"[,(;]", rest, maxsplit=1)[0].strip().strip("(),")
        name = re.split(r"\s+(?:that|which|serving|which serves|serves)\b", name, maxsplit=1)[0].strip()
        if not name:
            continue
        out.setdefault(end.upper(), (name, (r.get("evidence_id") or "").strip()))
    return out


def _peer_names(work_dir: Path) -> dict[str, str]:
    """{PEER: role text} from the unrecorded-peers hints: without "Likely " and
    without anything from ", confirm" on."""
    out = {}
    for r in _csv(work_dir, "hosts", "unrecorded-peers.csv"):
        h = (r.get("hint") or "").strip()
        if h.startswith("Likely "):
            h = h[len("Likely "):]
        h = re.split(r",\s*confirm", h, maxsplit=1)[0].strip(" ,;")
        peer = (r.get("peer") or "").strip().upper()
        if h and peer:
            out.setdefault(peer, h)
    return out


def build(work_dir: Path) -> dict:
    """Merge the endpoint sources into hosts/endpoints.csv; reviewed rows are never overwritten."""
    work_dir = Path(work_dir)
    reg, ip2host = _register(work_dir)
    zone_rules = zones.load(work_dir)
    ot_zones = {r["zone"].strip() for r in zone_rules if (r.get("kind") or "").strip().lower() == "ot"}
    zp = zones.Zones(zone_rules, {h: [x for x in (r.get("ips") or "").split(";") if x.strip()] for h, r in reg.items()}) \
        if zone_rules else None

    rows: dict[str, dict] = {}
    existing = {r["end"].strip().upper(): r for r in _csv(work_dir, "hosts", "endpoints.csv")
                if (r.get("end") or "").strip()}

    def row(end: str) -> dict:
        key = end.strip().upper()
        prev = existing.get(key) or {}
        reviewed = (prev.get("reviewed") or "").strip().lower() in ("yes", "y")
        return rows.setdefault(key, {
            "end": end.strip(),
            "name": prev.get("name") or "" if reviewed else "",
            "zone": prev.get("zone") or "" if reviewed else "",
            "confidence": prev.get("confidence") or "" if reviewed else "",
            "basis": [prev["basis"]] if reviewed and (prev.get("basis") or "").strip() else [],
            "evidence": {prev["evidence"]} if reviewed and (prev.get("evidence") or "").strip() else set(),
            "reviewed": reviewed,
        })

    def fill(r: dict, name: str = "", zone: str = "", conf: str = "", basis: str = "", ev: str = "") -> None:
        if r["reviewed"]:
            return
        if name and not r["name"]:
            r["name"] = name
            r["confidence"] = r["confidence"] or conf
        if zone and not r["zone"]:
            r["zone"] = zone
        if basis:
            r["basis"].append(basis)
        if ev:
            r["evidence"].add(ev)

    conflicts: list[str] = []

    # 2. register hosts: name = role, confidence = observed
    for h, r in reg.items():
        role = (r.get("role") or "").strip()
        if role:
            fill(row(h), name=role, conf="observed", basis="register role")

    # 3. the zone zones.for_project gives the host; 4. a register host with no zone,
    # an in-scope role and a site gets "OT <site>" when zones.csv has that ot zone;
    # a step-3 zone that disagrees with it is kept and listed as a conflict.
    for h, r in reg.items():
        e = row(h)
        site = (r.get("site") or "").strip()
        want = f"OT {site}".strip()
        in_scope = bool(r.get("role")) and (r.get("in_scope") or "").lower() not in ("", "peer")
        if zp is not None:
            z = zp.of(h)
            if z is not zp.private:
                fill(e, zone=z.get("zone") or "", basis=f"zones.csv {h}")
        if in_scope and site and want in ot_zones and not e["reviewed"]:
            if e["zone"] and e["zone"] != want:
                conflicts.append(f"{e['end']}: zones.csv says {e['zone']}, site {site} in the register says {want} (kept {e['zone']})")
            elif not e["zone"]:
                fill(e, zone=want, basis=f"site {site} in the register")

    # 5. parts.json assign: name = the assigned part, confidence = documented
    pf = work_dir / "parts.json"
    if pf.is_file():
        try:
            doc = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        for key, part in (doc.get("assign") or {}).items():
            key_u = str(key).strip().upper()
            if key_u in reg and str(part).strip():
                fill(row(key_u), name=str(part).strip(), conf="documented", basis="parts.json assign")

    # 6. VERIFIED gap_lookup evidence rows naming the end. The claim's <end> is written as-is;
    # an <end> that a register host carries in its ips then also fills that host's empty name
    # (E-1547: "10.45.229.194 is the internal address of MOTPRDPDM101 ..., the Mackay ...").
    ev = _evidence_names(work_dir)
    for end, (name, eid) in ev.items():
        fill(row(end), name=name, conf="observed", basis="gap lookup evidence", ev=eid)
        host = ip2host.get(end)
        if host:
            fill(row(host), name=name, conf="observed", basis=f"gap lookup evidence ({end})", ev=eid)

    # 7. peer hints from unrecorded-peers.csv
    for peer, name in _peer_names(work_dir).items():
        fill(row(peer), name=name, conf="likely", basis="unrecorded-peer hint")

    # reviewed rows are kept as they are; everything else in first-seen order
    out_rows = []
    for key in existing:
        p = existing[key]
        if (p.get("reviewed") or "").strip().lower() in ("yes", "y"):
            out_rows.append({k: (p.get(k) or "") for k in FIELDS})
    seen = {k.upper() for k in (p["end"] for p in out_rows)}
    for r in rows.values():
        if r["end"].upper() in seen:
            continue
        out_rows.append({"end": r["end"], "name": r["name"], "zone": r["zone"], "confidence": r["confidence"],
                         "basis": "; ".join(dict.fromkeys(b for b in r["basis"] if b)),
                         "evidence": ";".join(sorted(r["evidence"])), "reviewed": "yes" if r["reviewed"] else "no"})
    (work_dir / "hosts").mkdir(exist_ok=True)
    with path(work_dir).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    proposed = [r["end"] for r in rows.values()
                if not r["reviewed"] and r["name"] and any("gap lookup" in b or "unrecorded-peer" in b for b in r["basis"])]
    return {"status": "OK", "rows": len(out_rows), "conflicts": conflicts, "proposed": proposed,
            "out": str(path(work_dir))}


def load(work_dir: Path) -> dict[str, dict]:
    """Rows keyed by `end` upper-cased; an address a register host carries in its ips
    resolves to the host name too."""
    out = {r["end"].strip().upper(): r for r in _csv(work_dir, "hosts", "endpoints.csv") if (r.get("end") or "").strip()}
    reg, ip2host = _register(work_dir)
    for ip, h in ip2host.items():
        if ip.upper() not in out and h in out:
            out[ip.upper()] = out[h]
    return out


def label(row: dict) -> str:
    """`name`, or `likely <name> (to confirm)` for a likely name, or "" when unknown."""
    name = (row.get("name") or "").strip()
    if not name:
        return ""
    return f"likely {name} (to confirm)" if (row.get("confidence") or "").strip().lower() == "likely" else name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.work_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
