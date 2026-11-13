"""TETRA scope classification tests use a temporary database only."""

import csv
from pathlib import Path

from csa_docx.v2repo import Repo


ROOT = Path(__file__).resolve().parents[4]
REGISTER = ROOT / "TETRA/06 REVELOC TETRA/csa-work/hosts/hosts.csv"


def test_tetra_register_has_expected_owned_and_peer_populations(tmp_path):
    rows = list(csv.DictReader(REGISTER.open(encoding="utf-8", newline="")))
    owned = [r for r in rows if r["in_scope"] in {"Yes", "No"}]
    peers = [r for r in rows if r["in_scope"] == "peer"]
    assert len(owned) == 26
    assert len(peers) == 144

    repo = Repo(tmp_path / "v2")
    with repo.tx():
        for row in rows:
            repo.hosts.create(row["host"], role=row.get("role") or None, site=row.get("site") or None)
            repo.application_scope.add(
                "tetra-reveloc", row["host"],
                "owned" if row["in_scope"] in {"Yes", "No"} else "peer",
                basis=f"hosts.csv:in_scope={row['in_scope']}",
                source_ref="hosts/hosts.csv",
                active=row["in_scope"] in {"Yes", "No"},
            )
    assert len(repo.application_scope.list_app_hosts("tetra-reveloc", membership="owned")) == 26
    assert len(repo.application_scope.list_app_hosts("tetra-reveloc", membership="peer", active=False)) == 144
    repo.close()
