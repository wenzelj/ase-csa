"""S454: parts and flows read the endpoint register - a resolved identity groups a peer under its
name, and a register zone feeds the flow zone lookups and the OT-side rule."""
import csv

from csa_docx import endpoints as ep
from csa_docx import flows as F
from csa_docx import parts as P

HOSTS = (
    "host,in_scope,system,role,site,system_source,role_source,site_source,conflicts,fqdn,ips,ou,capture,captured_in,listening,sources,ad_site\n"
    "ROTPRDREV102,Yes,Reveloc,OT Reveloc Server,Rockhampton,register,register,register,,,ROTPRDREV102.fqdn,10.40.229.210,cap,,,listening,source,,\n"
)
ZONES = (
    "zone,kind,match,basis,reviewed\n"
    "OT Rockhampton,ot,subnet:10.40.228.0/27,fixture,yes\n"
    "Internal, zone not recorded,unknown,default:private,,yes\n"
    "Internet,internet,default:public,,yes\n"
)


def _wd(tmp) -> None:
    wd = tmp / "csa-work"
    (wd / "hosts").mkdir(parents=True)
    (wd / "hosts" / "hosts.csv").write_text(HOSTS, encoding="utf-8")
    (wd / "hosts" / "zones.csv").write_text(ZONES, encoding="utf-8")
    with (wd / "hosts" / "endpoints.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ep.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerow({"end": "10.40.254.6", "name": "Dell PowerProtect Data Manager server", "zone": "",
                    "confidence": "observed", "basis": "gap lookup evidence", "evidence": "E-1547", "reviewed": "no"})
        w.writerow({"end": "EH-RADIO-GPS-PRD", "name": "Azure Service Bus endpoint", "zone": "",
                    "confidence": "likely", "basis": "flow map name", "evidence": "", "reviewed": "no"})
        w.writerow({"end": "SITEONLY99", "name": "", "zone": "OT Rockhampton",
                    "confidence": "", "basis": "site zone", "evidence": "", "reviewed": "no"})


def test_observed_register_name_groups_under_that_name(tmp_path):
    """An end with an observed register name groups under that name, not 'Unidentified internal peers'."""
    _wd(tmp_path)
    rows = ep.load(tmp_path / "csa-work")
    name, basis = P.dependency_of("10.40.254.6", "", {}, set(), rows)
    assert name == "Dell PowerProtect Data Manager server"
    assert basis == "endpoint register: gap lookup evidence"
    # and an end with no register name and no zone still goes to Unidentified internal peers
    name, basis = P.dependency_of("10.99.99.99", "", {}, set(), rows)
    assert name == "Unidentified internal peers"
    assert basis == "no name, role or service zone recorded"


def test_register_site_zone_puts_the_host_on_the_ot_side(tmp_path):
    """A register host with only a site zone in endpoints.csv is on the OT side in ot_sides."""
    _wd(tmp_path)
    side = F.ot_sides(tmp_path / "csa-work")
    assert side("SITEONLY99") == "ot"
    # an end with no register row and no zone is still unknown
    assert side("10.99.99.99") == "unknown"


def test_likely_name_carries_the_doubt(tmp_path):
    """An end with a likely name gets the '(to confirm)' label."""
    _wd(tmp_path)
    rows = ep.load(tmp_path / "csa-work")
    name, basis = P.dependency_of("EH-RADIO-GPS-PRD", "", {}, set(), rows)
    assert name == "likely Azure Service Bus endpoint (to confirm)"
    assert basis == "endpoint register: flow map name"


def test_zone_of_list_reads_the_register_when_zones_csv_gives_none(tmp_path):
    """_zone_of_list uses the register zone when zones.csv gives none (kind unknown)."""
    _wd(tmp_path)
    from csa_docx import zones as Z
    z = Z.for_project(tmp_path / "csa-work")
    rows = ep.load(tmp_path / "csa-work")
    out = F._zone_of_list(z, {"SITEONLY99"}, rows)
    assert out["zone"] == "OT Rockhampton"


def test_assemble_groups_observed_name_peers(tmp_path):
    """assemble() groups an end with an observed register name under that name."""
    _wd(tmp_path)
    # write a flows.csv with the observed peer
    wd = tmp_path / "csa-work"
    flows_text = (
        "flow_id,status,mechanism,data,src,src_role,src_zone,src_zone_kind,src_process,"
        "dst,dst_role,dst_zone,dst_zone_kind,dst_process,port,cross_zone,zones_reviewed,"
        "declared_id,declared_flow,signature,confirm,connections,sources,excerpt\n"
        "F001,observed,web/API,no,ROTPRDREV102,OT Reveloc Server,OT Rockhampton,ot,,"
        "10.40.254.6,,,unknown,,8080,unknown,no,,,fixture,0,fixture,fixture\n"
    )
    (wd / "hosts" / "flows.csv").write_text(flows_text, encoding="utf-8")
    doc = P.assemble(wd)
    part = [p for p in doc["parts"] if "10.40.254.6" in p["members"]]
    assert part, f"10.40.254.6 not in any part: {[p['members'] for p in doc['parts']]}"
    assert part[0]["name"] == "Dell PowerProtect Data Manager server"
    assert part[0]["basis"].startswith("endpoint register:")
