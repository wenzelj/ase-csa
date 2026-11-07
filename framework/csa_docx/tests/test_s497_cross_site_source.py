"""S497: source_in_other_site finds hosts whose time source is registered in another site."""
import csv
from pathlib import Path

from csa_docx import topic_frames as T

REG = [("MOTPRDREV101", "Mackay", "10.1.0.1"), ("MOTPRDLOG103", "Mackay", "10.1.0.2"),
       ("MOTPRDCLU101", "Mackay", "10.1.0.3"), ("MOTPRDCLU103", "Mackay", "10.1.0.4"),
       ("ROTPRDSRV122", "Rockhampton", "10.2.0.22"), ("MOTPRDSRV122", "Mackay", "10.1.0.22"),
       ("NOSITE01", "", "10.3.0.1"), ("UNKSRC01", "Mackay", "10.1.0.9")]
SOURCES = {"MOTPRDREV101": "ROTPRDSRV122 (10.2.0.22)", "MOTPRDLOG103": "ROTPRDSRV122", "MOTPRDCLU101": "ROTPRDSRV122.corp.example",
           "MOTPRDCLU103": "MOTPRDSRV122", "NOSITE01": "ROTPRDSRV122", "UNKSRC01": "SOMEWHERE99",
           "ROTPRDSRV122": "MOTPRDSRV122"}


def project(tmp_path: Path) -> Path:
    h = tmp_path / "hosts"
    h.mkdir()
    with (h / "hosts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["host", "in_scope", "system", "role", "site", "ips", "capture"])
        for n, site, ip in REG:
            w.writerow([n, "yes", "S", "Server", site, ip, "X"])
    with (h / "host_settings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["host", "topic", "attribute", "value", "capture", "source", "excerpt"])
        for n, v in SOURCES.items():
            w.writerow([n, "time", "time.source", v, "X", f"{n}/20_time.txt line 3", f"Source: {v}"])
    return tmp_path


def run(tmp_path):
    return T.cross_site_findings(project(tmp_path), {"attr": "time.source", "blocks": ["SEP-TIME-01", "Drawbridge Impact"]},
                                 "SEP-TIME-01", "time_synchronisation", "time synchronisation")


def test_three_mackay_hosts_found(tmp_path):
    f = [x for x in run(tmp_path) if x["class"] == "source_in_other_site" and x["source_host"] == "ROTPRDSRV122"]
    assert len(f) == 1
    assert {"MOTPRDREV101", "MOTPRDLOG103", "MOTPRDCLU101"} <= set(f[0]["hosts"])
    assert "MOTPRDCLU103" not in f[0]["hosts"] and "NOSITE01" not in f[0]["hosts"]
    assert f[0]["evidence"] and f[0]["source_site"] == "Rockhampton"


def test_same_site_source_not_found(tmp_path):
    other = [x for x in run(tmp_path) if x["class"] == "source_in_other_site"]
    assert all("MOTPRDCLU103" not in x["hosts"] for x in other)


def test_unknown_site_listed_separately(tmp_path):
    u = [x for x in run(tmp_path) if x["class"] == "source_site_unknown"]
    assert len(u) == 1 and u[0]["hosts"] == ["NOSITE01"]


def test_bound_to_requirement_and_drawbridge(tmp_path):
    slot = {"requirements": ["SEP-TIME-01"]}
    f = run(tmp_path)
    T.bind_requirements(slot, f)
    res = {"slots": [{"id": "S6", "question": "q", "requirements": ["SEP-TIME-01"], "findings": f}]}
    m = T.must_address(res)
    assert any("Source in another site" in x["text"] for x in m["SEP-TIME-01"])
    assert any("Source in another site" in x["text"] for x in m["Drawbridge Impact"])
