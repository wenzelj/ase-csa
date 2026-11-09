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


def test_device_items_carry_revision_and_register_provenance(tmp_path: Path) -> None:
    out = assets.build(_work(tmp_path), AGENTS, kind="devices")
    printer = next(d for d in out["groups"]["devices"]["items"] if d["id"] == "CD-000001")
    assert printer["revision"] == "1" and printer["active"] is True
    assert printer["provenance"] == "asset register" and printer["reviewer"] == "WM" and printer["recorded"] == "2026-01-06"
    assert "retired_devices" not in out and out["counts"]["devices"] == 2      # default response is unchanged


def test_retired_devices_are_listed_only_on_request_and_never_connect(tmp_path: Path, monkeypatch) -> None:
    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    api.retire_connected_device("alpha-app", "CD-000001", {"expected_revision": "1", "reviewer": "WM"})
    default = api.system_assets("alpha-app", "", "", "", "", 1, 50, False)
    assert default["counts"]["devices"] == 1 and "retired_devices" not in default
    assert [d["id"] for d in default["groups"]["devices"]["items"]] == ["CD-000002"]
    full = api.system_assets("alpha-app", "", "devices", "", "", 1, 50, True)
    assert full["counts"]["devices"] == 1 and full["retired_devices"] == 1
    by = {d["id"]: d for d in full["groups"]["devices"]["items"]}
    gone = by["CD-000001"]
    assert gone["active"] is False and gone["revision"] == "2" and gone["reviewer"] == "WM"
    assert gone["aliases"] == [] and gone["connected_application_hosts"] == [] and gone["observation_type"] == []
    assert by["CD-000002"]["active"] is True
    # a retired device no longer makes its addresses conflict, and its row is reachable for Restore
    assert api.system_assets("alpha-app", "", "conflicts", "", "", 1, 50, True)["groups"]["conflicts"]["items"] == []
    detail = api.system_asset_detail("alpha-app", "CD-000001", "devices")
    assert detail["asset"]["active"] is False and detail["asset"]["revision"] == "2"
    back = api.restore_connected_device("alpha-app", "CD-000001", {"expected_revision": detail["asset"]["revision"]})
    assert back["device"]["active"] == "true"


# --- guarded conversion of a connected device to an application host (S547) -----------------------

def _ups(api) -> dict:
    return api.create_connected_device("alpha-app", {"name": "UPS monitor", "device_type": "ups", "site_zone": "Perth",
                                                     "reviewer": "WM", "addresses": ["10.124.32.230"]})["device"]


_CONVERT = {"host_name": "powermon1", "source": "Asset register v3, row 41", "operator": "WM"}


def test_preview_is_read_only_and_names_every_block(tmp_path: Path, monkeypatch) -> None:
    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    dev = _ups(api)
    before = _snapshot(root)
    ready = api.preview_host_conversion("alpha-app", dev["device_id"], _CONVERT)
    assert ready["status"] == "READY" and ready["host"] == "POWERMON1" and ready["ips"] == ["10.124.32.230"]
    assert ready["revision"] == "1" and ready["preview_id"] and "hosts/hosts.csv" in ready["unchanged"]
    assert _snapshot(root) == before                                       # nothing written by a preview
    blocked = {
        "host exists": api.preview_host_conversion("alpha-app", dev["device_id"], {**_CONVERT, "host_name": "APP1"}),
        "owned address": api.preview_host_conversion("alpha-app", "CD-000001", _CONVERT),     # alias 10.124.32.40 belongs to APP1
        "no source": api.preview_host_conversion("alpha-app", dev["device_id"], {**_CONVERT, "source": ""}),
        "no operator": api.preview_host_conversion("alpha-app", dev["device_id"], {**_CONVERT, "operator": ""}),
        "bad name": api.preview_host_conversion("alpha-app", dev["device_id"], {**_CONVERT, "host_name": "9 bad name"}),
        "unknown device": api.preview_host_conversion("alpha-app", "CD-404404", _CONVERT),
    }
    assert all(p["status"] == "BLOCKED" for p in blocked.values())
    assert any("already in the host register" in x for x in blocked["host exists"]["problems"])
    assert any("10.124.32.40 is already owned by register host APP1" in x for x in blocked["owned address"]["problems"])
    assert any("unknown device" in x for x in blocked["unknown device"]["problems"])
    no_ip = api.create_connected_device("alpha-app", {"name": "Name only"})["device"]
    assert any("no active IP address alias" in x for x in api.preview_host_conversion("alpha-app", no_ip["device_id"], _CONVERT)["problems"])
    api.patch_connected_device("alpha-app", "CD-000002", {"expected_revision": "1", "changes": {"identification_state": "disputed"}})
    assert any("disputed" in x for x in api.preview_host_conversion("alpha-app", "CD-000002", _CONVERT)["problems"])
    assert _snapshot(root) != before                                       # (only the setup edits above)


def test_conversion_needs_the_preview_confirmation_and_a_current_revision(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    dev = _ups(api)
    plan = api.preview_host_conversion("alpha-app", dev["device_id"], _CONVERT)
    base = {**_CONVERT, "expected_revision": "1", "preview_id": plan["preview_id"], "confirm": True}
    for bad, code, status in (({**base, "confirm": False}, "confirmation_required", 422),
                              ({**base, "preview_id": ""}, "preview_required", 422),
                              ({**base, "expected_revision": ""}, "revision_required", 422),
                              ({**base, "expected_revision": "9"}, "conflict", 409),
                              ({**base, "preview_id": "0000000000000000"}, "stale_preview", 409),
                              ({**base, "host_name": "APP1"}, "scope_conflict", 409)):
        with pytest.raises(HTTPException) as exc:
            api.convert_device_to_host("alpha-app", dev["device_id"], bad)
        assert (exc.value.status_code, exc.value.detail["code"]) == (status, code), bad
    assert not (tmp_path / "alpha" / "csa-work" / "hosts" / "host_scope.csv").exists()


def test_conversion_writes_only_its_decision_and_can_be_reversed(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    dev = _ups(api)
    plan = api.preview_host_conversion("alpha-app", dev["device_id"], _CONVERT)
    before = _snapshot(root)
    done = api.convert_device_to_host("alpha-app", dev["device_id"], {
        **_CONVERT, "expected_revision": "1", "preview_id": plan["preview_id"], "confirm": True})
    assert done["rebuild_required"] is True and done["decision"]["decision_id"] == "HS-000001"
    assert done["decision"]["host"] == "POWERMON1" and done["decision"]["active"] == "true"
    after = _snapshot(root)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert {Path(k).name for k in changed} == {"host_scope.csv", "device-audit.jsonl"}
    assert (root / "csa-work" / "hosts" / "hosts.csv").read_bytes() == before["csa-work/hosts/hosts.csv"]
    # the device, its aliases and its history stay; its own revision did not move
    still = api.system_asset_detail("alpha-app", dev["device_id"], "devices")["asset"]
    assert still["revision"] == "1" and still["aliases"] == ["10.124.32.230"]
    with pytest.raises(HTTPException) as exc:                              # a second conversion is refused
        api.preview_host_conversion("alpha-app", dev["device_id"], {**_CONVERT, "host_name": "OTHERNAME"})
        api.convert_device_to_host("alpha-app", dev["device_id"], {**_CONVERT, "host_name": "OTHERNAME", "expected_revision": "1",
                                                                   "preview_id": plan["preview_id"], "confirm": True})
    assert exc.value.status_code == 409
    assert any("already has an active conversion" in p for p in api.preview_host_conversion(
        "alpha-app", dev["device_id"], {**_CONVERT, "host_name": "OTHERNAME"})["problems"])
    undone = api.reverse_host_conversion("alpha-app", dev["device_id"], {"operator": "WM", "reason": "it is a switch, not a host"})
    assert undone["decision"]["active"] == "false" and undone["decision"]["reversed_by"] == "WM"
    assert "switch" in undone["decision"]["reverse_reason"] and undone["rebuild_required"] is True
    with pytest.raises(HTTPException) as exc:
        api.reverse_host_conversion("alpha-app", dev["device_id"], {"operator": "WM", "reason": "again"})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        api.reverse_host_conversion("alpha-app", dev["device_id"], {"operator": "", "reason": ""})
    assert exc.value.status_code == 422
    assert api.preview_host_conversion("alpha-app", dev["device_id"], _CONVERT)["status"] == "READY"   # free to decide again


def test_creating_editing_and_confirming_never_changes_host_membership(tmp_path: Path, monkeypatch) -> None:
    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    root = tmp_path / "alpha"
    hosts_before = (root / "csa-work" / "hosts" / "hosts.csv").read_bytes()
    dev = _ups(api)
    api.patch_connected_device("alpha-app", dev["device_id"], {"expected_revision": "1", "source": "site walk",
                                                              "changes": {"identification_state": "confirmed", "role": "monitor a host"}})
    api.add_device_alias("alpha-app", dev["device_id"], {"address": "10.124.32.231", "expected_revision": "2"})
    assert not (root / "csa-work" / "hosts" / "host_scope.csv").exists()
    assert (root / "csa-work" / "hosts" / "hosts.csv").read_bytes() == hosts_before
    counts = api.system_assets("alpha-app", "", "", "", "", 1, 50)["counts"]
    assert counts["application_hosts"] == 1


def test_conversion_cannot_cross_projects(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from fastapi import HTTPException

    from backend import app as api

    _register_two(tmp_path, monkeypatch)
    dev = _ups(api)
    assert api.preview_host_conversion("beta-app", dev["device_id"], _CONVERT)["status"] == "BLOCKED"
    with pytest.raises(HTTPException) as exc:
        api.convert_device_to_host("beta-app", dev["device_id"], {**_CONVERT, "expected_revision": "1", "preview_id": "x", "confirm": True})
    assert exc.value.status_code in (404, 409)
    assert not (tmp_path / "beta" / "csa-work" / "hosts" / "host_scope.csv").exists()
    with pytest.raises(HTTPException) as exc:
        api.preview_host_conversion("nope", dev["device_id"], _CONVERT)
    assert exc.value.status_code == 404


# --- end to end: identify -> rebuild -> resolved in the browser read model -> retire (S549) -------

def _captured_project(tmp_path: Path, monkeypatch) -> Path:
    """A synthetic project with a real discovery index: APP1 captured, one outbound session to 10.9.9.9."""
    import json
    import sqlite3

    root = tmp_path / "e2e"
    work = root / "csa-work"
    (work / "hosts").mkdir(parents=True)
    con = sqlite3.connect(work / "discovery-index.sqlite")
    con.executescript("""
      create table captures(capture_id, folder, host, collector, capture_utc, archived, superseded_by, file_count);
      create table files(file_id, rel_path, capture_id, host, ext, size, mtime, sha1, status, reason, dup_of, source_class);
      create table rows(file_id, table_name, fmt, block_no, line_no, data);
    """)
    con.execute("insert into captures values ('c1','cap/APP1','APP1','t','x',0,null,1)")
    con.execute("insert into files values (1,'cap/APP1/21.txt','c1','APP1','x',0,0,'','indexed','',null,'other')")
    con.execute("insert into rows values (1,'established_connections_raw','csv',0,2,?)", (json.dumps({
        "LocalAddress": "10.9.9.1", "LocalPort": "50000", "RemoteAddress": "10.9.9.9", "RemotePort": "445"}),))
    con.commit()
    con.close()
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,status,claim,review_state\n"
        "E-1,network_and_connectivity,VERIFIED,APP1 has an established connection from svchost.exe to 10.9.9.9 on port 445,reviewed\n",
        encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text(f"projects:\n  - key: e2e-app\n    label: E2E\n    project_root: {root}\n    work_dir: {work}\n", encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    return work


def _rebuild(work: Path) -> dict:
    from csa_docx import hostmodel
    return hostmodel.build(work)


def _csv_rows(path: Path) -> list[dict]:
    import csv as _csv
    with path.open(newline="", encoding="utf-8") as fh:
        return list(_csv.DictReader(fh))


def test_identified_peer_survives_a_rebuild_and_retirement_leaves_the_observation(tmp_path: Path, monkeypatch) -> None:
    from backend import app as api
    from backend import network

    work = _captured_project(tmp_path, monkeypatch)
    _rebuild(work)
    # 1. unidentified: the address is listed with what was seen, and no device exists yet
    first = api.system_assets("e2e-app", "", "", "", "", 1, 50, False)
    seen = {u["address"]: u for u in first["groups"]["unidentified"]["items"]}
    assert seen["10.9.9.9"]["ports"] == ["445"] and seen["10.9.9.9"]["directions"] == ["outbound"]
    assert first["counts"]["devices"] == 0

    # 2. identify it: preview first, then save a confirmed device with a role and a cited source
    preview = api.preview_device_aliases("e2e-app", {"add": ["10.9.9.9"]})
    assert preview["changes"][0]["before"]["resolves_to"] == "unidentified_address" and preview["blocked"] is False
    made = api.create_connected_device("e2e-app", {
        "name": "Label printer", "device_type": "printer", "role": "labels the despatch", "owner": "Logistics",
        "site_zone": "Perth", "classification": "supporting IT", "identification_state": "confirmed",
        "source": "Asset register v3, row 41", "reviewer": "WM", "addresses": ["10.9.9.9"]})["device"]
    assert made["identification_state"] == "confirmed" and made["revision"] == "1"
    registers = {n: (work / "hosts" / n).read_bytes() for n in ("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl")}

    # 3. rebuild: the decision survives, the address is resolved, and the browser read model shows the connection
    result = _rebuild(work)
    assert result["devices_resolved"] == 1 and result["device_conflicts"] == []
    assert {n: (work / "hosts" / n).read_bytes() for n in registers} == registers        # the register is untouched
    assert "10.9.9.9" not in {r["address"] for r in _csv_rows(work / "hosts" / "addresses.csv")}
    peer = _csv_rows(work / "hosts" / "device_peers.csv")[0]
    assert (peer["address"], peer["device_id"], peer["revision"]) == ("10.9.9.9", made["device_id"], "1")
    assert "Asset register v3" in peer["provenance"] and peer["ports"] == "445"
    after = api.system_assets("e2e-app", "", "", "", "", 1, 50, False)
    assert "10.9.9.9" not in {u["address"] for u in after["groups"]["unidentified"]["items"]}
    device = next(d for d in after["groups"]["devices"]["items"] if d["id"] == made["device_id"])
    assert "captured_connection" in device["observation_type"] and {e["evidence_id"] for e in device["evidence"]} == {"E-1"}
    assert [h["name"] for h in after["groups"]["application_hosts"]["items"]] == ["APP1"]    # still the only host
    node = next(n for n in network.build(work, api.agents_dir())["nodes"] if n["id"] == "10.9.9.9")
    assert node["device"]["device_id"] == made["device_id"] and node["device"]["state"] == "confirmed" and node["ips"] == "10.9.9.9"

    # 4. retire: the observation is still there and the address is unidentified again
    api.retire_connected_device("e2e-app", made["device_id"], {"expected_revision": "1", "reviewer": "WM"})
    _rebuild(work)
    assert "10.9.9.9" in {r["address"] for r in _csv_rows(work / "hosts" / "addresses.csv")}
    assert _csv_rows(work / "hosts" / "device_peers.csv") == []
    back = api.system_assets("e2e-app", "", "", "", "", 1, 50, False)
    again = {u["address"]: u for u in back["groups"]["unidentified"]["items"]}
    assert again["10.9.9.9"]["ports"] == ["445"] and back["counts"]["devices"] == 0
    node = next(n for n in network.build(work, api.agents_dir())["nodes"] if n["id"] == "10.9.9.9")
    assert "device" not in node and node["kind"] == "unnamed"
    assert any(e["ids"] == ["E-1"] for e in network.build(work, api.agents_dir())["edges"])         # the connection is still recorded
    retired = api.system_assets("e2e-app", "", "devices", "", "", 1, 50, True)["groups"]["devices"]["items"]
    assert retired[0]["active"] is False and retired[0]["revision"] == "2"                          # restorable, history kept


def test_a_new_capture_that_conflicts_with_the_saved_identity_does_not_overwrite_it(tmp_path: Path, monkeypatch) -> None:
    import json
    import sqlite3

    from backend import app as api

    work = _captured_project(tmp_path, monkeypatch)
    made = api.create_connected_device("e2e-app", {
        "name": "Label printer", "identification_state": "confirmed", "source": "Asset register v3",
        "reviewer": "WM", "addresses": ["10.9.9.9"]})["device"]
    _rebuild(work)
    assert _csv_rows(work / "hosts" / "device_peers.csv")[0]["device_id"] == made["device_id"]
    registers = {n: (work / "hosts" / n).read_bytes() for n in ("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl")}

    # a later capture of another machine reports 10.9.9.9 as its own address
    con = sqlite3.connect(work / "discovery-index.sqlite")
    con.execute("insert into captures values ('c2','cap/NEWBOX','NEWBOX','t','x',0,null,1)")
    con.execute("insert into files values (2,'cap/NEWBOX/21.txt','c2','NEWBOX','x',0,0,'','indexed','',null,'other')")
    con.execute("insert into rows values (2,'established_connections_raw','csv',0,2,?)", (json.dumps({
        "LocalAddress": "10.9.9.9", "LocalPort": "50001", "RemoteAddress": "10.9.9.50", "RemotePort": "80"}),))
    con.commit()
    con.close()
    result = _rebuild(work)
    assert result["device_conflicts"] == [{"address": "10.9.9.9", "device_id": made["device_id"], "host": "NEWBOX"}]
    assert _csv_rows(work / "hosts" / "device_peers.csv") == []                    # the capture's host keeps the address
    assert {n: (work / "hosts" / n).read_bytes() for n in registers} == registers   # the saved identity is not overwritten
    hosts = {r["host"]: r for r in _csv_rows(work / "hosts" / "hosts.csv")}
    assert "10.9.9.9" in hosts["NEWBOX"]["ips"]
    conflicts = api.system_assets("e2e-app", "", "conflicts", "", "", 1, 50, False)["groups"]["conflicts"]["items"]
    assert [(c["kind"], c["address"], c["host"], c["claimed_by"]) for c in conflicts] == [
        ("host_owned_alias", "10.9.9.9", "NEWBOX", [made["device_id"]])]
