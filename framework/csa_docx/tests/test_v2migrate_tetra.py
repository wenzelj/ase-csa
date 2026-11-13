import csv
import sqlite3
from pathlib import Path

import pytest

from csa_docx.v2migrate import migrate

ROOT = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
CW = ROOT / "csa-work"

pytestmark = pytest.mark.skipif(not (CW / "evidence-matrix.csv").is_file(),
                                reason="TETRA csa-work not present")


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    v2 = tmp_path_factory.mktemp("tetra-v2")
    res = migrate(ROOT, v2, "tetra-reveloc")
    assert res["status"] == "OK", res
    return v2, res


def test_evidence_and_host_counts(migrated):
    v2, _ = migrated
    con = sqlite3.connect(v2 / "csa.sqlite")
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == len(_rows(CW / "evidence-matrix.csv")) - 1
    skipped_hosts = [l for l in (v2 / "MIGRATION-REPORT.md").read_text(encoding="utf-8").splitlines()
                     if l.startswith("| hosts/hosts.csv |")]
    assert con.execute("SELECT COUNT(*) FROM host").fetchone()[0] == \
        len(_rows(CW / "hosts" / "hosts.csv")) - 1 - len(skipped_hosts)
    con.close()


def test_graph_has_every_dns_time_provider(migrated):
    v2, _ = migrated
    con = sqlite3.connect(v2 / "csa.sqlite")
    assert con.execute("SELECT COUNT(*) FROM graph_node").fetchone()[0] > 0
    assert con.execute("SELECT COUNT(*) FROM graph_edge").fetchone()[0] > 0
    nodes = {r[0] for r in con.execute("SELECT node_id FROM graph_node")}
    edges = {(r[0], r[1], r[2]) for r in con.execute("SELECT src, dst, kind FROM graph_edge")}
    for client, provider, name in con.execute(
            "SELECT host, provider_host, name FROM service "
            "WHERE provider_host IS NOT NULL AND provider_host != '' AND name IN ('dns', 'time')"):
        assert f"host/{provider}" in nodes
        if client != provider:
            assert (f"host/{client}", f"host/{provider}", name) in edges
    con.close()


def test_exports_and_report(migrated):
    v2, res = migrated
    assert _rows(v2 / "exports" / "evidence.csv")[0] == _rows(CW / "evidence-matrix.csv")[0]
    report = (v2 / "MIGRATION-REPORT.md").read_text(encoding="utf-8")
    assert f"Skipped rows ({res['skipped']})" in report
    table_lines = [l for l in report.split("## Skipped rows", 1)[1].splitlines() if l.startswith("| ")]
    assert len(table_lines) - (2 if res["skipped"] else 0) == res["skipped"]
    assert "Delta:" in report
