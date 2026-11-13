from __future__ import annotations

from pathlib import Path

from csa_docx.v2repo import Repo
from csa_docx.v2repo import graph as _graph  # noqa: F401


def _repo(tmp_path: Path) -> Repo:
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.hosts.create("APP1", role="Application")
        repo.hosts.create("PEER1", role="Peer")
        repo.hosts.create("OTHER", role="Other")
        repo.application_scope.add("app-a", "APP1", "owned", review_state="accepted")
        repo.application_scope.add("app-a", "PEER1", "peer", review_state="accepted")
        repo.application_scope.add("app-a", "OTHER", "peer", review_state="accepted")
        eid = repo.evidence.create("APP1 has an established connection to PEER1 on port 443", "Discovery Data/a.txt", status="VERIFIED")
        repo.evidence.accept(eid, by="test")
        repo.con.execute("INSERT INTO flow(src_host,dst_host,port) VALUES ('APP1','PEER1',443)")
        repo.graph.refresh(actor="test")
    return repo


def test_v2_graph_ignores_legacy_files_and_projects_scope(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "graph").mkdir()
    (tmp_path / "graph" / "nodes.csv").write_text("legacy,wrong\n", encoding="utf-8")
    assert {node["node_id"] for node in repo.graph.nodes(view="application", application_key="app-a")} == {"host/APP1", "host/PEER1"}
    assert repo.graph.verify()["status"] == "OK"
    assert repo.graph.get("flow/does-not-exist") is None
    repo.close()


def test_v2_graph_review_requires_transaction_and_audits(tmp_path):
    repo = _repo(tmp_path)
    edge = next(row for row in repo.graph.edges() if row["kind"] == "flow")
    try:
        repo.graph.review(edge["edge_id"], "rejected")
    except RuntimeError as exc:
        assert "transaction" in str(exc)
    else:
        raise AssertionError("graph review must require a transaction")
    with repo.tx():
        result = repo.graph.review(edge["edge_id"], "rejected", actor="test")
    assert result["status"] == "OK"
    assert repo.con.execute("SELECT COUNT(*) FROM review_event WHERE action='graph.review.rejected'").fetchone()[0] == 1
    assert repo.evidence.list()[0]["review_state"] == "rejected"
    repo.close()
