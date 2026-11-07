"""Host-centred evidence (csa_docx.hostmodel): register, facts by host, links, grouping."""
import csv
import json
import sqlite3
from pathlib import Path

from csa_docx import host_settings as hs
from csa_docx import hostmodel as hm


def _index(tmp: Path):
    con = sqlite3.connect(tmp / "discovery-index.sqlite")
    con.executescript("""
      create table captures(capture_id, folder, host, collector, capture_utc, archived, superseded_by, file_count);
      create table files(file_id, rel_path, capture_id, host, ext, size, mtime, sha1, status, reason, dup_of, source_class);
      create table rows(file_id, table_name, fmt, block_no, line_no, data);
    """)
    con.execute("insert into captures values ('c1','cap/HMA1','HMA1','t','x',0,null,1)")
    con.execute("insert into captures values ('c2','cap/HMB1','HMB1','t','x',0,null,1)")
    files = [(1, "inv.xlsx", None, None), (2, "upd.xlsx", None, None), (3, "cap/A1/21.txt", "c1", "HMA1"),
             (4, "cap/HMB1/20.txt", "c2", "HMB1"), (5, "cap/A1/11.txt", "c1", "HMA1"), (6, "cap/HMB1/11.txt", "c2", "HMB1")]
    for fid, rel, cap, host in files:
        con.execute("insert into files values (?,?,?,?,'x',0,0,'', 'indexed','',null,'other')", (fid, rel, cap, host))
    rows = [
        (1, "tcs_computers/tcs_computers", {"ComputerName": "HMA1", "IP Addresses": "10.0.0.1", "In Scope": "Yes"}),
        (1, "tcs_computers/tcs_computers", {"ComputerName": "HMB1", "IP Addresses": "10.0.0.2", "In Scope": "Yes"}),
        (1, "tcs_computers/tcs_computers", {"ComputerName": "HOST101", "In Scope": "No"}),
        (1, "tcs_computers/tcs_computers", {"ComputerName": "HOST102", "In Scope": "No"}),
        (2, "upd/groups", {"CollectionID": "BRI0001", "Target Collection": "Coll X", "UTC": "HMA1\nHOST101 / 102"}),
        (3, "established_connections_raw", {"RemoteAddress": "10.0.0.2", "RemotePort": "6010"}),
        (3, "established_connections_raw", {"RemoteAddress": "10.0.0.2", "RemotePort": "55555"}),
        (4, "listening_ports", {"LocalPort": "6010"}),
    ]
    for i, (fid, t, d) in enumerate(rows):
        con.execute("insert into rows values (?,?,'csv',0,?,?)", (fid, t, i + 2, json.dumps(d)))
    con.commit()


def test_expand_hosts():
    assert hm.expand_hosts("CONTROLLER70 / 73 / 76") == ["CONTROLLER70", "CONTROLLER73", "CONTROLLER76"]
    assert hm.expand_hosts("VPC101 - 103") == ["VPC101", "VPC102", "VPC103"]
    assert hm.expand_hosts("HMA1\nHMB1, C1") == ["HMA1", "HMB1", "C1"]


def test_build_show_group_links(tmp_path):
    _index(tmp_path)
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "roles.csv").write_text("kind,match,system,role,site,basis,reviewed\ninventory,tcs_computers/tcs_computers,,ComputerName,,test,yes\nname,^HOST,UTC,Workstation,,test,no\n", encoding="utf-8")
    (tmp_path / "evidence-matrix.csv").write_text(
        "evidence_id,question,claim,evidence_excerpt,page_or_location,status,review_state\n"
        "E-001,q,HOST101 / 102 are in Coll X,,,VERIFIED,pending\nE-002,q,system wide,,,VERIFIED,pending\n", encoding="utf-8")
    res = hm.build(tmp_path)
    assert res["hosts"] == 4 and res["evidence_without_host"] == 1
    s = hm.show(tmp_path, "host102")
    assert s["host"]["role"] == "Workstation" and "unreviewed" in s["host"]["role_source"]
    assert any(f["attribute"].endswith("Target Collection") and f["value"] == "Coll X" for f in s["facts"])
    assert not any(f["value"] == "BRI0001" and "Collection" not in f["attribute"] for f in s["facts"])
    assert [e["evidence_id"] for e in s["evidence"]] == ["E-001"]
    g = hm.group(tmp_path, ["Target Collection"], system="UTC", all_hosts=True)
    assert hm.group(tmp_path, ["Target Collection"], system="UTC") == []   # both marked In Scope: No
    assert g[0]["hosts"] == ["HOST101", "HOST102"] and g[0]["Target Collection"] == "Coll X"
    links = list(csv.DictReader((tmp_path / "hosts" / "host_links.csv").open()))
    assert [(l["src_host"], l["dst_host"], l["dst_port"]) for l in links] == [("HMA1", "HMB1", "6010")]


def test_graph_quotes_indexed_duplicate_sources_and_listener(tmp_path, monkeypatch):
    work = tmp_path / "csa-work"
    hosts = work / "hosts"
    hosts.mkdir(parents=True)
    (hosts / "hosts.csv").write_text(
        "host,in_scope,role,role_source,site,site_source,ips,capture\n"
        "SRCA01,Yes,,,,,10.0.0.1,CAP_SRCA01_20260101T000000Z\n"
        "DSTA01,Yes,,,,,10.0.0.2,CAP_DSTA01_20260101T000000Z\n", encoding="utf-8")
    (hosts / "host_links.csv").write_text(
        "src_host,dst_host,dst_port,sessions,basis,source\n"
        "SRCA01,DSTA01,6010,1,dst listens on port,old/CAP_SRCA01_20260101T000000Z/21_established_connections_raw.txt line 1\n",
        encoding="utf-8")
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,question,claim,review_state\n", encoding="utf-8")
    con = sqlite3.connect(work / "discovery-index.sqlite")
    con.executescript("""
      create table files(file_id integer, rel_path text, host text, dup_of integer);
      create table rows(file_id integer, table_name text, line_no integer, data text);
      create table chunk_map(chunk_id integer, file_id integer, line_start integer);
      create table chunks_content(id integer, c0 text);
    """)
    established = ("LocalAddress  : 10.0.0.1\nLocalPort     : 55000\n"
                   "RemoteAddress : 10.0.0.2\nRemotePort    : 6010\nOwningProcess : 42\n")
    listening = "0.0.0.0           6010           42\n"
    files = [
        (1, "new/CAP_SRCA01_20260101T000000Z/21_established_connections_raw.txt", "SRCA01", None),
        (2, "new/CAP_DSTA01_20260101T000000Z/20_listening_ports.txt", "DSTA01", None),
        (101, "copy/CAP_SRCA01_20260101T000000Z/21_established_connections_raw.txt", "SRCA01", 1),
        (102, "copy/CAP_DSTA01_20260101T000000Z/20_listening_ports.txt", "DSTA01", 2),
    ]
    con.executemany("insert into files values (?,?,?,?)", files)
    con.execute("insert into rows values (1,'established_connections_raw',1,?)",
                (json.dumps({"RemoteAddress": "10.0.0.2", "RemotePort": "6010"}),))
    con.execute("insert into rows values (2,'listening_ports',1,?)",
                (json.dumps({"LocalAddress": "0.0.0.0", "LocalPort": "6010"}),))
    con.executemany("insert into chunk_map values (?,?,1)", [(1, 1), (2, 2)])
    con.executemany("insert into chunks_content values (?,?)", [(1, established), (2, listening)])
    con.commit()
    captured = []
    def fake_script(name, workspace, *args, payload=None):
        captured.extend(payload or [])
        return {"would_write": [{"evidence_id": "E-101"} for _ in (payload or [])]}
    monkeypatch.setattr(hm, "_script", fake_script)
    result = hm.to_graph(work, tmp_path, dry_run=True)
    assert result["status"] == "DRY_RUN" and result["evidence_new"] == 1
    excerpt = captured[0]["evidence_excerpt"]
    assert "RemoteAddress : 10.0.0.2" in excerpt
    assert "RemotePort    : 6010" in excerpt
    assert "0.0.0.0           6010" in excerpt
    assert "DSTA01:6010" not in excerpt


def test_alias_addresses_uses_non_ambiguous_index_identity(tmp_path):
    con = sqlite3.connect(tmp_path / "t.sqlite")
    con.executescript("""create table files(file_id integer, rel_path text);
        create table aliases(norm text, host text, kind text, basis text, confidence text,
                             file_id integer, line_no integer, ambiguous integer);""")
    con.execute("insert into files values (1, 'dns/41_dns_query_tests.txt')")
    con.executemany("insert into aliases values (?,?,?,?,?,?,?,?)", [
        ("10.1.1.5", "SQLSRV001", "address", "paired-line", "medium", 1, 9, 0),
        ("10.2.2.2", "HOSTA", "address", "paired-line", "medium", 1, 10, 1),
        ("10.2.2.2", "HOSTB", "address", "paired-line", "medium", 1, 10, 1),
    ])
    out = hm.alias_addresses(con, {"10.1.1.5", "10.2.2.2"})
    assert out == {"10.1.1.5": {"name": "SQLSRV001", "cite": "41_dns_query_tests.txt line 9", "conflict": []}}


def test_time_source_pairs_reads_address_and_name_from_one_status_block():
    text = (
        "Stratum: 5\n"
        "ReferenceId: 0x0A28E461 (source IP:  10.40.228.97)\n"
        "Last Successful Sync Time: 08-Jun-26 4:29:39\n"
        "Source: ROTPRDSRV122.internal.qr.com.au \n"
        "\n"
        "ReferenceId: 0x00000000 (source IP:  10.1.1.1)\n"
        "Source: Local CMOS Clock\n"
    )
    assert hm.time_source_pairs(text) == [("10.40.228.97", "ROTPRDSRV122", 3)]



def test_resolver_servers_reads_preference_order_from_a_dnsclient_table():
    text = (
        "InterfaceAlias              AddressFamily ServerAddresses\r\n"
        "--------------              ------------- ---------------\r\n"
        "Ethernet 3                              2 {10.45.228.97, 10.40.228.97}\r\n"
        "Ethernet 3                             23 {}\r\n"
        "Loopback Pseudo-Interface 1            23 {fec0:0:0:ffff::1, fec0:0:0:ffff::2, fec0:0:0:ffff::3}\r\n"
    )
    rows = hm.resolver_servers(text)
    assert [ip for ip in rows[0]["servers"]] == ["10.45.228.97", "10.40.228.97"]
    assert rows[0]["interface"] == "Ethernet 3" and rows[0]["family"] == "IPv4"
    assert len(rows) == 1 and rows[0]["line"] == 2      # {} rows and the loopback defaults are left out


def test_resolver_servers_keeps_every_interface_and_marks_ipv6():
    text = (
        "InterfaceAlias AddressFamily ServerAddresses\n"
        "-------------- ------------- ---------------\n"
        "Local Area Connection* 10  2 {10.0.1.10}\n"
        "Ethernet0 2 {10.0.1.10, 10.0.2.10}\n"
        "Ethernet0 23 {fd00::53}\n"
    )
    rows = hm.resolver_servers(text)
    assert [r["servers"] for r in rows] == [["10.0.1.10"], ["10.0.1.10", "10.0.2.10"], ["fd00::53"]]
    assert [r["family"] for r in rows] == ["IPv4", "IPv4", "IPv6"]
    assert rows[0]["interface"] == "Local Area Connection* 10"


def test_resolver_servers_marks_a_list_powershell_cut_short():
    text = "InterfaceAlias AddressFamily ServerAddresses\nEthernet0 2 {10.0.1.10, 10.0.2.10, 10.0.3.10...}\n"
    rows = hm.resolver_servers(text)
    assert rows[0]["servers"] == ["10.0.1.10", "10.0.2.10", "10.0.3.10"]
    assert rows[0]["truncated"] is True


def test_resolver_servers_gives_nothing_without_a_table():
    assert hm.resolver_servers("") == []
    assert hm.resolver_servers("Ethernet0 is up\nno table here\n") == []

def test_configured_services_reads_resolver_and_time_for_one_capture():
    resolver = (
        "InterfaceAlias AddressFamily ServerAddresses\n"
        "-------------- ------------- ---------------\n"
        "Ethernet 3 2 {10.0.2.10, 10.0.1.10}\n"
        "Ethernet 4 2 {10.0.3.10}\n"
    )
    time_status = (
        "Stratum: 5\n"
        "ReferenceId: 0x0A00010A (source IP:  10.0.1.10)\n"
        "Last Successful Sync Time: 1/06/2026\n"
        "Source: SRV1.test.local \n"
    )
    folder = "TST_discovery_HOSTA01_20260505T011354Z"
    records = [(f"Data/{folder}/14_resolver.txt", 1, resolver),
               (f"Data/{folder}/03_time_status.txt", 1, time_status)]
    rows = hm.configured_services(records, {"10.0.1.10": "SRV1"})
    key = lambda r: (r["service"], int(r["preference"]))
    rows = sorted(rows, key=key)
    assert rows[0] == {"client_host": "HOSTA01", "service": "dns", "server_ip": "10.0.2.10", "server_host": "",
                       "preference": 1, "capture": folder,
                       "source": f"{folder}/14_resolver.txt line 3", "excerpt": "Ethernet 3 2 {10.0.2.10, 10.0.1.10}"}
    assert rows[1] == {"client_host": "HOSTA01", "service": "dns", "server_ip": "10.0.1.10", "server_host": "SRV1",
                       "preference": 2, "capture": folder,
                       "source": f"{folder}/14_resolver.txt line 3", "excerpt": "Ethernet 3 2 {10.0.2.10, 10.0.1.10}"}
    assert rows[2] == {"client_host": "HOSTA01", "service": "dns", "server_ip": "10.0.3.10", "server_host": "",
                       "preference": 3, "capture": folder,
                       "source": f"{folder}/14_resolver.txt line 4", "excerpt": "Ethernet 4 2 {10.0.3.10}"}
    assert rows[3] == {"client_host": "HOSTA01", "service": "time", "server_ip": "10.0.1.10", "server_host": "SRV1",
                       "preference": 1, "capture": folder,
                       "source": f"{folder}/03_time_status.txt line 4", "excerpt": "Source: SRV1.test.local"}


def test_configured_services_takes_only_the_newest_capture_of_a_host():
    new = "Data/TST_discovery_HOSTA01_20260505T011354Z"
    old = "Data/TST_discovery_HOSTA01_20260401T000000Z"
    resolver_new = "InterfaceAlias AddressFamily ServerAddresses\nEthernet 3 2 {10.0.2.10, 10.0.1.10}\n"
    resolver_old = "InterfaceAlias AddressFamily ServerAddresses\nEthernet 3 2 {10.0.7.7}\n"
    rows = hm.configured_services([(f"{new}/14_resolver.txt", 1, resolver_new),
                                   (f"{old}/14_resolver.txt", 1, resolver_old)], {})
    assert [r["server_ip"] for r in rows] == ["10.0.2.10", "10.0.1.10"]
    assert all(r["capture"] == "TST_discovery_HOSTA01_20260505T011354Z" for r in rows)


def test_overlapping_index_chunks_are_reassembled_once():
    folder = "TST_discovery_HOSTA01_20260505T011354Z"
    records = [(f"Data/{folder}/14_resolver.txt", 1,
                "heading\nEthernet 3 2 {10.0.1.10}\nrepeated context"),
               (f"Data/{folder}/14_resolver.txt", 3,
                "repeated context\nEthernet 4 2 {10.0.2.10}")]
    rows = hm.configured_services(records, {})
    assert [(r["server_ip"], r["preference"]) for r in rows] == [("10.0.1.10", 1), ("10.0.2.10", 2)]
    assert hs._join_chunks([(1, "a\nb\nc"), (3, "c\nd")]) == (1, "a\nb\nc\nd")


def test_configured_services_skips_a_capture_folder_without_a_host_name():
    resolver = "InterfaceAlias AddressFamily ServerAddresses\nEthernet 3 2 {10.0.2.10}\n"
    rows = hm.configured_services([("Data/tg_discovery_20260317T002440Z/14_resolver.txt", 1, resolver)], {})
    assert rows == []


def test_configured_services_counts_dns_order_across_two_interfaces_and_skips_repeats():
    resolver = ("InterfaceAlias AddressFamily ServerAddresses\n"
                "Ethernet 3 2 {10.0.1.10, 10.0.2.10}\n"
                "Ethernet 4 2 {10.0.1.10, 10.0.3.10}\n")
    rows = hm.configured_services([("Data/TST_discovery_HOSTA01_20260505T011354Z/14_resolver.txt", 0, resolver)], {})
    assert [(r["server_ip"], r["preference"]) for r in rows] == [
        ("10.0.1.10", 1), ("10.0.2.10", 2), ("10.0.3.10", 3)]

def test_attr_match_accepts_a_bare_column_or_a_qualified_attribute():
    assert hm._attr_match("Source", "time_status: Source")
    assert hm._attr_match("Source", "sheet1: Source")
    assert hm._attr_match("time_status: Source", "time_status: Source")
    assert not hm._attr_match("time_status: Source", "sheet1: Source")


def _roles_workspace(tmp_path, monkeypatch, rules_csv):
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    (hosts / "roles.csv").write_text(rules_csv, encoding="utf-8")
    (hosts / "hosts.csv").write_text("host,capture,listening,ips\nAPP01,cap,7000;7001,10.0.0.5\n", encoding="utf-8")
    monkeypatch.setattr(hm, "_db", lambda wd: None)
    monkeypatch.setattr(hm, "_processes", lambda wd, con: {"APP01": ({"revadmin.exe"}, "24_tasklist_services.txt")})
    monkeypatch.setattr(hm, "_rows", lambda con, where, args=(): iter(
        [("x", "APP01", "services_inventory", 1, {"Name": "GatewaySvc", "DisplayName": "Gateway", "State": "Running"})]))
    return tmp_path


RULES = ("kind,match,system,role,site,basis,reviewed\n"
         "process,RevAdmin.exe,S,App,,seen,no\n"
         "process,Missing.exe,S,Ghost,,claimed,yes\n"
         "service,GatewaySvc,S,Gateway,,seen,no\n"
         "listening,7001,S,Listener,,seen,no\n"
         "subnet,10.0.0.0/24,,,Site A,names,yes\n"
         "name,^APP,,App,,prefix,yes\n"
         "name_source,design,,,,doc,no\n")


def test_verify_roles_reports_what_each_rule_matches(tmp_path, monkeypatch):
    wd = _roles_workspace(tmp_path, monkeypatch, RULES)
    res = hm.verify_roles(wd)
    verdicts = {(r["kind"], r["match"]): r["verdict"] for r in res["results"]}
    assert verdicts == {("process", "RevAdmin.exe"): "VALID", ("process", "Missing.exe"): "NO_MATCH",
                        ("service", "GatewaySvc"): "VALID", ("listening", "7001"): "VALID",
                        ("subnet", "10.0.0.0/24"): "NEEDS_SOURCE", ("name", "^APP"): "NOT_EVIDENCE",
                        ("name_source", "design"): "NEEDS_APPROVAL"}
    assert res["status"] == "PROBLEMS" and res["problems"] == 1     # Missing.exe is reviewed=yes but matches nothing
    assert [r["hosts"] for r in res["results"] if r["match"] == "RevAdmin.exe"] == [["APP01"]]
    assert "no" in (wd / "hosts" / "roles.csv").read_text()          # a check alone never edits the file


def test_verify_roles_fix_marks_only_what_the_evidence_settles(tmp_path, monkeypatch):
    wd = _roles_workspace(tmp_path, monkeypatch, RULES)
    res = hm.verify_roles(wd, fix=True)
    rows = {(r["kind"], r["match"]): r for r in csv.DictReader((wd / "hosts" / "roles.csv").open(encoding="utf-8"))}
    assert rows[("process", "RevAdmin.exe")]["reviewed"] == "yes"
    assert "verified" in rows[("process", "RevAdmin.exe")]["basis"]
    assert rows[("process", "Missing.exe")]["reviewed"] == "no"     # claimed evidence that is not there
    assert rows[("subnet", "10.0.0.0/24")]["reviewed"] == "yes"     # not decided by captures: left as the person set it
    assert rows[("name_source", "design")]["reviewed"] == "no"
    assert res["fixed"] is True


def test_domain_controller_list_reads_host_site_and_pdc_role():
    text = ("Get list of DCs in domain 'INTERNAL' from '\\\\ROTPRDSRV122'.\n"
            "    IPTPRDSRV123.internal.qr.com.au [PDC]  [DS] Site: IPT\n"
            "    ROTPRDSRV122.internal.qr.com.au        [DS] Site: ROT\n"
            "                    AzureADKerberos [RODC]     \n"
            "The command completed successfully\n")
    assert hm.domain_controller_list(text) == [
        ("IPTPRDSRV123", "iptprdsrv123.internal.qr.com.au", "IPT", True, 1),
        ("ROTPRDSRV122", "rotprdsrv122.internal.qr.com.au", "ROT", False, 2)]


def test_fact_role_and_fact_site_take_the_documented_role_and_site_over_a_subnet_guess(tmp_path):
    """A workbook that gives a host's role, and a capture table that says where it is, beat the
    address-based site; the address rule stays visible as a conflict."""
    _index(tmp_path)
    con = sqlite3.connect(tmp_path / "discovery-index.sqlite")
    con.execute("insert into files values (7,'matrix.xlsx',null,null,'x',0,0,'','indexed','',null,'other')")
    con.execute("insert into rows values (7,'matrix/sheet2','csv',0,7,?)", (json.dumps({"System": "HMA1", "Current Role": "Jump Host"}),))
    con.execute("insert into rows values (3,'host_map','csv',0,3,?)", (json.dumps({"Host": "HMB1", "Role": "Reveloc Mackay physical server"}),))
    con.execute("insert into rows values (3,'ip_route','csv',0,4,?)", (json.dumps({"IPv4Address": "{10.9.9.9}"}),))
    con.commit()
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "roles.csv").write_text(
        "kind,match,system,role,site,basis,reviewed\n"
        "inventory,tcs_computers/tcs_computers,,ComputerName,,test,yes\n"
        "fact_role,matrix/sheet2:System:Current Role,Reveloc,,,test,yes\n"
        "fact_site,host_map:Host:Role,,,Mackay,test,yes\n"
        "subnet,10.0.0.0/24,,,Rockhampton,test,no\n", encoding="utf-8")
    hm.build(tmp_path)
    hosts = {r["host"]: r for r in csv.DictReader((tmp_path / "hosts" / "hosts.csv").open(encoding="utf-8"))}
    assert hosts["HMA1"]["role"] == "Jump Host" and hosts["HMA1"]["system"] == "Reveloc"
    assert hosts["HMA1"]["role_source"].startswith("evidence: Current Role")
    assert hosts["HMB1"]["site"] == "Mackay" and "Role" in hosts["HMB1"]["site_source"]
    assert "gives Rockhampton" in hosts["HMB1"]["conflicts"]
    res = hm.verify_roles(tmp_path)
    verdicts = {r["kind"]: r["verdict"] for r in res["results"]}
    assert verdicts["fact_role"] == "VALID" and verdicts["fact_site"] == "VALID"
