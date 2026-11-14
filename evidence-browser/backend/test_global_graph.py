import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "framework"))
from csa_docx.v2repo import Repo
from csa_docx.v2repo import graph as _graph  # noqa: F401
from backend.global_graph import build


def _store(root: Path, key: str, hosts: tuple[str, ...], source: str, target: str):
    work = root / key / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        for host in hosts:
            repo.hosts.create(host)
        repo.con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES (?,?,443)", (source, target))
        for host in hosts:
            repo.application_scope.add(key, host, "owned", review_state="accepted")
        repo.graph.refresh()
    repo.close()
    return {"key": key, "label": key.upper(), "work_dir": str(work)}


def test_global_graph_qualifies_hosts_and_deduplicates_shared_edge(tmp_path, monkeypatch):
    a = _store(tmp_path, "app-a", ("A", "SHARED"), "A", "SHARED")
    b = _store(tmp_path, "app-b", ("SHARED", "B"), "SHARED", "B")
    # A registered project without scope must not have all hosts treated as owned.
    empty = tmp_path / "empty" / "csa-work-v2"
    empty.mkdir(parents=True)
    sqlite3.connect(empty / "csa.sqlite").close()
    result = build([a, b, {"key": "empty", "label": "Empty", "work_dir": str(empty)}])
    assert {node["id"] for node in result["nodes"]} == {"app-a::A", "app-a::SHARED", "app-b::SHARED", "app-b::B"}
    assert all(edge["source_projects"] for edge in result["edges"])
    assert result["partial"] is True
    assert any(item["application_key"] == "empty" and item["state"] == "missing-scope"
               for item in result["applications"])


def test_portfolio_graph_and_store_global_view_both_keep_cross_application_edges(tmp_path):
    """S615: the portfolio endpoint stays, and one store's explicit global view is never scope-filtered."""
    from backend import network
    a = _store(tmp_path, "app-a", ("A", "SHARED"), "A", "SHARED")
    work = Path(a["work_dir"])
    repo = Repo(work)
    with repo.tx():
        repo.hosts.create("FOREIGN")
        repo.con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('SHARED','FOREIGN',22)")
        repo.application_scope.add("app-b", "FOREIGN", "owned", review_state="accepted")
        repo.graph.refresh()
    repo.close()
    agents = Path(__file__).resolve().parents[2]
    scoped = network.build(work, agents, view="application", application_key="app-a")
    whole = network.build(work, agents, view="global", application_key="app-a")
    assert "FOREIGN" not in {node["id"] for node in scoped["nodes"]}
    assert "FOREIGN" in {node["id"] for node in whole["nodes"]}
    assert ("SHARED", "FOREIGN", "22") in network.identity(whole)["edges"]
    assert whole["view"] == "global" and whole["application_key"] == "app-a"
    portfolio = build([a])
    assert {node["id"] for node in portfolio["nodes"]} >= {"app-a::A", "app-a::SHARED"}
