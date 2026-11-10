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


# --- confirmed connected devices label observed peers (S546) --------------------------------------

_DEVICES = ("device_id,name,device_type,role,owner,site_zone,relationship,classification,identification_state,"
            "provenance,reviewer,recorded,active,revision\n")
_ALIASES = "device_id,address,normalized,address_type,first_seen,last_seen,source,active\n"
_PEERS = ("address,device_id,device_name,device_type,classification,identification_state,revision,provenance,"
          "alias_source,basis,kind,seen_from,directions,ports,processes,sessions,evidence_ids\n")


def _with_devices(wd: Path, devices: str, aliases: str, peers: str) -> Path:
    (wd / "hosts" / "connected_devices.csv").write_text(_DEVICES + devices, encoding="utf-8")
    (wd / "hosts" / "device_addresses.csv").write_text(_ALIASES + aliases, encoding="utf-8")
    (wd / "hosts" / "device_peers.csv").write_text(_PEERS + peers, encoding="utf-8")
    return wd


def _peer_line(address: str, device: str, name: str, revision: str = "2", prov: str = "asset register row 9") -> str:
    return f"{address},{device},{name},printer,supporting IT,confirmed,{revision},{prov},reg,observed connection,private,APP1,outbound,445,svchost.exe,2,E-7;E-8\n"


def test_confirmed_device_names_an_observed_peer_with_its_provenance(tmp_path):
    wd = _with_devices(
        _work(tmp_path),
        "CD-000001,Print server,printer,,,,,supporting IT,confirmed,asset register row 9,WM,x,true,2\n",
        "CD-000001,10.40.254.9,10.40.254.9,ipv4,,,s,true\n",
        _peer_line("10.40.254.9", "CD-000001", "Print server"))
    res = ep.build(wd)
    r = _rows(wd)["10.40.254.9"]                              # the raw address stays the end
    assert r["name"] == "Print server" and r["confidence"] == "confirmed" and r["reviewed"] == "no"
    assert "connected device CD-000001 (revision 2): asset register row 9" in r["basis"]
    assert r["evidence"] == "E-7;E-8"
    assert ep.label(r) == "Print server"                      # not "likely ... (to confirm)"
    assert res["devices"] == ["10.40.254.9"] and res["conflicts"] == []


def test_device_name_outranks_a_hint_and_the_clash_is_listed(tmp_path):
    wd = _with_devices(
        _work(tmp_path),
        "CD-000002,Backup appliance,backup,,,,,supporting IT,confirmed,site walk,WM,x,true,1\n",
        "CD-000002,10.40.254.6,10.40.254.6,ipv4,,,s,true\n",
        _peer_line("10.40.254.6", "CD-000002", "Backup appliance", "1", "site walk"))
    res = ep.build(wd)
    r = _rows(wd)["10.40.254.6"]
    assert r["name"] == "Backup appliance" and r["confidence"] == "confirmed"
    assert any("unrecorded-peer hint" in c and "Dell PowerProtect Data Manager server" in c and "CD-000002" in c
               for c in res["conflicts"])
    assert "10.40.254.6" not in res["proposed"] or r["confidence"] == "confirmed"


def test_reviewed_label_is_kept_and_the_disagreement_is_surfaced(tmp_path):
    wd = _with_devices(
        _work(tmp_path),
        "CD-000001,Print server,printer,,,,,supporting IT,confirmed,src,WM,x,true,2\n",
        "CD-000001,10.40.254.9,10.40.254.9,ipv4,,,s,true\n",
        _peer_line("10.40.254.9", "CD-000001", "Print server"))
    with (wd / "hosts" / "endpoints.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ep.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerow({"end": "10.40.254.9", "name": "Plotter", "zone": "", "confidence": "observed",
                    "basis": "reviewed by hand", "evidence": "", "reviewed": "yes"})
    res = ep.build(wd)
    r = _rows(wd)["10.40.254.9"]
    assert r["name"] == "Plotter" and r["reviewed"] == "yes" and r["basis"] == "reviewed by hand"
    assert any("reviewed label 'Plotter'" in c and "CD-000001" in c for c in res["conflicts"])


def test_retired_disputed_or_moved_devices_do_not_appear_confirmed(tmp_path):
    peers = (_peer_line("10.40.254.9", "CD-000001", "Retired one") + _peer_line("10.40.254.10", "CD-000002", "Disputed one")
             + _peer_line("10.40.254.11", "CD-000003", "Moved one"))
    wd = _with_devices(
        _work(tmp_path),
        "CD-000001,Retired one,t,,,,,unknown,confirmed,s,WM,x,false,3\n"
        "CD-000002,Disputed one,t,,,,,unknown,disputed,s,WM,x,true,2\n"
        "CD-000003,Moved one,t,,,,,unknown,confirmed,s,WM,x,true,2\n",
        "CD-000001,10.40.254.9,10.40.254.9,ipv4,,,s,false\n"
        "CD-000002,10.40.254.10,10.40.254.10,ipv4,,,s,true\n"
        "CD-000003,10.40.254.99,10.40.254.99,ipv4,,,s,true\n",   # no longer holds .11: the projection row is stale
        peers)
    res = ep.build(wd)
    rows = _rows(wd)
    assert res["devices"] == []
    for address in ("10.40.254.9", "10.40.254.10", "10.40.254.11"):
        assert address not in rows or rows[address]["confidence"] != "confirmed"


def test_no_device_files_leaves_the_register_as_before(tmp_path):
    wd = _work(tmp_path)
    res = ep.build(wd)
    assert res["devices"] == [] and all(r["confidence"] != "confirmed" for r in _rows(wd).values())
