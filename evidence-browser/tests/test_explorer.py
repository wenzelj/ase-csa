from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend import explorer

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path: Path) -> Path:
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>DNS</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>HOSTA uses enterprise DNS.</w:t></w:r><w:r><w:delText>HOSTB deleted</w:delText></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>[Aspect]</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Resolvers</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>hosta and HOSTC</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return path


def test_mentions_follow_headings_and_skip_deleted_and_placeholders(tmp_path: Path) -> None:
    blocks = explorer.document_blocks(make_docx(tmp_path / "csa.docx"))
    assert [b["kind"] for b in blocks] == ["paragraph", "table row"]
    found = explorer.mentions(blocks, "HOSTA")
    assert [m["section"] for m in found] == ["DNS", "DNS"]
    assert explorer.mentions(blocks, "HOSTB") == []


def spec() -> dict:
    return {"components": [{"id": "a", "host": "H1", "evidence": ["E-1"]}, {"id": "b", "host": "H2", "evidence": []},
                           {"id": "x", "host": None, "evidence": []}],
            "journeys": [{"id": "j", "evidence": [], "steps": [{"id": "s1", "transition": "t1", "evidence": ["E-1"]},
                                                              {"id": "s2", "transition": ["t2"], "evidence": []}],
                          "transitions": [{"id": "t1", "from": "a", "to": "b", "status": "verified", "edge": {"s": "H1", "t": "H2", "port": "1"}, "evidence": ["E-1"]},
                                          {"id": "t2", "from": "b", "to": "x", "status": "unknown", "edge": None, "evidence": []}]}]}


def test_valid_journey_has_no_issues() -> None:
    assert explorer._validate(spec(), {"E-1": {}}, {("H1", "H2", "1")}, {"H1", "H2"}) == []


def test_journey_rejects_missing_evidence_and_uncaptured_link() -> None:
    issues = explorer._validate(spec(), {}, set(), {"H1"})
    assert any("evidence E-1 is not in the evidence matrix" in i for i in issues)
    assert any("no captured link H1 -> H2 port 1" in i for i in issues)
    assert any("host H2 is not in the host register" in i for i in issues)


def test_verified_transition_without_link_is_an_issue() -> None:
    s = spec(); s["journeys"][0]["transitions"][1]["status"] = "verified"
    assert any("has no captured link" in i for i in explorer._validate(s, {"E-1": {}}, {("H1", "H2", "1")}, {"H1", "H2"}))


def test_build_reads_project_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "csa-work"; (work / "hosts").mkdir(parents=True); (work / "explorer").mkdir()
    (work / "evidence-matrix.csv").write_text("evidence_id,claim,status\nE-1,H1 talks to H2,VERIFIED\n", encoding="utf-8")
    (work / "hosts" / "hosts.csv").write_text("host,in_scope,system,role,site\nH1,,App,App server,Site A\nH2,,App,DB,Site A\n", encoding="utf-8")
    (work / "hosts" / "evidence_hosts.csv").write_text("evidence_id,hosts\nE-1,H1;H2\n", encoding="utf-8")
    (work / "hosts" / "host_facts.csv").write_text("host,attribute,value,source,line\nH1,os: Caption,Windows,f.txt,3\n", encoding="utf-8")
    (work / "explorer" / "journeys.json").write_text(json.dumps(spec()), encoding="utf-8")
    monkeypatch.setattr(explorer.network, "build", lambda w, a: {
        "nodes": [{"id": "H1", "kind": "captured", "role": "App server", "site": "Site A", "ips": ""},
                  {"id": "H2", "kind": "captured", "role": "DB", "site": "Site A", "ips": ""}],
        "edges": [{"s": "H1", "t": "H2", "port": "1", "procs": [], "ids": ["E-1"], "est": True}], "source": "test"})
    out = explorer.build({"work_dir": str(work), "label": "App"}, tmp_path, make_docx(tmp_path / "d.docx"))
    assert out["issues"] == []
    h1 = next(h for h in out["hosts"] if h["id"] == "H1")
    assert h1["facts"][0]["value"] == "Windows" and h1["evidence_ids"] == ["E-1"]
    assert out["evidence"]["E-1"]["claim"] == "H1 talks to H2"


def test_diagrams_draw_every_host_and_journey(tmp_path: Path, monkeypatch) -> None:
    """The System explorer's drawings come from csa_docx.techdiagram: one overview plus one flow per journey."""
    net = {"nodes": [{"id": "H1", "kind": "captured", "role": "Reveloc application server", "site": "S1", "ips": "10.0.0.1"},
                     {"id": "H2", "kind": "captured", "role": "SQL Server cluster node", "site": "S2", "ips": "10.0.0.2"},
                     {"id": "8.8.8.8", "kind": "public", "role": "", "site": "", "ips": "8.8.8.8"}],
           "edges": [{"s": "H1", "t": "H2", "port": "1433", "procs": ["app"], "ids": ["E-1"], "est": True},
                     {"s": "H1", "t": "8.8.8.8", "port": "443", "procs": [], "ids": ["E-2"], "est": True}],
           "source": "test"}
    monkeypatch.setattr(explorer.network, "build", lambda work, agents: net)
    work = tmp_path / "csa-work"; (work / "explorer").mkdir(parents=True)
    (work / "explorer" / "journeys.json").write_text(json.dumps({**spec(), "application": "APP"}), encoding="utf-8")
    import sys
    fw = str(Path(__file__).resolve().parents[2] / "framework")
    if fw not in sys.path:
        sys.path.insert(0, fw)
    out = explorer.diagrams({"key": "none", "work_dir": str(work), "label": "APP"}, tmp_path)
    ids = [d["id"] for d in out["diagrams"]]
    assert ids[0] == "system-overview" and ids[1] == "flow-j"
    over = out["diagrams"][0]
    assert {n["id"] for n in over["model"]["nodes"]} >= {"H1", "H2", "G-INTERNET"}
    assert 'data-id="H1"' in over["svg"] and over["svg"].startswith("<svg")
    flow = out["diagrams"][1]
    for d in (over, flow):
        # Both keep the detailed screen SVG and add the A4 portrait rendering of the same model.
        assert d["svg"].startswith("<svg") and 'data-id="H1"' in d["svg"]
        assert d["print_svg"].startswith("<svg") and ' width="170.0mm"' in d["print_svg"]
        assert d["print"]["width_mm"] == 170.0
        assert d["print"]["height_mm"] > 0
        assert d["print"]["min_text_pt"] > 0
        assert isinstance(d["print"]["fits_page"], bool)
        assert d["model"] is (over["model"] if d is over else flow["model"])  # one model object per diagram
    # The portrait (S323) exposes the grouped hosts and their source edges as interaction metadata.
    import re
    assert re.search(r'<g class="node"[^>]*data-hosts="([^"]*)"', over["print_svg"])
    assert re.search(r'data-line-id="([^"]+)"[^>]*data-s="([^"]*)"[^>]*data-t="([^"]*)"[^>]*data-edge-ids="([^"]*)"',
                     over["print_svg"])
    assert re.search(r'data-line-id="([^"]+)"[^>]*data-s="([^"]*)"[^>]*data-t="([^"]*)"[^>]*data-edge-ids="([^"]*)"',
                     flow["print_svg"])


def test_system_types_come_from_the_recorded_role() -> None:
    import sys
    fw = str(Path(__file__).resolve().parents[2] / "framework")
    if fw not in sys.path:
        sys.path.insert(0, fw)
    from csa_docx.techdiagram.model import classify
    cases = {"SQL Server cluster node (instance S01)": "database", "RevViewer Jump Host": "jump_host", "Siemens S7 PLC": "plc",
             "ABB RTU560": "rtu", "OSIsoft PI historian": "historian", "Wonderware HMI": "hmi", "Splunk SIEM": "logging",
             "Core switch": "switch", "VMware ESXi host": "hypervisor", "TETRA base station controller": "server", "": "unknown"}
    for role, kind in cases.items():
        assert classify(role, "captured")[0] == kind, role
    assert classify("", "dc")[0] == "directory"
