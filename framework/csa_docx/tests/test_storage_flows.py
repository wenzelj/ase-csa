"""Zones, data flows, storage and transfer settings, the analysis frame and the two 3.7 tables."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import answer_sheet as A, flows, host_settings, topic_frames, topic_tables as tt, zones  # noqa: E402


def test_zone_rules_host_beats_subnet_and_defaults_apply():
    z = zones.Zones([{"zone": "OT A", "kind": "ot", "match": "subnet:10.1.0.0/16", "reviewed": "no"},
                     {"zone": "OT A small", "kind": "ot", "match": "subnet:10.1.2.0/24", "reviewed": "no"},
                     {"zone": "IT DC", "kind": "it", "match": "host:DCSRV001", "reviewed": "no"}],
                    {"APPSRV001": ["10.1.2.5"], "DCSRV001": ["10.1.9.9"]})
    assert z.of("APPSRV001")["zone"] == "OT A small"           # longest subnet
    assert z.of("DCSRV001")["zone"] == "IT DC"                 # host rule wins over its subnet
    assert z.of("10.9.9.9")["kind"] == "unknown"               # private, no rule
    assert z.of("34.120.2.104")["kind"] == "internet"


MAPPING = {"OTDBSRV001": {"folder": "X_discovery_OTDBSRV001_20260101T000000Z", "fname": "23_process_connection_mapping.txt", "start": 1,
                       "text": "10.1.2.5:7000 -> 10.9.9.9:51000 PID=9 PROC=agentService\n"
                               "10.1.2.5:51515 -> 10.9.1.1:445 PID=4 PROC=System\n"
                               "127.0.0.1:1 -> 127.0.0.1:2 PID=1 PROC=x\n"}}


def test_direction_comes_from_the_listener_and_flows_are_written_from_the_initiator():
    rows = flows.observed(MAPPING, {"OTDBSRV001": {"7000"}}, {"10.9.9.9": "BKPSRV001"})
    by_port = {r["port"]: r for r in rows}
    assert by_port["7000"]["src"] == "BKPSRV001" and by_port["7000"]["dst"] == "OTDBSRV001"     # pulled in
    assert by_port["7000"]["dst_process"] == "agentService"
    assert by_port["445"]["src"] == "OTDBSRV001" and by_port["445"]["dst"] == "10.9.1.1"        # opened by the host
    assert all(r["sources"] and "line" in r["sources"][0] for r in rows) and len(rows) == 2  # loopback dropped


def test_declared_flows_are_read_and_matched():
    text = ("CSID        : R1\nSource      : APPSRV001\nDestination : OTDBSRV001, OTDBSRV002\nFlow        : App to SQL\n"
            "Ports       : 1433 expected\n\nCSID        : RB2\nSource      : BRDSRV001\nDestination : Internet / Azure\n"
            "Flow        : PN data out\nPorts       : 443 expected\n")
    d = {x["id"]: x for x in flows.declared(text)}
    assert d["R1"]["dst_hosts"] == {"OTDBSRV001", "OTDBSRV002"} and "1433" in d["R1"]["port_list"]
    assert flows._matches(d["R1"], {"src": "APPSRV001", "dst": "OTDBSRV002", "port": "1433"})
    assert not flows._matches(d["R1"], {"src": "APPSRV001", "dst": "OTDBSRV002", "port": "445"})
    assert flows._matches(d["RB2"], {"src": "BRDSRV001", "dst": "10.86.160.4", "port": "443"})   # end named by description
    assert not flows._matches(d["RB2"], {"src": "BRDSRV001", "dst": "10.86.160.4", "port": "80"})


def test_declared_flows_match_named_instance_and_candidate_vendor_ports():
    text = ("CSID        : R1\nSource      : APPSRV001\nDestination : OTDBSRV001\nFlow        : App to SQL\n"
            "Ports       : 1433 expected, confirm\n\nCSID        : R2\nSource      : APPSRV001\nDestination : LOGSRV001\n"
            "Flow        : App to log API\nPorts       : 80/443/8080/8443 candidates, confirm\n\n"
            "CSID        : R3\nSource      : Other app\nDestination : OTDBSRV001\nFlow        : x\nPorts       : 1433 expected\n")
    d = {x["id"]: x for x in flows.declared(text)}
    db = {"src": "APPSRV001", "dst": "OTDBSRV001", "port": "56420"}
    assert flows._matches(d["R1"], db, "database")                        # named SQL instance port
    assert not flows._matches(d["R1"], db, "database replication")
    assert not flows._matches(d["R1"], {**db, "port": "445"}, "file share")
    api = {"src": "APPSRV001", "dst": "LOGSRV001", "port": "42380"}
    assert flows._matches(d["R2"], api, "other")                          # vendor port, declared ports only candidates
    assert not flows._matches(d["R2"], {**api, "port": "445"}, "file share")
    assert not flows._matches(d["R3"], {"src": "X", "dst": "OTDBSRV001", "port": "56420"}, "database")  # unnamed end: port must match
    assert flows._matches(d["R3"], {"src": "X", "dst": "OTDBSRV001", "port": "1433"}, "database")
    assert not flows._matches(d["R3"], {"src": "X", "dst": "OTDBSRV001", "port": "1433"}, "patch management")


def _row(src, dst, port, mech="file share", status="observed", cz="no"):
    return {"src": src, "dst": dst, "port": port, "mechanism": mech, "status": status, "cross_zone": cz, "src_zone": "OT",
            "dst_zone": "OT", "sources": "c: 23_process_connection_mapping.txt line 1", "excerpt": "x", "signature": "",
            "confirm": "", "declared_id": "", "declared_flow": "", "src_process": "System", "dst_process": ""}


def test_groups_merge_sources_to_one_end_and_ends_of_one_source():
    gs = flows.groups([_row("A1", "PEER", "445"), _row("A2", "PEER", "445"),
                       _row("WEB1", "8.8.8.8", "443", "web/API", cz="yes"), _row("WEB1", "8.8.4.4", "443", "web/API", cz="yes")])
    assert {tuple(g["srcs"]) for g in gs} == {("A1", "A2"), ("WEB1",)}
    assert [g for g in gs if g["srcs"] == ["WEB1"]][0]["dsts"] == ["8.8.8.8", "8.8.4.4"]
    assert gs[0]["cross_zone"] == "yes"                        # cross-zone groups come first


def test_groups_keep_different_declared_flows_apart():
    a = {**_row("APP1", "DB1", "56420", "database"), "declared_id": "R1"}
    b = {**_row("CLIENT1", "DB1", "56420", "database"), "declared_id": "M1"}
    gs = flows.groups([a, b])
    assert sorted(g["srcs"][0] for g in gs) == ["APP1", "CLIENT1"] and len(gs) == 2


def _cap(fname, text, host="H1"):
    return {host: {"folder": f"X_discovery_{host}_20260101T000000Z", "fname": fname, "start": 1, "text": text}}


def test_storage_and_transfer_settings_keep_quotes_and_record_absences():
    caps = {"shares": _cap("42_local_shares.txt", "Name : ADMIN$\nPath : C:\\WINDOWS\nName : CAcom\nPath : C:\\\n"),
            "software": _cap("67_installed_software.txt", "DisplayName : WinSCP 5.9.5\nDisplayName : Notepad++\n"),
            "gpo": _cap("61_gpresult_verbose.txt", "Computer Settings\n  Password policy\n"),
            "sql": _cap("52_reveloc_sql_cluster_evidence.txt", "MSSQL$S01        SQL Server (S01)              Running Automatic\nAPP_AG\n")}
    got = {r["attribute"]: r for r in host_settings.storage_settings(caps)}
    assert got["storage.shares"]["value"] == "CAcom (C:\\)" and got["storage.shares"]["excerpt"] == "Name : CAcom"
    assert got["transfer.tools"]["value"] == "WinSCP 5.9.5"
    assert got["transfer.removable"]["value"] == "Not set in applied Group Policy" and got["transfer.removable"]["excerpt"] == ""
    assert got["storage.database"]["value"] == "SQL Server (S01); availability group APP_AG"


def test_frame_card_asks_every_slot_and_flags_likely_notes_as_background():
    res = {"status": "OK", "key": "STOR", "slots": [
        {"id": "S1", "question": "Where is data held?", "requirements": ["SEP-STOR-01"], "cross_zone": False,
         "findings": [{"text": "Database service on DB1: SQL Server (S01)", "ids": ["E-901"], "hint": "", "tokens": ["DB1"]}]},
        {"id": "S3", "question": "Which flows cross zones?", "requirements": ["SEP-STOR-03"], "cross_zone": True,
         "findings": [{"text": "Backup agent: BKP1 opens connections to DB1", "ids": ["E-902"], "cross_zone": "yes",
                       "hint": "Likely: a backup agent. Confirm which data it copies.", "tokens": ["BKP1", "DB1"],
                       "direction": "pull_into_ot"}]},
        {"id": "S9", "question": "Retention?", "requirements": [], "cross_zone": False, "findings": []}]}
    text = "\n".join(topic_frames.card_lines(res))
    assert "## F1 Analysis frame" in text and "### S9 Retention?" in text and "nothing in the captures" in text
    assert "(E-902)" in text and "Likely:" in text and "not evidence" in text
    assert topic_frames.coverage_targets(res) == [{"text": "Backup agent: BKP1 opens connections to DB1", "tokens": ["BKP1", "DB1"],
                                                   "ids": ["E-902"], "direction": "pull_into_ot"}]
    assert topic_frames.all_ids(res) == {"E-901", "E-902"}


def _card_with_frame():
    return {"key": "STOR", "ratings": ["Met", "Not Met"], "evidence": {}, "keep": [],
            "questions": [{"id": "B1", "kind": "requirement", "req_id": "SEP-STOR-01", "part": 0, "text": "q"}],
            "frame": {"slots": ["S1", "S3"], "ids": ["E-901", "E-902"],
                      "coverage": [{"text": "Backup agent", "tokens": ["BKP1"]}]}}


def test_frame_block_is_required_and_parsed():
    card = _card_with_frame()
    base = "## B1 SEP-STOR-01\nFacts:\n- DB1 holds the data. (E-901) {observed; DB1}\nRating: Not Met\nRating reason: r\n"
    res = A.validate(A.parse(base), card)
    assert "FRAME_UNCOVERED" in {f["code"] for f in res["findings"] if f["level"] == "ERROR"}
    sheet = A.parse(base + "\n## F1 Analysis frame\n- S1: B1\n- S3: Unknown: whether BKP1 copies the database\n")
    assert sheet["F1"]["frame"] == {"S1": "B1", "S3": "Unknown: whether BKP1 copies the database"}
    assert sheet["F1"]["unknown"] == ["whether BKP1 copies the database"]
    res = A.validate(sheet, card)
    codes = {f["code"]: f["level"] for f in res["findings"]}
    assert "FRAME_UNCOVERED" not in codes and "EXTRA_BLOCK" not in codes
    assert codes.get("FLOW_NOT_COVERED") == "WARN"             # BKP1 is named nowhere in the answer
    sheet = A.parse(base.replace("DB1 holds the data.", "DB1 holds the data and BKP1 connects in.") +
                    "\n## F1 Analysis frame\n- S1: B1\n- S3: B1\n")
    assert "FLOW_NOT_COVERED" not in {f["code"] for f in A.validate(sheet, card)["findings"]}


def test_frame_slot_pointing_at_a_missing_block_is_refused():
    card = _card_with_frame()
    sheet = A.parse("## B1 SEP-STOR-01\nFacts:\n- DB1 holds the data. (E-901) {observed; DB1}\nRating: Not Met\nRating reason: r\n"
                    "\n## F1 Analysis frame\n- S1: B7\n- S3: B1\n")
    msgs = [f["message"] for f in A.validate(sheet, card)["findings"] if f["code"] == "FRAME_UNCOVERED"]
    assert msgs and "S1" in msgs[0]


DOC = ('<w:document xmlns:w="w"><w:body>'
       '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Storage &amp; Data Transfer</w:t></w:r></w:p>'
       '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Discovery Information</w:t></w:r></w:p>'
       '<w:tbl><w:tblPr><w:tblStyle w:val="CSATable"/></w:tblPr><w:tblGrid><w:gridCol w:w="9638"/></w:tblGrid>'
       '<w:tr><w:tc><w:p><w:pPr><w:pStyle w:val="TableHeader"/></w:pPr><w:r><w:t>Aspect</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
       '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Drawbridge Impact</w:t></w:r></w:p>'
       '</w:body></w:document>')


def test_two_tables_are_placed_and_replaced_together():
    t1 = {"status": "OK", "columns": ["Role", "Hosts", "Shares"], "common": "All hosts in this table run SQL.", "markers": [],
          "rows": [{"role": "SQL node", "first": True, "hosts": ["DB1"], "cells": ["CAcom (C:\\)"]}]}
    t2 = {"status": "OK", "columns": ["Mechanism", "From (opens the connection)", "To", "Port", "Flow map"],
          "common": "From is the side that opens the connection.", "markers": [],
          "rows": [{"role": "Backup agent", "first": True, "hosts": ["BKP1 (IT)"], "cells": ["DB1 (OT, crosses zones)", "7000", "Seen"]}]}
    once, what = tt.place_xml(DOC, [t1, t2], "Storage & Data Transfer")
    assert what == "inserted" and once.count(f'w:tblCaption w:val="{tt.CAPTION}"') == 2
    assert once.index("CAcom") < once.index("BKP1") < once.index(">Aspect<")
    twice, what2 = tt.place_xml(once, [t1, t2], "Storage & Data Transfer")
    assert what2 == "replaced" and twice == once
    gone, what3 = tt.place_xml(once, [], "Storage & Data Transfer")
    assert what3 == "removed" and gone == DOC


def test_requirement_table_markdown_names_the_requirement():
    table = {"status": "OK", "requirement": "SEP-STOR-01", "evidence_title": "Storage discovery evidence",
             "columns": ["Role", "Hosts", "Database"], "common": "", "markers": [],
             "rows": [{"role": "SQL node", "first": True, "hosts": ["DB1"], "cells": ["SQL Server"]}]}
    text = tt.markdown([table])
    assert text.startswith("### SEP-STOR-01 — Storage discovery evidence")
