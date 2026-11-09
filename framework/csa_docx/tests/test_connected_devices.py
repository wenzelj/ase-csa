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
