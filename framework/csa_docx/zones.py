"""Zones: which side of the IT/OT boundary every host and address sits on.

`csa-work/hosts/zones.csv` (project data, reviewed by a person):

    zone,kind,match,basis,reviewed
    OT Rockhampton,ot,subnet:10.40.228.0/27,"roles.csv subnet rule ...",no
    Enterprise directory,it,host:ROTPRDSRV122,"...",no
    Internal, zone not recorded,unknown,default:private,,yes
    Internet,internet,default:public,,yes

kind is one of ot, it, internet, cloud, vendor, unknown. A host rule wins over a subnet rule; the longest
subnet wins; then the defaults. `seed` writes a first version from roles.csv subnet rules (reviewed=no),
so a person confirms it before the zones are treated as settled; the flows keep the zone's review state.

    python3 -m csa_docx.zones seed  --work-dir <work_dir>     (never overwrites an existing zones.csv)
    python3 -m csa_docx.zones show  --work-dir <work_dir> [ADDRESS_OR_HOST ...]
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import sys
from pathlib import Path

FIELDS = ["zone", "kind", "match", "basis", "reviewed"]
KINDS = ("ot", "it", "internet", "cloud", "vendor", "unknown")


def path(work_dir: Path) -> Path:
    return Path(work_dir) / "hosts" / "zones.csv"


def load(work_dir: Path) -> list[dict]:
    f = path(work_dir)
    return list(csv.DictReader(f.open(encoding="utf-8"))) if f.is_file() else []


class Zones:
    def __init__(self, rules: list[dict], host_ips: dict[str, list[str]] | None = None):
        self.hosts = {r["match"].split(":", 1)[1].strip().upper(): r for r in rules if r["match"].startswith("host:")}
        nets = []
        for r in rules:
            if r["match"].startswith("subnet:"):
                try:
                    nets.append((ipaddress.ip_network(r["match"].split(":", 1)[1].strip(), strict=False), r))
                except ValueError:
                    continue
        self.nets = sorted(nets, key=lambda x: -x[0].prefixlen)
        self.private = next((r for r in rules if r["match"] == "default:private"),
                            {"zone": "Internal, zone not recorded", "kind": "unknown", "reviewed": "yes"})
        self.public = next((r for r in rules if r["match"] == "default:public"),
                           {"zone": "Internet", "kind": "internet", "reviewed": "yes"})
        self.host_ips = {h.upper(): ips for h, ips in (host_ips or {}).items()}

    def of_ip(self, ip: str) -> dict:
        try:
            a = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return self.private
        for net, r in self.nets:
            if a.version == net.version and a in net:
                return r
        return self.private if (a.is_private or a.is_link_local) else self.public

    def of(self, name_or_ip: str) -> dict:
        """The zone rule for a host name (host rule, else its first address) or an address."""
        n = (name_or_ip or "").strip()
        if n.upper() in self.hosts:
            return self.hosts[n.upper()]
        if n.upper() in self.host_ips:
            for ip in self.host_ips[n.upper()]:
                r = self.of_ip(ip)
                if r is not self.private:
                    return r
            return self.private
        return self.of_ip(n)


def for_project(work_dir: Path) -> Zones:
    reg = Path(work_dir) / "hosts" / "hosts.csv"
    ips = {}
    if reg.is_file():
        from csa_docx import modelstore
        for r in modelstore.read_csv(reg):
            ips[r["host"]] = [x for x in (r.get("ips") or "").split(";") if x]
    return Zones(load(work_dir), ips)


def seed(work_dir: Path) -> dict:
    """A first zones.csv from roles.csv subnet rules (OT sites), marked reviewed=no."""
    f = path(work_dir)
    if f.is_file():
        return {"status": "EXISTS", "file": str(f)}
    rows = []
    rf = Path(work_dir) / "hosts" / "roles.csv"
    if rf.is_file():
        for r in csv.DictReader(rf.open(encoding="utf-8")):
            if r.get("kind") == "subnet" and r.get("match"):
                site = (r.get("site") or "").strip()
                rows.append({"zone": f"OT {site}".strip(), "kind": "ot", "match": f"subnet:{r['match']}",
                             "basis": f"roles.csv subnet rule for site {site or '(none)'}: confirm this subnet is inside OT",
                             "reviewed": "no"})
    rows += [{"zone": "Internal, zone not recorded", "kind": "unknown", "match": "default:private",
              "basis": "any private address no rule above covers", "reviewed": "yes"},
             {"zone": "Internet", "kind": "internet", "match": "default:public", "basis": "any public address", "reviewed": "yes"}]
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return {"status": "OK", "file": str(f), "rules": len(rows)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--work-dir", type=Path, required=True)
    s = sub.add_parser("show"); s.add_argument("--work-dir", type=Path, required=True); s.add_argument("names", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "seed":
        out = seed(a.work_dir)
    else:
        z = for_project(a.work_dir)
        out = {n: {k: z.of(n).get(k) for k in ("zone", "kind", "reviewed")} for n in a.names} if a.names else load(a.work_dir)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
