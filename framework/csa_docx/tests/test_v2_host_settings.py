from __future__ import annotations

import json
from pathlib import Path

from csa_docx import host_settings, topic_tables
from csa_docx.v2repo import Repo
from csa_docx.v2repo import graph as _graph  # noqa: F401


def _project(tmp_path: Path) -> Path:
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        for host, role in (("APP1", "Application server"), ("DNS1", "DNS server"), ("OTHER", "Other peer")):
            repo.hosts.create(host, role=role, site="Site A")
        repo.con.execute("INSERT INTO address(ip, owner_host) VALUES ('10.0.0.1','APP1')")
        repo.con.execute("INSERT INTO service(host,provider_host,name,port,protocol) VALUES ('APP1','DNS1','dns',53,'udp')")
        repo.con.execute("INSERT INTO service(host,provider_host,name,port,protocol) VALUES ('APP1','DNS1','time',123,'udp')")
        repo.con.execute("INSERT INTO flow(src_host,dst_host,port) VALUES ('APP1','DNS1',53)")
        repo.application_scope.add("app-a", "APP1", "owned", review_state="accepted")
        repo.application_scope.add("app-a", "DNS1", "peer", review_state="accepted")
        repo.application_scope.add("app-a", "OTHER", "peer", review_state="accepted")
        repo.graph.refresh()
    repo.close()
    return work


def test_v2_settings_use_sqlite_and_exclude_unqualified_peer(tmp_path):
    work = _project(tmp_path)
    result = host_settings.build(work, application_key="app-a", view="application")
    assert result["status"] == "OK"
    rows = json.loads((work / "host-settings.json").read_text())["rows"]
    assert {row["host"] for row in rows} == {"APP1"}
    assert {row["attribute"] for row in rows} >= {"dns.primary", "time.source", "net.address"}
    assert all(row["capture"] == "csa.sqlite" and row["source"] for row in rows)
    table = topic_tables.build(work, "DNS")
    assert table["status"] == "OK"
    assert all("OTHER" not in str(row) for row in table["rows"])


def test_v2_owned_view_keeps_peer_out_of_settings(tmp_path):
    work = _project(tmp_path)
    host_settings.build(work, application_key="app-a", view="owned")
    rows = host_settings.load(work)
    assert set(rows) == {"APP1"}
