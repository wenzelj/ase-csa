"""Isolation dependency matrix (I9): for every host, which services outside its own zone it depends on.

Built from what the other extractors already hold, so it adds no new capture reading:

* directory, time and DNS: identity.kdc, time.source, dns.primary (host_settings.csv)
* patching: patch.source
* monitoring and logs: monitoring, log forwarding and security telemetry flows the host opens (flows.csv)
* backup: backup-agent flows into the host (who pulls the backup)
* certificates: the issuer of the host's machine certificate (cert.machine)

Each provider is tagged with its zone from zones.csv: (IT), (internet), (OT) or (zone not recorded). The rows
go to hosts/isolation.csv in the host_settings.csv format and ``host_settings.load`` merges them, so the topic
table for 3.12 reads them like any other setting. The evidence for 3.12's frame comes from the underlying
settings, which keep their exact quotes; a row here cites the first underlying source only.

    python -m csa_docx.isolation build --work-dir <csa-work>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

FIELDS = ["host", "topic", "attribute", "value", "capture", "source", "excerpt"]
_KIND = {"it": "IT", "internet": "internet", "cloud": "cloud", "vendor": "vendor", "ot": "OT"}
MONITOR = {"monitoring", "log forwarding", "security agent telemetry"}


def _name(v: str) -> str:
    """'ROTPRDSRV122 (10.40.228.97)' -> 'ROTPRDSRV122'; 'WSUS on IPTPRDCCM202 port 8531' -> 'IPTPRDCCM202'."""
    v = re.sub(r"^WSUS on\s+", "", v or "").strip()
    v = re.sub(r"\s+port\s+\d+$", "", v)
    return re.split(r"\s*[(,]", v)[0].strip()


def _list(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def build(work_dir: Path) -> dict:
    from csa_docx import flows as flows_mod, host_settings, zones as zones_mod
    work_dir = Path(work_dir)
    settings = host_settings.load(work_dir, merge_isolation=False)
    z = zones_mod.for_project(work_dir)
    rows_f = flows_mod.load(work_dir)

    def zone(name: str) -> str:
        return _KIND.get(z.of(name).get("kind", ""), "zone not recorded")

    def tag(name: str) -> str:
        return f"{name} ({zone(name)})"

    def tags(names: list[str], more: bool = False) -> str:
        """'a and b (zone not recorded), c (internet)': names grouped under their zone, in first-seen order."""
        by: dict[str, list[str]] = {}
        for n in names:
            by.setdefault(zone(n), []).append(n)
        parts = [f"{_list(ns)} ({k})" for k, ns in by.items()]
        return ", ".join(parts) + (", and others" if more else "")

    out = []
    for h, attrs in sorted(settings.items()):
        def row(attr, value, src_row=None, flow=None):
            src = (src_row or {}).get("source", "") or ((flow or {}).get("sources", "").split("; ")[0] if flow else "")
            out.append({"host": h, "topic": "isolation", "attribute": attr, "value": value,
                        "capture": (src_row or {}).get("capture", ""), "source": src,
                        "excerpt": (src_row or {}).get("excerpt", "") or (flow or {}).get("excerpt", "")})
        core = [(label, attrs.get(a)) for label, a in (("directory", "identity.kdc"), ("time", "time.source"),
                                                       ("DNS", "dns.primary"))]
        names = {label: _name(r["value"]) for label, r in core if r and r.get("value")
                 and not r["value"].startswith(("No ", "None"))}
        if names:
            if len(set(names.values())) == 1:
                row("iso.core", tag(next(iter(names.values()))), next(r for _, r in core if r))
            else:
                by: dict[str, list[str]] = {}
                for label, n in names.items():
                    by.setdefault(n, []).append(label)
                row("iso.core", ", ".join(f"{_list(ls)} {tag(n)}" for n, ls in by.items()), next(r for _, r in core if r))
        r = attrs.get("patch.source")
        if r and r.get("value"):
            row("iso.patch", tag(_name(r["value"])) if r["value"].startswith("WSUS") else r["value"], r)
        mine = [f for f in rows_f if f["status"] in ("observed", "both") and f["mechanism"] in MONITOR
                and h in {x.strip().upper() for x in f["src"].split(",")}]
        if mine or attrs:
            dsts = list(dict.fromkeys(f["dst"] for f in mine))
            row("iso.monitoring", tags(dsts[:4], len(dsts) > 4) if dsts else "None seen", None, mine[0] if mine else None)
        bk = [f for f in rows_f if f["status"] in ("observed", "both") and f["mechanism"] == "backup agent"
              and h in {x.strip().upper() for x in f["dst"].split(",")}]
        srcs = list(dict.fromkeys(f["src"] for f in bk))
        if bk or attrs.get("agent.backup"):
            row("iso.backup", tags(srcs) if srcs else "None seen", None, bk[0] if bk else None)
        r = attrs.get("cert.machine")
        if r and r.get("value") and r["value"] != "None found":
            issuers = [x.strip() for x in re.split(r",\s*(?:expires|expired)\s+[0-9/]+,?", r["value"]) if x.strip()]
            row("iso.cert", ", ".join(dict.fromkeys(issuers)), r)
    f = work_dir / "hosts" / "isolation.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return {"status": "OK", "rows": len(out), "hosts": len({r["host"] for r in out}), "out": str(f)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build"); s.add_argument("--work-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.work_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
