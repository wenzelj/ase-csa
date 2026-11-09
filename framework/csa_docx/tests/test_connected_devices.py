"""Durable connected-device register: CRUD, aliases, revisions, locking, atomicity, audit."""
import csv
import fcntl
import json
import os
from pathlib import Path

import pytest

from csa_docx import connected_devices as cd


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "csa-work" / "hosts").mkdir(parents=True)
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: test\n"
        '    label: "Test"\n'
        f'    project_root: "{project}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{project / "csa-work"}"\n',
        encoding="utf-8",
    )
    os.environ["CSA_PROJECTS_FILE"] = str(registry)
    return project


def _devices(project: Path) -> list[dict]:
    with (_project and (project / "csa-work" / "hosts" / "connected_devices.csv")).open(
            encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _addresses(project: Path) -> list[dict]:
    with (project / "csa-work" / "hosts" / "device_addresses.csv").open(
            encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _audit(project: Path) -> list[dict]:
    path = project / "csa-work" / "hosts" / "device-audit.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_create_allocates_stable_ids_and_writes_all_files(tmp_path):
    project = _project(tmp_path)
    out = cd.create_device(project, name="DNS relay", values={
        "device_type": "server", "role": "DNS", "owner": "Network team",
        "site_zone": "DMZ", "classification": "supporting IT",
        "provenance": "owner statement 2026-11-08", "identification_state": "proposed"},
        reviewer="Wenzel", addresses=["10.1.2.3", "dns-relay.corp.example"])
    assert out["status"] == "OK" and out["device_id"] == "CD-000001"
    assert out["addresses"] == ["10.1.2.3", "dns-relay.corp.example"]
    rows = _devices(project)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "DNS relay" and row["active"] == "true" and row["revision"] == "1"
    assert row["reviewer"] == "Wenzel"
    addrs = _addresses(project)
    assert [(a["normalized"], a["address_type"]) for a in addrs] == [
        ("10.1.2.3", "ipv4"), ("dns-relay.corp.example", "fqdn")]
    second = cd.create_device(project, name="Second")
    assert second["device_id"] == "CD-000002"


def test_create_requires_a_name_and_valid_values(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="name is required"):
        cd.create_device(project, name="")
    with pytest.raises(ValueError, match="classification"):
        cd.create_device(project, name="X", values={"classification": "bogus"})
    with pytest.raises(ValueError, match="provenance"):
        cd.create_device(project, name="X", values={"identification_state": "confirmed"})


def test_create_rejects_an_invalid_address(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="not a valid IP"):
        cd.create_device(project, name="X", addresses=["no such host.."])
    with pytest.raises(ValueError, match="not a valid IP"):
        cd.create_device(project, name="X", addresses=["10.1.2."])


def test_edit_bumps_revision_and_is_audited(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay")["device_id"]
    out = cd.edit_device(project, dev, changes={"role": "DNS relay", "classification": "shared"})
    assert out["status"] == "OK" and out["after"]["revision"] == "2"
    assert out["before"]["classification"] == "unknown"
    with pytest.raises(ValueError, match="not editable"):
        cd.edit_device(project, dev, changes={"device_id": "CD-000099"})
    events = _audit(project)
    assert [e["action"] for e in events] == ["create", "edit"]
    assert events[1]["device_id"] == dev
    assert events[1]["before"]["name"] == "Relay" and events[1]["after"]["role"] == "DNS relay"


def test_stale_revision_is_rejected_and_current_revision_accepted(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay")["device_id"]
    cd.edit_device(project, dev, changes={"role": "A"}, expected_revision="1")
    with pytest.raises(ValueError, match="stale revision"):
        cd.edit_device(project, dev, changes={"role": "B"}, expected_revision="1")
    out = cd.edit_device(project, dev, changes={"role": "B"}, expected_revision="2")
    assert out["after"]["revision"] == "3"


def test_duplicate_active_alias_is_rejected_across_devices(tmp_path):
    project = _project(tmp_path)
    a = cd.create_device(project, name="A")["device_id"]
    b = cd.create_device(project, name="B")["device_id"]
    cd.add_address(project, a, "10.9.9.9")
    with pytest.raises(ValueError, match="already an active alias"):
        cd.add_address(project, b, "10.9.9.9")
    # case-insensitive: same alias, different case
    with pytest.raises(ValueError, match="already an active alias"):
        cd.add_address(project, b, "10.9.9.9 ")
    # the same device may re-add its own alias only after retiring it
    cd.remove_address(project, a, "10.9.9.9")
    out = cd.add_address(project, b, "10.9.9.9")
    assert out["address"]["device_id"] == b


def test_remove_address_retires_keeps_row(tmp_path):
    project = _project(tmp_path)
    a = cd.create_device(project, name="A")["device_id"]
    cd.add_address(project, a, "10.5.5.5")
    cd.remove_address(project, a, "10.5.5.5")
    rows = _addresses(project)
    assert len(rows) == 1 and rows[0]["active"] == "false"
    # re-adding creates a fresh active row
    cd.add_address(project, a, "10.5.5.5")
    assert [r["active"] for r in _addresses(project)] == ["false", "true"]
    with pytest.raises(ValueError, match="not attached"):
        cd.remove_address(project, a, "10.6.6.6")


def test_retire_and_restore_keep_rows_and_aliases(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay", addresses=["10.2.2.2"])["device_id"]
    out = cd.retire_device(project, dev, reviewer="Wenzel")
    assert out["status"] == "OK" and out["after"]["active"] == "false"
    rows = _devices(project)
    assert len(rows) == 1 and rows[0]["active"] == "false"
    assert all(r["active"] == "false" for r in _addresses(project))
    # a retired device cannot be edited
    with pytest.raises(ValueError, match="retired"):
        cd.edit_device(project, dev, changes={"role": "X"})
    # retired aliases are released to other devices
    other = cd.create_device(project, name="Other")["device_id"]
    cd.add_address(project, other, "10.2.2.2")
    back = cd.restore_device(project, dev, reviewer="Wenzel")
    assert back["status"] == "OK" and back["after"]["active"] == "true"
    actions = [e["action"] for e in _audit(project)]
    assert actions[:1] == ["create"] and "retire" in actions and "restore" in actions


def test_audit_is_append_only_with_before_after(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay", addresses=["10.3.3.3"])["device_id"]
    before = len(_audit(project))
    cd.edit_device(project, dev, changes={"role": "DNS"})
    after = _audit(project)
    assert len(after) == before + 1
    ev = after[-1]
    assert ev["action"] == "edit" and ev["device_id"] == dev
    assert ev["before"]["role"] == "" and ev["after"]["role"] == "DNS"
    assert ev["before"]["revision"] == "1" and ev["after"]["revision"] == "2"
    # the audit file itself is only ever appended: byte offset grows
    path = project / "csa-work" / "hosts" / "device-audit.jsonl"
    size1 = path.stat().st_size
    cd.retire_device(project, dev)
    assert path.stat().st_size > size1


def test_rebuild_simulation_does_not_touch_the_register(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay", addresses=["10.4.4.4"])["device_id"]
    hosts = project / "csa-work" / "hosts"
    hosts.joinpath("hosts.csv").write_text("host,ip\n", encoding="utf-8")
    hosts.joinpath("addresses.csv").write_text("address\n10.4.4.4\n", encoding="utf-8")
    # hostmodel-style rebuild: these files are regenerated
    hosts.joinpath("hosts.csv").write_text("host,ip\nHOST1,10.0.0.1\n", encoding="utf-8")
    hosts.joinpath("addresses.csv").write_text("address\n10.9.9.9\n", encoding="utf-8")
    assert cd.get_device(project, dev)["name"] == "Relay"
    assert cd.resolve(project, "10.4.4.4")["device_id"] == dev
    assert cd.verify(project)["status"] == "OK"


def test_atomic_write_keeps_backup_and_leaves_no_tmp(tmp_path):
    project = _project(tmp_path)
    dev = cd.create_device(project, name="Relay")["device_id"]
    cd.edit_device(project, dev, changes={"role": "A"})
    hosts = project / "csa-work" / "hosts"
    backups = [p.name for p in hosts.glob("connected_devices.csv.bak-*")]
    assert backups, "a backup of the previous file must exist after a rewrite"
    assert not list(hosts.glob("*.tmp-*")), "no temp file may remain"


def _create_n(args):
    project, n = args
    os.environ["CSA_PROJECTS_FILE"] = str(Path(project).parent / "PROJECTS.yaml")
    out = []
    for _ in range(n):
        out.append(cd.create_device(project, name=f"w-{os.getpid()}")["device_id"])
    return out


def test_concurrent_writers_get_unique_ids(tmp_path):
    import multiprocessing as mp
    project = _project(tmp_path)
    with mp.Pool(3) as pool:
        ids = [i for chunk in pool.map(_create_n, [(str(project), 5)] * 3) for i in chunk]
    assert len(ids) == 15 and len(set(ids)) == 15
    assert len(cd.list_devices(project)) == 15


def test_unregistered_project_is_rejected(tmp_path, monkeypatch):
    stray = tmp_path / "outside" / "stray"
    stray.mkdir(parents=True)
    registered = tmp_path / "inside" / "project"
    (registered / "csa-work").mkdir(parents=True)
    registry = tmp_path / "REG2.yaml"
    registry.write_text("projects:\n  - key: test\n"
        f'    project_root: "{registered}"\n'
        f'    work_dir: "{registered / "csa-work"}"\n', encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))
    with pytest.raises(ValueError):
        cd.create_device(stray, name="X")
    # the registered project still works
    out = cd.create_device(registered, name="Ok")
    assert out["status"] == "OK"


def test_resolve_and_verify(tmp_path):
    project = _project(tmp_path)
    a = cd.create_device(project, name="A", addresses=["10.8.8.8"])["device_id"]
    assert cd.resolve(project, "10.8.8.8")["device_id"] == a
    assert cd.resolve(project, "10.7.7.7") is None
    assert cd.verify(project)["status"] == "OK"
    assert cd.list_devices(project, include_retired=False) and len(cd.list_addresses(project, a)) == 1


def test_resolution_map_reads_only_and_separates_confirmed_from_the_rest(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    (hosts / "connected_devices.csv").write_text(
        ",".join(cd.DEVICE_FIELDS) + "\n"
        "CD-000001,A,printer,,,,,unknown,confirmed,src,WM,x,true,2\n"
        "CD-000002,B,printer,,,,,unknown,proposed,,WM,x,true,1\n"
        "CD-000003,C,printer,,,,,unknown,confirmed,src,WM,x,false,1\n", encoding="utf-8")
    (hosts / "device_addresses.csv").write_text(
        ",".join(cd.ADDRESS_FIELDS) + "\n"
        "CD-000001,10.0.0.1,10.0.0.1,ipv4,,,s,true\n"
        "CD-000001,a.example.org,a.example.org,fqdn,,,s,true\n"
        "CD-000002,10.0.0.2,10.0.0.2,ipv4,,,s,true\n"
        "CD-000003,10.0.0.3,10.0.0.3,ipv4,,,s,true\n", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in hosts.iterdir()}
    out = cd.resolution_map(tmp_path)
    assert list(out["confirmed"]) == ["10.0.0.1"] and out["confirmed"]["10.0.0.1"]["revision"] == "2"
    assert list(out["unresolved"]) == ["10.0.0.2"] and out["ambiguous"] == {} and out["present"] is True
    assert {p.name: p.read_bytes() for p in hosts.iterdir()} == before
    assert cd.resolution_map(tmp_path / "nowhere") == {"confirmed": {}, "ambiguous": {}, "unresolved": {}, "present": False}


# --- importing reviewed endpoints.csv labels (S548); synthetic data only ------------------------------

_EP_HEAD = "end,name,zone,confidence,basis,evidence,reviewed\n"


def _import_project(tmp_path: Path, endpoints: str, devices: str = "", aliases: str = "") -> Path:
    project = _project(tmp_path)
    hosts = project / "csa-work" / "hosts"
    (hosts / "endpoints.csv").write_text(_EP_HEAD + endpoints, encoding="utf-8")
    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,ips\nAPP1,Yes,S,Application server,Perth,10.1.1.10\nPEER9,peer,,,,10.1.1.9\n",
        encoding="utf-8")
    if devices or aliases:
        (hosts / "connected_devices.csv").write_text(",".join(cd.DEVICE_FIELDS) + "\n" + devices, encoding="utf-8")
        (hosts / "device_addresses.csv").write_text(",".join(cd.ADDRESS_FIELDS) + "\n" + aliases, encoding="utf-8")
    return project


def _tree(project: Path) -> dict[str, bytes]:
    return {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}


_MIXED = (
    "10.1.1.5,Print server,OT Perth,observed,asset register row 9,E-3;E-4,yes\n"       # ready
    "print.site.example,Plotter,,observed,site walk,,yes\n"                            # ready (an FQDN)
    "10.1.1.6,Unreviewed thing,,likely,hint,,no\n"                                     # only counted
    "ROTPRDREV102,OT Reveloc Server,OT Perth,observed,register role,,yes\n"            # a host name, not an address
    "10.1.1.10,Dell box,,observed,somewhere,,yes\n"                                    # owned by APP1
    "10.1.1.9,Peer label,,observed,somewhere,,yes\n"                                   # owned by a register peer
    "10.1.1.7,No source,,observed,,,yes\n"                                             # uncited
    "10.1.1.8,,,observed,somewhere,,yes\n"                                             # no name
    "10.1.1.20,Name A,,observed,b1,,yes\n10.1.1.20,Name B,,observed,b2,,yes\n"         # two reviewed rows disagree
    "10.1.1.30,Switch 1,,observed,b3,,yes\n"                                           # an existing device says otherwise
    "10.1.1.31,Camera,,observed,b4,,yes\n"                                             # claimed by two devices
    "10.1.1.32,Badge reader,,observed,b5,,yes\n"                                       # already imported
)
_DEVS = (
    "CD-000001,Core switch,,,,,,unknown,proposed,x,WM,t,true,1\n"
    "CD-000002,Cam A,,,,,,unknown,proposed,x,WM,t,true,1\n"
    "CD-000003,Cam B,,,,,,unknown,proposed,x,WM,t,true,1\n"
    "CD-000004,Badge reader,,,,,,unknown,proposed,x,WM,t,true,1\n"
)
_ALS = (
    "CD-000001,10.1.1.30,10.1.1.30,ipv4,,,s,true\n"
    "CD-000002,10.1.1.31,10.1.1.31,ipv4,,,s,true\n"
    "CD-000003,10.1.1.31,10.1.1.31,ipv4,,,s,true\n"
    "CD-000004,10.1.1.32,10.1.1.32,ipv4,,,s,true\n"
)


def test_dry_run_sorts_every_row_and_writes_nothing(tmp_path):
    project = _import_project(tmp_path, _MIXED, _DEVS, _ALS)
    before = _tree(project)
    plan = cd.import_endpoints_plan(project)
    assert _tree(project) == before
    assert plan["status"] == "READY" and plan["ignored_unreviewed"] == 1
    assert [(r["address"], r["name"]) for r in plan["ready"]] == [("10.1.1.5", "Print server"), ("print.site.example", "Plotter")]
    first = plan["ready"][0]
    assert first["zone"] == "OT Perth" and first["evidence"] == "E-3;E-4"
    assert first["provenance"] == "imported from hosts/endpoints.csv (reviewed label): asset register row 9; evidence E-3;E-4"
    problems = {r["end"]: r["problem"] for r in plan["review"]}
    assert problems == {"ROTPRDREV102": "not_an_address", "10.1.1.10": "host_owned", "10.1.1.9": "host_owned",
                        "10.1.1.7": "uncited", "10.1.1.8": "no_name", "10.1.1.20": "conflict",
                        "10.1.1.30": "conflict", "10.1.1.31": "ambiguous"}
    assert plan["already_imported"] == [{"end": "10.1.1.32", "name": "Badge reader", "device_id": "CD-000004"}]
    assert "hosts/endpoints.csv" in plan["unchanged"] and plan["plan_id"]


def test_apply_needs_the_current_plan_and_an_operator(tmp_path):
    project = _import_project(tmp_path, _MIXED, _DEVS, _ALS)
    plan = cd.import_endpoints_plan(project)
    before = _tree(project)
    with pytest.raises(ValueError, match="stale preview"):
        cd.import_endpoints_apply(project, operator="WM", plan_id="0000000000000000")
    with pytest.raises(ValueError, match="operator"):
        cd.import_endpoints_apply(project, operator="", plan_id=plan["plan_id"])
    assert {k: v for k, v in _tree(project).items() if not k.endswith(".lock")} == before


def test_apply_creates_proposed_devices_and_touches_only_the_register(tmp_path):
    project = _import_project(tmp_path, _MIXED, _DEVS, _ALS)
    plan = cd.import_endpoints_plan(project)
    before = _tree(project)
    out = cd.import_endpoints_apply(project, operator="WM", plan_id=plan["plan_id"])
    assert [c["address"] for c in out["created"]] == ["10.1.1.5", "print.site.example"]
    assert [c["device_id"] for c in out["created"]] == ["CD-000005", "CD-000006"]
    after = _tree(project)
    changed = {Path(k).name for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert all(n.startswith(("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl", ".connected-devices.lock")) for n in changed), changed
    assert any(".bak-" in n for n in changed)                                  # the existing register files were backed up
    for untouched in ("endpoints.csv", "hosts.csv"):
        assert after[f"csa-work/hosts/{untouched}"] == before[f"csa-work/hosts/{untouched}"]
    made = {d["device_id"]: d for d in _devices(project)}
    new = made["CD-000005"]
    assert new["name"] == "Print server" and new["identification_state"] == "proposed" and new["revision"] == "1"
    assert new["site_zone"] == "OT Perth" and new["reviewer"] == "WM" and new["active"] == "true"
    assert "asset register row 9" in new["provenance"] and "E-3;E-4" in new["provenance"]
    alias = next(a for a in _addresses(project) if a["device_id"] == "CD-000005")
    assert alias["normalized"] == "10.1.1.5" and alias["source"] == cd.IMPORT_SOURCE and alias["address_type"] == "ipv4"
    assert next(a for a in _addresses(project) if a["device_id"] == "CD-000006")["address_type"] == "fqdn"
    events = [e for e in _audit(project) if e["action"] == "import_endpoint"]
    assert [e["device_id"] for e in events] == ["CD-000005", "CD-000006"] and events[0]["before"] is None
    assert events[0]["after"]["name"] == "Print server" and events[0]["addresses_after"][0]["normalized"] == "10.1.1.5"
    # imported labels are only proposed: they do not resolve a peer until someone confirms them
    assert "10.1.1.5" not in cd.resolution_map(project / "csa-work")["confirmed"]
    assert "10.1.1.5" in cd.resolution_map(project / "csa-work")["unresolved"]


def test_apply_is_idempotent(tmp_path):
    project = _import_project(tmp_path, _MIXED, _DEVS, _ALS)
    cd.import_endpoints_apply(project, operator="WM", plan_id=cd.import_endpoints_plan(project)["plan_id"])
    again = cd.import_endpoints_plan(project)
    assert again["status"] == "NOTHING_TO_IMPORT" and again["ready"] == []
    assert {a["end"] for a in again["already_imported"]} == {"10.1.1.5", "print.site.example", "10.1.1.32"}
    snapshot = _tree(project)
    out = cd.import_endpoints_apply(project, operator="WM", plan_id=again["plan_id"])
    assert out["created"] == [] and _tree(project) == snapshot


def test_import_works_with_no_register_and_no_endpoints_file(tmp_path):
    project = _import_project(tmp_path, "10.1.1.5,Print server,,observed,asset register,,yes\n")
    out = cd.import_endpoints_apply(project, operator="WM", plan_id=cd.import_endpoints_plan(project)["plan_id"])
    assert out["created"][0]["device_id"] == "CD-000001"
    (project / "csa-work" / "hosts" / "endpoints.csv").unlink()
    assert cd.import_endpoints_plan(project)["counts"] == {"ready": 0, "review": 0, "already_imported": 0, "unreviewed": 0}


def test_cli_dry_run_prints_the_plan(tmp_path, capsys):
    project = _import_project(tmp_path, "10.1.1.5,Print server,,observed,asset register,,yes\n")
    assert cd.main(["import-endpoints", str(project)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts"]["ready"] == 1 and not (project / "csa-work" / "hosts" / "connected_devices.csv").exists()


# --- the register survives rebuilds, end to end (S549) --------------------------------------------

def _rebuild_addresses(project: Path, reg: dict | None = None) -> dict:
    from csa_docx import hostmodel
    return hostmodel.build_addresses(project / "csa-work", reg if reg is not None else {"APP1": {"ips": {"10.9.9.1"}}}, {})


def _seed_observation(project: Path) -> None:
    import sqlite3
    work = project / "csa-work"
    con = sqlite3.connect(work / "discovery-index.sqlite")
    con.executescript("""
      create table captures(capture_id, folder, host, collector, capture_utc, archived, superseded_by, file_count);
      create table files(file_id, rel_path, capture_id, host, ext, size, mtime, sha1, status, reason, dup_of, source_class);
      create table rows(file_id, table_name, fmt, block_no, line_no, data);
    """)
    con.commit()
    con.close()
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,status,claim,review_state\n"
        "E-1,network_and_connectivity,VERIFIED,APP1 has an established connection from svchost.exe to 10.9.9.9 on port 445,reviewed\n",
        encoding="utf-8")


def _addresses_listed(project: Path) -> set[str]:
    with (project / "csa-work" / "hosts" / "addresses.csv").open(newline="", encoding="utf-8") as fh:
        return {r["address"] for r in csv.DictReader(fh)}


def test_identity_retire_and_restore_survive_every_rebuild(tmp_path):
    project = _project(tmp_path)
    _seed_observation(project)
    _rebuild_addresses(project)
    assert "10.9.9.9" in _addresses_listed(project)                       # unidentified to begin with

    made = cd.create_device(project, name="Label printer", values={
        "device_type": "printer", "role": "labels", "identification_state": "confirmed",
        "provenance": "Asset register v3"}, reviewer="WM", addresses=["10.9.9.9"])
    device_id = made["device_id"]
    _rebuild_addresses(project)
    assert "10.9.9.9" not in _addresses_listed(project)                    # resolved to the device
    peers = list(csv.DictReader((project / "csa-work" / "hosts" / "device_peers.csv").open(encoding="utf-8")))
    assert [(p["device_id"], p["revision"], p["provenance"]) for p in peers] == [(device_id, "1", "Asset register v3")]

    cd.retire_device(project, device_id, reviewer="WM")
    snapshot = {n: (project / "csa-work" / "hosts" / n).read_bytes()
                for n in ("connected_devices.csv", "device_addresses.csv", "device-audit.jsonl")}
    _rebuild_addresses(project)
    _rebuild_addresses(project)                                            # a repeat rebuild changes nothing either
    assert {n: (project / "csa-work" / "hosts" / n).read_bytes() for n in snapshot} == snapshot
    assert "10.9.9.9" in _addresses_listed(project)                        # the observation is back, unidentified
    assert "E-1" in (project / "csa-work" / "evidence-matrix.csv").read_text(encoding="utf-8")

    cd.restore_device(project, device_id)
    cd.add_address(project, device_id, "10.9.9.9", source="asset register")  # retiring switched its alias off; re-attach it
    _rebuild_addresses(project)
    assert "10.9.9.9" not in _addresses_listed(project)
    events = [e["action"] for e in _audit(project)]
    assert events == ["create", "retire", "restore", "add_address"]
    assert _devices(project)[0]["revision"] == "3"                         # create 1, retire 2, restore 3


def test_a_register_host_that_later_owns_the_address_wins_and_the_clash_is_reported(tmp_path):
    from csa_docx import hostmodel
    project = _project(tmp_path)
    _seed_observation(project)
    made = cd.create_device(project, name="Label printer", values={"identification_state": "confirmed", "provenance": "Asset register v3"},
                            reviewer="WM", addresses=["10.9.9.9"])
    before = {n: (project / "csa-work" / "hosts" / n).read_bytes() for n in ("connected_devices.csv", "device_addresses.csv")}
    summary: dict = {}
    hostmodel.build_addresses(project / "csa-work", {"APP1": {"ips": {"10.9.9.1"}}, "NEWBOX": {"ips": {"10.9.9.9"}}}, summary)
    assert summary["conflicts"] == [{"address": "10.9.9.9", "device_id": made["device_id"], "host": "NEWBOX"}]
    assert summary["resolved"] == []
    assert {n: (project / "csa-work" / "hosts" / n).read_bytes() for n in before} == before     # the saved identity is untouched
    assert cd.get_device(project, made["device_id"])["identification_state"] == "confirmed"
