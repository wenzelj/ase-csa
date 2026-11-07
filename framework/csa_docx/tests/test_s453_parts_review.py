"""S453: the parts review proposes identities, flags confusable names and shows a part by its display name."""
import csv
import json

from csa_docx import endpoints as ep
from csa_docx import parts as P


def _work(tmp) -> None:
    wd = tmp / "csa-work"
    (wd / "hosts").mkdir(parents=True)
    (wd / "hosts" / "hosts.csv").write_text(
        "host,in_scope,system,role,site,system_source,role_source,site_source,conflicts,fqdn,ips,ou,capture,captured_in,listening,sources,ad_site\n"
        "ROTPRDLOG102,Yes,Reveloc,TETRA log server,Rockhampton,register,register,register,,,ROTPRDLOG102.fqdn,10.1.1.1,cap,,,listening,source,,\n"
        "MOTPRDLOG103,Yes,Reveloc,OT TETRA Log Server, DAAM Node Controller,Mackay,register,register,register,,,MOTPRDLOG103.fqdn,10.2.2.2,cap,,,listening,source,,\n",
        encoding="utf-8")
    (wd / "hosts" / "unrecorded-peers.csv").write_text(
        "peer,side,ports,mechanisms,processes,talks_to,flows,flow_ids,hint\n"
        "10.40.254.6,receives,8080,web/API,System,MOTPRDREV102,1,F014,\"Likely Dell PowerProtect Data Manager server, confirm: which system connects in\"\n",
        encoding="utf-8")


def _wd(tmp):
    _work(tmp)
    wd = tmp / "csa-work"
    P.build(wd)
    return wd


def test_display_name_prefers_display_else_first_role():
    assert P.display_name({"name": "A, B", "display": "The thing"}) == "The thing"
    assert P.display_name({"name": "OT TETRA Log Server, DAAM Node Controller"}) == "OT TETRA Log Server"
    assert P.display_name({"name": "TETRA log server"}) == "TETRA log server"
    # a blank display falls through
    assert P.display_name({"name": "A, B", "display": "  "}) == "A"


def test_confusable_pairs():
    doc = {"parts": [{"name": "TETRA log server"},
                     {"name": "OT TETRA Log Server, DAAM Node Controller"},
                     {"name": "Radio"}]}
    assert P.confusable(doc) == [("TETRA log server", "OT TETRA Log Server")]
    # a display name removes the pair
    doc["parts"][1]["display"] = "DAAM Node Controller"
    assert P.confusable(doc) == []


def test_display_survives_assemble(tmp_path):
    wd = _wd(tmp_path)
    doc = P.load(wd)
    for p in doc["parts"]:
        if p["name"].startswith("OT TETRA Log Server"):
            p["display"] = "DAAM Node Controller"
    P.path(wd).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    again = P.assemble(wd)
    p = [x for x in again["parts"] if x["name"] == "OT TETRA Log Server"][0]
    assert p.get("display") == "DAAM Node Controller"
    assert P.confusable(again) == []


def test_show_prints_both_sections_when_there_is_something(tmp_path):
    wd = _wd(tmp_path)
    ep.build(wd)                                  # adds the proposed 10.40.254.6 row to hosts/endpoints.csv
    doc = P.load(wd)
    # the fixture's second part carries an alias equal to its display name, so take two plainly separate parts
    doc["parts"] = [
        {"name": "TETRA log server", "kind": "system", "side": "ot", "zones": ["OT Rockhampton"],
         "members": ["ROTPRDLOG102"], "basis": "host register"},
        {"name": "OT TETRA Log Server, DAAM Node Controller", "kind": "system", "side": "ot",
         "zones": ["OT Mackay"], "members": ["MOTPRDLOG103"], "basis": "host register"}]
    out = P.show(doc, P._proposed(wd))
    assert "Identities to confirm (hosts/endpoints.csv):" in out
    assert ('- 10.40.254.6: likely Dell PowerProtect Data Manager server (to confirm) []  '
            '(set reviewed=yes in hosts/endpoints.csv to accept, or correct the name)') in out
    assert "Names a reader could confuse:" in out
    assert ('"TETRA log server" and "OT TETRA Log Server": '
            'set "display" on one of them in parts.json') in out


def test_show_prints_neither_when_there_is_nothing(tmp_path):
    wd = _wd(tmp_path)
    ep.build(wd)
    doc = P.load(wd)
    for p in doc["parts"]:
        if p["name"].startswith("OT TETRA Log Server"):
            p["display"] = "DAAM Node Controller"
    with (wd / "hosts" / "endpoints.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["end"].upper() == "10.40.254.6":
            r["reviewed"] = "yes"
    with (wd / "hosts" / "endpoints.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ep.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    out = P.show(doc, P._proposed(wd))
    assert "Identities to confirm" not in out
    assert "Names a reader could confuse" not in out


def test_show_omits_the_sections_by_default(tmp_path):
    # no proposed identities and a display name on the two-role part: nothing to show
    wd = _wd(tmp_path)
    doc = P.load(wd)
    for p in doc["parts"]:
        if p["name"].startswith("OT TETRA Log Server"):
            p["display"] = "DAAM Node Controller"
    out = P.show(doc)
    assert "Identities to confirm" not in out
    assert "Names a reader could confuse" not in out
