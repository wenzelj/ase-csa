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
