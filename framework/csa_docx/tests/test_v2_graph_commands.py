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


# --------------------------------------------------------------------------- S616

def _legacy_graph(root: Path) -> None:
    """Conflicting V1 graph files beside and inside the V2 work folder: they must never be read."""
    for folder in (root / "graph", root / "csa-work-v2" / "graph", root / "csa-work" / "graph"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "nodes.csv").write_text("node_id,node_type,label\nhost/LEGACY,host,LEGACY\n", encoding="utf-8")
        (folder / "edges.csv").write_text("edge_id,src,dst,relationship_type,evidence_ids\n"
                                          "x,host/LEGACY,host/APP1,flow,E-999\n", encoding="utf-8")


def test_graph_command_reads_only_the_v2_database(tmp_path):
    from csa_docx.v2repo.scope import GRAPH_SOURCE, graph_command
    repo = _repo(tmp_path)
    before = {a: graph_command(repo, [a], project_key="app-a") for a in ("stats", "list", "verify")}
    _legacy_graph(tmp_path)
    for action, expected in before.items():
        assert graph_command(repo, [action], project_key="app-a") == expected
    stats = before["stats"]
    assert stats["status"] == "OK" and stats["view"] == "global" and stats["source"] == GRAPH_SOURCE
    assert stats["nodes"] == len(repo.graph.nodes()) and stats["edges"] == len(repo.graph.edges())
    assert "host/LEGACY" not in {n["node_id"] for n in before["list"]["nodes"]}
    assert before["verify"]["status"] == "OK" and before["verify"]["issues"] == []
    assert graph_command(repo, [], project_key="app-a") == stats          # stats is the default action
    got = graph_command(repo, ["get", "host/APP1"], project_key="app-a")
    assert got["status"] == "OK" and got["subject"]["node_id"] == "host/APP1"
    assert graph_command(repo, ["get", "host/LEGACY"], project_key="app-a")["code"] == "V2_GRAPH_NOT_FOUND"
    repo.close()


def test_graph_command_follows_the_projection_contract(tmp_path):
    from csa_docx.v2repo.scope import graph_command, projected_graph
    repo = _repo(tmp_path)
    owned = graph_command(repo, ["list", "--view", "owned"], project_key="app-a")
    assert owned["view"] == "owned" and owned["application_key"] == "app-a"
    assert {n["node_id"] for n in owned["nodes"]} == {"host/APP1"} and owned["edges"] == []
    assert owned["nodes"] == projected_graph(repo, "app-a", view="owned")["nodes"]
    app = graph_command(repo, ["list", "--view=application", "--application-key=app-a"])
    assert {n["node_id"] for n in app["nodes"]} == {"host/APP1", "host/PEER1"}        # OTHER has no relationship
    assert app["edges"] == projected_graph(repo, "app-a")["edges"]
    assert graph_command(repo, ["verify", "--view", "application"], project_key="app-a")["status"] == "OK"
    # a subject outside the selected view is not found there, though the global graph holds it
    assert graph_command(repo, ["get", "host/OTHER", "--view", "application"], project_key="app-a")["code"] == "V2_GRAPH_NOT_FOUND"
    assert graph_command(repo, ["get", "host/OTHER"], project_key="app-a")["status"] == "OK"
    for rest in (["stats", "--view", "application", "--application-key", "missing"],
                 ["stats", "--view", "everything"], ["stats", "--view"]):
        assert graph_command(repo, rest, project_key="app-a")["code"] == "V2_GRAPH_SCOPE_ERROR"
    assert graph_command(repo, ["stats", "--view", "owned"])["code"] == "V2_GRAPH_SCOPE_ERROR"   # no key at all
    repo.close()


def test_graph_command_unsupported_actions_return_the_documented_error(tmp_path):
    from csa_docx.v2repo import scope
    repo = _repo(tmp_path)
    _legacy_graph(tmp_path)
    assert set(scope.V2_GRAPH_ERRORS) == {"V2_GRAPH_COMMAND_UNAVAILABLE", "V2_GRAPH_NOT_FOUND",
                                          "V2_GRAPH_SCOPE_ERROR", "V2_GRAPH_REVIEW_ERROR"}
    events = repo.con.execute("SELECT COUNT(*) FROM review_event").fetchone()[0]
    for action in ("build", "add-node", "add-edge", "export", "sync", "links"):
        result = scope.graph_command(repo, [action, "x"], project_key="app-a")
        assert result["status"] == "ERROR" and result["code"] == "V2_GRAPH_COMMAND_UNAVAILABLE"
        assert result["code"] in scope.V2_GRAPH_ERRORS and "old graph files were not used" in result["message"]
    assert repo.con.execute("SELECT COUNT(*) FROM review_event").fetchone()[0] == events
    repo.close()


def test_graph_command_review_runs_in_a_transaction_and_appends_an_event(tmp_path):
    from csa_docx.v2repo.scope import graph_command
    repo = _repo(tmp_path)
    edge = next(row for row in repo.graph.edges() if row["kind"] == "flow")
    result = graph_command(repo, ["review", edge["edge_id"], "rejected", "wrong", "peer"], project_key="app-a")
    assert result["status"] == "OK" and result["state"] == "rejected"
    row = repo.con.execute("SELECT actor, subject_id, note FROM review_event "
                           "WHERE action='graph.review.rejected'").fetchall()
    assert row == [("csa graph review", edge["edge_id"], "wrong peer")]
    assert repo.evidence.list()[0]["review_state"] == "rejected"
    events = repo.con.execute("SELECT COUNT(*) FROM review_event").fetchone()[0]
    assert graph_command(repo, ["review", "flow/missing", "rejected"])["code"] == "V2_GRAPH_REVIEW_ERROR"
    assert graph_command(repo, ["review", edge["edge_id"], "maybe"])["code"] == "V2_GRAPH_REVIEW_ERROR"
    assert repo.con.execute("SELECT COUNT(*) FROM review_event").fetchone()[0] == events    # a failed review writes nothing
    repo.close()


def test_csa_graph_uses_the_v2_store_and_never_the_legacy_files(tmp_path):
    import json
    import os
    import subprocess
    import sys
    _repo(tmp_path).close()
    _legacy_graph(tmp_path)
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text("projects:\n  - key: app-a\n    label: \"App A\"\n"
                        f"    project_root: \"{tmp_path}\"\n    project_context: \"\"\n"
                        f"    work_dir: \"{tmp_path / 'csa-work-v2'}\"\n    default_source_set: \"\"\n", encoding="utf-8")
    csa = Path(__file__).resolve().parents[3] / "bin" / "csa"

    def run(*args):
        proc = subprocess.run([sys.executable, str(csa), "-p", "app-a", "graph", *args], capture_output=True, text=True,
                              env={**os.environ, "CSA_PROJECTS_FILE": str(registry)})
        return proc.returncode, json.loads(proc.stdout[proc.stdout.index("{"):])

    code, stats = run("stats")
    assert code == 0 and stats["status"] == "OK" and stats["nodes_by_type"] == {"host": 3}
    code, owned = run("list", "--view", "owned")
    assert code == 0 and [n["node_id"] for n in owned["nodes"]] == ["host/APP1"]
    assert run("verify")[1]["status"] == "OK"
    code, legacy = run("get", "host/LEGACY")
    assert code == 2 and legacy["code"] == "V2_GRAPH_NOT_FOUND"
    code, build = run("build")
    assert code == 2 and build["code"] == "V2_GRAPH_COMMAND_UNAVAILABLE"
