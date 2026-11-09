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


def _register_two(tmp_path: Path, monkeypatch):
    """Two registered projects: 'alpha' has the full fixture, 'beta' one host of its own."""
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    work_a = _work(alpha)
    beta = tmp_path / "beta"
    (beta / "csa-work" / "hosts").mkdir(parents=True)
    (beta / "csa-work" / "hosts" / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips,capture,sources,ad_site\n"
        "BETAONLY,Yes,Other,Server,Perth,10.77.0.5,,inventory,\n", encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text(
        "projects:\n"
        f"  - key: alpha-app\n    label: Alpha\n    project_root: {alpha}\n    work_dir: {work_a}\n"
        f"  - key: beta-app\n    label: Beta\n    project_root: {beta}\n    work_dir: {beta / 'csa-work'}\n",
        encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))


def test_assets_routes_filter_paginate_and_scope_to_project(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    out = api.system_assets("alpha-app", "", "", "", "", 1, 50)
    assert out["project_key"] == "alpha-app" and out["counts"]["devices"] == 2
    assert set(out["groups"]) == {"application_hosts", "devices", "unidentified", "conflicts"}
    printers = api.system_assets("alpha-app", "", "devices", "Printer", "confirmed", 1, 50)
    assert [d["id"] for d in printers["groups"]["devices"]["items"]] == ["CD-000001"]
    assert printers["groups"]["devices"]["total"] == 1
    paged = api.system_assets("alpha-app", "", "unidentified", "", "", 2, 2)
    assert paged["groups"]["unidentified"]["total"] == 3 and len(paged["groups"]["unidentified"]["items"]) == 1
    # the other project's data is not reachable through the selected key
    beta = api.system_assets("beta-app", "", "", "", "", 1, 50)
    assert [h["name"] for h in beta["groups"]["application_hosts"]["items"]] == ["BETAONLY"]
    assert beta["groups"]["devices"]["items"] == []
    with pytest.raises(HTTPException) as exc:
        api.system_asset_detail("beta-app", "CD-000001", "")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        api.system_assets("nope", "", "", "", "", 1, 50)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        api.system_assets("alpha-app", "", "bogus", "", "", 1, 50)
    assert exc.value.status_code == 422


def test_asset_detail_has_source_links_and_stable_shape(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    dev = api.system_asset_detail("alpha-app", "CD-000001", "")
    assert dev["kind"] == "devices" and dev["asset"]["name"] == "Printer room 2"
    assert set(dev) == {"system", "project_key", "id", "kind", "asset", "other_kinds", "source_links"}
    assert dev["source_links"]["files"] == ["asset register"]
    assert {e["evidence_id"] for e in dev["source_links"]["evidence"]} == {"E-200"}
    host = api.system_asset_detail("alpha-app", "APP1", "application_hosts")
    assert host["source_links"]["files"] == ["hosts/hosts.csv"]
    with pytest.raises(HTTPException) as exc:
        api.system_asset_detail("alpha-app", "CD-999999", "")
    assert exc.value.status_code == 404 and "CD-999999" in exc.value.detail


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _only_register_changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    allowed = ("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl", ".connected-devices.lock")
    assert all(Path(k).name.startswith(allowed) for k in changed), changed
    assert all(Path(k).parent.name == "hosts" for k in changed), changed
    return changed


def _code(exc) -> tuple[int, str]:
    return exc.value.status_code, exc.value.detail["code"]


def test_create_validates_and_blocks_claimed_addresses(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    before = _snapshot(root)
    with pytest.raises(HTTPException) as exc:     # 10.124.32.10 belongs to register host APP1
        api.create_connected_device("alpha-app", {"name": "UPS", "addresses": ["10.124.32.10"]})
    assert _code(exc) == (409, "host_owned") and "APP1" in exc.value.detail["message"]
    with pytest.raises(HTTPException) as exc:     # 10.124.32.210 is an active alias of CD-000001
        api.create_connected_device("alpha-app", {"name": "UPS", "addresses": ["10.124.32.210"]})
    assert _code(exc) == (409, "alias_claimed")
    with pytest.raises(HTTPException) as exc:
        api.create_connected_device("alpha-app", {"name": "UPS", "addresses": ["not an address"]})
    assert _code(exc) == (422, "invalid_address")
    with pytest.raises(HTTPException) as exc:
        api.create_connected_device("alpha-app", {"name": "UPS", "classification": "made up"})
    assert exc.value.status_code == 422
    assert _snapshot(root) == before              # every rejection left the project untouched
    made = api.create_connected_device("alpha-app", {
        "name": "UPS", "device_type": "ups", "reviewer": "WM", "addresses": ["10.124.32.230"]})
    dev = made["device"]
    assert dev["device_id"] == "CD-000003" and dev["revision"] == "1" and dev["identification_state"] == "unidentified"
    assert dev["provenance"] == "Evidence Browser entry" and dev["recorded"]
    assert [a["normalized"] for a in dev["aliases"]] == ["10.124.32.230"]
    _only_register_changed(before, _snapshot(root))


def test_confirmed_needs_a_source_or_dated_owner_confirmation_and_adds_no_evidence(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    matrix = (root / "csa-work" / "evidence-matrix.csv").read_bytes()
    with pytest.raises(HTTPException) as exc:
        api.create_connected_device("alpha-app", {"name": "UPS", "identification_state": "confirmed"})
    assert _code(exc) == (422, "confirmation_required")
    with pytest.raises(HTTPException) as exc:
        api.create_connected_device("alpha-app", {"name": "UPS", "identification_state": "confirmed",
                                                  "owner_confirmed_on": "last week"})
    assert _code(exc) == (422, "invalid_date")
    cited = api.create_connected_device("alpha-app", {"name": "UPS", "identification_state": "confirmed",
                                                      "source": "Asset register v3, row 41"})["device"]
    assert cited["identification_state"] == "confirmed" and "source: Asset register v3, row 41" in cited["provenance"]
    # an existing unconfirmed device becomes confirmed only with the same backing
    with pytest.raises(HTTPException) as exc:
        api.patch_connected_device("alpha-app", "CD-000002", {
            "expected_revision": "1", "changes": {"identification_state": "confirmed"}})
    assert _code(exc) == (422, "confirmation_required")
    ok = api.patch_connected_device("alpha-app", "CD-000002", {
        "expected_revision": "1", "owner_confirmed_on": "2026-11-02", "reviewer": "WM",
        "changes": {"identification_state": "confirmed"}})["device"]
    assert ok["identification_state"] == "confirmed" and "owner confirmed 2026-11-02" in ok["provenance"]
    assert (root / "csa-work" / "evidence-matrix.csv").read_bytes() == matrix     # no VERIFIED row appended


def test_patch_requires_the_expected_revision(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        api.patch_connected_device("alpha-app", "CD-000001", {"changes": {"role": "x"}})
    assert _code(exc) == (422, "revision_required")
    done = api.patch_connected_device("alpha-app", "CD-000001", {"expected_revision": "1", "changes": {"role": "front office printing"}})
    assert done["device"]["role"] == "front office printing" and done["device"]["revision"] == "2"
    with pytest.raises(HTTPException) as exc:     # a second editor still holding revision 1
        api.patch_connected_device("alpha-app", "CD-000001", {"expected_revision": "1", "changes": {"role": "stale"}})
    assert _code(exc) == (409, "conflict")
    with pytest.raises(HTTPException) as exc:
        api.patch_connected_device("alpha-app", "CD-000001", {"expected_revision": "2", "changes": {"device_id": "CD-9"}})
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        api.patch_connected_device("alpha-app", "CD-404404", {"expected_revision": "1", "changes": {"role": "x"}})
    assert exc.value.status_code == 404


def test_alias_retire_and_restore_edits_touch_only_the_register(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    before = _snapshot(root)
    with pytest.raises(HTTPException) as exc:
        api.add_device_alias("alpha-app", "CD-000002", {"address": "10.124.32.40", "expected_revision": "1"})
    assert _code(exc) == (409, "host_owned")
    with pytest.raises(HTTPException) as exc:
        api.add_device_alias("alpha-app", "CD-000002", {"address": "printer.room2.local", "expected_revision": "1"})
    assert _code(exc) == (409, "alias_claimed")
    with pytest.raises(HTTPException) as exc:
        api.add_device_alias("alpha-app", "CD-000001", {"address": "printer.room2.local", "expected_revision": "1"})
    assert _code(exc) == (409, "alias_claimed")
    with pytest.raises(HTTPException) as exc:
        api.add_device_alias("alpha-app", "CD-000002", {"address": "10.124.32.77"})
    assert _code(exc) == (422, "revision_required")
    added = api.add_device_alias("alpha-app", "CD-000002", {
        "address": "10.124.32.77", "source": "site walk", "expected_revision": "1"})["device"]
    assert "10.124.32.77" in {a["normalized"] for a in added["aliases"] if a["active"] == "true"}
    removed = api.remove_device_alias("alpha-app", "CD-000002", "10.124.32.77", "1")["device"]
    assert "10.124.32.77" not in {a["normalized"] for a in removed["aliases"] if a["active"] == "true"}
    with pytest.raises(HTTPException) as exc:
        api.remove_device_alias("alpha-app", "CD-000002", "10.124.32.77", "")
    assert _code(exc) == (422, "revision_required")
    gone = api.retire_connected_device("alpha-app", "CD-000002", {"expected_revision": "1", "reviewer": "WM"})["device"]
    assert gone["active"] == "false" and gone["revision"] == "2"
    assert api.system_assets("alpha-app", "", "devices", "", "", 1, 50)["counts"]["devices"] == 1
    back = api.restore_connected_device("alpha-app", "CD-000002", {"expected_revision": "2"})["device"]
    assert back["active"] == "true" and back["revision"] == "3"
    changed = _only_register_changed(before, _snapshot(root))
    assert any(k.endswith("device-audit.jsonl") for k in changed)
    assert any(".bak-" in Path(k).name for k in changed)         # the previous register file was backed up
    for generated in ("hosts.csv", "addresses.csv", "host_links.csv", "host_services.csv"):
        assert (root / "csa-work" / "hosts" / generated).read_bytes() == before[f"csa-work/hosts/{generated}"]


def test_reconcile_preview_is_read_only_and_shows_before_and_after(tmp_path: Path, monkeypatch) -> None:
    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    before = _snapshot(root)
    out = api.preview_device_aliases("alpha-app", {
        "device_id": "CD-000002", "add": ["10.124.32.200", "10.124.32.40", "10.124.32.210", "nope"],
        "remove": ["10.124.32.210"]})
    by = {(c["action"], c["address"]): c for c in out["changes"]}
    free = by[("add", "10.124.32.200")]
    assert free["status"] == "ready" and free["before"]["resolves_to"] == "unidentified_address"
    assert free["after"] == {"resolves_to": "connected_device", "id": "CD-000002", "name": "Vending bay 4"}
    host = by[("add", "10.124.32.40")]
    assert host["status"] == "blocked" and host["before"]["resolves_to"] == "application_host" and "APP1" in host["reasons"][0]
    assert host["after"] == host["before"]
    held = by[("add", "10.124.32.210")]                                  # both fixture devices already claim it
    assert held["status"] == "blocked" and held["before"]["resolves_to"] == "ambiguous"
    assert by[("add", "nope")]["status"] == "blocked"
    gone = by[("remove", "10.124.32.210")]
    assert gone["status"] == "ready" and gone["after"] == {
        "resolves_to": "connected_device", "id": "CD-000001", "name": "Printer room 2"}
    assert out["blocked"] is True and out["writes"] == []
    assert _snapshot(root) == before


def test_device_edits_cannot_cross_projects(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    beta = tmp_path / "beta"
    before = _snapshot(beta)
    with pytest.raises(HTTPException) as exc:
        api.patch_connected_device("beta-app", "CD-000001", {"expected_revision": "1", "changes": {"role": "x"}})
    assert exc.value.status_code == 404
    api.create_connected_device("beta-app", {"name": "Beta switch"})
    assert [d["id"] for d in api.system_assets("alpha-app", "", "devices", "", "", 1, 50)["groups"]["devices"]["items"]] == ["CD-000001", "CD-000002"]
    assert not (tmp_path / "alpha" / "csa-work" / "hosts" / "device-audit.jsonl").exists()
    assert (beta / "csa-work" / "hosts" / "device-audit.jsonl").is_file() and _snapshot(beta) != before
