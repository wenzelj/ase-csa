"""S455: figures take labels and confidence from the endpoint register.

flowview, brief and storeview all show the register's name: plain for an observed
name, `likely <name> (to confirm)` for a likely one. An end the register does not
know keeps today's label (the peer hint, or "Role not recorded").
"""
from __future__ import annotations

import csv
from pathlib import Path

from csa_docx.figures import brief as BR
from csa_docx.figures import flowview as FV
from csa_docx.figures import storeview as SV

_FLOWS_FIELDS = ["flow_id", "status", "mechanism", "data", "src", "src_role", "src_zone", "src_zone_kind",
                 "src_process", "dst", "dst_role", "dst_zone", "dst_zone_kind", "dst_process", "port",
                 "cross_zone", "zones_reviewed", "declared_id", "declared_flow", "signature", "confirm",
                 "connections", "sources", "excerpt"]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _flow(fid: str, src: str, dst: str) -> dict:
    return {"flow_id": fid, "status": "observed", "mechanism": "database", "data": "yes",
            "src": src, "src_role": "", "src_zone": "Internal, zone not recorded", "src_zone_kind": "unknown",
            "src_process": "sqlservr", "dst": dst, "dst_role": "Reveloc Store Server",
            "dst_zone": "OT Rockhampton", "dst_zone_kind": "ot", "dst_process": "", "port": "1433",
            "cross_zone": "yes", "zones_reviewed": "yes", "declared_id": "", "declared_flow": "",
            "signature": "", "confirm": "", "connections": "", "sources": "E-1547", "excerpt": ""}


def _work(tmp: Path) -> Path:
    wd = tmp / "csa-work"
    _write_csv(wd / "hosts" / "hosts.csv",
        ["host", "in_scope", "system", "role", "site", "system_source", "role_source", "site_source",
         "conflicts", "fqdn", "ips", "ou", "capture", "captured_in", "listening", "sources", "ad_site"],
        [{"host": "STORESRV101", "in_scope": "Yes", "system": "Reveloc", "role": "Reveloc Store Server",
          "site": "Rockhampton", "fqdn": "STORESRV101.aznops.aurizonnetwork.com.au",
          "ips": "10.40.229.210", "listening": "listening", "sources": "source"}])
    _write_csv(wd / "hosts" / "flows.csv", _FLOWS_FIELDS, [
        _flow("F001", "10.45.229.194", "STORESRV101"),
        _flow("F002", "10.40.254.6", "STORESRV101"),
        _flow("F003", "10.9.9.9", "STORESRV101"),
    ])
    _write_csv(wd / "hosts" / "host_settings.csv",
        ["host", "attribute", "value", "source"],
        [{"host": "STORESRV101", "attribute": "storage.database", "value": "SQL Server (S01)", "source": "capture"},
         {"host": "STORESRV101", "attribute": "storage.shares", "value": "Default and administrative shares only", "source": "capture"},
         {"host": "STORESRV101", "attribute": "agent.edr", "value": "None found", "source": "capture"},
         {"host": "STORESRV101", "attribute": "agent.antivirus", "value": "None found", "source": "capture"},
         {"host": "STORESRV101", "attribute": "transfer.tools", "value": "None found", "source": "capture"}])
    # the endpoint register: observed name for 10.45.229.194, likely name for 10.40.254.6,
    # 10.9.9.9 is not in the register at all
    _write_csv(wd / "hosts" / "endpoints.csv",
        ["end", "name", "zone", "confidence", "basis", "evidence", "reviewed"],
        [{"end": "STORESRV101", "name": "Reveloc Store Server", "zone": "OT Rockhampton",
          "confidence": "observed", "basis": "register role", "evidence": "", "reviewed": "no"},
         {"end": "10.45.229.194", "name": "Mackay Dell PowerProtect Data Manager", "zone": "",
          "confidence": "observed", "basis": "gap lookup evidence", "evidence": "E-1547", "reviewed": "no"},
         {"end": "10.40.254.6", "name": "Dell PowerProtect Data Manager server", "zone": "",
          "confidence": "likely", "basis": "unrecorded-peer hint", "evidence": "", "reviewed": "no"}])
    return wd


def _node(key: str) -> dict:
    return {"key": key, "number": "", "title": key, "level": 2, "kind": "section", "figures": [], "parts": []}


def _row(archetype: str, title: str) -> dict:
    return {"key": "STOR", "number": "", "title": title, "archetype": archetype, "question": "",
            "requirements": [], "part": "", "caption": ""}


def _ev(wd: Path) -> dict:
    reg = {}
    f = wd / "hosts" / "hosts.csv"
    if f.is_file():
        with f.open(newline="", encoding="utf-8") as fh:
            reg = {r["host"].upper(): r for r in csv.DictReader(fh)}
    return {"register": reg}


def test_flowview_takes_roles_from_the_endpoint_register(tmp_path):
    wd = _work(tmp_path)
    m = FV.view(wd, {"nodes": [], "zones": []}, {"data_centres": []}, {}, key="STOR", title="Data flows", subtitle="")
    roles = {n["id"]: n["role"] for n in m["nodes"]}
    assert roles["10.45.229.194"] == "Mackay Dell PowerProtect Data Manager"
    assert roles["10.40.254.6"] == "likely Dell PowerProtect Data Manager server (to confirm)"
    # 10.9.9.9 is not in the register and has no peer hint: today's label stays
    assert roles["10.9.9.9"] == "Role not recorded"


def test_brief_flow_gaps_recognise_the_new_confirm_text(tmp_path):
    wd = _work(tmp_path)
    m = FV.view(wd, {"nodes": [], "zones": []}, {"data_centres": []}, {}, key="STOR", title="Data flows", subtitle="")
    b = BR.build(_row("F", "Data stores and data flows"), _node("STOR"), _ev(wd), {"data_centres": []}, model=m)
    gap_whats = [g["what"] for g in b["gaps"]]
    # the likely end carries its qualified name in the gap entry
    assert any("10.40.254.6" in w and "likely Dell PowerProtect Data Manager server (to confirm)" in w for w in gap_whats)
    # the observed end has its register name, so it is not listed among the unrecorded roles
    assert not any("The role of 10.45.229.194" in w for w in gap_whats)


def test_storeview_takes_roles_from_the_endpoint_register(tmp_path):
    wd = _work(tmp_path)
    m = SV.view(wd, {"nodes": [], "zones": []}, {}, {}, key="STOR", title="Data stores", subtitle="")
    uses = [u for c in m["cards"] for u in c["uses"]]
    roles = {h: u["role"] for u in uses for h in u["hosts"]}
    assert roles["10.45.229.194"] == "Mackay Dell PowerProtect Data Manager"
    assert roles["10.40.254.6"] == "likely Dell PowerProtect Data Manager server (to confirm)"
    assert roles["10.9.9.9"] == "Role not recorded"


def test_brief_store_gaps_recognise_the_new_confirm_text(tmp_path):
    wd = _work(tmp_path)
    m = SV.view(wd, {"nodes": [], "zones": []}, {}, {}, key="STOR", title="Data stores", subtitle="")
    b = BR.build(_row("G", "Where the system holds its data"), _node("STOR"), _ev(wd), {"data_centres": []}, model=m)
    gap_whats = [g["what"] for g in b["gaps"]]
    # the likely end carries its qualified name, so it is not listed among the unrecorded roles
    # (its zone is still not recorded: that separate gap legitimately names it)
    assert not any("The role of 10.40.254.6" in w for w in gap_whats)


def test_flowview_falls_back_to_the_hint_when_the_register_has_no_name(tmp_path):
    wd = _work(tmp_path)
    # remove the likely end from the register, but leave a peer hint for it
    _write_csv(wd / "hosts" / "endpoints.csv",
        ["end", "name", "zone", "confidence", "basis", "evidence", "reviewed"],
        [{"end": "STORESRV101", "name": "Reveloc Store Server", "zone": "OT Rockhampton",
          "confidence": "observed", "basis": "register role", "evidence": "", "reviewed": "no"},
         {"end": "10.45.229.194", "name": "Mackay Dell PowerProtect Data Manager", "zone": "",
          "confidence": "observed", "basis": "gap lookup evidence", "evidence": "E-1547", "reviewed": "no"}])
    # give F002 the backup-agent mechanism so the signal-signatures backup-agent row
    # (opener_role "Dell PowerProtect Data Manager server") provides a peer hint for 10.40.254.6
    _write_csv(wd / "hosts" / "flows.csv", _FLOWS_FIELDS, [
        _flow("F001", "10.45.229.194", "STORESRV101"),
        {**_flow("F002", "10.40.254.6", "STORESRV101"),
         "mechanism": "backup agent", "src_process": "agentService",
         "dst_process": "agentService", "port": "7000", "dst_role": ""},
        _flow("F003", "10.9.9.9", "STORESRV101"),
    ])
    m = FV.view(wd, {"nodes": [], "zones": []}, {"data_centres": []}, {}, key="STOR", title="Data flows", subtitle="")
    roles = {n["id"]: n["role"] for n in m["nodes"]}
    # F002 (10.40.254.6 opens backup-agent to STORESRV101) triggers the signature hint
    assert roles["10.40.254.6"] == "Dell PowerProtect Data Manager server (likely, confirm)"
    assert roles["10.45.229.194"] == "Mackay Dell PowerProtect Data Manager"
