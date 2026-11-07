"""The product and agent catalogue: services and installed software classified per host."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings, topic_tables  # noqa: E402

SERVICES = """
Name        : CSFalconService
DisplayName : CrowdStrike Falcon Sensor Service
State       : Running
StartMode   : Auto
StartName   : LocalSystem
PathName    : "C:\\Program Files\\CrowdStrike\\CSFalconService.exe"

Name        : AgentService
DisplayName : PowerProtect Agent Service
State       : Running
StartMode   : Auto
StartName   : LocalSystem
PathName    : "C:\\Program Files\\DPSAPPS\\AgentService\\agentServiceMon.exe"

Name        : UevAgentService
DisplayName : User Experience Virtualization Service
State       : Stopped
StartMode   : Disabled
StartName   : LocalSystem
PathName    : C:\\WINDOWS\\system32\\AgentService.exe

Name        : AppIDSvc
DisplayName : Application Identity
State       : Stopped
StartMode   : Manual
StartName   : NT Authority\\LocalService
PathName    : C:\\WINDOWS\\system32\\svchost.exe -k LocalServiceNetworkRestricted

Name        : AdtAgent
DisplayName : Microsoft Monitoring Agent Audit Forwarding
State       : Stopped
StartMode   : Disabled
StartName   : NT AUTHORITY\\NetworkService
PathName    : C:\\WINDOWS\\system32\\AdtAgent.exe
"""


def _caps():
    cap = lambda f, t: {"H1": {"folder": "X_discovery_H1_20260101T000000Z", "fname": f, "start": 1, "text": t}}  # noqa: E731
    return {"services": cap("32_services_inventory.txt", SERVICES),
            "software": cap("67_installed_software.txt", "DisplayName : UltraVNC 1.4\nDisplayName : 7-Zip\n"),
            "gpo": cap("61_gpresult_verbose.txt", "Computer Settings\n  Security Options\n")}


def test_service_blocks_keep_every_field_and_its_line():
    b = host_settings.service_blocks(SERVICES)
    assert b[0]["Name"] == "CSFalconService" and b[0]["State"] == "Running"
    assert SERVICES.splitlines()[b[1]["_lines"]["StartName"]].strip() == "StartName   : LocalSystem"


def test_catalogue_classifies_services_and_software():
    got = {r["attribute"]: r for r in host_settings.agent_settings(_caps())}
    assert got["agent.edr"]["value"] == "CrowdStrike Falcon"
    assert got["agent.edr"]["excerpt"] == "Name        : CSFalconService"
    assert got["agent.backup"]["value"] == "Dell PowerProtect agent"            # by path, not the UEV AgentService
    assert got["agent.backup_account"]["value"] == "PowerProtect Agent Service: LocalSystem"
    assert got["agent.log_forwarding"]["value"] == "SCOM Audit Collection (AdtAgent) (stopped, disabled)"
    assert got["agent.application_control"]["value"] == "None found"          # AppIDSvc is not running
    assert got["agent.application_control"]["excerpt"] == ""
    assert got["agent.remote_support"]["value"] == "UltraVNC 1.4"             # from installed software
    assert got["agent.remote_support"]["source"].endswith("67_installed_software.txt line 1")
    assert got["appcontrol.policy"]["value"] == "Not set in applied Group Policy"


def test_flows_table_filters_by_mechanism(tmp_path):
    (tmp_path / "hosts").mkdir()
    rows = [{"flow_id": "F1", "status": "observed", "mechanism": "backup agent", "data": "yes", "src": "BKPSRV001", "dst": "DBSRV001",
             "port": "7000", "cross_zone": "unknown", "src_zone": "", "dst_zone": "OT", "sources": "c: f line 1", "excerpt": "x"},
            {"flow_id": "F2", "status": "observed", "mechanism": "file share", "data": "yes", "src": "DBSRV001", "dst": "10.0.0.9",
             "port": "445", "cross_zone": "unknown", "src_zone": "OT", "dst_zone": "", "sources": "c: f line 2", "excerpt": "y"}]
    with (tmp_path / "hosts" / "flows.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    t = topic_tables.build_flows(tmp_path, "Backup & Recovery", {"key": "BAK", "flows": {"mechanisms": ["backup agent"]}})
    assert [r["role"] for r in t["rows"]] == ["Backup agent"]
