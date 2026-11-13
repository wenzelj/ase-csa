import csv
from pathlib import Path

from csa_docx.v2repo import Repo
from csa_docx.v2scope import rebuild


def test_scope_rebuild_dry_run_and_apply(tmp_path):
    root = tmp_path / "project"
    source = root / "csa-work" / "hosts"
    source.mkdir(parents=True)
    with (source / "hosts.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["host", "in_scope"])
        writer.writeheader()
        writer.writerows([{"host": "APP01", "in_scope": "Yes"},
                          {"host": "PEER01", "in_scope": "peer"}])
    v2 = root / "csa-work-v2"
    repo = Repo(v2)
    with repo.tx():
        repo.hosts.create("APP01")
        repo.hosts.create("PEER01")
        repo.con.execute("INSERT INTO flow (src_host,dst_host,port) VALUES ('APP01','PEER01',443)")
    repo.close()
    assert rebuild(root, v2, "tetra-reveloc", dry_run=True)["active_peers"] == 1
    result = rebuild(root, v2, "tetra-reveloc")
    repo = Repo(v2)
    assert repo.application_scope.active_count() == 2
    assert Path(result["report_path"]).is_file()
    assert repo.con.execute("SELECT COUNT(*) FROM review_event WHERE action='scope-rebuild'").fetchone()[0] == 2
    assert not (root / "csa-work" / "evidence-matrix.csv").exists()
    assert not (root / "csa-work" / "evidence-reviews.jsonl").exists()
    assert list((v2 / "backups").glob("csa.sqlite.*")), "Repo transaction should create a V2 backup"
    repo.close()
