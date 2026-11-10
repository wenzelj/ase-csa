from __future__ import annotations

from pathlib import Path

from backend import network


def test_uncaptured_inventory_host_keeps_recorded_role(tmp_path: Path) -> None:
    """A role in hosts.csv remains evidence even when no discovery capture exists for that host."""
    work = tmp_path / "csa-work"
    hosts = work / "hosts"
    hosts.mkdir(parents=True)
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,status,claim\n", encoding="utf-8"
    )
    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "ROTPRDREV102,Yes,Reveloc,OT Reveloc Server,Rockhampton,10.124.32.84,,asset inventory,\n",
        encoding="utf-8",
    )

    out = network.build(work, Path(__file__).resolve().parents[2])

    assert out["nodes"] == [{
        "id": "ROTPRDREV102", "kind": "named", "role": "OT Reveloc Server",
        "site": "Rockhampton", "ips": "10.124.32.84", "listed": True,
    }]


def _device_project(tmp_path: Path, state: str = "confirmed", active: str = "true") -> Path:
    work = tmp_path / "csa-work"
    hosts = work / "hosts"
    hosts.mkdir(parents=True)
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,status,claim\n"
        "E-1,network_and_connectivity,VERIFIED,APP1 has an established connection from svchost.exe to 10.124.32.200 on port 445\n"
        "E-2,network_and_connectivity,VERIFIED,APP1 has an established connection from svchost.exe to 10.124.32.201 on port 445\n",
        encoding="utf-8")
    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "APP1,Yes,Sample,Application server,Rockhampton,10.124.32.10,2026-01-05,capture,\n", encoding="utf-8")
    (hosts / "connected_devices.csv").write_text(
        "device_id,name,device_type,role,owner,site_zone,relationship,classification,identification_state,provenance,reviewer,recorded,active,revision\n"
        f"CD-000001,Print server,printer,,,Rockhampton,,supporting IT,{state},asset register row 9,WM,x,{active},4\n", encoding="utf-8")
    (hosts / "device_addresses.csv").write_text(
        "device_id,address,normalized,address_type,first_seen,last_seen,source,active\n"
        "CD-000001,10.124.32.200,10.124.32.200,ipv4,,,s,true\n", encoding="utf-8")
    return work


def test_confirmed_device_labels_the_peer_and_keeps_the_raw_address(tmp_path: Path) -> None:
    out = network.build(_device_project(tmp_path), Path(__file__).resolve().parents[2])
    nodes = {n["id"]: n for n in out["nodes"]}
    peer = nodes["10.124.32.200"]
    assert peer["kind"] == "unnamed" and peer["ips"] == "10.124.32.200"           # still an address, not a host
    assert peer["role"] == "Print server (printer)" and peer["site"] == "Rockhampton"
    assert peer["device"] == {"device_id": "CD-000001", "name": "Print server", "type": "printer",
                              "classification": "supporting IT", "site": "Rockhampton", "revision": "4",
                              "provenance": "asset register row 9", "state": "confirmed"}
    assert nodes["10.124.32.201"] == {"id": "10.124.32.201", "kind": "unnamed", "role": "", "site": "", "ips": "10.124.32.201"}
    assert nodes["APP1"]["kind"] == "captured" and "device" not in nodes["APP1"]
    assert {(e["s"], e["t"], e["port"]) for e in out["edges"]} == {("APP1", "10.124.32.200", "445"), ("APP1", "10.124.32.201", "445")}
    assert next(e for e in out["edges"] if e["t"] == "10.124.32.200")["ids"] == ["E-1"]


def test_retired_or_disputed_devices_do_not_label_the_peer(tmp_path: Path) -> None:
    for state, active in (("disputed", "true"), ("proposed", "true"), ("confirmed", "false")):
        out = network.build(_device_project(tmp_path / f"{state}-{active}", state, active), Path(__file__).resolve().parents[2])
        peer = next(n for n in out["nodes"] if n["id"] == "10.124.32.200")
        assert "device" not in peer and peer["role"] == ""
