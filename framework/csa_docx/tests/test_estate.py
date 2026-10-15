"""Estate register: shared DNS and time servers across the projects of one estate."""
import csv

import pytest

from csa_docx import estate

SVC = ["client_host", "service", "server_ip", "server_host", "preference", "capture", "source", "excerpt"]
HDR = ["evidence_id", "csa_area", "question", "claim", "status", "source_title", "source_version", "section",
       "page_or_location", "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state"]


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _svc(client, service, ip, host, pref):
    return {"client_host": client, "service": service, "server_ip": ip, "server_host": host, "preference": str(pref)}


def _read(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def est(tmp_path, monkeypatch):
    lines = ["projects:"]
    work = {}
    for key, member in (("aa", True), ("bb", True), ("cc", False)):
        wd = tmp_path / key / "csa-work"
        (wd / "hosts").mkdir(parents=True)
        work[key] = wd
        lines += [f"  - key: {key}", f'    label: "{key.upper()} app"', f'    project_root: "{tmp_path / key}"',
                  f'    work_dir: "{wd}"'] + (['    estate: "corp.test"'] if member else [])
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    monkeypatch.setenv("CSA_ESTATES_DIR", str(tmp_path / "estates"))
    _write(work["aa"] / "hosts" / "host_services.csv", SVC, [
        _svc("A1", "dns", "10.1.0.1", "DNS1", 1), _svc("A1", "dns", "10.2.0.1", "DNS2", 2),
        _svc("A2", "dns", "10.2.0.1", "DNS2", 1), _svc("A2", "dns", "10.1.0.1", "DNS1", 2),
        _svc("A1", "time", "10.1.0.1", "DNS1", 1)])
    _write(work["aa"] / "evidence-matrix.csv", HDR, [
        {"evidence_id": "E-010", "question": "Which DNS servers is A1 configured to use?", "status": "VERIFIED"},
        {"evidence_id": "E-011", "question": "Which time source does A1 synchronise from?", "status": "VERIFIED"}])
    _write(work["bb"] / "hosts" / "host_services.csv", SVC, [
        _svc("B1", "dns", "10.1.0.1", "", 1), _svc("B1", "time", "10.9.0.9", "TIME9", 1)])
    _write(work["cc"] / "hosts" / "host_services.csv", SVC, [_svc("C1", "dns", "10.1.0.1", "DNS1", 1)])
    return tmp_path, work


def test_members_and_estate(est):
    assert estate.estate_of("aa") == "corp.test" and estate.estate_of("cc") is None
    assert [k for k, _ in estate.members("bb")] == ["aa", "bb"]
    assert estate.members("cc") == []


def test_an_unnamed_address_takes_the_name_another_member_gives_it(est):
    tmp, _ = est
    res = estate.build("corp.test")
    assert res["status"] == "OK" and res["servers"] == 3 and res["shared"] == 1
    rows = {r["server"]: r for r in _read(tmp / "estates" / "corp.test" / "servers.csv")}
    assert rows["DNS1"]["projects"] == "aa;bb" and rows["DNS1"]["shared"] == "yes"
    assert rows["DNS1"]["services"] == "dns;time"
    assert rows["DNS2"]["shared"] == "no" and rows["TIME9"]["projects"] == "bb"


def test_preference_counts_and_member_evidence(est):
    tmp, _ = est
    estate.build("corp.test")
    uses = {(r["server"], r["service"], r["project"]): r for r in _read(tmp / "estates" / "corp.test" / "services.csv")}
    a = uses[("DNS1", "dns", "aa")]
    assert a["clients"] == "2" and a["client_hosts"] == "A1;A2" and a["preference"] == "primary 1, secondary 1"
    assert a["evidence_ids"] == "aa:E-010"
    assert uses[("DNS1", "time", "aa")]["evidence_ids"] == "aa:E-011"
    assert uses[("DNS1", "dns", "bb")]["preference"] == "primary 1"


def test_one_address_with_two_names_is_reported_not_merged(est):
    tmp, work = est
    _write(work["bb"] / "hosts" / "host_services.csv", SVC, [_svc("B1", "dns", "10.2.0.1", "OTHERNAME", 1)])
    estate.build("corp.test")
    rows = {r["server"]: r for r in _read(tmp / "estates" / "corp.test" / "servers.csv")}
    assert "OTHERNAME" in rows and "DNS2" in rows
    assert "10.2.0.1 also named OTHERNAME in bb" in rows["DNS2"]["conflicts"]
    assert "10.2.0.1 also named DNS2 in aa" in rows["OTHERNAME"]["conflicts"]


def test_a_project_outside_the_estate_is_never_read(est):
    tmp, _ = est
    estate.build("corp.test")
    rows = _read(tmp / "estates" / "corp.test" / "services.csv")
    assert all(r["project"] != "cc" for r in rows)


def test_shared_servers_names_the_other_members(est):
    estate.build("corp.test")
    got = estate.shared_servers("aa")
    assert set(got) == {"DNS1"}
    assert got["DNS1"] == {"services": ["dns", "time"], "projects": ["bb"], "labels": ["BB app"], "ips": ["10.1.0.1"]}
    assert estate.shared_servers("cc") == {}


HOSTS = ["host", "in_scope", "role", "site", "capture"]


def test_a_site_split_evenly_is_compared_with_the_estate(est):
    from csa_docx import section_card
    tmp, work = est
    _write(work["aa"] / "hosts" / "hosts.csv", HOSTS, [
        {"host": "A1", "site": "North", "capture": "c"}, {"host": "A2", "site": "North", "capture": "c"}])
    _write(work["bb"] / "hosts" / "hosts.csv", HOSTS, [
        {"host": f"B{i}", "site": "North", "capture": "c"} for i in range(1, 5)])
    _write(work["bb"] / "hosts" / "host_services.csv", SVC, [_svc(f"B{i}", "dns", "10.2.0.1", "DNS2", 1) for i in range(1, 5)])
    _write(work["bb"] / "evidence-matrix.csv", HDR, [
        {"evidence_id": "E-020", "question": "Which DNS servers is B1 configured to use?", "status": "VERIFIED"}])
    rows = [{"evidence_id": "E-010", "question": "Which DNS servers is A1 configured to use?"}]
    got = section_card._dns_order_candidates(tmp / "aa", rows)
    assert len(got) == 1 and "4 of 4 North hosts in BB app (bb) use DNS2 first" in got[0]["text"]
    assert "A1 use DNS1 first" in got[0]["text"] and got[0]["ids"] == ["E-010", "bb:E-020"]
