from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend import network


def v2_work(tmp_path: Path) -> Path:
    work = tmp_path / "csa-work-v2"
    work.mkdir()
    schema = Path(__file__).resolve().parents[2] / "framework" / "csa_docx" / "v2repo" / "schema.sql"
    with sqlite3.connect(work / "csa.sqlite") as con:
        con.executescript(schema.read_text(encoding="utf-8"))
        con.executemany("INSERT INTO host(name, role) VALUES (?, ?)",
                        [("APP1", "Application"), ("PEER1", "Database"), ("OTHER", "Other")])
        con.executemany("INSERT INTO application_scope(application_key, host_name, membership, review_state) VALUES (?, ?, ?, 'accepted')",
                        [("app-a", "APP1", "owned"), ("app-a", "PEER1", "peer"), ("other-app", "OTHER", "owned")])
        con.execute("INSERT INTO flow(src_host, dst_host, port) VALUES ('APP1', 'PEER1', 1433)")
    return work


def test_application_view_keeps_only_owned_hosts_and_captured_endpoints(tmp_path: Path) -> None:
    work = v2_work(tmp_path)
    result = network.build(work, Path(__file__).resolve().parents[2], view="application", application_key="app-a")
    assert result["view"] == "application"
    assert result["application_key"] == "app-a"
    assert {n["id"] for n in result["nodes"]} == {"APP1", "PEER1"}
    assert {(e["s"], e["t"]) for e in result["edges"]} == {("APP1", "PEER1")}


def test_scoped_view_requires_known_application_scope(tmp_path: Path) -> None:
    work = v2_work(tmp_path)
    with pytest.raises(ValueError, match="unknown application_key"):
        network.build(work, Path(__file__).resolve().parents[2], view="owned", application_key="missing")
    with pytest.raises(ValueError, match="required"):
        network.build(work, Path(__file__).resolve().parents[2], view="application")


def test_global_view_returns_all_hosts_and_labels_scope(tmp_path: Path) -> None:
    work = v2_work(tmp_path)
    result = network.build(work, Path(__file__).resolve().parents[2], view="global")
    assert result["view"] == "global"
    assert result["application_key"] is None
    assert {n["id"] for n in result["nodes"]} == {"APP1", "PEER1", "OTHER"}


# --------------------------------------------------------------------------- S615

AGENTS = Path(__file__).resolve().parents[2]


def contract_work(tmp_path: Path) -> Path:
    """app-a owns APP1 and APP2. PEER1 is its flow-linked scoped peer, STRAY an active peer with no
    relationship, UNRELATED another application's host that APP1 talks to, and 203.0.113.10 an
    external address an accepted evidence row links to APP1."""
    work = tmp_path / "csa-work-v2"
    work.mkdir()
    schema = AGENTS / "framework" / "csa_docx" / "v2repo" / "schema.sql"
    with sqlite3.connect(work / "csa.sqlite") as con:
        con.executescript(schema.read_text(encoding="utf-8"))
        con.executemany("INSERT INTO host(name, role) VALUES (?, ?)",
                        [("APP1", "Application"), ("APP2", "Database"), ("PEER1", "Directory"),
                         ("STRAY", "Other"), ("UNRELATED", "Other")])
        con.executemany("INSERT INTO application_scope(application_key, host_name, membership, review_state) "
                        "VALUES (?, ?, ?, 'accepted')",
                        [("app-a", "APP1", "owned"), ("app-a", "APP2", "owned"), ("app-a", "PEER1", "peer"),
                         ("app-a", "STRAY", "peer"), ("app-b", "UNRELATED", "owned"), ("app-b", "APP1", "peer")])
        con.executemany("INSERT INTO flow(src_host, dst_host, port) VALUES (?, ?, ?)",
                        [("APP1", "APP2", 1433), ("APP1", "PEER1", 389), ("APP1", "UNRELATED", 445),
                         ("PEER1", "STRAY", 80)])
        con.executemany("INSERT INTO evidence(id, area, claim, status, source_title, review_state) "
                        "VALUES (?, 'network_and_connectivity', ?, 'VERIFIED', ?, ?)",
                        [("E-001", "APP1 has an established connection from app.exe to 203.0.113.10 on port 443",
                          "cap/001.txt", "accepted"),
                         ("E-002", "APP2 has an established connection from app.exe to 198.51.100.9 on port 22",
                          "cap/002.txt", "rejected")])
    return work


def _project(work: Path, key: str = "app-a") -> dict[str, str]:
    return {"key": key, "label": key, "work_dir": str(work)}


def test_unrelated_peer_is_excluded_while_evidenced_external_ip_stays(tmp_path: Path) -> None:
    net = network.build(contract_work(tmp_path), AGENTS, view="application", application_key="app-a")
    ids = {n["id"] for n in net["nodes"]}
    assert ids == {"APP1", "APP2", "PEER1", "203.0.113.10"}
    assert "UNRELATED" not in ids and "STRAY" not in ids and "198.51.100.9" not in ids
    assert ("APP1", "203.0.113.10", "443") in network.identity(net)["edges"]
    assert next(e for e in net["edges"] if e["t"] == "203.0.113.10")["ids"] == ["E-001"]
    assert all(e["s"] in net["scope"]["owned"] or e["t"] in net["scope"]["owned"] for e in net["edges"])
    assert net["scope"] == {"owned": ["APP1", "APP2"], "peers": ["PEER1"], "external": ["203.0.113.10"]}


def test_owned_view_keeps_only_owned_hosts_and_internal_links(tmp_path: Path) -> None:
    net = network.build(contract_work(tmp_path), AGENTS, view="owned", application_key="app-a")
    assert {n["id"] for n in net["nodes"]} == {"APP1", "APP2"}
    assert network.identity(net)["edges"] == {("APP1", "APP2", "1433")}


def test_global_view_keeps_cross_application_relationships(tmp_path: Path) -> None:
    net = network.build(contract_work(tmp_path), AGENTS, view="global", application_key="app-a")
    assert net["view"] == "global" and net["application_key"] == "app-a"
    ids = {n["id"] for n in net["nodes"]}
    assert {"APP1", "APP2", "PEER1", "STRAY", "UNRELATED", "203.0.113.10"} <= ids
    assert {("APP1", "UNRELATED", "445"), ("PEER1", "STRAY", "80")} <= network.identity(net)["edges"]


def test_application_key_alias_is_deterministic(tmp_path: Path) -> None:
    assert network.resolve_application_key(["tetra-reveloc", "iamps-08"], "tetra") == "tetra-reveloc"
    assert network.resolve_application_key(["tetra-reveloc"], "tetra-reveloc") == "tetra-reveloc"
    with pytest.raises(ValueError, match="ambiguous application_key: tetra matches tetra-dmr, tetra-reveloc"):
        network.resolve_application_key(["tetra-dmr", "tetra-reveloc"], "tetra")
    with pytest.raises(ValueError, match="unknown application_key: radio"):
        network.resolve_application_key(["tetra-reveloc"], "radio")
    work = contract_work(tmp_path)                   # "app" matches app-a and app-b
    with pytest.raises(ValueError, match="ambiguous application_key"):
        network.build(work, AGENTS, view="application", application_key="app")


def test_every_surface_uses_the_same_scoped_network(tmp_path: Path) -> None:
    from backend import csa_figures, explorer
    project = _project(contract_work(tmp_path))
    for view in ("owned", "application", "global"):
        net = network.scoped_network(project, AGENTS, view=view)
        explored = explorer.build(project, AGENTS, None, view=view)
        figures = csa_figures.scoped_network(project, AGENTS, view)
        diagrams = explorer.diagrams(project, AGENTS, view=view)
        for payload in (net, explored, figures, diagrams):
            assert payload["view"] == view and payload["application_key"] == "app-a"
        report = network.parity({"host_network": network.identity(net),
                                 "system_explorer": network.identity(explored, "hosts"),
                                 "csa_figures": network.identity(figures)})
        assert report["status"] == "OK" and report["differences"] == []
        assert report["counts"]["host_network"] == report["counts"]["system_explorer"]


def test_parity_reports_identity_differences() -> None:
    a = {"nodes": {"APP1", "PEER1"}, "edges": {("APP1", "PEER1", "443")}}
    b = {"nodes": {"APP1", "OTHER"}, "edges": {("APP1", "PEER1", "443")}}
    report = network.parity({"host_network": a, "system_explorer": b})
    assert report["status"] == "MISMATCH"
    assert report["differences"] == [{"surface": "system_explorer", "against": "host_network", "part": "nodes",
                                      "missing": ["PEER1"], "extra": ["OTHER"]}]
    assert report["counts"]["system_explorer"] == {"nodes": 2, "edges": 1}


def test_live_store_parity_reports_counts(tmp_path: Path) -> None:
    """Read-only diagnostic over the registered V2 stores: skipped when none is available here."""
    import os
    registry = Path(os.environ.get("CSA_PROJECTS_FILE") or AGENTS / "csa-context" / "PROJECTS.yaml")
    if os.environ.get("CSA_LIVE_PARITY") != "1" or not registry.is_file():
        pytest.skip("set CSA_LIVE_PARITY=1 to compare the surfaces on the registered V2 stores")
    from backend import app as api, csa_figures, explorer
    checked = 0
    for project in api.projects().values():
        work = Path(project["work_dir"]).expanduser()
        if work.name != "csa-work-v2" or not (work / "csa.sqlite").is_file():
            continue
        for view in ("owned", "application", "global"):
            try:
                net = network.scoped_network(project, AGENTS, view=view)
            except ValueError as exc:                # a store with no scope metadata has no scoped view
                print(project["key"], view, "not available:", exc)
                continue
            report = network.parity({"host_network": network.identity(net),
                                     "system_explorer": network.identity(explorer.build(project, AGENTS, None, view=view), "hosts"),
                                     "csa_figures": network.identity(csa_figures.scoped_network(project, AGENTS, view))})
            print(project["key"], view, report["counts"], report["differences"])
            assert report["status"] == "OK", report["differences"]
            checked += 1
    assert checked
