"""Figures as native Word drawings: icon paths, the shape group, the standalone document and placement."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from csa_docx.techdiagram import svgpath
from csa_docx.techdiagram.icons import ICONS, KINDS
from csa_docx.techdiagram.word_drawing import drawing_xml
from csa_docx.techdiagram.word_docx import write_docx

SCHEMA = Path(__file__).resolve().parents[1] / "techdiagram" / "model.schema.json"


def _model():
    nodes = [{"id": "APPSRV101", "label": "APPSRV101", "role": "Application server", "kind": "app_server", "zone": "dc1", "tier": "app"},
             {"id": "DBSRV101", "label": "DBSRV101", "role": "SQL Server node", "kind": "database", "zone": "dc1", "tier": "db"},
             {"id": "DCSRV101", "label": "DCSRV101", "role": "Domain controller", "kind": "directory", "zone": "it"},
             {"id": "GAP-OT", "label": "None evidenced", "role": "OT-resident time source", "kind": "gap", "zone": "shared"}]
    edges = [{"id": "E1", "s": "APPSRV101", "t": "DCSRV101", "dir": "forward", "label": "Time", "short": "", "status": "configured", "evidence": ["E-001"]},
             {"id": "E2", "s": "DBSRV101", "t": "DCSRV101", "dir": "forward", "label": "Time", "short": "not in use", "status": "inactive", "evidence": ["E-002"]},
             {"id": "E3", "s": "APPSRV101", "t": "DBSRV101", "dir": "forward", "label": "TCP 1433 SQL", "status": "observed", "evidence": ["E-003"]}]
    return {"id": "t", "title": "Time", "zones": [{"id": "it", "label": "IT (enterprise)"}, {"id": "dc1", "label": "Data centre 1"},
                                                  {"id": "shared", "label": "OT-resident services"}],
            "groups": [], "nodes": nodes, "edges": edges, "notes": ["No OT time source appears in the evidence."],
            "layout": {"dcs": ["dc1"]}}


def test_every_icon_becomes_vector_paths():
    for name, frag in ICONS.items():
        shapes = svgpath.parse(frag)
        assert shapes and all(s["subpaths"] for s in shapes), name
        for s in shapes:
            for sub in s["subpaths"]:
                assert {seg[0] for seg in sub} <= {"M", "L", "C", "Z"}, name
    assert {i for i, _, _ in KINDS.values()} <= set(ICONS)
    for k in ("wireless", "cloud", "api", "vm", "rack", "workstation", "scada", "dhcp", "firewall", "router", "switch", "plc"):
        assert k in KINDS


def test_arcs_and_relative_commands_become_absolute_curves():
    sub = svgpath.path_d("M8.2 4.8a5.5 5.5 0 0 0 0 6.4")[0]
    assert sub[0] == ("M", 8.2, 4.8) and sub[-1][0] == "C"
    assert abs(sub[-1][-2] - 8.2) < 1e-6 and abs(sub[-1][-1] - 11.2) < 1e-6
    sub = svgpath.path_d("m2 6 10 7 10-7")[0]
    assert sub == [("M", 2, 6), ("L", 12, 13), ("L", 22, 6)]


def test_drawing_is_one_group_of_editable_shapes():
    run, info = drawing_xml(_model(), width_mm=170)
    assert "wordprocessingGroup" in run and "<wpg:wgp>" in run and "<pic:pic" not in run
    assert info["shapes"] >= 20 and info["cards"] == 4          # one nested group per card
    for name in ("APPSRV101", "DBSRV101", "DCSRV101", "None evidenced", "Application server"):
        assert f">{name}<" in run                                 # every label is real, editable text
    assert "<a:custGeom>" in run and ('<a:tailEnd type="triangle"' in run or '<a:headEnd type="triangle"' in run) and "<a:custDash>" in run
    assert abs(info["width_mm"] - 170) < 0.01


def test_picture_fallback_is_alternate_content():
    run, _ = drawing_xml(_model(), png_rid="rId9")
    assert run.startswith("<mc:AlternateContent") and 'Requires="wpg"' in run and 'r:embed="rId9"' in run


def test_standalone_document_opens_and_has_a_numbered_caption(tmp_path):
    out = write_docx(tmp_path / "f.docx", _model(), "3.4 Time", "Hosts take time from IT", "Source: test", ["A note."])
    with zipfile.ZipFile(out["path"]) as z:
        doc = z.read("word/document.xml").decode()
        assert "word/styles.xml" in z.namelist()
    assert "SEQ Figure" in doc and "Hosts take time from IT" in doc and "A note." in doc and "<wpg:wgp>" in doc
    assert re.search(r'<w:pgSz w:w="\d+" w:h="\d+"', doc)


def test_place_as_word_drawing_is_tracked(tmp_path):
    import importlib
    T = importlib.import_module("csa_docx.tests.test_figures")
    from csa_docx.figures import place as PL
    d, png = T._docx(tmp_path / "w.docx"), tmp_path / "f.png"
    png.write_bytes(T._png())
    r = PL.place(d, "Time", 2, "TIME", png, "Hosts take time from IT", "Source: test", "Tester", close_word=False,
                 word={"model": _model(), "aggregate": False})
    assert r["status"] == "OK" and "Word shapes" in r["message"]
    x = T._xml(d)
    assert "<w:ins " in x and "<wpg:wgp>" in x and "mc:AlternateContent" in x and "_CSAFig_TIME" in x


def test_schema_lists_every_kind():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    kinds = set(schema["properties"]["nodes"]["items"]["properties"]["kind"]["enum"])
    assert set(KINDS) <= kinds


def test_band_design_layers_roles_and_function_lines():
    from csa_docx.techdiagram.band_layout import render_band_svg, classify
    svg, info = render_band_svg(_model())
    # IT, boundary and OT bands, top to bottom
    assert svg.index("IT AND INTERNET") < svg.index("IT / OT BOUNDARY") < svg.index("OPERATIONAL TECHNOLOGY")
    assert 'fill="#f2f7fc"' in svg and 'fill="#fff8f0"' in svg and 'fill="#f1f9f7"' in svg
    # one line per function: directory services in purple, no alarm red on lines
    assert 'stroke="#7b5ea7"' in svg and 'class="edge"' in svg
    assert not any('stroke="#c4432b"' in ln or 'stroke="#cf222e"' in ln for ln in svg.split("\n") if 'class="edge"' in ln)
    assert "Directory, name and time services" in svg and info["min_text_pt"] >= 8
    assert classify("SMB", {"directory"}) == "directory" and classify("SMB", set()) == "management"
    assert classify("HTTPS", set()) == "web" and classify("TCP 56403", set()) == "other" and classify("sqlservr", set()) == "application"
    run, _ = drawing_xml(_model())
    assert 'val="DDEDF2"' in run and 'val="7B5EA7"' in run                  # icon fills and line colours survive in Word


def test_band_design_puts_jump_hosts_in_the_boundary_and_joins_sites_for_conduits():
    from csa_docx.techdiagram.band_layout import build
    m = _model()
    m["nodes"].append({"id": "JMP101", "label": "JMP101", "role": "Jump host", "kind": "jump_host", "zone": "dc1"})
    m["edges"].append({"id": "E9", "s": "JMP101", "t": "APPSRV101", "dir": "forward", "label": "TCP 3389 RDP", "status": "observed"})
    B = build(m, conduits=True)
    assert any(t["band"] == "boundary" and t["kind"] == "jump_host" for t in B["tiles"].values())
    assert any(l["t"].startswith("Z:ot|dc1") and l["fn"] == "management" for l in B["lines"])
