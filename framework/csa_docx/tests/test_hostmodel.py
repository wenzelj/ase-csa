"""Host-centred evidence (csa_docx.hostmodel): register, facts by host, links, grouping."""
import csv
import json
import sqlite3
from pathlib import Path

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


def test_name_addresses_trusted_and_spread(tmp_path):
    con = sqlite3.connect(tmp_path / "t.sqlite")
    con.executescript("""create table files(file_id integer, rel_path text);
        create table chunk_map(chunk_id integer, file_id integer, line_start integer);
        create table chunks_content(id integer, c0 text);""")
    docs = {"design/NetSeg_design.docx": "SQLSRV001 10.1.1.5",
            "logs/fw.log": "\n".join(f"FWLOG01 10.9.9.{i} deny" for i in range(1, 5))
                           + "\nOTHERHOST1 10.1.1.5 allow\nLONEHOST9 10.2.2.2 allow"}
    for i, (rel, text) in enumerate(docs.items(), 1):
        con.execute("insert into files values (?,?)", (i, rel))
        con.execute("insert into chunk_map values (?,?,1)", (i, i))
        con.execute("insert into chunks_content values (?,?)", (i, text))
    ips = {"10.1.1.5", "10.2.2.2"} | {f"10.9.9.{i}" for i in range(1, 5)}
    out = hm.name_addresses(con, ips, {}, ["NetSeg_"])
    assert out["10.1.1.5"]["name"] == "SQLSRV001"          # trusted source wins over the log line
    assert "NetSeg_design.docx" in out["10.1.1.5"]["cite"]
    assert out["10.2.2.2"]["name"] == "LONEHOST9"          # one name on one line elsewhere still counts
    assert "10.9.9.1" not in out                           # FWLOG01 names 4 addresses: it is the log writer
    untrusted = hm.name_addresses(con, {"10.1.1.5"}, {}, [])["10.1.1.5"]
    assert untrusted["name"] is None and untrusted["ambiguous"] == ["OTHERHOST1", "SQLSRV001"]


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


def test_name_addresses_ignores_a_prose_line_that_lists_many_addresses(tmp_path):
    con = sqlite3.connect(tmp_path / "t.sqlite")
    con.executescript("""create table files(file_id integer, rel_path text);
        create table chunk_map(chunk_id integer, file_id integer, line_start integer);
        create table chunks_content(id integer, c0 text);""")
    prose = ("Resolved addresses: " + "; ".join(f"HOSTAA{i:02d} - 10.5.5.{i}" for i in range(1, 8))
             + "; mail.example.com.au - 10.6.6.1 and 10.6.6.2.")
    docs = {"doc.docx": prose, "dns/41_dns_query_tests.txt": "HOSTAA03  10.5.5.3"}
    for i, (rel, text) in enumerate(docs.items(), 1):
        con.execute("insert into files values (?,?)", (i, rel))
        con.execute("insert into chunk_map values (?,?,1)", (i, i))
        con.execute("insert into chunks_content values (?,?)", (i, text))
    out = hm.name_addresses(con, {"10.5.5.3"}, {}, [])
    assert out["10.5.5.3"]["name"] == "HOSTAA03"          # only the one-address line counts; MAIL is not offered


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
