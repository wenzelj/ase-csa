"""Network placement, host firewall, alternate RDP port and the shared flow filter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import flows, host_settings  # noqa: E402

LISTEN = """
LocalAddress LocalPort OwningProcess
------------ --------- -------------
0.0.0.0            135           700
::                 445             4
::                5985             4
0.0.0.0           1433          2200
0.0.0.0           1434          2200
0.0.0.0           2383          2200
0.0.0.0           2384          2200
0.0.0.0          49664           688
0.0.0.0          56403          1192
127.0.0.1         8100          3000
"""
PROCS = "135\tPID=700\tsvchost\n445\tPID=4\tSystem\n5985\tPID=4\tSystem\n1433\tPID=2200\tsqlservr\n56403\tPID=1192\tsvchost\n"
TASKS = """
Image Name                     PID Services
========================= ======== ============================================
svchost.exe                   1192 TermService
svchost.exe                    700 RpcEptMapper, RpcSs
"""
PROFILES = """
Name    Enabled DefaultInboundAction DefaultOutboundAction
----    ------- -------------------- ---------------------
Domain     True        NotConfigured         NotConfigured
Private    True        NotConfigured         NotConfigured
Public    False        NotConfigured         NotConfigured
"""
RULES = """
DisplayName : Cortana
Enabled     : True
Direction   : Inbound
Action      : Allow

DisplayName : Remote Desktop - User Mode (TCP-In)
Enabled     : True
Direction   : Inbound
Action      : Allow

DisplayName : Allow Alternate RDP (TCP 56403)
Enabled     : True
Direction   : Inbound
Action      : Allow

DisplayName : Vendor tool
Enabled     : False
Direction   : Inbound
Action      : Allow
"""
IPCFG = """
IPAddress         : 10.124.32.13
PrefixLength      : 26
AddressFamily     : IPv4
IPAddress         : 169.254.3.169
PrefixLength      : 16
"""
ROUTES = "Network Destination        Netmask          Gateway       Interface  Metric\n" \
         "          0.0.0.0          0.0.0.0     10.124.32.62     10.124.32.13    271\n"


def _cap(fname, text):
    return {"HOSTAA101": {"folder": "X_discovery_HOSTAA101_20260101T000000Z", "fname": fname, "start": 1, "text": text}}


def test_rdp_is_found_by_its_service_on_an_alternate_port():
    got = {r["attribute"]: r["value"] for r in host_settings.identity_settings(
        {"listen": _cap("20_listening_ports.txt", LISTEN), "tasks": _cap("24_tasklist_services.txt", TASKS)})}
    assert got["admin.listeners"] == "RDP 56403, WinRM 5985"
    assert got["admin.rdp_port"] == "56403"


def test_firewall_settings():
    caps = {"profiles": _cap("31_firewall_profiles.txt", PROFILES), "rules": _cap("33_firewall_rules.txt", RULES),
            "listen": _cap("20_listening_ports.txt", LISTEN), "procs": _cap("10_listeners_by_process.txt", PROCS),
            "tasks": _cap("24_tasklist_services.txt", TASKS)}
    got = {r["attribute"]: r["value"] for r in host_settings.firewall_settings(caps)}
    assert got["fw.profiles"] == "Off for Public, default actions not set"
    assert got["fw.custom_inbound"] == "Allow Alternate RDP (TCP 56403)"
    assert got["fw.exposed"] == "135 (svchost), 445 (System), 5985 (System), 56403 (RDP), sqlservr (1433, 1434, 2383 and others)"


def test_network_settings():
    caps = {"ipcfg": _cap("12_ip_interface_config.txt", IPCFG), "routes": _cap("11_ip_route.txt", ROUTES)}
    got = {r["attribute"]: r["value"] for r in host_settings.net_settings(caps, lambda ip: "OT Rockhampton")}
    assert got == {"net.address": "10.124.32.13/26", "net.zone": "OT Rockhampton", "net.gateway": "10.124.32.62"}


def test_flow_select_direction_and_any_of():
    rows = [{"src": "10.1.1.1", "dst": "HOSTAA101", "mechanism": "other", "status": "observed", "cross_zone": "unknown",
             "dst_zone": "OT", "data": "no"},
            {"src": "HOSTAA101", "dst": "8.8.8.8", "mechanism": "web/API", "status": "observed", "cross_zone": "yes",
             "dst_zone": "Internet", "data": "yes"},
            {"src": "HOSTAA101", "dst": "MAIL", "mechanism": "mail", "status": "declared", "cross_zone": "unknown",
             "dst_zone": "", "data": "yes"}]
    reg = {"HOSTAA101"}
    assert [r["dst"] for r in flows.select(rows, {"direction": "inbound"}, reg)] == ["HOSTAA101"]
    got = flows.select(rows, {"any_of": [{"dst_zones": ["Internet"]}, {"mechanisms": ["mail"]}]}, reg)
    assert [r["dst"] for r in got] == ["8.8.8.8", "MAIL"]


def test_a_flows_column_and_a_kept_column(tmp_path):
    import csv
    from csa_docx import topic_tables
    (tmp_path / "hosts").mkdir()
    row = {"flow_id": "F1", "status": "observed", "mechanism": "web/API", "data": "yes", "src": "HOSTAA101", "dst": "8.8.8.8",
           "port": "443", "cross_zone": "yes", "src_zone": "OT", "dst_zone": "Internet", "sources": "c/23 line 4", "excerpt": "x"}
    with (tmp_path / "hosts" / "flows.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    prof = {"topic": "Internet", "key": "INET", "columns": [
        {"label": "Proxy", "attribute": "transfer.proxy", "keep": True},
        {"label": "Internet", "attribute": "flows.internet", "flows": {"dst_zones": ["Internet"]}, "keep": True}]}
    hosts = [{"host": "HOSTAA101", "role": "App", "site": ""}, {"host": "HOSTBB101", "role": "DB", "site": ""}]
    s = {"value": "Direct", "source": "c/15 line 2", "excerpt": "y"}
    t = topic_tables.build(tmp_path, "Internet", profile=prof, hosts=hosts,
                           settings={"HOSTAA101": {"transfer.proxy": s}, "HOSTBB101": {"transfer.proxy": s}})
    assert {r["role"]: r["cells"] for r in t["rows"]} == {"App": ["Direct", "web/API"], "DB": ["Direct", "None seen"]}


def test_netstat_samples_give_attempted_and_observed_internet_flows():
    text = ("  TCP    10.1.1.5:63001     172.178.240.163:443    SYN_SENT        4392\n"
            "  TCP    10.1.1.5:63001     172.178.240.163:443    SYN_SENT        4392\n"
            "  TCP    10.1.1.5:63002     20.190.142.165:443     ESTABLISHED     4392\n"
            "  TCP    10.1.1.5:63003     10.40.254.6:8080       ESTABLISHED     4392\n")
    tasks = "svchost.exe                   4392 DiagTrack\n"
    samples = {"HOSTAA101": {"folder": "F", "fname": "25_netstat_tcp_samples.txt", "start": 1, "text": text}}
    rows = {r["dst"]: r for r in flows.sampled(samples, {"HOSTAA101": {"text": tasks}}, set())}
    assert set(rows) == {"172.178.240.163", "20.190.142.165"}          # private addresses are left to 23
    assert rows["172.178.240.163"]["status_hint"] == "attempted"
    assert rows["20.190.142.165"]["status_hint"] == "observed"
    assert rows["172.178.240.163"]["src_process"] == "svchost"
    assert rows["172.178.240.163"]["sources"] == ["F: 25_netstat_tcp_samples.txt line 1", "F: 25_netstat_tcp_samples.txt line 2"]
