"""S589: v2 ingest - the six `csa ingest` steps against csa.sqlite."""
import hashlib

import pytest

from csa_docx import v2_ingest
from csa_docx.v2repo import Repo

DD = "Discovery Data"


@pytest.fixture
def proj(tmp_path):
    """A source set with 3 new files (a, b, c), 1 changed (d) and 1 removed (gone), and a seeded repo."""
    root = tmp_path / "proj"
    src = root / DD
    src.mkdir(parents=True)
    (src / "a.txt").write_text("alpha line\nHost: HOSTA address 10.0.0.1\n")
    (src / "b.txt").write_text("bravo line\n")
    (src / "c.txt").write_text("charlie line\n")
    (src / "d.txt").write_text("delta now says something else\nstill has the stable quote here\n")
    v2 = root / "csa-work-v2"
    r = Repo(v2)
    with r.tx() as con:
        r.hosts.create("DNS01", role="Domain controller", site="S1")
        r.hosts.create("HOSTA", role="Application server", site="S1")
        con.execute("INSERT INTO service (host, provider_host, name) VALUES ('HOSTA', 'DNS01', 'dns')")
        con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES (?, 'old', 1)", (f"{DD}/d.txt",))
        con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES (?, 'old', 1)", (f"{DD}/gone.txt",))
        con.execute("INSERT INTO indexed_chunk(rel_path, heading, text) VALUES (?, 'lines 1-1', 'gone text')",
                    (f"{DD}/gone.txt",))
        r.evidence.create("HOSTA runs the application", f"{DD}/gone.txt", excerpt="gone text",
                          area="3.1 Hosting", question="What does HOSTA run?")
        r.evidence.create("old delta quote", f"{DD}/d.txt", excerpt="the old quote",
                          area="3.2 Network", question="What did delta say?")
        r.evidence.create("stable delta quote", f"{DD}/d.txt", excerpt="still has the stable quote here",
                          area="3.3 Other", question="What is stable?")
        r.evidence.create("alpha", f"{DD}/a.txt", excerpt="alpha line", area="3.4 Other", question="What is alpha?")
    r.close()
    cards = v2 / "cards"
    cards.mkdir()
    (cards / "HOSTING.answer.md").write_text("HOSTA runs the application [E-001].\n")
    (cards / "NETWORK.answer.md").write_text("Delta [E-002] and stable [E-003].\n")
    (cards / "OTHER.answer.md").write_text("Stable [E-003], alpha [E-004].\n")
    return root, v2


def _count(r, sql, *args):
    return r.con.execute(sql, args).fetchone()[0]


def test_run_ingest_summary_and_tables(proj):
    root, v2 = proj
    s = v2_ingest.run_ingest(root, v2)
    assert tuple(s) == v2_ingest.SUMMARY_KEYS
    r = Repo(v2)
    try:
        assert s == {
            "indexed_files_added": 3,
            "indexed_files_changed": 1,
            "indexed_files_removed": 1,
            "graph_nodes": _count(r, "SELECT COUNT(*) FROM graph_node"),
            "graph_edges": _count(r, "SELECT COUNT(*) FROM graph_edge"),
            "evidence_rejected": 1,
            "evidence_recheck": 1,
            "estate_servers": 1,
            "model_build": "skipped (DB is the model)",
            "stale_subsections": 2,
            "pending_intake_files": 4,
        }
        assert s["graph_nodes"] > 0 and s["graph_edges"] > 0
        # the 4 current files are indexed, the removed one is gone with its chunks
        assert {x[0] for x in r.con.execute("SELECT rel_path FROM indexed_file")} == {f"{DD}/{n}.txt" for n in "abcd"}
        assert _count(r, "SELECT COUNT(*) FROM indexed_chunk WHERE rel_path=?", f"{DD}/gone.txt") == 0
        assert _count(r, "SELECT COUNT(*) FROM indexed_chunk") == 4
        assert _count(r, "SELECT COUNT(*) FROM fts") == 4
        assert _count(r, "SELECT COUNT(*) FROM indexed_file WHERE length(sha256) = 64") == 4
        assert _count(r, "SELECT COUNT(*) FROM entity") > 0
        # what came in: one record, 4 pending files and the removed one
        rows = r.con.execute("SELECT rel_path, status FROM intake_file ORDER BY rel_path").fetchall()
        assert rows == [(f"{DD}/{n}.txt", "pending") for n in "abcd"] + [(f"{DD}/gone.txt", "removed")]
        assert _count(r, "SELECT COUNT(*) FROM intake_record") == 1
        assert [f["rel_path"] for f in r.intake.pending()] == [f"{DD}/{n}.txt" for n in "abcd"]
        # evidence: the row on the removed file is rejected, the lost quote is listed for re-check
        assert r.evidence.get("E-001")["review_state"] == "rejected"
        assert r.con.execute("SELECT actor, note FROM review_event WHERE action='reject' AND subject_id='E-001'"
                             ).fetchone() == ("evidence-refresh", "source removed")
        assert [r.evidence.get(i)["review_state"] for i in ("E-002", "E-003", "E-004")] == ["proposed"] * 3
        rec = r.con.execute("SELECT subject_type, subject_id, note FROM review_event "
                            "WHERE action='evidence.refresh.recheck'").fetchall()
        assert [x[:2] for x in rec] == [("evidence", "E-002")]
        assert f"{DD}/d.txt" in rec[0][2]
    finally:
        r.close()


def test_second_run_is_quiet(proj):
    root, v2 = proj
    v2_ingest.run_ingest(root, v2)
    s = v2_ingest.run_ingest(root, v2)
    assert (s["indexed_files_added"], s["indexed_files_changed"], s["indexed_files_removed"]) == (0, 0, 0)
    assert s["evidence_rejected"] == 0 and s["evidence_recheck"] == 0
    assert s["pending_intake_files"] == 4
    r = Repo(v2)
    try:
        assert _count(r, "SELECT COUNT(*) FROM intake_record") == 1
        assert _count(r, "SELECT COUNT(*) FROM intake_file") == 5
    finally:
        r.close()


def test_migrated_sha1_is_not_a_change(tmp_path):
    root = tmp_path / "p"
    (root / DD).mkdir(parents=True)
    (root / DD / "a.txt").write_text("alpha\n")
    v2 = root / "csa-work-v2"
    r = Repo(v2)
    with r.tx() as con:
        con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES (?, ?, 6)",
                    (f"{DD}/a.txt", hashlib.sha1(b"alpha\n").hexdigest()))
    r.close()
    s = v2_ingest.run_ingest(root, v2)
    assert (s["indexed_files_added"], s["indexed_files_changed"], s["pending_intake_files"]) == (0, 0, 0)


def test_rebuild_drops_and_rebuilds_index_tables(proj):
    root, v2 = proj
    v2_ingest.run_ingest(root, v2)
    r = Repo(v2)
    with r.tx() as con:
        con.execute("INSERT INTO indexed_chunk(rel_path, heading, text) VALUES (?, 'x', 'bogus')", (f"{DD}/a.txt",))
    r.close()
    assert v2_ingest.run_ingest(root, v2)["indexed_files_changed"] == 0
    r = Repo(v2)
    before = _count(r, "SELECT COUNT(*) FROM indexed_chunk")      # a plain run keeps the stray chunk
    r.close()
    s = v2_ingest.run_ingest(root, v2, rebuild=True)
    r = Repo(v2)
    try:
        assert before == 5
        assert _count(r, "SELECT COUNT(*) FROM indexed_chunk") == 4
        assert _count(r, "SELECT COUNT(*) FROM indexed_chunk WHERE text='bogus'") == 0
        assert _count(r, "SELECT COUNT(*) FROM fts") == 4
        assert _count(r, "SELECT COUNT(*) FROM indexed_file") == 4
    finally:
        r.close()
    assert (s["indexed_files_added"], s["indexed_files_changed"], s["indexed_files_removed"]) == (0, 0, 0)


def test_estate_reads_hosts(tmp_path):
    root = tmp_path / "p"
    (root / DD).mkdir(parents=True)
    v2 = root / "csa-work-v2"
    r = Repo(v2)
    with r.tx() as con:
        for name in ("APP1", "APP2", "OLD1"):
            r.hosts.create(name, role="Application server")
        con.executemany("INSERT INTO service (host, provider_host, name) VALUES (?, ?, ?)", [
            ("APP1", "dns01.example.internal", "dns"), ("APP2", "DNS01", "dns"), ("APP1", "NTP01", "time"),
            ("OLD1", "DNS99", "dns"), ("APP1", "FILE01", "smb"), ("APP2", None, "dns")])
        r.hosts.retire("OLD1")
    try:
        assert v2_ingest.estate_servers(r) == ["DNS01", "NTP01"]
        with r.tx():
            r.hosts.retire("APP1")
        assert v2_ingest.estate_servers(r) == ["DNS01"]
        with r.tx():
            r.hosts.reactivate("APP1")
    finally:
        r.close()
    assert v2_ingest.run_ingest(root, v2)["estate_servers"] == 2


def test_model_step_is_a_noop(proj):
    root, v2 = proj
    v2_ingest.run_ingest(root, v2)
    r = Repo(v2)
    try:
        assert _count(r, "SELECT COUNT(*) FROM review_event WHERE action='model.build.skipped'") == 1
    finally:
        r.close()
    assert not list(root.rglob("model.sqlite"))


def test_stale_step_reads_evidence(proj):
    root, v2 = proj
    r = Repo(v2)
    try:
        assert v2_ingest.stale_subsections(r, v2) == {}
        with r.tx():
            r.evidence.reject("E-004", by="test", note="seeded")
        assert v2_ingest.stale_subsections(r, v2) == {"OTHER": ["E-004"]}
        assert v2_ingest.stale_subsections(r, v2, recheck=["E-002"]) == {"NETWORK": ["E-002"], "OTHER": ["E-004"]}
    finally:
        r.close()
    lines = []
    s = v2_ingest.run_ingest(root, v2, log=lambda n, name, line: lines.append((n, line)))
    assert s["stale_subsections"] == 3
    assert "HOSTING, NETWORK, OTHER" in lines[5][1]


def test_log_callback_one_line_per_step(proj):
    root, v2 = proj
    seen = []
    v2_ingest.run_ingest(root, v2, log=lambda n, name, line: seen.append((n, name)))
    assert seen == list(enumerate(v2_ingest.STEP_NAMES, 1))


def test_missing_source_changes_nothing(proj):
    root, v2 = proj
    with pytest.raises(FileNotFoundError):
        v2_ingest.run_ingest(root, v2, sources=[root / "not there"])
    r = Repo(v2)
    try:
        assert _count(r, "SELECT COUNT(*) FROM indexed_file") == 2
        assert _count(r, "SELECT COUNT(*) FROM intake_file") == 0
    finally:
        r.close()
