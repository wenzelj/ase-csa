from __future__ import annotations

import csv
from pathlib import Path

from backend import assets

AGENTS = Path(__file__).resolve().parents[2]


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "csa-work"
    hosts = work / "hosts"
    hosts.mkdir(parents=True, exist_ok=True)

    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "APP1,Yes,Sample,Application server,Rockhampton,10.124.32.10;10.124.32.40,2026-01-05,asset inventory;capture,\n"
        "PEER1,peer,Other,Neighbour system,Brisbane,10.124.32.99,2026-01-05,neighbour inventory,\n",
        encoding="utf-8",
    )

    matrix_rows = [
        {"evidence_id": "E-101", "csa_area": "network_and_connectivity", "status": "VERIFIED",
         "claim": "PEER1 (10.124.32.99) has an established connection to APP1 on port 5985, served by wsmprovhost.exe",
         "review_state": "reviewed"},
        {"evidence_id": "E-102", "csa_area": "network_and_connectivity", "status": "VERIFIED",
         "claim": "APP1 has an established connection from svchost.exe to 10.124.32.200 on port 445",
         "review_state": "reviewed"},
        {"evidence_id": "E-103", "csa_area": "network_and_connectivity", "status": "VERIFIED",
         "claim": "APP1 has an established connection from Edge.exe to 203.0.113.9 on a dynamic (https)",
         "review_state": "reviewed"},
        {"evidence_id": "E-200", "csa_area": "network_and_connectivity", "status": "VERIFIED",
         "claim": "APP1 talks to the print room 2 printer at 10.124.32.210",
         "review_state": "reviewed"},
        {"evidence_id": "E-300", "csa_area": "network_and_connectivity", "status": "NOT_FOUND",
         "claim": "APP1 uses 10.124.32.250 for an unrecorded service",
         "review_state": "pending"},
    ]
    with (work / "evidence-matrix.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["evidence_id", "csa_area", "status", "claim", "review_state"])
        w.writeheader()
        for r in matrix_rows:
            w.writerow(r)

    (hosts / "addresses.csv").write_text(
        "address,name,kind,seen_from,host_count,directions,ports,processes,sessions,evidence_ids\n"
        "10.124.32.200,name not captured,private,APP1,1,outbound,445,svchost.exe,3,E-101\n"
        "10.124.32.10,name not captured,private,PEER1,1,inbound,5985,wsmprovhost.exe,2,E-102\n"
        "203.0.113.9,name not captured,public,APP1,1,outbound,443,Edge.exe,5,E-103\n",
        encoding="utf-8",
    )
    (hosts / "host_links.csv").write_text(
        "src_host,dst_host,dst_port,connections,basis,source\n"
        "APP1,10.124.32.200,445,3,dst not captured; port not verified,captures\n"
        "PEER1,APP1,5985,2,dst listens on port,captures\n"
        "APP1,PEER1,3389,1,dst not captured; port not verified,captures\n",
        encoding="utf-8",
    )
    (hosts / "host_services.csv").write_text(
        "client_host,service,server_ip,server_host,preference,capture,source,excerpt\n"
        "APP1,dns,10.124.32.10,DC1,0,2026-01-05,14_resolver.txt,line 3\n",
        encoding="utf-8",
    )
    (hosts / "connected_devices.csv").write_text(
        "device_id,name,device_type,role,owner,site_zone,relationship,classification,identification_state,provenance,reviewer,recorded,active,revision\n"
        "CD-000001,Printer room 2,printer,print,ops,Rockhampton,supporting IT,supporting IT,confirmed,asset register,WM,2026-01-06,true,1\n"
        "CD-000002,Vending bay 4,vending machine,shared,vendors,Perth,shared,shared,unidentified,,WM,2026-01-06,true,1\n",
        encoding="utf-8",
    )
    (hosts / "device_addresses.csv").write_text(
        "device_id,address,normalized,address_type,first_seen,last_seen,source,active\n"
        "CD-000001,10.124.32.210,10.124.32.210,ipv4,,,asset register,true\n"
        "CD-000001,printer.room2.local,printer.room2.local,fqdn,,,asset register,true\n"
        "CD-000001,10.124.32.40,10.124.32.40,ipv4,,,asset register,true\n"
        "CD-000002,10.124.32.210,10.124.32.210,ipv4,,,asset register,true\n",
        encoding="utf-8",
    )
    return work


def test_groups_are_distinct_and_complete(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS)
    counts = out["counts"]
    assert counts == {"application_hosts": 1, "devices": 2, "unidentified": 3, "conflicts": 2}
    assert set(out["groups"]) == {"application_hosts", "devices", "unidentified", "conflicts"}
    names = [h["name"] for h in out["groups"]["application_hosts"]["items"]]
    assert names == ["APP1"]


def test_application_host_keeps_role_site_and_exact_aliases(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="application_hosts")
    h = out["groups"]["application_hosts"]["items"][0]
    assert h["role"] == "Application server"
    assert h["site"] == "Rockhampton"
    assert h["state"] == "captured"
    assert "10.124.32.10" in h["aliases"] and "10.124.32.40" in h["aliases"]
    assert h["services"][0]["service"] == "dns"
    assert h["services"][0]["server_ip"] == "10.124.32.10"
    inbound = next(c for c in h["observed_connections"] if c["src"] == "PEER1" and c["dst"] == "APP1")
    assert inbound["dst_port"] == "5985"
    assert {e["evidence_id"] for e in h["evidence"]} == {"E-101", "E-102", "E-103", "E-200"}


def test_device_rows_keep_register_fields_and_multiple_aliases(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="devices")
    items = out["groups"]["devices"]["items"]
    printer = next(d for d in items if d["id"] == "CD-000001")
    assert printer["type"] == "printer" and printer["role"] == "print"
    assert printer["site"] == "Rockhampton" and printer["state"] == "confirmed"
    assert printer["classification"] == "supporting IT"
    assert set(printer["aliases"]) == {"10.124.32.210", "printer.room2.local", "10.124.32.40"}
    assert printer["connected_application_hosts"] == ["APP1"]
    assert "captured_connection" in printer["observation_type"]
    vending = next(d for d in items if d["id"] == "CD-000002")
    assert vending["state"] == "unidentified"
    assert vending["connected_application_hosts"] == []
    assert vending["observation_type"] == []


def test_conflicts_are_ambiguous_or_host_owned_only(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="conflicts")
    kinds = {c["kind"] for c in out["groups"]["conflicts"]["items"]}
    assert kinds == {"ambiguous_alias", "host_owned_alias"}
    amb = next(c for c in out["groups"]["conflicts"]["items"] if c["kind"] == "ambiguous_alias")
    assert amb["address"] == "10.124.32.210" and amb["claimed_by"] == ["CD-000001", "CD-000002"]
    owned = next(c for c in out["groups"]["conflicts"]["items"] if c["kind"] == "host_owned_alias")
    assert owned["address"] == "10.124.32.40" and owned["host"] == "APP1"


def test_unidentified_addresses_keep_direction_ports_and_evidence(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="unidentified")
    items = out["groups"]["unidentified"]["items"]
    assert [u["address"] for u in items] == ["10.124.32.10", "10.124.32.200", "203.0.113.9"]
    pub = next(u for u in items if u["address"] == "203.0.113.9")
    assert pub["type"] == "public" and pub["directions"] == ["outbound"] and pub["ports"] == ["443"]
    assert pub["claimed_by_device"] == ""
    internal = next(u for u in items if u["address"] == "10.124.32.200")
    assert internal["type"] == "private" and internal["sessions"] == "3"
    assert {e["evidence_id"] for e in internal["evidence"]} == {"E-102"}


def test_missing_optional_files_still_build(tmp_path: Path) -> None:
    work = tmp_path / "csa-work"
    hosts = work / "hosts"
    hosts.mkdir(parents=True, exist_ok=True)
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,status,claim,review_state\n", encoding="utf-8")
    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "ONLY1,Yes,Sample,Server,Perth,10.10.0.5,,inventory,\n", encoding="utf-8")
    out = assets.build(work, AGENTS)
    assert out["counts"] == {"application_hosts": 1, "devices": 0, "unidentified": 0, "conflicts": 0}
    assert out["groups"]["devices"]["items"] == []
    assert "hosts/hosts.csv" in out["sources"] and "hosts/host_links.csv" not in out["sources"]


def test_no_matrix_still_builds_from_register(tmp_path: Path) -> None:
    work = tmp_path / "csa-work"
    (work / "hosts").mkdir(parents=True, exist_ok=True)
    (work / "hosts" / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "ONLY1,Yes,Sample,Server,Perth,10.10.0.5,,inventory,\n", encoding="utf-8")
    out = assets.build(work, AGENTS)
    assert out["counts"]["application_hosts"] == 1
    assert out["matrix_rows"] == 0


def test_pagination_and_filter(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="unidentified", page=1, per_page=2)
    g = out["groups"]["unidentified"]
    assert g["total"] == 3 and g["per_page"] == 2 and len(g["items"]) == 2
    out2 = assets.build(_work(tmp_path), AGENTS, kind="unidentified", page=2, per_page=2)
    assert out2["groups"]["unidentified"]["items"][0]["address"] == "203.0.113.9"
    out3 = assets.build(_work(tmp_path), AGENTS, kind="unidentified", query="public")
    assert [u["address"] for u in out3["groups"]["unidentified"]["items"]] == ["203.0.113.9"]


def test_does_not_mutate_project_data(tmp_path: Path) -> None:
    work = _work(tmp_path)
    before = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}
    assets.build(work, AGENTS)
    assets.build(work, AGENTS, kind="devices", query="x")
    after = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}
    assert before == after
