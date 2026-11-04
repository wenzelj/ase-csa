import csv
import json

from csa_docx import answer_sheet as A
from csa_docx import network_facts as N


def _work(tmp_path):
    h = tmp_path / "hosts"
    h.mkdir()
    (h / "hosts.csv").write_text("host,in_scope,ips\nROTPRDSRV122,peer,10.40.228.97\nMOTPRDSRV122,peer,10.45.228.97\n", encoding="utf-8")
    ident = "host identities confirmed 2026-10-19: "
    rows = [("ROTPRDSRV122", "Hosted In", "OT (Rockhampton)"), ("ROTPRDSRV122", "Confirmed By", "Wenzel"),
            ("ROTPRDSRV122", "Confirmed On", "2026-10-19"), ("ROTPRDSRV122", "Role", "Domain Controller"),
            ("MOTPRDSRV122", "Hosted In", "OT (Mackay)"), ("MOTPRDSRV122", "Role", "Domain Controller"),
            ("MOTPRDSRV122", "Note", "assumed same as ROTPRDSRV122 (Wenzel 01/11/2026)")]
    with (h / "host_facts.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "attribute", "value", "record", "listed_as", "source", "table", "line"])
        for host, a, v in rows:
            w.writerow([host, ident + a, v, "", "Name", "", "", ""])
    (h / "zones.csv").write_text(
        "zone,kind,match,basis,reviewed\nOT Rockhampton,ot,subnet:10.40.228.0/27,rule,yes\n"
        "OT Rockhampton,ot,subnet:10.40.228.160/27,rule,yes\nPatch,ot,host:10.40.228.98,\"inside OT 10.40.228.0/27\",yes\n", encoding="utf-8")
    (tmp_path / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,review_state\n"
        "E-1570,a,q,ROTPRDSRV122 is hosted in OT at Rockhampton.,VERIFIED,Host identities confirmed.csv,pending\n", encoding="utf-8")
    return tmp_path


def test_a_confirmed_host_is_placed_with_its_row_and_an_assumed_one_is_labelled(tmp_path):
    nf = N.NetworkFacts(_work(tmp_path))
    rot = nf.host("ROTPRDSRV122")
    assert rot["zone"] == "OT (Rockhampton)" and rot["evidence"] == "E-1570" and not rot["assumed"]
    assert "E-1570, basis stated" in nf.line("ROTPRDSRV122")
    mot = nf.host("MOTPRDSRV122")
    assert mot["assumed"] and "do not state it as confirmed" in nf.line("MOTPRDSRV122")
    assert "subnet is not recorded" in nf.line("ROTPRDSRV122")           # .97 is in neither listed /27
    assert nf.outside_listed("10.40.228.97") and not nf.outside_listed("10.40.228.7")


def test_only_confirmed_rows_are_marked_reviewed(tmp_path):
    work = _work(tmp_path)
    assert [t["evidence_id"] for t in N.promote(work)] == ["E-1570"]
    N.promote(work, apply=True)
    assert json.loads((work / "evidence-reviews.jsonl").read_text().splitlines()[-1])["state"] == "reviewed"
    assert N.promote(work) == []                                         # nothing left to promote


def test_the_register_check_finds_a_subnet_claim_that_is_arithmetically_wrong(tmp_path):
    out = N.check(_work(tmp_path))
    assert any("10.40.228.98" in x and "10.40.228.0/27" in x for x in out)
    assert any("MOTPRDSRV122" in x and "assumed" in x for x in out)


def _card():
    peer = [{"host": "ROTPRDSRV122", "known": True, "zone": "OT (Rockhampton)", "how": "confirmed by Wenzel"}]
    return {"questions": [{"id": "B1", "kind": "requirement", "text": "q"}], "frame": {"peer_identity": peer, "register_answered": ["S3"]}}


def _blk(**kw):
    b = {"facts": [], "rows": [], "bullets": [], "unknown": [], "text": "", "summary": "", "story": ""}
    b.update(kw)
    return b


def test_a_question_the_register_answers_and_a_server_put_outside_ot_are_errors():
    sheet = {"B1": _blk(unknown=["Are the Rockhampton DNS server and the Mackay DNS server inside the OT zone?",
                                 "What is the subnet of the Rockhampton DNS server?"],
                        text="The DNS servers sit in the Rockhampton and Mackay sites rather than in the OT zone.")}
    got = A.register_answer_checks(sheet, _card())
    assert sorted(f["code"] for f in got) == ["QUESTION_ANSWERED_BY_REGISTER", "ZONE_CONTRADICTED"]
    assert "subnet" not in got[0]["message"].split(":", 1)[1].lower().split("ask only")[0]   # the subnet question is allowed
    ok = {"B1": _blk(unknown=["What is the subnet of the Rockhampton DNS server?"], text="ROTPRDSRV122 is hosted in OT at Rockhampton.")}
    assert A.register_answer_checks(ok, _card()) == []
    assert A.register_answer_checks(sheet, {"questions": [], "frame": {}}) == []        # no register answer on the card: no check


def test_a_zone_fact_must_cite_the_registers_row_and_not_state_an_assumed_server():
    card = _card()
    card["frame"]["network_ids"] = ["E-1570"]
    card["frame"]["peer_identity"].append({"host": "MOTPRDSRV122", "known": True, "zone": "OT (Mackay)", "how": "assumed (same as ROT)"})
    wrong = {"B1": _blk(facts=[{"text": "ROTPRDSRV122 is hosted in OT.", "ids": ["E-031"]}])}
    assert "ZONE_FACT_NOT_BACKED" in [f["code"] for f in A.register_answer_checks(wrong, card)]
    right = {"B1": _blk(facts=[{"text": "ROTPRDSRV122 is hosted in OT at Rockhampton.", "ids": ["E-1570"]}])}
    assert A.register_answer_checks(right, card) == []
    assumed = {"B1": _blk(facts=[{"text": "MOTPRDSRV122 is hosted in OT.", "ids": ["E-1570"]}])}
    assert any("only assumed" in f["message"] for f in A.register_answer_checks(assumed, card))


def test_the_registers_answer_must_be_used_by_a_fact():
    card = _card()
    card["frame"]["network_ids"] = ["E-1570"]
    silent = {"B1": _blk(facts=[{"text": "ROTPRDSRV122 is the primary DNS server.", "ids": ["E-2951"]}])}
    assert [f["code"] for f in A.register_answer_checks(silent, card)] == ["NETWORK_ANSWER_UNUSED"]
    used = {"B1": _blk(facts=[{"text": "ROTPRDSRV122 is hosted in OT at Rockhampton.", "ids": ["E-1570"]}])}
    assert A.register_answer_checks(used, card) == []


def test_a_zone_fact_may_name_only_the_hosts_its_cited_row_is_about():
    matrix = {"E-1570": {"claim": "ROTPRDSRV122 is hosted in OT at Rockhampton."}}
    bad = {"B1": _blk(facts=[{"text": "The DNS servers ROTPRDSRV122 and MOTPRDSRV122 are hosted in OT.", "ids": ["E-1570"]}])}
    got = A.register_answer_checks(bad, {"questions": [], "frame": {}}, matrix)
    assert [f["code"] for f in got] == ["ZONE_FACT_NOT_BACKED"] and "MOTPRDSRV122" in got[0]["message"]
    ok = {"B1": _blk(facts=[{"text": "ROTPRDSRV122 is hosted in OT.", "ids": ["E-1570"]}])}
    assert A.register_answer_checks(ok, {"questions": [], "frame": {}}, matrix) == []


def test_a_host_rule_keyed_by_address_and_a_host_named_only_by_an_evidence_row_find_their_zone(tmp_path):
    from csa_docx import zones as Z
    work = _work(tmp_path)
    (work / "hosts" / "zones.csv").write_text("zone,kind,match,basis,reviewed\nPatch service,ot,host:10.40.228.98,rule,yes\n", encoding="utf-8")
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,review_state\n"
        "E-1,a,q,ROTPRDCCM111 is the OT Config Manager at 10.40.228.98 and a further address 10.89.163.73.,VERIFIED,s,reviewed\n", encoding="utf-8")
    z = Z.for_project(work)
    assert z.of_ip("10.40.228.98")["zone"] == "Patch service"
    assert z.of("ROTPRDCCM111")["zone"] == "Patch service"
