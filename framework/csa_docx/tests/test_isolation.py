"""The isolation dependency matrix: providers per host from settings and flows, tagged with their zone."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings, isolation  # noqa: E402


def _write(path, rows):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_isolation_matrix(tmp_path):
    h = tmp_path / "hosts"
    h.mkdir()
    s = lambda a, v: {"host": "HOSTAA101", "topic": "x", "attribute": a, "value": v, "capture": "c", "source": "c/f line 1", "excerpt": "e"}  # noqa: E731
    _write(h / "host_settings.csv", [s("identity.kdc", "DCSRV00122"), s("time.source", "DCSRV00122 (10.0.0.1)"),
                                     s("dns.primary", "DNSSRV00101 (10.0.0.2)"), s("patch.source", "WSUS on WSUSRV0001 port 8531"),
                                     s("cert.machine", "Example Issuing CA, expires 29/10/2026"), s("agent.backup", "PowerProtect")])
    f = {"flow_id": "", "status": "observed", "mechanism": "backup agent", "data": "yes", "src": "BKPSRV0001", "dst": "HOSTAA101",
         "port": "7000", "cross_zone": "unknown", "src_zone": "", "dst_zone": "", "sources": "c: 23 line 4", "excerpt": "x"}
    _write(h / "flows.csv", [f, f | {"mechanism": "monitoring", "src": "HOSTAA101", "dst": "10.9.9.9", "port": "5723"}])
    _write(h / "zones.csv", [{"zone": "Enterprise IT", "kind": "it", "match": "host:DCSRV00122", "basis": "", "reviewed": "no"}])
    isolation.build(tmp_path)
    got = {a: r["value"] for a, r in host_settings.load(tmp_path)["HOSTAA101"].items() if a.startswith("iso.")}
    assert got == {"iso.core": "directory and time DCSRV00122 (IT), DNS DNSSRV00101 (zone not recorded)",
                   "iso.patch": "WSUSRV0001 (zone not recorded)", "iso.monitoring": "10.9.9.9 (zone not recorded)",
                   "iso.backup": "BKPSRV0001 (zone not recorded)", "iso.cert": "Example Issuing CA"}
