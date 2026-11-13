"""Group Policy settings come from whichever file the discovery script wrote: the verbose text or the XML."""
import sqlite3

from csa_docx import host_settings as H

XML = "Rsop ReadTime 2026-10-29\nComputerResults\nName All Removable Storage classes: Deny all access\n"
CLEAN = "Rsop ReadTime 2026-10-29\nComputerResults\nName Turn off Autoplay\n"


def _index(files):
    """A minimal discovery index: files = [(rel_path, text)]."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        create table files(file_id integer primary key, rel_path, capture_id, host, status, dup_of, archived);
        create table chunk_map(file_id, chunk_id, line_start);
        create table chunks_content(id integer primary key, c0);
        create table captures(capture_id integer primary key, folder, host, capture_utc, archived, superseded_by);
    """)
    for i, (rel, text) in enumerate(files, 1):
        con.execute("insert into files values (?,?,?,?,?,?,?)", (i, rel, i, "", "indexed", None, 0))
        con.execute("insert into chunk_map values (?,?,?)", (i, i, 1))
        con.execute("insert into chunks_content values (?,?)", (i, text))
        folder = next(x for x in rel.split("/") if x.startswith("REVELOC_discovery_"))
        host, ts = folder.split("_")[2], folder.split("_")[3]
        con.execute("insert into captures values (?,?,?,?,?,?)", (i, folder, host, ts, 0, None))
    return con


def _rows(con):
    return H.storage_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))


def test_xml_group_policy_is_read_when_there_is_no_verbose_file():
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/64_gpresult.xml", XML)])
    r = [x for x in _rows(con) if x["attribute"] == "transfer.removable"]
    assert len(r) == 1 and "Removable Storage" in r[0]["value"] and r[0]["source"].endswith("64_gpresult.xml line 3")


def test_xml_without_a_restriction_reports_not_set():
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/64_gpresult.xml", CLEAN)])
    assert [x["value"] for x in _rows(con) if x["attribute"] == "transfer.removable"] == ["Not set in applied Group Policy"]


def test_newest_capture_wins_whichever_file_it_holds():
    con = _index([("s/REVELOC_discovery_HOSTA01_20260605T010000Z/61_gpresult_verbose.txt", "Name Nothing here\n"),
                  ("s/REVELOC_discovery_HOSTA01_20261029T010000Z/64_gpresult.xml", XML)])
    r = [x for x in _rows(con) if x["attribute"] == "transfer.removable"]
    assert len(r) == 1 and "20261029" in r[0]["capture"]


def test_an_incomplete_xml_proves_nothing():
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/64_gpresult.xml", "Rsop ReadTime only\n")])
    assert not [x for x in _rows(con) if x["attribute"] == "transfer.removable"]


def test_a_capture_with_gpresult_files_but_no_setting_is_reported():
    con = _index([("s/REVELOC_discovery_HOSTB01_20261029T010000Z/64_gpresult.xml", "Rsop ReadTime only\n")])
    caps = H.read_captures(con, {"gpo": H.GPO_LIKES})
    gaps = H.capture_gaps(con, caps)
    assert len(gaps) == 1 and gaps[0].startswith("HOSTB01") and "64_gpresult.xml" in gaps[0]
    ok = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/64_gpresult.xml", XML)])
    assert H.capture_gaps(ok, H.read_captures(ok, {"gpo": H.GPO_LIKES})) == []


# ---- the newer script's files are read next to the older ones -------------------------------------------------

SHARES = """
Share             : ADMIN$
AccountName       : BUILTIN\\Administrators
AccessRight       : Full
AccessControlType : Allow

Share             : Temp
AccountName       : Everyone
AccessRight       : Full
AccessControlType : Allow
"""


def _settings(files, kinds):
    con = _index(files)
    return H.storage_settings(H.read_captures(con, kinds))


def test_share_access_names_who_may_open_a_share_beyond_the_defaults():
    r = _settings([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/42E_smb_share_access.txt", SHARES)],
                  {"share_access": "%42E_smb_share_access%"})
    assert [x["value"] for x in r if x["attribute"] == "storage.share_access"] == ["Temp: Everyone Full"]


def test_windows_backup_history_and_the_no_backup_answer():
    got = {}
    for host, text in (("HOSTA01", "Backup time: 25/04/2018 5:36 AM\nBackup location: Fixed Disk labeled C:\n"
                                   "Backup time: 29/11/2018 12:00 AM\nBackup location: Fixed Disk labeled C:\n"),
                       ("HOSTB01", "wbadmin 1.0\nERROR - No backup was found.\n")):
        r = _settings([(f"s/REVELOC_discovery_{host}_20261029T010000Z/85_windows_backup_configuration.txt", text)],
                      {"wbadmin": "%85_windows_backup_configuration%"})
        got[host] = [x["value"] for x in r if x["attribute"] == "storage.backup_windows"][0]
    assert got["HOSTA01"].startswith("2 Windows Server Backup versions, the latest on 29/11/2018")
    assert got["HOSTB01"] == "No Windows Server Backup version found"


def test_open_file_share_sessions_are_listed():
    text = "\nServerName : SRV222.internal.example\nShareName  : sysvol\nDialect    : 3.1.1\n"
    r = _settings([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/42A_smb_connections.txt", text)], {"smb_client": "%42A_smb_connections%"})
    assert [x["value"] for x in r if x["attribute"] == "transfer.smb_sessions"] == ["SRV222\\sysvol (SMB 3.1.1)"]


def test_root_certificates_come_from_either_script_version():
    stores = "=== Cert:\\LocalMachine\\Root ===\n\nSubject : CN=Aurizon Offline Root CA\nThumbprint : AA\n\n=== Cert:\\LocalMachine\\CA ===\n\nSubject : CN=Other CA\n"
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/68A_Trusted_Certificate_Stores.txt", stores),
                  ("s/REVELOC_discovery_HOSTB01_20260605T010000Z/69_certificates_localmachine_root.txt",
                   "Subject : CN=Old Style Root CA\nThumbprint : BB\n")])
    caps = H.read_captures(con, {"root": H.CERT_CAPTURES["root"]})
    assert sorted(caps["root"]) == ["HOSTA01", "HOSTB01"]
    assert "Other CA" not in caps["root"]["HOSTA01"]["text"] and "Aurizon Offline Root CA" in caps["root"]["HOSTA01"]["text"]


NEWER_ONLY = ["01_scope_validation", "05_AD_Computer_Identity", "13_dns_client_cache", "16_processes_inventory", "42A_smb_connections",
              "42B_smb_sessions", "42C_smb_open_files_metadata", "42D_net_use", "42E_smb_share_access", "66B_scheduled_task_actions",
              "66C_scheduled_task_triggers_results", "68A_Trusted_Certificate_Stores", "68B_certificate_trust_chains",
              "69A_certificate_extended", "69B_http_ssl_bindings", "69_identity_computer", "85A_backup_services_products",
              "85B_sql_backup_metadata", "85C_backup_and_unc_configuration_references", "85D_volume_shadow_copy_metadata",
              "85E_backup_destination_clues", "85_windows_backup_configuration", "88A_host_files_collection_summary",
              "88B_host_files_collection_manifest", "64_gpresult", "001_windows_hosts"]


def test_no_file_the_newer_script_writes_is_left_unread():
    wanted = " ".join(str(v) for d in (H.STORAGE_CAPTURES, H.NEWER_CAPTURES, H.CERT_CAPTURES, H.AGENT_CAPTURES) for v in d.values())
    missing = [n for n in NEWER_ONLY if n not in wanted]
    assert not missing, f"discovery files no reader asks for: {missing}"


def test_every_new_setting_has_a_label_and_a_frame_slot_that_asks_for_it():
    import json
    from pathlib import Path
    from csa_docx import topic_frames
    src = Path(H.__file__).read_text(encoding="utf-8")
    import re
    attrs = set(re.findall(r'"((?:storage|transfer|backup|cert|dns|identity|schedule|scope|capture|platform)\.[a-z_]+)"', src[src.index("def newer_settings"):src.index("CATALOGUE = Path")]))
    attrs |= {"storage.share_access", "storage.backup_windows", "transfer.smb_sessions"}
    frames = " ".join(p.read_text(encoding="utf-8") for p in (Path(topic_frames.__file__).resolve().parents[2] / "references" / "topic-frames").glob("*.json"))
    for a in sorted(attrs):
        assert a in topic_frames.LABELS, f"{a} has no label"
        assert f'"{a}"' in frames, f"no frame slot asks for {a}"


NEWER_TEXT = {
    "hosts": "# Copyright\n127.0.0.1 localhost\n10.1.1.5\tpdm.example\tpdm\n",
    "scope": "Name         FQDN               ExpectedIP       Role                          Zone          ExpectedOS\n"
             "----         ----               ----------       ----                          ----          ----------\n"
             "HOSTA01      HOSTA01.example    Resolve from DNS TETRA Log Server              OT_TETRA_LOG  Windows Server 2022\n",
    "tasks": "TaskPath         : \\\nTaskName         : Nightly copy\nRunAs            : SYSTEM\nExecute          : C:\\Tools\\copy.exe\n"
             "TaskPath         : \\Microsoft\\Windows\\X\\\nTaskName         : Stock\nRunAs            : SYSTEM\nExecute          : C:\\Windows\\x.exe\n",
}


def test_hosts_file_scope_and_scheduled_task_readers():
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/Collected_Host_Files/001_windows_hosts", NEWER_TEXT["hosts"]),
                  ("s/REVELOC_discovery_HOSTA01_20261029T010000Z/01_scope_validation.txt", NEWER_TEXT["scope"]),
                  ("s/REVELOC_discovery_HOSTA01_20261029T010000Z/66B_scheduled_task_actions.txt", NEWER_TEXT["tasks"])])
    got = {x["attribute"]: x["value"] for x in H.newer_settings(H.read_captures(con, H.NEWER_CAPTURES))}
    assert got["dns.hosts_file"] == "10.1.1.5 is pdm.example, pdm"
    assert got["scope.script_allow_list"] == "Listed in the discovery script's allow-list as TETRA Log Server (zone OT_TETRA_LOG)"
    assert got["schedule.custom_tasks"] == "Nightly copy (as SYSTEM) runs copy.exe"


def test_empty_files_are_answers_not_gaps():
    con = _index([("s/REVELOC_discovery_HOSTA01_20261029T010000Z/42B_smb_sessions.txt", "\n"),
                  ("s/REVELOC_discovery_HOSTA01_20261029T010000Z/85D_volume_shadow_copy_metadata.txt", "\n")])
    got = {x["attribute"]: x["value"] for x in H.newer_settings(H.read_captures(con, H.NEWER_CAPTURES))}
    assert got["transfer.smb_inbound_sessions"] == "None found" and got["backup.vss"] == "None found"


VERBOSE = """COMPUTER SETTINGS
    Applied Group Policy Objects
    -----------------------------
        Default Trust Store
        2019 Prod - SQL Firewall Rules

    The following GPOs were not applied because they were filtered out
    -------------------------------------------------------------------
        Microsoft Defender for Identity - Auditing for CAs
            Filtering:  Denied (Security)

        Microsoft Defender for Identity - Advanced Audit Policy for CAs
            Filtering:  Denied (Security)

    The computer is a part of the following security groups
    -------------------------------------------------------
        BUILTIN\\Administrators
USER SETTINGS
    Applied Group Policy Objects
    -----------------------------
        Default Domain Policy

    The following GPOs were not applied because they were filtered out
    -------------------------------------------------------------------
        Local Group Policy
            Filtering:  Not Applied (Empty)
"""


def test_the_older_text_reports_the_filtered_out_objects_of_the_computer_only():
    con = _index([("s/REVELOC_discovery_SQLNODE1_20260709T010000Z/61_gpresult_verbose.txt", VERBOSE)])
    rows = {x["attribute"]: x for x in H.gpo_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))}
    assert rows["gpo.applied"]["value"] == "Default Trust Store, 2019 Prod - SQL Firewall Rules"
    assert rows["gpo.not_applied"]["value"] == ("Microsoft Defender for Identity - Auditing for CAs, "
                                                "Microsoft Defender for Identity - Advanced Audit Policy for CAs")
    assert "Local Group Policy" not in rows["gpo.not_applied"]["value"]


def test_the_older_text_without_a_filtered_out_list_still_says_none_found():
    text = VERBOSE.split("    The following GPOs were not applied")[0] + "\nUSER SETTINGS\n"
    con = _index([("s/REVELOC_discovery_SQLNODE1_20260709T010000Z/61_gpresult_verbose.txt", text)])
    rows = {x["attribute"]: x for x in H.gpo_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))}
    assert rows["gpo.not_applied"]["value"] == "None found"


def test_the_older_text_gives_the_reason_each_object_was_not_applied():
    con = _index([("s/REVELOC_discovery_SQLNODE1_20260709T010000Z/61_gpresult_verbose.txt", VERBOSE)])
    rows = {x["attribute"]: x for x in H.gpo_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))}
    assert rows["gpo.not_applied_reason"]["value"] == ("Microsoft Defender for Identity - Advanced Audit Policy for CAs: Denied (Security); "
                                                       "Microsoft Defender for Identity - Auditing for CAs: Denied (Security)")
    assert "Denied (Security)" in rows["gpo.not_applied_reason"]["excerpt"] or rows["gpo.not_applied_reason"]["excerpt"]


XML_DENIED = """Rsop ReadTime 2026-10-29
ComputerResults
GPO
Name Default Domain Policy
IsValid true
FilterAllowed true
AccessDenied false
GPO
Name Microsoft Defender for Identity - Auditing for CAs
IsValid true
FilterAllowed true
AccessDenied true
GPO
Name A Policy With A Filter
IsValid true
FilterAllowed false
AccessDenied false
"""


def test_the_xml_flags_give_the_reason():
    con = _index([("s/REVELOC_discovery_HOSTX01_20261029T010000Z/64_gpresult.xml", XML_DENIED)])
    rows = {x["attribute"]: x for x in H.gpo_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))}
    assert rows["gpo.not_applied"]["value"] == "Microsoft Defender for Identity - Auditing for CAs, A Policy With A Filter"
    assert rows["gpo.not_applied_reason"]["value"] == ("A Policy With A Filter: Filter not allowed; "
                                                       "Microsoft Defender for Identity - Auditing for CAs: Denied (Security)")


def test_no_reason_row_when_nothing_was_filtered_out():
    con = _index([("s/REVELOC_discovery_HOSTX01_20261029T010000Z/64_gpresult.xml", "Rsop ReadTime 2026\nComputerResults\nGPO\nName Ok\nIsValid true\nFilterAllowed true\nAccessDenied false\n")])
    attrs = [x["attribute"] for x in H.gpo_settings(H.read_captures(con, {"gpo": H.GPO_LIKES}))]
    assert "gpo.not_applied_reason" not in attrs and "gpo.not_applied" in attrs
