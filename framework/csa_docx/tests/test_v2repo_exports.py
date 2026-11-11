"""S587: on-demand exports — csv, md, report, read-only, and the CLI."""
import csv
import hashlib

import pytest

from csa_docx import v2_export_cli
from csa_docx.v2repo import Repo

CORE = ["hosts", "evidence", "addresses", "services", "flows", "leads", "gap_checks",
        "intake_records", "intake_files", "graph_nodes", "graph_edges", "aliases",
        "entities", "review_events", "evidence_sources", "indexed_files"]


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "v2")
    with r.tx() as con:
        r.hosts.create("ROTPRDREV101", role="RevServer", site="Site A", os="Windows Server 2019")
        r.hosts.create("H2", role="client", site="Site B")
        con.execute("INSERT INTO address(ip, scope, owner_host) VALUES ('10.0.0.1','lan','ROTPRDREV101')")
        con.execute("INSERT INTO service(host, port, protocol, name) VALUES ('ROTPRDREV101',443,'tcp','https')")
        con.execute("INSERT INTO flow(src_host, dst_host, port, protocol, purpose) "
                    "VALUES ('H2','ROTPRDREV101',443,'tcp','viewer')")
        con.execute("INSERT INTO evidence(id, claim, status, source_title) "
                    "VALUES ('E-001','ROTPRDREV101 runs RevServer','VERIFIED','Build sheet')")
        con.execute("INSERT INTO evidence(id, claim, status, source_title) "
                    "VALUES ('E-002','Unrelated claim','UNCONFIRMED','Notes')")
        con.execute("INSERT INTO lead(id, question, state) VALUES ('L-1','Where is the backup?','open')")
        con.execute("INSERT INTO intake_record(id) VALUES ('R1')")
        con.execute("INSERT INTO intake_file(record_id, rel_path, status) VALUES ('R1','a.txt','pending')")
    yield r
    r.close()


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def test_csv_hosts(repo, tmp_path):
    out = tmp_path / "hosts.csv"
    repo.export.csv("hosts", out)
    rows = _rows(out)
    assert rows[0] == ["name", "role", "site", "os", "status", "created_at", "updated_at"]
    assert len(rows) == 3


def test_csv_evidence_filter(repo, tmp_path):
    out = tmp_path / "e.csv"
    repo.export.csv("evidence", out, status="VERIFIED")
    rows = _rows(out)
    assert len(rows) == 2
    assert rows[1][rows[0].index("status")] == "VERIFIED"


def test_md_host_card(repo, tmp_path):
    out = tmp_path / "cards" / "h.md"
    repo.export.md("ROTPRDREV101", out)
    text = out.read_text(encoding="utf-8")
    assert "ROTPRDREV101" in text and "RevServer" in text and "E-001" in text
    assert "10.0.0.1" in text and "https" in text and "viewer" in text
    assert "E-002" not in text


def test_report_names_every_table(repo, tmp_path):
    out = tmp_path / "REPORT.md"
    repo.export.report(out)
    text = out.read_text(encoding="utf-8")
    for t in CORE:
        assert f"| {t} |" in text
    assert "| hosts | 2 |" in text
    assert "a.txt" in text and "L-1" in text


def test_exports_are_read_only(repo, tmp_path):
    def snap():
        return hashlib.sha256(repr([
            repo.con.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("host", "evidence", "review_event")]).encode()).hexdigest()
    before = snap()
    repo.export.csv("hosts", tmp_path / "a.csv")
    repo.export.md("ROTPRDREV101", tmp_path / "a.md")
    repo.export.report(tmp_path / "r.md")
    assert snap() == before


def test_unknown_table_clear_error(repo, tmp_path):
    with pytest.raises(ValueError, match="unknown table 'nope'"):
        repo.export.csv("nope", tmp_path / "x.csv")


def test_cli_refuses_missing_v2_dir(tmp_path, capsys):
    rc = v2_export_cli.main(["--v2-dir", str(tmp_path / "none"), "report", "--out", str(tmp_path / "r.md")])
    assert rc != 0
    assert "S586" in capsys.readouterr().err


def test_cli_export_and_bad_table(repo, tmp_path, capsys):
    v2 = str(repo.path.parent)
    out = tmp_path / "ev.csv"
    assert v2_export_cli.main(["--v2-dir", v2, "export", "--table", "evidence",
                               "--status", "VERIFIED", "--out", str(out)]) == 0
    assert len(_rows(out)) == 2
    assert v2_export_cli.main(["--v2-dir", v2, "export", "--table", "nope", "--out", str(out)]) == 2
    assert "unknown table" in capsys.readouterr().err
    assert v2_export_cli.main(["--v2-dir", v2, "host", "NOPE", "--out", str(tmp_path / "n.md")]) == 2
