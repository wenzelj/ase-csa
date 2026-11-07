"""S452: the endpoint register (csa_docx.endpoints) - one identity, zone and confidence per end."""
import csv
from pathlib import Path

from csa_docx import endpoints as ep


def _work(tmp: Path) -> Path:
    wd = tmp / "csa-work"
    (wd / "hosts").mkdir(parents=True)
    (wd / "hosts" / "hosts.csv").write_text(
        "host,in_scope,system,role,site,system_source,role_source,site_source,conflicts,fqdn,ips,ou,capture,captured_in,listening,sources,ad_site\n"
        "ROTPRDREV102,Yes,Reveloc,OT Reveloc Server,Rockhampton,register,register,register,,,ROTPRDREV102.aznops.aurizonnetwork.com.au,10.40.229.210,cap,,,listening,source,,\n"
        "MOTPRDPDM101,peer,,,,,,, ,MOTPRDPDM101.aznops.aurizonnetwork.com.au,10.45.229.194,cap,,,listening,source,,\n",
        encoding="utf-8")
    (wd / "hosts" / "zones.csv").write_text(
        "zone,kind,match,basis,reviewed\n"
        "OT Rockhampton,ot,subnet:10.40.228.0/27,fixture,yes\n"
        "OT Mackay,ot,subnet:10.45.228.0/27,fixture,yes\n"
        "Internal, zone not recorded,unknown,default:private,,yes\n"
        "Internet,internet,default:public,,yes\n",
        encoding="utf-8")
    (wd / "hosts" / "unrecorded-peers.csv").write_text(
        "peer,side,ports,mechanisms,processes,talks_to,flows,flow_ids,hint\n"
        "10.40.254.6,receives,8080,web/API,System,MOTPRDREV102,1,F014,\"Likely Dell PowerProtect Data Manager server, confirm: which system connects in on TCP 7000, whether it is the backup platform, and which data it copies out\"\n",
        encoding="utf-8")
    (wd / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,source_version,section,page_or_location,evidence_excerpt,inference_reason,confidence,gap_or_action,review_state\n"
        "E-1547,gap_lookup,\"Resolve open question in 3.7 Storage & Data Transfer (B3 SEP-STOR-03) - zone and operational role of 10.45.229.194\","
        "\"10.45.229.194 is the internal address of MOTPRDPDM101.aznops.aurizonnetwork.com.au, the Mackay Dell PowerProtect Data Manager that receives the Dell PowerProtect backup agent connection (agentService, TCP 7000) from MOTPRDREV101.\",VERIFIED,fixture,,,,,,,\n",
        encoding="utf-8")
    return wd


def _rows(wd: Path) -> dict[str, dict]:
    with (wd / "hosts" / "endpoints.csv").open(newline="", encoding="utf-8") as fh:
        return {r["end"].upper(): r for r in csv.DictReader(fh)}


def test_site_zone_and_evidence_name_and_peer_hint(tmp_path):
    wd = _work(tmp_path)
    res = ep.build(wd)
    rows = _rows(wd)

    # register host at site Rockhampton, no zones.csv row for it -> the site's OT zone
    r = rows["ROTPRDREV102"]
    assert r["zone"] == "OT Rockhampton"
    assert r["name"] == "OT Reveloc Server"
    assert r["confidence"] == "observed"
    assert "site Rockhampton in the register" in r["basis"]

    # the gap_lookup row resolves the address to the register host and gives its name
    r = rows["MOTPRDPDM101"]
    assert r["name"] == "Mackay Dell PowerProtect Data Manager"
    assert r["confidence"] == "observed"
    assert r["evidence"] == "E-1547"
    # the address itself resolves to the same row through load()
    assert ep.load(wd)["10.45.229.194"]["name"] == "Mackay Dell PowerProtect Data Manager"

    # the peer hint: likely, with the confirm part stripped
    r = rows["10.40.254.6"]
    assert r["name"] == "Dell PowerProtect Data Manager server"
    assert r["confidence"] == "likely"
    assert ep.label(r) == "likely Dell PowerProtect Data Manager server (to confirm)"

    # name came from a gap lookup or a hint, and no one has reviewed it: proposed
    assert "10.40.254.6" in res["proposed"]
    assert "MOTPRDPDM101" in res["proposed"]
    assert "ROTPRDREV102" not in res["proposed"]
    assert res["conflicts"] == []
    assert ep.label(rows["ROTPRDREV102"]) == "OT Reveloc Server"


def test_reviewed_row_survives_rebuild(tmp_path):
    wd = _work(tmp_path)
    ep.build(wd)
    with (wd / "hosts" / "endpoints.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["end"].upper() == "ROTPRDREV102":
            r["reviewed"] = "yes"
    with (wd / "hosts" / "endpoints.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ep.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    # the evidence now gives the host a different name: the reviewed row must not change
    (wd / "evidence-matrix.csv").open(encoding="utf-8").close()
    (wd / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,source_version,section,page_or_location,evidence_excerpt,inference_reason,confidence,gap_or_action,review_state\n"
        "E-1547,gap_lookup,\"Resolve open question in 3.7 Storage & Data Transfer (B3 SEP-STOR-03) - zone and operational role of ROTPRDREV102\","
        "ROTPRDREV102 is a totally different thing, VERIFIED,fixture,,,,,,,\n",
        encoding="utf-8")
    res = ep.build(wd)
    rows = _rows(wd)
    assert rows["ROTPRDREV102"]["name"] == "OT Reveloc Server"
    assert rows["ROTPRDREV102"]["zone"] == "OT Rockhampton"
    assert rows["ROTPRDREV102"]["reviewed"] == "yes"
    assert "ROTPRDREV102" not in res["proposed"]


def test_site_zone_conflict_is_kept_and_listed(tmp_path):
    wd = _work(tmp_path)
    # a zones.csv host rule says a different zone: step 3 wins, the site zone is a conflict
    (wd / "hosts" / "zones.csv").write_text(
        "zone,kind,match,basis,reviewed\n"
        "Enterprise IT,it,host:ROTPRDREV102,fixture,yes\n"
        "OT Rockhampton,ot,subnet:10.40.228.0/27,fixture,yes\n"
        "Internal, zone not recorded,unknown,default:private,,yes\n"
        "Internet,internet,default:public,,yes\n",
        encoding="utf-8")
    res = ep.build(wd)
    rows = _rows(wd)
    assert rows["ROTPRDREV102"]["zone"] == "Enterprise IT"
    assert any("Enterprise IT" in c and "OT Rockhampton" in c for c in res["conflicts"])
