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
