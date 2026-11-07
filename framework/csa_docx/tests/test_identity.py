"""Identity and admin access settings: domain, answering DC, local accounts, service accounts, group members, listeners."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings, topic_tables  # noqa: E402

AUTH = """
Domain             PartOfDomain
------             ------------
internal.qr.com.au         True

internal\\_stetra_admin
"""
KERB = """
Cached Tickets: (1)

#0>	Client: _stetra_admin @ INTERNAL.QR.COM.AU
	KerbTicket Encryption Type: AES-256-CTS-HMAC-SHA1-96
	Kdc Called: ROTPRDSRV122.internal.qr.com.au
"""
USERS = """
Name             : DefaultAccount
Enabled          : False

Name             : SrvAdmin
Enabled          : True
"""
ADMINS = """
Name                                        ObjectClass PrincipalSource
----                                        ----------- ---------------
INTERNAL\\Aurizon Core System Administrators Group       ActiveDirectory
INTERNAL\\Domain Admins                      Group       ActiveDirectory
HOSTAA101\\SrvAdmin                          User                  Local
"""
RDP = """
Name                            ObjectClass PrincipalSource
----                            ----------- ---------------
"""
SERVICES = """
Name        : MSSQLSERVER
State       : Running
StartName   : internal\\_sSQLCDNCLU002

Name        : W32Time
State       : Running
StartName   : NT AUTHORITY\\LocalService
"""
LISTEN = """
LocalAddress LocalPort OwningProcess
------------ --------- -------------
::                5985             4
0.0.0.0            22          3000
"""


def _cap(fname, text):
    return {"HOSTAA101": {"folder": "X_discovery_HOSTAA101_20260101T000000Z", "fname": fname, "start": 1, "text": text}}


def _rows():
    caps = {"auth": _cap("54_auth_configs.txt", AUTH), "kerberos": _cap("56_kerberos_ticket_detail.txt", KERB),
            "users": _cap("44_local_users.txt", USERS), "admins": _cap("46_local_admins_membership.txt", ADMINS),
            "rdp": _cap("47_remote_desktop_users_membership.txt", RDP), "services": _cap("32_services_inventory.txt", SERVICES),
            "listen": _cap("20_listening_ports.txt", LISTEN)}
    return {r["attribute"]: r for r in host_settings.identity_settings(caps)}


def test_member_table_uses_column_positions():
    rows = host_settings.member_table(ADMINS)
    assert [r[1] for r in rows] == ["INTERNAL\\Aurizon Core System Administrators", "INTERNAL\\Domain Admins", "HOSTAA101\\SrvAdmin"]
    assert rows[0][2] == "Group" and rows[2][3] == "Local"


def test_identity_settings_quote_the_capture():
    got = _rows()
    assert got["identity.domain"]["value"] == "internal.qr.com.au"
    assert got["identity.kdc"]["value"] == "ROTPRDSRV122"
    assert got["identity.kerberos"]["value"] == "AES-256"
    assert got["identity.local_users"]["value"] == "SrvAdmin"
    assert got["identity.service_accounts"]["value"] == "internal\\_sSQLCDNCLU002 (MSSQLSERVER)"
    assert got["identity.service_accounts"]["excerpt"] == "StartName   : internal\\_sSQLCDNCLU002"
    assert got["admin.local_admins"]["value"] == ("INTERNAL\\Aurizon Core System Administrators, INTERNAL\\Domain Admins, "
                                                  "SrvAdmin (local)")
    assert got["admin.rdp_users"]["value"] == "No members" and got["admin.rdp_users"]["excerpt"] == ""
    assert got["admin.listeners"]["value"] == "WinRM 5985, SSH 22"


def _s(v):
    return {"value": v, "source": "c/f line 1", "excerpt": "x"}


def test_list_column_moves_shared_members_to_the_common_line(tmp_path):
    prof = {"topic": "Management & Admin Access", "key": "MGT",
            "columns": [{"label": "Administrators", "attribute": "admin.local_admins", "list": True,
                         "common_shared": "have {value} in local Administrators"}]}
    hosts = [{"host": "HOSTAA101", "role": "SQL node", "site": ""}, {"host": "HOSTBB101", "role": "Jump Host", "site": ""}]
    settings = {"HOSTAA101": {"admin.local_admins": _s("INTERNAL\\Domain Admins, SQL Admins, SrvAdmin (local)")},
                "HOSTBB101": {"admin.local_admins": _s("INTERNAL\\Domain Admins, SrvAdmin (local)")}}
    t = topic_tables.build(tmp_path, "Management & Admin Access", profile=prof, hosts=hosts, settings=settings)
    assert t["common"] == "All hosts in this table have INTERNAL\\Domain Admins and SrvAdmin (local) in local Administrators."
    cells = {r["role"]: r["cells"][0] for r in t["rows"]}
    assert cells == {"SQL node": "SQL Admins", "Jump Host": "No others"}


def test_an_empty_membership_listing_means_no_members():
    caps = {"rdp": _cap("47_remote_desktop_users_membership.txt", "\r\n")}
    got = {r["attribute"]: r for r in host_settings.identity_settings(caps)}
    assert got["admin.rdp_users"]["value"] == "No members"
