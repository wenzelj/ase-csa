"""Figures: service relationships from evidence, residency, and where a section needs a figure."""
from __future__ import annotations

import csv
from pathlib import Path

from csa_docx.figures import need as N
from csa_docx.figures import relations as R

RULE = {"residency": {"it_domains": ["corp.example"], "ot_domains": ["ot.example"], "evidence": ["E-9"]}}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def _work(tmp_path: Path) -> Path:
    _write(tmp_path / "evidence-matrix.csv", [
        {"evidence_id": "E-1", "status": "VERIFIED", "claim": "APPSRV101: Active NTP peer DCSRV101.corp.example"},
        {"evidence_id": "E-2", "status": "VERIFIED", "claim": "time.windows.com is configured as a pending peer on APPSRV101 and DBSRV101."},
        {"evidence_id": "E-3", "status": "VERIFIED", "claim": "APPSRV101 and DBSRV101 use DNS servers 10.0.0.5, 10.9.9.9"},
        {"evidence_id": "E-4", "status": "REJECTED", "claim": "DBSRV101: Active NTP peer ROGUE101"},
        {"evidence_id": "E-5", "status": "VERIFIED", "claim": "All hosts use DNS servers 10.0.0.5"},
    ])
    _write(tmp_path / "hosts" / "hosts.csv", [
        {"host": "APPSRV101", "ips": "10.1.0.1", "system": "Demo", "in_scope": "yes", "fqdn": "appsrv101.corp.example", "sources": "", "ad_site": ""},
        {"host": "DBSRV101", "ips": "10.1.0.2", "system": "Demo", "in_scope": "yes", "fqdn": "dbsrv101.corp.example", "sources": "", "ad_site": ""},
        {"host": "DCSRV101", "ips": "10.0.0.5", "system": "", "in_scope": "peer", "fqdn": "dcsrv101.corp.example", "sources": "domain controller list", "ad_site": "A"},
        {"host": "OTDC101", "ips": "10.2.0.5", "system": "", "in_scope": "peer", "fqdn": "otdc101.ot.example", "sources": "", "ad_site": ""},
    ])
    _write(tmp_path / "hosts" / "host_facts.csv", [
        {"host": "DBSRV101", "attribute": "time_status: Source", "value": "DCSRV101.corp.example", "source": "/x/DBSRV101.txt", "line": "42"},
    ])
    return tmp_path


def test_time_relations_cite_their_evidence_and_skip_rejected_rows(tmp_path):
    rel = R.relations(_work(tmp_path), ["time"])["time"]
    active = {(r["consumer"], r["provider"]): r for r in rel if r["state"] == "active"}
    assert active[("APPSRV101", "DCSRV101")]["evidence"] == ["E-1"]
    assert active[("DBSRV101", "DCSRV101")]["evidence"] == ["DBSRV101.txt line 42"]   # from the capture
    assert ("DBSRV101", "ROGUE101") not in active                                      # rejected row
    pending = {r["consumer"] for r in rel if r["state"] == "inactive" and r["provider"] == "time.windows.com"}
    assert pending == {"APPSRV101", "DBSRV101"}


def test_dns_relations_keep_order_and_name_known_addresses(tmp_path):
    rel = R.relations(_work(tmp_path), ["dns"])["dns"]
    app = sorted((r["order"], r["provider"]) for r in rel if r["consumer"] == "APPSRV101")
    assert app == [(1, "DCSRV101"), (2, "10.9.9.9")]
    assert all(r["evidence"] == ["E-3"] for r in rel)          # the summary row names no host: not used


def test_residency_follows_the_stated_rule_only(tmp_path):
    ev = R.load(_work(tmp_path))
    assert R.residency("DCSRV101", ev, RULE)[0] == "it"
    assert R.residency("OTDC101", ev, RULE)[0] == "ot"
    assert R.residency("APPSRV101", ev, RULE)[0] == "unknown"   # member of IT domain, not a DC: not stated
    assert R.residency("10.9.9.9", ev, RULE)[0] == "unknown"
    assert R.residency("8.8.8.8", ev, RULE)[0] == "internet"
    assert R.residency("time.windows.com", ev, RULE)[0] == "internet"


def _node(key, title, ids=(), kind="section", level=2):
    reqs = [{"id": i, "text": "t", "current_state": "", "rating": ""} for i in ids]
    return {"key": key, "number": "", "title": title, "level": level, "kind": kind, "figures": [],
            "parts": [{"kind": "requirement", "requirements": reqs}] if reqs else []}


def test_need_marks_time_needed_and_unbuilt_kinds_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    spec = {"nodes": [_node("TIME", "Time", ["SEP-TIME-01"]), _node("NETWORK", "PKI", ["SEP-PKI-01"]),
                      _node("ISOLATION", "Isolation", ["SEP-ISO-01"]), _node("ANNEX", "Annex", kind="container", level=1)]}
    rows = {r["key"]: r for r in N.assess(spec, _work(tmp_path), "demo")}
    assert rows["TIME"]["status"] == "needed" and rows["TIME"]["archetype"] == "B"
    assert "2 vital hosts take time" in rows["TIME"]["reason"]
    assert rows["NETWORK"]["status"] == "not-built"
    assert rows["ISOLATION"]["status"] == "not-useful"
    assert rows["ANNEX"]["status"] == "none"


def test_need_reports_a_figure_already_in_the_document(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    n = _node("TIME", "Time", ["SEP-TIME-01"])
    n["figures"] = [{"image": True, "placeholder": False}]
    assert N.assess({"nodes": [n]}, _work(tmp_path), "demo")[0]["status"] == "placed"


# ------------------------------------------------------------------ brief, wording check, fit
from csa_docx.figures import brief as BR
from csa_docx.figures import fit as FT


def _time_rows(tmp_path):
    ev = R.load(_work(tmp_path))
    return ev, N.scope_relations("time", ev, RULE)


def test_brief_ties_items_to_evidence_and_lists_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    ev, rows = _time_rows(tmp_path)
    node = _node("TIME", "Time", ["SEP-TIME-01"])
    node["parts"][0]["requirements"][0]["current_state"] = "APPSRV101 takes time from DCSRV101. No OT-local time source."
    row = {**N.assess({"nodes": [node]}, tmp_path, "demo")[0]}
    b = BR.build(row, node, ev, RULE, rows)
    whats = [i["what"] for i in b["items"]]
    assert any("DCSRV101" in w and "enterprise (IT)" in w for w in whats)
    assert any(i["status"] == "absent" for i in b["items"])               # no OT time source: the finding
    assert b["items"][0]["section_says"].startswith("APPSRV101 takes time")
    assert "no OT-resident time source" in b["caption"]["text"]
    assert "E-001" in b["source"]["text"]


def test_wording_that_names_something_not_in_the_figure_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    ev, rows = _time_rows(tmp_path)
    node = _node("TIME", "Time", ["SEP-TIME-01"])
    row = N.assess({"nodes": [node]}, tmp_path, "demo")[0]
    b = BR.build(row, node, ev, RULE, rows)
    assert BR.wording_check(b, caption="Vital hosts take time from DCSRV101, outside OT") == []
    bad = BR.wording_check(b, caption="7 hosts take time from ROGUE999 and 8.8.8.8")
    assert any("ROGUE999" in p for p in bad) and any("8.8.8.8" in p for p in bad) and any("number 7" in p for p in bad)
    b2, problems = BR.edit(b, caption="Taken from ROGUE999")
    assert problems and b2["caption"]["by"] == "framework"


def test_fit_flags_text_that_contradicts_the_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    ev, rows = _time_rows(tmp_path)
    rows = rows + [{"service": "time", "consumer": "DBSRV101", "provider": "OTDC101", "order": 1, "state": "active",
                    "evidence": ["E-9"], "text": "", "side": "ot", "side_reason": ""}]
    node = _node("TIME", "Time", ["SEP-TIME-01"])
    node["parts"][0]["requirements"][0].update(current_state="OTDC101 is the time source of APPSRV101.", rating="Met")
    row = N.assess({"nodes": [node]}, tmp_path, "demo")[0]
    b = BR.build(row, node, ev, RULE, rows)
    model = {"nodes": [{"id": h, "label": h} for h in ("APPSRV101", "DBSRV101", "DCSRV101", "time.windows.com")], "groups": []}
    res = FT.check(node, b, model, rows, set(ev["register"]))
    flags = [c["text"] for c in res["checks"] if c["level"] == "flag"]
    assert any("APPSRV101 takes it from OTDC101" in f for f in flags)
    assert any("rated Met" in f for f in flags)


# ------------------------------------------------------------------ placing a figure (tracked)
import struct
import zipfile
import zlib

from csa_docx.figures import place as PL

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _png(w=40, h=20) -> bytes:
    raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _docx(path: Path) -> Path:
    body = (_p("Summary", "Heading2") + _p("Text.") + _p("[Insert figure here]", "Figure")
            + '<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t xml:space="preserve">Figure </w:t></w:r>'
              '<w:fldSimple w:instr=" SEQ Figure \\* ARABIC "><w:r><w:t>1</w:t></w:r></w:fldSimple><w:r><w:t>: [Figure caption]</w:t></w:r></w:p>'
            + _p("Source: [originator]", "FigureSource")
            + _p("Time", "Heading2") + _p("Discovery Information", "Heading3")
            + "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>" + _p("Drawbridge Impact", "Heading3")
            + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:left="1134" w:right="1134" w:top="1134" w:bottom="1134"/></w:sectPr>')
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
        z.writestr("word/document.xml", doc)
    return path


def _xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode()


def test_place_inserts_after_discovery_information_then_replaces(tmp_path):
    d, png = _docx(tmp_path / "w.docx"), tmp_path / "f.png"
    png.write_bytes(_png())
    r = PL.place(d, "Time", 2, "TIME", png, "Hosts take time from IT", "Source: test", "Tester", close_word=False)
    assert r["status"] == "OK" and r["mode"] == "insert"
    x = _xml(d)
    assert x.index("_CSAFig_TIME") > x.index("</w:tbl>") and x.index("_CSAFig_TIME") < x.index("Drawbridge Impact")
    assert "<w:ins " in x and "SEQ Figure" in x and "Hosts take time from IT" in x and 'w:author="Tester"' in x
    with zipfile.ZipFile(d) as z:
        assert any(n.startswith("word/media/csa-figure-time") for n in z.namelist())
        assert 'Extension="png"' in z.read("[Content_Types].xml").decode()
    r2 = PL.place(d, "Time", 2, "TIME", png, "New caption", "Source: test", "Tester", close_word=False, backup=False)
    assert r2["mode"] == "replace"
    x = _xml(d)
    assert "<w:delText" in x and "New caption" in x and x.count('w:name="_CSAFig_TIME"') == 2     # old (deleted) and new
    with zipfile.ZipFile(d) as z:
        assert sum(n.startswith("word/media/csa-figure-time") for n in z.namelist()) == 2      # the old image stays for Reject


def test_place_fills_the_template_slot(tmp_path):
    d, png = _docx(tmp_path / "w.docx"), tmp_path / "f.png"
    png.write_bytes(_png())
    r = PL.place(d, "Summary", 2, "EXECUTIVE_SUMMARY", png, "The system", "Source: captures", "Tester", close_word=False)
    assert r["status"] == "OK" and r["mode"] == "slot"
    x = _xml(d)
    assert "[Insert figure here]</w:delText>" in x and ": [Figure caption]</w:delText>" in x
    assert ": The system" in x and 'SEQ Figure' in x and "Source: captures" in x
    r2 = PL.place(d, "Summary", 2, "EXECUTIVE_SUMMARY", png, "Again", "Source: captures", "Tester", close_word=False, backup=False)
    assert r2["mode"] == "replace"


def test_place_refuses_a_section_it_cannot_find(tmp_path):
    d, png = _docx(tmp_path / "w.docx"), tmp_path / "f.png"
    png.write_bytes(_png())
    assert PL.place(d, "Nowhere", 2, "X", png, "c", "s", "T", close_word=False)["status"] == "BLOCKED"


def test_a_placed_figure_keeps_its_profile_so_it_can_be_redrawn(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_layout", lambda key: RULE)
    n = _node("TIME", "Time", ["SEP-TIME-01"])
    n["figures"] = [{"image": True, "placeholder": False}]
    row = N.assess({"nodes": [n]}, _work(tmp_path), "demo")[0]
    assert row["status"] == "placed" and row["profile"] == "time" and row["archetype"] == "B"


def test_place_finds_a_heading_with_an_ampersand(tmp_path):
    d, png = _docx(tmp_path / "w.docx"), tmp_path / "f.png"
    png.write_bytes(_png())
    x = _xml(d).replace(">Time<", ">Management &amp; Access<")
    with zipfile.ZipFile(d) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = x.encode()
    with zipfile.ZipFile(d, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)
    assert PL.place(d, "Management & Access", 2, "MGT", png, "c", "s", "T", close_word=False)["status"] == "OK"


def test_print_layout_keeps_text_at_8pt_or_more():
    from csa_docx.techdiagram.print_layout import render_print_svg
    nodes = [{"id": f"H{i}", "label": f"HOSTNAME{i:03d}", "role": "Application server", "kind": "app_server", "zone": "dc1",
              "tier": "app"} for i in range(6)] + [{"id": "P", "label": "PROVIDER1", "role": "Domain controller", "kind": "directory", "zone": "it"}]
    edges = [{"id": f"E{i}", "s": f"H{i}", "t": "P", "dir": "forward", "label": "Time", "short": "", "status": "configured",
              "evidence": ["E-1"]} for i in range(6)]
    model = {"id": "t", "title": "t", "zones": [{"id": "it", "label": "IT"}, {"id": "dc1", "label": "Data centre 1"}],
             "groups": [], "nodes": nodes, "edges": edges, "notes": ["A note."], "layout": {"dcs": ["dc1"]}}
    svg, info = render_print_svg(model)
    assert info["min_text_pt"] >= 8 and info["fits_page"] and 'width="170.0mm"' in svg
    assert "HOSTNAME000–005" in svg and "PROVIDER1" in svg          # one icon for the role, its hosts as a range


def test_transfer_scope_keeps_the_recorded_backup_path(tmp_path):
    from csa_docx.techdiagram import views as V
    assert "7000" in V.TRANSFER_PORTS                                  # the PPDM agentService data path is a transfer
    over = {
        "nodes": [{"id": "ROTPRDPDM101", "kind": "named", "zone": "nosite"},
                  {"id": "MOTPRDCLU101", "kind": "app_server", "zone": "mky"}],
        "edges": [
            {"id": "E1", "s": "ROTPRDPDM101", "t": "MOTPRDCLU101", "dir": "forward", "status": "observed",
             "detail": {"ports": {"7000": 1}, "hosts": ["MOTPRDCLU101"]}},
            {"id": "E2", "s": "ROTPRDPDM101", "t": "MOTPRDCLU101", "dir": "forward", "status": "observed",
             "detail": {"ports": {"135": 1}, "hosts": ["MOTPRDCLU101"]}},
        ],
        "groups": [], "notes": [],
        "zones": [{"id": "nosite", "label": "Site not recorded"},
                  {"id": "mky", "label": "Mackay"}],
    }
    prof = {"data_centres": [{"key": "mky", "label": "Mackay", "sites": ["OT Mackay"]}]}
    # the model passed to conduit_view has already rolled same-zone ends to Z:<zone>
    over["edges"][0]["t"] = "Z:mky"
    over["edges"][1]["t"] = "Z:mky"
    v = V.conduit_view(over, prof, key="STOR", title="t", subtitle="s", scope="transfer")
    kept = {(e["s"], e["t"]) for e in v["edges"]}
    assert ("ROTPRDPDM101", "Z:mky") in kept and "MOTPRDCLU101" in {n["id"] for n in v["nodes"]}
    assert not any(str(135) in {str(p) for p in (e.get("detail") or {}).get("ports", {})} for e in v["edges"])
