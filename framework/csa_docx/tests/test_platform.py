"""Platform and patch facts: OS, support end, hardware, latest update (three date formats), update source, client."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings  # noqa: E402

SUMMARY = """
Caption        : Microsoft Windows Server 2016 Standard
Version        : 10.0.14393
BuildNumber    : 14393

Manufacturer        : Dell Inc.
Model               : PowerEdge R730
"""
WU = """
UpdateServiceUrlAlternate                              : http://localhost:8005
WUServer                                               : https://IPTPRDCCM202.internal.qr.com.au:8531
NoAutoUpdate               : 1
"""
MECM = """
Status   Name               DisplayName
------   ----               -----------
Running  ccmexec            SMS Agent Host

ClientVersion           : 5.00.9141.1030
"""
LIFE = [{"match": "Windows Server 2016", "extended_end": "12/01/2027"}]


def _cap(fname, text):
    return {"HOSTAA101": {"folder": "X_discovery_HOSTAA101_20260101T000000Z", "fname": fname, "start": 1, "text": text}}


def test_platform_and_patch_settings():
    caps = {"summary": _cap("00_host_summary.txt", SUMMARY), "wu": _cap("70_windows_update_config.txt", WU),
            "mecm": _cap("72_sccm_mecm_check.txt", MECM),
            "hotfix": _cap("71_installed_hotfixes.txt", "HOSTAA101  Update  KB5087061  SYSTEM  30/05/2026 12:00:00 AM\n"
                                                         "HOSTAA101  Update  KB4464455           29/10/2018 12:00:00 AM\n")}
    got = {r["attribute"]: r for r in host_settings.platform_settings(caps, LIFE)}
    assert got["platform.os"]["value"] == "Windows Server 2016 Standard (build 14393)"
    assert got["platform.support"]["value"] == "Extended support to 12/01/2027"
    assert got["platform.hardware"]["value"] == "Physical, Dell PowerEdge R730"
    assert got["patch.latest"]["value"] == "KB5087061 on 30/05/2026"
    assert got["patch.source"]["value"] == "WSUS on IPTPRDCCM202 port 8531"
    assert got["patch.auto"]["value"] == "Automatic Updates off"
    assert got["patch.client"]["value"] == "MECM client 5.00.9141.1030"


def test_hotfix_dates_read_month_first_and_named_months():
    us = "H  Update  KB1000001  S  5/22/2026 0:00\nH  Update  KB1000002  S  4/1/2026 0:00\n"
    assert max(d for _, _, d in host_settings.hotfix_dates(us)) == (2026, 5, 22)
    named = "H  Security Update  KB1000003  S  03-Jun-26 0:00:00\nH  Update  KB1000004  S  26-May-26 0:00:00\n"
    assert max(host_settings.hotfix_dates(named), key=lambda x: x[2])[1] == "KB1000003"
    au = "H  Update  KB1000005  S  4/1/2026\nH  Update  KB1000006  S  3/2/2026\n"
    assert max(host_settings.hotfix_dates(au), key=lambda x: x[2])[2] == (2026, 2, 3)   # day first: 3 February
