"""Answer quality against the topic frame (S341-S355): the faults the 3.7 Storage & Data Transfer answer had are refused
in the draft lane, and a good answer passes. Built from a small throw-away workspace, no project data."""
import csv
import json

from csa_docx import answer_sheet as A
from csa_docx import section_card as SC
from csa_docx import topic_frames as TF

FIELDS = ["flow_id", "status", "mechanism", "data", "src", "src_role", "src_zone", "src_zone_kind", "src_process", "dst",
          "dst_role", "dst_zone", "dst_zone_kind", "dst_process", "port", "cross_zone", "zones_reviewed", "declared_id",
          "declared_flow", "signature", "confirm", "connections", "sources", "excerpt"]
FRAME = {"topic": "Storage & Data Transfer", "key": "STOR", "strict": True, "headings": ["Storage & Data Transfer"], "slots": [
    {"id": "S1", "question": "Where is the data held?", "requirements": ["SEP-STOR-01"],
     "source": {"settings": ["storage.database"]}, "baseline_values": ["None found"]},
    {"id": "S3", "question": "Which flows cross the OT boundary?", "requirements": ["SEP-STOR-02", "SEP-STOR-03"],
     "source": {"flows": {"data": True}},
     "bind": {"ot_push": ["SEP-STOR-03"], "pull_into_ot": ["SEP-STOR-03"], "into_ot": ["SEP-STOR-02"], "inside_ot": ["SEP-STOR-01"]}},
    {"id": "S9", "question": "How long is the data held?", "requirements": ["SEP-STOR-01"], "source": {}}]}


def _flow(fid, mech, src, dst, port, proc=""):
    return {**{k: "" for k in FIELDS}, "flow_id": fid, "status": "observed", "mechanism": mech, "data": "yes", "src": src,
            "dst": dst, "dst_process": proc, "port": port, "cross_zone": "unknown", "connections": "1",
            "sources": f"CAP: 23_process_connection_mapping.txt line {fid[1:]}", "excerpt": f"{src} -> {dst}"}


def _workspace(tmp_path):
    h = tmp_path / "csa-work" / "hosts"
    h.mkdir(parents=True)
    with (h / "flows.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader()
        w.writerows([_flow("F1", "backup agent", "PDM1", "SQL1", "7000", "agentService"),
                     _flow("F2", "database", "APP1", "SQL1", "1433", "sqlservr"),
                     _flow("F3", "web/API", "RADIO1", "8.8.8.8", "443")])
    with (h / "host_settings.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["host", "area", "attribute", "value", "capture", "source", "excerpt"])
        w.writerow(["SQL1", "storage", "storage.database", "SQL Server (S01)", "C", "C/52.txt line 1", "S01"])
        w.writerow(["RADIO1", "storage", "storage.database", "SQL Server (RADIO)", "C", "C/52.txt line 1", "RADIO"])
    (h / "hosts.csv").write_text("host,in_scope,system,role,site,ips,capture\nSQL1,yes,S,SQL node,Rock,10.1.0.11,X\n"
                                 "APP1,yes,S,App server,Rock,10.1.0.21,X\nRADIO1,yes,S,OT Radio Manager,IPT,10.9.0.7,X\nPDM1,peer,,,,,\n",
                                 encoding="utf-8")
    (h / "zones.csv").write_text("zone,kind,match,basis,reviewed\nOT Rock,ot,subnet:10.1.0.0/24,f,yes\nIT Core,it,subnet:10.9.0.0/24,f,yes\n"
                                 "\"Internal, zone not recorded\",unknown,default:private,,yes\nInternet,internet,default:public,,yes\n",
                                 encoding="utf-8")
    return tmp_path


def _card(tmp_path, monkeypatch):
    d = tmp_path / "frames"; d.mkdir()
    (d / "stor.json").write_text(json.dumps(FRAME), encoding="utf-8")
    monkeypatch.setattr(TF, "FRAMES", d)
    fr = TF.build(_workspace(tmp_path), "Storage & Data Transfer", "STOR", evidence=False)
    n = 0
    for s in fr["slots"]:
        for f in s["findings"]:
            n += 1
            f["ids"] = [f"E-{100 + n}"]
    qs = [{"id": "B1", "kind": "requirement", "req_id": "SEP-STOR-01", "part": 0, "text": "q"},
          {"id": "B3", "kind": "requirement", "req_id": "SEP-STOR-03", "part": 0, "text": "q"}]
    owed = SC.must_address_by_question(qs, fr)
    frame = {"slots": [s["id"] for s in fr["slots"]], "ids": sorted(TF.all_ids(fr)), "coverage": TF.coverage_targets(fr),
             "must_address": owed, "context_ids": TF.context_ids(fr), "zone_conflicts": fr["zone_conflicts"],
             "strict": fr["strict"]}
    return {"key": "STOR", "ratings": ["Met", "Partially Met", "Not Met"], "evidence": {}, "keep": [], "questions": qs,
            "frame": frame}, fr


def _ids(fr, needle):
    return next(f["ids"][0] for s in fr["slots"] for f in s["findings"] if needle in f["text"])


def _sheet(b1, b3, r3="Not Met"):
    return (f"## B1 SEP-STOR-01\nFacts:\n{b1}\nRating: Partially Met\nRating reason: r\n\n"
            f"## B3 SEP-STOR-03\nFacts:\n{b3}\nRating: {r3}\nRating reason: r\n")


def _codes(sheet, card):
    return {(f["code"], f["level"]) for f in A.validate(A.parse(sheet), card, draft=True)["findings"]}


def test_the_frame_sorts_flows_by_the_ot_boundary(tmp_path, monkeypatch):
    card, fr = _card(tmp_path, monkeypatch)
    d = {f["text"].split("]")[0] + "]": f["direction"] for s in fr["slots"] for f in s["findings"] if f.get("direction")}
    assert d["[Pull out of OT]"] == "pull_into_ot" and d["[Outside OT, context only]"] == "not_ot"
    assert [c["host"] for c in fr["zone_conflicts"]] == ["RADIO1"]
    owed = card["frame"]["must_address"]
    assert any("PDM1" in x["text"] for x in owed["B3"]) and not any("8.8.8.8" in x["text"] for x in owed["B3"])
    assert any(x["empty"] for x in owed["B1"])                                   # S9 asks for an Unknown


def test_a_good_answer_passes(tmp_path, monkeypatch):
    card, fr = _card(tmp_path, monkeypatch)
    b1 = (f"- SQL1 holds the S01 SQL Server database in OT. ({_ids(fr, 'SQL1: SQL Server')})\n"
          f"- RADIO1, an IT-hosted OT Radio Manager, holds the RADIO database in IT. ({_ids(fr, 'RADIO1: SQL Server')})\n"
          f"- APP1 opens database connections to SQL1 inside OT. ({_ids(fr, 'APP1')})\n"
          "Unknown: how long the S01 data is held")
    b3 = f"- PDM1, whose zone is not recorded, opens backup agent connections to SQL1 and takes its data out. ({_ids(fr, 'PDM1')})"
    errors = {c for c, lvl in _codes(_sheet(b1, b3), card) if lvl == "ERROR"}
    assert not errors & {"SLOT_NOT_ANSWERED", "FLOW_NOT_COVERED", "ZONE_CONTRADICTED", "FRAME_UNCOVERED"}, errors


def test_the_3_7_faults_are_refused(tmp_path, monkeypatch):
    card, fr = _card(tmp_path, monkeypatch)
    sqlx, radio, app, pull, web = (_ids(fr, "SQL1: SQL Server"), _ids(fr, "RADIO1: SQL Server"), _ids(fr, "APP1"),
                                   _ids(fr, "PDM1"), _ids(fr, "8.8.8.8"))
    b1_bad = (f"- The system holds its data in OT-resident SQL Server instances on SQL1 and in the RADIO database on the "
              f"OT Radio Manager. ({sqlx}, {radio})\n- APP1 opens database connections to SQL1. ({app})\nUnknown: retention")
    b3_bad = f"- RADIO1 opens outbound connections to the internet, so OT pushes data out. ({web})"
    codes = _codes(_sheet(b1_bad, b3_bad, r3="Met"), card)
    assert ("ZONE_CONTRADICTED", "ERROR") in codes            # the IT host called OT-resident
    assert ("SLOT_NOT_ANSWERED", "ERROR") in codes            # the PDM1 pull is missing from SEP-STOR-03
    assert ("FLOW_NOT_COVERED", "ERROR") in codes             # and covered nowhere
    assert ("NOT_OT_FLOW_IN_REQUIREMENT", "WARN") in codes    # the IT to internet flow used as an OT push
    assert ("RATING_ABOVE_FLOOR", "WARN") in codes            # Met although OT data is pulled out
