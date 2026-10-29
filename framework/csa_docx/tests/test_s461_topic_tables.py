"""S461: section tables - one column once, flow table only for flows that cross OT."""
import csv
from pathlib import Path

from csa_docx import endpoints as ep
from csa_docx import topic_tables as tt

HOSTS_CSV = (
    "host,in_scope,system,role,site,system_source,role_source,site_source,conflicts,fqdn,ips,ou,capture,captured_in,listening,sources,ad_site\n"
    "ROTPRDREV102,Yes,Reveloc,OT Reveloc Server,Rockhampton,register,register,register,,,ROTPRDREV102.fqdn,10.40.229.210,cap,,,listening,source,,\n"
    "MOTPRDPDM101,Yes,Reveloc,Peer,Mackay,register,register,register,,,MOTPRDPDM101.fqdn,10.45.229.194,cap,,,listening,source,,\n"
)
ZONES_CSV = (
    "zone,kind,match,basis,reviewed\n"
    "OT Rockhampton,ot,subnet:10.40.228.0/27,fixture,yes\n"
    "OT Mackay,ot,subnet:10.45.228.0/27,fixture,yes\n"
    "Internal, zone not recorded,unknown,default:private,,yes\n"
    "Internet,internet,default:public,,yes\n"
)


def _work(tmp) -> Path:
    wd = tmp / "csa-work"
    (wd / "hosts").mkdir(parents=True)
    (wd / "hosts" / "hosts.csv").write_text(HOSTS_CSV, encoding="utf-8")
    (wd / "hosts" / "zones.csv").write_text(ZONES_CSV, encoding="utf-8")
    return wd


def _flow_row(fid, status, mech, src, dst, port, src_zone, dst_zone, src_kind, dst_kind, cz):
    return {
        "flow_id": fid, "status": status, "mechanism": mech, "data": "yes",
        "src": src, "src_role": "", "src_zone": src_zone, "src_zone_kind": src_kind, "src_process": "agentService",
        "dst": dst, "dst_role": "", "dst_zone": dst_zone, "dst_zone_kind": dst_kind, "dst_process": "",
        "port": port, "cross_zone": cz, "zones_reviewed": "no",
        "declared_id": "", "declared_flow": "", "signature": "", "confirm": "", "connections": "1",
        "sources": "cap: 23 line 1", "excerpt": "x",
    }


def _write_flows(wd: Path, rows: list[dict]) -> None:
    with (wd / "hosts" / "flows.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


STOR_PROFILE = {
    "topic": "Storage & Data Transfer",
    "key": "STOR",
    "headings": ["Storage & Data Transfer"],
    "requirements": ["SEP-STOR-01", "SEP-STOR-02", "SEP-STOR-03"],
    "columns": [
        {"label": "Database", "attribute": "storage.database", "common": "run {value}"},
        {"label": "Shares", "attribute": "storage.shares", "common": "offer {value}"},
        {"label": "Transfer tools", "attribute": "transfer.tools", "common": "have file transfer tools {value}"},
    ],
    "evidence_tables": [
        {"requirement": "SEP-STOR-01", "kind": "roles", "title": "Storage discovery evidence",
         "attributes": ["storage.database", "storage.shares"]},
        {"requirement": "SEP-STOR-02", "kind": "roles", "title": "Transfer-control discovery evidence",
         "attributes": ["storage.shares", "transfer.tools"]},
        {"requirement": "SEP-STOR-03", "kind": "flows", "title": "Data-direction discovery evidence"},
    ],
    "replace_observation_table": True,
    "flows": {"data": True, "status": ["observed", "both", "declared", "attempted"]},
}

_HOSTS = [
    {"host": "ROTPRDREV102", "role": "OT Reveloc Server", "site": "Rockhampton", "capture": True},
    {"host": "MOTPRDPDM101", "role": "Peer", "site": "Mackay", "capture": True},
]


def _write_settings(wd: Path) -> None:
    """hosts/host_settings.csv rows the STOR profile reads (storage.database, storage.shares, transfer.tools)."""
    with (wd / "hosts" / "host_settings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "attribute", "value", "capture", "source", "excerpt"])
        for host, attrs in (
            ("ROTPRDREV102", [("storage.database", "SQL Server (S01)", "cap52 line 1"),
                              ("storage.shares", "CAcom (C:\\)", "cap42 line 1"),
                              ("transfer.tools", "WinSCP 5.9.5", "cap67 line 1")]),
            ("MOTPRDPDM101", [("storage.database", "SQL Server (S02)", "cap52 line 1"),
                              ("storage.shares", "DataMgr (D:\\)", "cap42 line 1"),
                              ("transfer.tools", "WinSCP 5.9.5", "cap67 line 1")]),
        ):
            for attr, value, source in attrs:
                w.writerow([host, attr, value, "fixture", source, "x"])


def test_stor_shares_appears_once(tmp_path):
    """The Shares column appears in one role table only; the later role table drops it."""
    wd = _work(tmp_path)
    _write_settings(wd)
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        tables = tt.build_all(wd, "Storage & Data Transfer", "STOR")
    finally:
        tt.register = orig_register
    ok = [t for t in tables if t.get("status") == "OK"]
    assert len(ok) >= 2, f"expected at least 2 OK tables, got {len(ok)}: {[t.get('status') for t in tables]}"
    shares_tables = [t for t in ok if "Shares" in t["columns"]]
    assert len(shares_tables) == 1, (
        f"Shares should appear in exactly one role table, found in {len(shares_tables)}: "
        f"{[(t['requirement'], t['columns']) for t in ok]}"
    )
    # The first role table (SEP-STOR-01) should still carry its own columns
    t1 = [t for t in ok if t["requirement"] == "SEP-STOR-01"][0]
    assert "Database" in t1["columns"]
    # The second role table (SEP-STOR-02) should not repeat Shares
    t2 = [t for t in ok if t["requirement"] == "SEP-STOR-02"][0]
    assert "Shares" not in t2["columns"], f"Shares repeated in SEP-STOR-02: {t2['columns']}"
    # Role and Hosts are always kept
    assert t2["columns"][:2] == ["Role", "Hosts"]


def test_monitoring_profile_builds_one_focused_table_per_requirement(tmp_path):
    """Monitoring uses the generic requirement-story-table layout, not one shared domain table."""
    wd = _work(tmp_path)
    with (wd / "hosts" / "host_settings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "topic", "attribute", "value", "capture", "source", "excerpt"])
        for host in ("ROTPRDREV102", "MOTPRDPDM101"):
            for attr, value in (
                ("agent.edr", "CrowdStrike Falcon" if host == "ROTPRDREV102" else "None found"),
                ("agent.antivirus", "Microsoft Defender Antivirus"),
                ("agent.monitoring", "Microsoft Monitoring Agent (SCOM)"),
                ("agent.security_telemetry", "None found"),
                ("agent.patch_management", "Microsoft Configuration Manager client (MECM)"),
                ("agent.log_forwarding", "Splunk Universal Forwarder" if host == "ROTPRDREV102" else "None found"),
            ):
                w.writerow([host, "agents", attr, value, "fixture", "capture line 1", "x"])
    _write_flows(wd, [
        _flow_row("F-MON-01", "observed", "monitoring", "ROTPRDREV102", "34.1.2.3", "5723",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes")
    ])
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        tables = [t for t in tt.build_all(wd, "Monitoring & Logging", "MON") if t.get("status") == "OK"]
    finally:
        tt.register = orig_register

    assert [t["requirement"] for t in tables] == ["SEP-MON-01", "SEP-MON-02", "SEP-MON-03"]
    assert tables[0]["columns"][0] == "Mechanism"
    assert "EDR" in tables[1]["columns"]
    assert "Patch compliance client" in tables[1]["columns"] or "Configuration Manager" in tables[1]["common"]
    assert tables[2]["columns"] == ["Role", "Hosts", "Log forwarding"]
    assert all(t["replace_observation_table"] for t in tables)


def test_stor_flow_table_crossing_only_and_direction(tmp_path):
    """The flow table shows only flows that cross OT, with a Direction column and pulls first."""
    wd = _work(tmp_path)
    rows = [
        # Both ends OT (filtered out)
        _flow_row("F001", "observed", "database replication", "ROTPRDREV102", "MOTPRDPDM101", "1433",
                  "OT Rockhampton", "OT Mackay", "ot", "ot", "yes"),
        # No OT end (filtered out)
        _flow_row("F002", "observed", "web/API", "10.9.9.9", "34.1.2.3", "443",
                  "Internal, zone not recorded", "Internet", "unknown", "internet", "yes"),
        # Pushed from OT (ROTPRDREV102 -> Internet)
        _flow_row("F004", "observed", "web/API", "ROTPRDREV102", "34.120.2.104", "443",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes"),
        # Zone not settled (ROTPRDREV102 -> unknown zone)
        _flow_row("F005", "observed", "file share", "ROTPRDREV102", "10.9.9.9", "445",
                  "OT Rockhampton", "Internal, zone not recorded", "ot", "unknown", "yes"),
    ]
    _write_flows(wd, rows)
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        t = tt.build_flows(wd, "Storage & Data Transfer", STOR_PROFILE)
    finally:
        tt.register = orig_register
    assert t["status"] == "OK"
    assert "Direction" in t["columns"]
    # Filtered rows: F001 (both OT) and F002 (no OT end) must not appear
    # F001: src ROTPRDREV102 dst MOTPRDPDM101 -- both OT, excluded
    # F002: src 10.9.9.9 dst 34.1.2.3 -- no OT, excluded
    all_dst_text = " ".join(r["cells"][0] for r in t["rows"])
    all_src_text = " ".join(r["hosts"][0] for r in t["rows"])
    assert "34.1.2.3" not in all_dst_text, f"no-OT row should be filtered: {all_dst_text}"
    assert "MOTPRDPDM101" not in all_dst_text, f"both-OT row should be filtered: {all_dst_text}"
    # The crossing rows should appear
    assert "34.120.2.104" in all_dst_text
    assert "10.9.9.9" in all_dst_text
    # Direction column present with valid values
    directions = [r["cells"][1] for r in t["rows"]]
    order = {"Pulled from OT": 0, "Pushed from OT": 1, "Zone not settled": 2}
    assert directions == sorted(directions, key=lambda d: order.get(d, 99)), f"wrong order: {directions}"


def test_no_attempted_sentence_when_no_row_attempted(tmp_path):
    """The 'Attempted' sentence only appears when a row is attempted."""
    wd = _work(tmp_path)
    rows = [
        _flow_row("F001", "observed", "web/API", "ROTPRDREV102", "34.120.2.104", "443",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes"),
    ]
    _write_flows(wd, rows)
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        t = tt.build_flows(wd, "Storage & Data Transfer", STOR_PROFILE)
    finally:
        tt.register = orig_register
    assert t["status"] == "OK"
    assert "Attempted" not in t["common"], f"unexpected Attempted sentence: {t['common']}"
    assert "Seen means it appeared in the sampled process connections." in t["common"]
    assert "From is the side that opens the connection." in t["common"]
    assert "Zones come from the project zone list." in t["common"]


def test_attempted_sentence_when_row_attempted(tmp_path):
    """The 'Attempted' sentence appears when a row is attempted."""
    wd = _work(tmp_path)
    rows = [
        _flow_row("F001", "observed", "web/API", "ROTPRDREV102", "34.120.2.104", "443",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes"),
        _flow_row("F002", "attempted", "web/API", "ROTPRDREV102", "34.120.2.105", "443",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes"),
    ]
    _write_flows(wd, rows)
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        t = tt.build_flows(wd, "Storage & Data Transfer", STOR_PROFILE)
    finally:
        tt.register = orig_register
    assert t["status"] == "OK"
    assert "Attempted means the host sent a connection request" in t["common"], t["common"]


def test_topic_with_no_flows_profile_unchanged(tmp_path):
    """A topic with no flows profile is unchanged - no Direction column, no flows table."""
    wd = _work(tmp_path)
    profile = {
        "topic": "Time Synchronisation",
        "key": "TIME",
        "headings": ["Time Synchronisation"],
        "requirements": ["SEP-TIME-01"],
        "columns": [
            {"label": "Time source", "attribute": "time.source", "common": "take time from {value}"},
        ],
    }
    hosts = [{"host": "ROTPRDREV102", "role": "OT Reveloc Server", "site": "Rockhampton", "capture": True}]
    settings = {
        "ROTPRDREV102": {"time.source": {"value": "SRV1", "source": "cap: 03 line 1", "excerpt": "x"}},
    }
    t = tt.build(wd, "Time Synchronisation", "TIME", profile, hosts=hosts, settings=settings)
    assert t["status"] == "OK"
    assert "Direction" not in t["columns"]
    f = tt.build_flows(wd, "Time Synchronisation", profile)
    assert f["status"] == "NO_FLOWS"


def test_endpoints_label_used_for_end_names(tmp_path):
    """Each end is written with endpoints.label when it has one, else as today."""
    wd = _work(tmp_path)
    with (wd / "hosts" / "endpoints.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ep.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerow({"end": "34.120.2.104", "name": "Azure Service Bus", "zone": "Internet",
                    "confidence": "observed", "basis": "fixture", "evidence": "", "reviewed": "no"})
    rows = [
        _flow_row("F001", "observed", "web/API", "ROTPRDREV102", "34.120.2.104", "443",
                  "OT Rockhampton", "Internet", "ot", "internet", "yes"),
    ]
    _write_flows(wd, rows)
    orig_register = tt.register
    tt.register = lambda work_dir: _HOSTS
    try:
        t = tt.build_flows(wd, "Storage & Data Transfer", STOR_PROFILE)
    finally:
        tt.register = orig_register
    assert t["status"] == "OK"
    dst = t["rows"][0]["cells"][0]
    assert "Azure Service Bus" in dst, f"expected endpoint label in dst, got: {dst}"
