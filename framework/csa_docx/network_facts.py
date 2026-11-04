"""Network facts: where a named host sits, and how the project knows it.

One deterministic answer per host or address, built from what the project already holds: the confirmed host identities
(`hosts/host_facts.csv`, the "Host identities confirmed" file), the zone rules (`hosts/zones.csv` through `zones.py`), the
captures' AD sites and addresses (`hosts/hosts.csv`), and the evidence rows that say the same thing (E-n). It never guesses:
a subnet nobody recorded is reported as not recorded, and an assumed identity stays labelled assumed.

    python3 -m csa_docx.network_facts --work-dir <csa-work> ROTPRDSRV122 10.40.228.97
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
from pathlib import Path

from csa_docx import zones as zones_mod

_IDENT = re.compile(r"^([^:]*):\s*(role|hosted in|note|notes|confirmed by|confirmed on|ip address)$", re.I)
_HOSTED = re.compile(r"\bhosted in\b", re.I)


def _rows(work: Path, name: str) -> list[dict]:
    p = Path(work) / "hosts" / name
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.is_file() else []


def _in_subnet(ip: str, match: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(match.split(":", 1)[1].strip(), strict=False)
    except ValueError:
        return False


class NetworkFacts:
    def __init__(self, work_dir: Path):
        self.work = Path(work_dir)
        self.zones = zones_mod.for_project(self.work)
        self.ident: dict[str, dict[str, str]] = {}
        self.ad_site: dict[str, str] = {}
        for r in _rows(self.work, "host_facts.csv"):
            host, attr, val = (r.get("host") or "").upper(), r.get("attribute") or "", (r.get("value") or "").strip()
            m = _IDENT.match(attr)
            if m and val and (r.get("listed_as") or "") != "capture":
                key = "note" if m[2].lower() == "notes" else m[2].lower()
                d = self.ident.setdefault(host, {})
                if "identit" in m[1].lower():                     # the confirmed-identities file outranks other sources
                    d[key] = val
                else:
                    d.setdefault(key, val)
            elif attr.endswith("AD site") and val:
                self.ad_site.setdefault(host, val)
        self.addresses: dict[str, str] = {}              # address -> host
        self.hosts_ips: dict[str, list[str]] = {}
        for r in _rows(self.work, "hosts.csv"):
            host = (r.get("host") or "").strip().upper()
            for ip in re.split(r"[;,\s]+", r.get("ips") or ""):
                if host and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                    self.addresses.setdefault(ip, host)
                    self.hosts_ips.setdefault(host, []).append(ip)
        for host, d in self.ident.items():
            ip = d.get("ip address", "")
            if ip:
                self.addresses.setdefault(ip, host)
                if ip not in self.hosts_ips.setdefault(host, []):
                    self.hosts_ips[host].append(ip)
        self._evidence = self._hosted_rows()
        try:                                              # a peer the register does not hold, named by an evidence row
            from csa_docx import evidence_live
            from csa_docx.section_card import evidence_address_hosts
            for ip, host in evidence_address_hosts(evidence_live.get_verified_evidence(self.work / "evidence-matrix.csv")).items():
                self.addresses.setdefault(ip, host)
                self.hosts_ips.setdefault(host, [])
                if ip not in self.hosts_ips[host]:
                    self.hosts_ips[host].append(ip)
        except Exception:
            pass

    def _hosted_rows(self) -> dict[str, str]:
        """host -> id of the matrix row that says it is hosted somewhere (E-1570: 'ROTPRDSRV122 is hosted in OT at Rockhampton')."""
        out: dict[str, str] = {}
        try:
            from csa_docx import evidence_live
            for r in evidence_live.read(self.work / "evidence-matrix.csv"):
                c = (r.get("claim") or "").strip()
                m = re.match(r"([A-Z][A-Z0-9]{6,})\b", c)
                if m and r.get("status") == "VERIFIED" and _HOSTED.search(c):
                    out.setdefault(m[1], r["evidence_id"])
        except Exception:
            pass
        return out

    def host(self, name: str) -> dict:
        """What is known about one host: role, zone, site, addresses, how it is known, and the row that backs it."""
        n = (name or "").strip().split(".")[0].upper()
        d = self.ident.get(n, {})
        note = d.get("note", "")
        zone = d.get("hosted in", "")
        z = self.zones.of(n)
        if not zone and z.get("kind") not in (None, "unknown"):
            zone = z.get("zone", "")
        how = "not recorded"
        if d:
            how = f"assumed ({re.sub(r'^assumed:?\s*', '', note)})" if re.search(r"assum", note, re.I) else \
                f"confirmed by {d.get('confirmed by', 'the user')}" + (f" {d['confirmed on']}" if d.get("confirmed on") else "")
        elif zone:
            how = "zone rule: " + (z.get("basis") or "zones.csv")[:90]
        ips = [ip for ip in dict.fromkeys(self.hosts_ips.get(n, [])) if not ip.startswith("169.254.")]
        return {"host": n, "role": d.get("role", ""), "zone": zone, "site": self.ad_site.get(n, ""), "addresses": ips,
                "how": how, "assumed": how.startswith("assumed"), "known": bool(d), "evidence": self._evidence.get(n, ""),
                "outside_listed_subnets": [ip for ip in ips if self.outside_listed(ip)]}

    def outside_listed(self, ip: str) -> bool:
        """True when the address lies in none of the subnets zones.csv lists for any zone (the host's own subnet is then not recorded)."""
        return not any(_in_subnet(ip, r["match"]) for _, r in self.zones.nets)

    def listed_subnets(self, zone: str) -> list[str]:
        return [r["match"].split(":", 1)[1] for _, r in self.zones.nets if (r.get("zone") or "").lower().startswith(zone.split(" (")[0].lower())]

    def line(self, name: str) -> str:
        """One sentence the writer can turn into a Fact: where the host sits, how that is known, and what is not recorded."""
        h = self.host(name)
        if not h["known"] and not h["zone"]:
            return f"{h['host']}: zone not recorded."
        where = f"hosted in {h['zone']}" if h["zone"] else "zone not recorded"
        site = re.search(r"\(([^)]+)\)", h["zone"] or "")
        label = (f"The {h['role']}" + (f" at {site[1]}" if site else "")) if h["role"] else h["host"]
        bits = [f"{label} (host {h['host']}" + (f", {', '.join(h['addresses'])}" if h["addresses"] else "") + f": for tables, not for prose) is {where}"]
        if h["site"]:
            bits.append(f"AD site {h['site']}")
        text = ", ".join(bits) + f"; {h['how']}"
        if h["evidence"] and not h["assumed"]:
            text += f" ({h['evidence']}, basis stated)"
        elif h["assumed"]:
            text += " (no evidence row: do not state it as confirmed; ask for the confirmation as a QUESTION)"
        if h["addresses"] and h["how"].startswith("confirmed"):
            out = h["outside_listed_subnets"]
            if out:
                text += (f". Its subnet is not recorded: {', '.join(out)} lies outside every subnet listed for the OT zones")
        return text + "."


_IDENTITY_ROW = re.compile(r"is the address of|further address|hosted in|\bAD site\b|Domain controller that issued|domain controller discovery|"
                           r"answers? DC discovery|is a domain controller|answered by", re.I)


def server_rows(work_dir: Path, hosts: list[str], skip: set[str] | None = None, per_host: int = 5, total: int = 14) -> list[dict]:
    """The evidence rows that say who a named server is and where it sits: its address, its place, its AD site, the domain controller
    that answered. A topic's slots cite what hosts do; the servers they name (a DNS server, a time source, a patch server) are asked about
    too (where is it, is it independent), and those rows are in other subject areas, so they are pulled here by host. Connection rows are
    left out: they say what the host did, not what it is. Rows already on the card (``skip``) are not repeated."""
    from csa_docx import evidence_live
    skip = {i.upper() for i in (skip or set())}
    rows = evidence_live.get_verified_evidence(Path(work_dir) / "evidence-matrix.csv")
    out: list[dict] = []
    for host in hosts:
        h = host.upper()
        mine = [r for r in rows if r["evidence_id"].upper() not in skip and h in (r.get("claim") or "").upper()
                and _IDENTITY_ROW.search(r.get("claim") or "") and "established connection" not in (r.get("claim") or "")]
        mine.sort(key=lambda r: (len(r.get("claim") or ""), r["evidence_id"]))
        out += [{"id": r["evidence_id"], "host": h, "claim": " ".join((r.get("claim") or "").split())[:300]} for r in mine[:per_host]]
    seen, uniq = set(), []
    for r in out:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    return uniq[:total]


def promote(work_dir: Path, apply: bool = False) -> list[dict]:
    """The evidence rows that state a host's place (E-1570: 'ROTPRDSRV122 is hosted in OT at Rockhampton') where the host register records
    the identity as confirmed by a named person. Each is marked reviewed in evidence-reviews.jsonl so an answer may cite it (basis stated).
    An identity the register only assumes is not promoted. Returns what was (or would be) marked."""
    import datetime
    from csa_docx import evidence_live
    work = Path(work_dir)
    nf = NetworkFacts(work)
    by_id = {r["evidence_id"]: r for r in evidence_live.read(work / "evidence-matrix.csv")}
    todo = []
    for host, eid in nf._evidence.items():
        h = nf.host(host)
        row = by_id.get(eid) or {}
        if h["known"] and not h["assumed"] and not evidence_live.is_verified(row):
            todo.append({"evidence_id": eid, "host": host, "by": h["how"], "claim": row.get("claim", "")[:100]})
    if apply and todo:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with (work / "evidence-reviews.jsonl").open("a", encoding="utf-8") as fh:
            for t in todo:
                fh.write(json.dumps({"evidence_id": t["evidence_id"], "state": "reviewed", "by": "host register (" + t["by"] + ")",
                                     "at": now, "note": f"identity of {t['host']} confirmed in the host register: " + t["claim"]}) + "\n")
    return todo


def check(work_dir: Path) -> list[str]:
    """Contradictions and gaps in the network register, for a person to settle (nothing is changed)."""
    work = Path(work_dir)
    nf = NetworkFacts(work)
    out: list[str] = []
    for r in zones_mod.load(work):                       # a basis that says an address is inside a subnet it is not inside
        for ip, net in re.findall(r"(?:host:|\b)(\d{1,3}(?:\.\d{1,3}){3})\b[^;]{0,60}?(?:inside|in)\s+(?:OT\s+)?(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})", (r.get("match", "") + " " + r.get("basis", ""))):
            if not _in_subnet(ip, "x:" + net):
                out.append(f"zones.csv: {r['zone']} {r['match']}: the basis puts {ip} inside {net}, which does not contain it")
    owners: dict[str, set[str]] = {}
    for host, ips in nf.hosts_ips.items():
        for ip in ips:
            owners.setdefault(ip, set()).add(host)
    out += [f"address {ip} is held by more than one host: {', '.join(sorted(h))}" for ip, h in owners.items() if len(h) > 1 and not ip.startswith("169.254.")]
    for host in sorted(nf.ident):
        h = nf.host(host)
        if h["assumed"]:
            out.append(f"{host}: zone {h['zone']} is {h['how']}; confirm it or leave it labelled assumed")
        z = nf.zones.of(host)
        if h["zone"].upper().startswith("OT") and z.get("kind") == "it":
            out.append(f"{host}: identity says {h['zone']} but zones.csv puts it in {z.get('zone')} (IT)")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--evidence", action="store_true", help="mark the rows that state a confirmed host's place as reviewed")
    ap.add_argument("--check", action="store_true", help="list contradictions and assumptions in the network register")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args(argv)
    if a.evidence:
        todo = promote(Path(a.work_dir), apply=a.apply)
        print(json.dumps({"applied": a.apply, "rows": todo}, indent=1))
        return 0
    if a.check:
        out = check(Path(a.work_dir))
        text = "# Network register check\n\n" + ("\n".join(f"- {x}" for x in out) or "Nothing to report.") + "\n"
        (Path(a.work_dir) / "network-check.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    nf = NetworkFacts(Path(a.work_dir))
    for n in a.names:
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", n):
            h = nf.addresses.get(n)
            print(n, "->", nf.line(h) if h else f"{n}: no host recorded for this address")
        else:
            print(json.dumps(nf.host(n)), "\n ", nf.line(n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
