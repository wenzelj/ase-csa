"""S458: the storage frame binds each finding to the requirement its kind tests, not every requirement the
slot touches. A file-share crossing from OT owes the data-location requirement as well as the crossing one;
a backup agent or web flow crossing owes only the crossing one; shares, tools, removable storage and proxy
owe only the local-exposure one. Other frames keep the same must_address as before."""
import csv

from csa_docx import topic_frames as TF

FIELDS = ["flow_id", "status", "mechanism", "data", "src", "src_role", "src_zone", "src_zone_kind", "src_process", "dst",
          "dst_role", "dst_zone", "dst_zone_kind", "dst_process", "port", "cross_zone", "zones_reviewed", "declared_id",
          "declared_flow", "signature", "confirm", "connections", "sources", "excerpt"]


def _flow(fid, mech, src, dst, port, status="observed", cz="unknown"):
    return {**{k: "" for k in FIELDS}, "flow_id": fid, "status": status, "mechanism": mech, "data": "yes", "src": src,
            "dst": dst, "port": port, "cross_zone": cz, "connections": "1",
            "sources": f"CAP: 23_process_connection_mapping.txt line {fid[1:]}", "excerpt": f"{src} -> {dst}"}


def _workspace(tmp_path):
    h = tmp_path / "csa-work" / "hosts"
    h.mkdir(parents=True)
    with (h / "flows.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader()
        w.writerows([
            _flow("F1", "backup agent", "BKPSRV01", "SQLSRV01", "7000"),                    # pulled out of OT
            _flow("F2", "file share", "APPSRV01", "FILESRV01", "445"),                       # OT opens to the file server
            _flow("F3", "web/API", "APPSRV01", "10.9.1.40", "8080"),                         # OT opens a web flow
            _flow("F4", "file share", "APPSRV01", "SQLSRV02", "445", cz="no"),                    # inside OT
            _flow("F5", "backup agent", "APPSRV01", "CLOUD01", "443", status="declared"),    # declared, not seen
        ])
    with (h / "host_settings.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["host", "area", "attribute", "value", "capture", "source", "excerpt"])
        w.writerow(["SQLSRV01", "storage", "storage.database", "SQL Server (S01)", "C", "C/52.txt line 1", "S01"])
        w.writerow(["APPSRV01", "storage", "storage.shares", "CAcom (C:\\)", "C", "C/42.txt line 3", "Name : CAcom"])
        w.writerow(["APPSRV01", "transfer", "transfer.tools", "WinSCP 5.9.5", "C", "C/67.txt line 2", "WinSCP 5.9.5"])
        w.writerow(["APPSRV01", "transfer", "transfer.removable", "Not set in applied Group Policy", "C", "C/61.txt line 9", ""])
        w.writerow(["APPSRV01", "transfer", "transfer.proxy", "ProxyServer : 10.9.1.2:8080", "C", "C/15.txt line 4", "ProxyServer : 10.9.1.2:8080"])
    (h / "hosts.csv").write_text("host,in_scope,system,role,site,ips,capture\n"
                                 "SQLSRV01,yes,S,SQL node,Rock,10.1.0.11,X\n"
                                 "APPSRV01,yes,S,App server,Rock,10.1.0.21,X\n"
                                 "SQLSRV02,yes,S,SQL node,Rock,10.1.0.31,X\n"
                                 "FILESRV01,peer,,,,,\nBKPSRV01,peer,,,,,\n", encoding="utf-8")
    (h / "zones.csv").write_text("zone,kind,match,basis,reviewed\nOT Rock,ot,subnet:10.1.0.0/24,f,yes\n"
                                 "\"Internal, zone not recorded\",unknown,default:private,,yes\n"
                                 "Internet,internet,default:public,,yes\n", encoding="utf-8")
    return tmp_path


def _build(tmp_path):
    ws = _workspace(tmp_path)
    fr = TF.build(ws, "Storage & Data Transfer", "STOR", evidence=False)
    n = 0
    for s in fr["slots"]:
        for f in s["findings"]:
            n += 1
            f["ids"] = [f"E-{100 + n}"]
    return fr


def _texts(fr, req):
    ma = TF.must_address(fr)
    return [x["text"] for x in ma.get(req, []) if not x["empty"]]


def _findings(fr, slot):
    return [f for f in next(s for s in fr["slots"] if s["id"] == slot)["findings"]]


def test_data_stores_bind_to_the_data_location_requirement(tmp_path):
    fr = _build(tmp_path)
    assert any(f["text"].startswith("Database service") for f in _findings(fr, "S1"))
    assert any("SQL Server (S01)" in t for t in _texts(fr, "SEP-STOR-01"))


def test_file_share_crossings_from_ot_bind_to_both_requirements(tmp_path):
    fr = _build(tmp_path)
    fs = [f for f in _findings(fr, "S3") if "445" in f["text"] and "FILESRV01" in f["text"]]
    assert fs and fs[0]["direction"] == "ot_push"
    assert set(fs[0]["requirements"]) == {"SEP-STOR-01", "SEP-STOR-03"}
    assert any("FILESRV01" in t and "445" in t for t in _texts(fr, "SEP-STOR-01"))
    assert any("FILESRV01" in t and "445" in t for t in _texts(fr, "SEP-STOR-03"))


def test_septor_01_has_no_shares_backup_or_web_findings(tmp_path):
    fr = _build(tmp_path)
    t = _texts(fr, "SEP-STOR-01")
    assert t and not any("CAcom" in x for x in t)                 # S2 share: local exposure only
    assert not any("backup agent" in x.lower() for x in t)        # the backup pull crosses only
    assert not any("8080" in x for x in t)                        # the web flow crosses only
    assert any("FILESRV01" in x and "445" in x for x in t)        # but the file-share crossing is here


def test_septor_02_has_the_shares_tools_removable_and_proxy(tmp_path):
    fr = _build(tmp_path)
    t = _texts(fr, "SEP-STOR-02")
    assert any("CAcom" in x for x in t)
    assert any("WinSCP" in x for x in t)
    assert any("Group Policy" in x for x in t)
    assert any("ProxyServer" in x for x in t)
    assert not any("FILESRV01" in x for x in t)
    assert not any("backup agent" in x.lower() for x in t)


def test_other_crossings_and_declared_flows_bind_to_the_crossing_requirement(tmp_path):
    fr = _build(tmp_path)
    s3 = _findings(fr, "S3")
    bkp = next(f for f in s3 if "BKPSRV01" in f["text"])
    web = next(f for f in s3 if "8080" in f["text"])
    assert bkp["requirements"] == ["SEP-STOR-03"] and web["requirements"] == ["SEP-STOR-03"]
    s5 = _findings(fr, "S5")
    decl = [f for f in s5 if f["status"] == "declared"]
    assert decl and all(f["requirements"] == ["SEP-STOR-03"] for f in decl)


def test_inside_ot_flows_bind_to_the_data_location_requirement_as_context(tmp_path):
    fr = _build(tmp_path)
    s4 = [f for f in _findings(fr, "S4") if "SQLSRV02" in f["text"]]
    assert s4 and s4[0]["direction"] == "inside_ot" and s4[0]["requirements"] == ["SEP-STOR-01"]
    assert not any("SQLSRV02" in t for t in _texts(fr, "SEP-STOR-02"))


def test_bind_entries_without_a_mechanism_filter_keep_the_old_behaviour(tmp_path):
    slot = {"requirements": ["R1", "R2"], "bind": {"ot_push": ["R2"]}}
    f = {"direction": "ot_push", "mechanism": "file share"}
    TF.bind_requirements(slot, [f])
    assert f["requirements"] == ["R2"]
    slot2 = {"requirements": ["R1", "R2"], "bind": {"ot_push": [
        {"mechanisms": ["file share"], "requirements": ["R1", "R2"]}, ["R2"]]}}
    fs, fo = {"direction": "ot_push", "mechanism": "file share"}, {"direction": "ot_push", "mechanism": "backup agent"}
    TF.bind_requirements(slot2, [fs, fo])
    assert fs["requirements"] == ["R1", "R2"] and fo["requirements"] == ["R2"]
    f3 = {"direction": "into_ot", "mechanism": "file share"}
    TF.bind_requirements(slot2, [f3])
    assert f3["requirements"] == ["R1", "R2"]                       # no bind entry for the direction: slot's requirements
