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
