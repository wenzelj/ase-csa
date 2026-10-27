"""Topic tables: role grouping, common sentence, uncaptured hosts, no totals, placement in the document."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import host_settings, topic_tables as tt  # noqa: E402

PROFILE = {"topic": "Time Synchronisation", "key": "TIME", "headings": ["Time Synchronisation"],
           "requirements": ["SEP-TIME-01"],
           "columns": [{"label": "Time source", "attribute": "time.source", "common": "take time from {value}"},
                       {"label": "Fallback peer", "attribute": "time.fallback", "common": "have fallback peer {value}",
                        "common_none": "have no fallback peer"},
                       {"label": "Poll interval", "attribute": "time.poll", "common": "poll every {value}"},
                       {"label": "Time service", "attribute": "time.service", "common": "run the {value}"},
                       {"label": "Empty", "attribute": "time.nothing"}]}


def _s(**attrs):
    return {k: {"value": v, "source": f"cap/03_time_status.txt line {i}"} for i, (k, v) in enumerate(attrs.items(), 1)}


def S(src, poll="1,024 s", fb="None"):
    return _s(**{"time.source": src, "time.poll": poll, "time.fallback": fb, "time.service": "Windows Time Service"})


HOSTS = [
    {"host": "ROTSQL1", "role": "SQL node", "site": "Rockhampton"},
    {"host": "ROTSQL2", "role": "SQL node", "site": "Rockhampton"},
    {"host": "MOTSQL3", "role": "SQL node", "site": "Mackay"},
    {"host": "ROTAPP1", "role": "App server", "site": "Rockhampton"},
    {"host": "ROTAPP2", "role": "App server", "site": "Rockhampton"},      # not captured, one variant -> dagger
    {"host": "ROTWEB1", "role": "Web server", "site": "Rockhampton"},      # no captured host in role -> gap only
    {"host": "MOTSQL9", "role": "SQL node", "site": "Mackay"},             # not captured, role varies -> double dagger
    {"host": "SQLX", "role": "", "site": ""},                              # no role -> left out
]
SETTINGS = {"ROTSQL1": S("SRV1 (10.0.0.1)"), "ROTSQL2": S("SRV1 (10.0.0.1)"), "MOTSQL3": S("SRV2 (10.0.0.2)"),
            "ROTAPP1": S("SRV1 (10.0.0.1)", poll="32,768 s")}


def build(tmp_path, hosts=HOSTS, settings=SETTINGS):
    (tmp_path / "hosts").mkdir(exist_ok=True)
    (tmp_path / "hosts" / "sites.txt").write_text("Rockhampton\nMackay\n")
    return tt.build(tmp_path, "Time Synchronisation", profile=PROFILE, hosts=hosts, settings=settings)


def test_columns_follow_the_data(tmp_path):
    t = build(tmp_path)
    assert t["columns"] == ["Role", "Hosts", "Time source", "Poll interval"]     # fallback, service same; Empty dropped
    assert t["common"] == "All hosts in this table have no fallback peer and run the Windows Time Service."


def test_role_split_only_where_values_differ(tmp_path):
    rows = [r for r in build(tmp_path)["rows"] if r["role"] == "SQL node"]
    assert [r["hosts"] for r in rows] == [["ROTSQL1", "ROTSQL2"], ["MOTSQL3"], ["MOTSQL9" + tt.VARIES]]
    assert [r["first"] for r in rows] == [True, False, False]
    assert rows[2]["cells"] == ["Not captured", "Not captured"]


def test_uncaptured_host_takes_its_role_values(tmp_path):
    t = build(tmp_path)
    app = [r for r in t["rows"] if r["role"] == "App server"]
    assert app == [{"role": "App server", "first": True, "hosts": ["ROTAPP1", "ROTAPP2" + tt.ASSUMED],
                    "cells": ["SRV1 (10.0.0.1)", "32,768 s"], "sources": app[0]["sources"]}]
    assert any("ROTAPP2" in g["text"] and g["text"].startswith("Confirm") for g in t["gaps"])
    assert tt.ASSUMED + " Not captured, assumed to match" in " ".join(t["markers"])


def test_role_without_capture_is_a_gap_not_a_row(tmp_path):
    t = build(tmp_path)
    assert not [r for r in t["rows"] if r["role"] == "Web server"]
    g = [g for g in t["gaps"] if g["role"] == "Web server"][0]
    assert g["dr_id"].startswith("DR-TIME-T") and "no host of this role was captured" in g["text"]
    assert t["unassigned"] == ["SQLX"]


def test_no_counts_or_totals_anywhere(tmp_path):
    t = build(tmp_path)
    text = tt.markdown(t) + " ".join(g["text"] for g in t["gaps"])
    assert not re.search(r"\b(\d+ of \d+|\d+ hosts?|one|two|three|nine|twelve) (captured )?hosts?\b", text, re.I)


def test_every_cell_keeps_its_capture_lines(tmp_path):
    for r in build(tmp_path)["rows"]:
        if "Not captured" not in r["cells"]:
            assert r["sources"] and all("03_time_status.txt line" in s for s in r["sources"])


def test_w32tm_output_is_read():
    text = """Leap Indicator: 0(no warning)
Stratum: 5 (secondary reference - syncd by (S)NTP)
ReferenceId: 0x0A28E461 (source IP:  10.40.228.97)
Source: ROTPRDSRV122.internal.qr.com.au
Poll Interval: 10 (1024s)

#Peers: 2

Peer: ROTPRDSRV122.internal.qr.com.au
State: Active
Stratum: 4 (secondary reference - syncd by (S)NTP)

Peer: time.windows.com,0x8
State: Pending
Stratum: 0 (unspecified)
"""
    got = {a: v for a, v, _ in host_settings.time_settings(text)}
    assert got == {"time.stratum": "5", "time.poll": "1,024 s", "time.service": "Windows Time Service",
                   "time.source": "ROTPRDSRV122 (10.40.228.97)", "time.source_stratum": "4",
                   "time.fallback": "time.windows.com (pending)"}
    assert host_settings.time_settings("nothing here") == []


DOC = ('<w:document xmlns:w="w"><w:body>'
       '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Time Synchronisation</w:t></w:r></w:p>'
       '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Discovery Information</w:t></w:r></w:p>'
       '<w:tbl><w:tblPr><w:tblStyle w:val="CSATable"/><w:tblW w:w="9638" w:type="dxa"/></w:tblPr>'
       '<w:tblGrid><w:gridCol w:w="2628"/><w:gridCol w:w="4380"/><w:gridCol w:w="2630"/></w:tblGrid>'
       '<w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p><w:pPr><w:pStyle w:val="TableHeader"/></w:pPr><w:r><w:t>Aspect</w:t></w:r></w:p></w:tc></w:tr>'
       '<w:tr><w:tc><w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr><w:r><w:t>OT source</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
       '<w:p><w:pPr><w:pStyle w:val="TableNote"/></w:pPr><w:r><w:t>Agent note</w:t></w:r></w:p>'
       '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Drawbridge Impact</w:t></w:r></w:p>'
       '<w:p><w:r><w:t>Paragraph</w:t></w:r></w:p>'
       '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>DNS</w:t></w:r></w:p>'
       '</w:body></w:document>')


def test_place_inserts_above_the_aspect_table_and_replaces_on_rerun(tmp_path):
    t = build(tmp_path)
    once, what = tt.place_xml(DOC, t, "Time Synchronisation")
    assert what == "inserted"
    di = once.index(">Discovery Information<")
    ours = once.index(f'w:tblCaption w:val="{tt.CAPTION}"')
    aspect = once.index(">Aspect<")
    assert di < ours < once.index("All hosts in this table") < aspect
    assert once.count("<w:tbl>") == 2 and "Agent note" in once            # the Aspect table and the note are untouched
    assert 'w:vMerge w:val="restart"' in once and "<w:vMerge/>" in once   # role cell merged over its sub-rows
    twice, what2 = tt.place_xml(once, t, "Time Synchronisation")
    assert what2 == "replaced" and twice == once                           # idempotent
    empty, what3 = tt.place_xml(once, {"status": "EMPTY"}, "Time Synchronisation")
    assert what3 == "removed" and empty == DOC


def test_place_replaces_topic_table_after_requirement_stories_without_duplication(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, "Time Synchronisation")
    ours = once.index(f'<w:tbl>', once.index(f'w:tblCaption w:val="{tt.CAPTION}"') - 200)
    story = ('<w:p><w:r><w:t>SEP-TIME-01 — The evidence-backed current-state story.</w:t></w:r></w:p>')
    with_story = once[:ours] + story + once[ours:]

    refreshed, what = tt.place_xml(with_story, t, "Time Synchronisation")

    assert what == "replaced"
    assert refreshed.count(f'w:tblCaption w:val="{tt.CAPTION}"') == 1
    assert refreshed.count("SEP-TIME-01 —") == 1
    assert refreshed.index("SEP-TIME-01 —") < refreshed.index(f'w:tblCaption w:val="{tt.CAPTION}"')
    again, what2 = tt.place_xml(refreshed, t, "Time Synchronisation")
    assert what2 == "replaced" and again == refreshed


def test_place_puts_requirement_table_after_split_story_body(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, "Time Synchronisation")
    ours = once.index(f'<w:tbl>', once.index(f'w:tblCaption w:val="{tt.CAPTION}"') - 200)
    story = (
        '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>SEP-TIME-01 — Independent OT time source</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>The evidence-backed current-state story.</w:t></w:r></w:p>'
    )
    with_story = once[:ours] + story + once[ours:]

    refreshed, _ = tt.place_xml(with_story, t, "Time Synchronisation")

    assert refreshed.index("Independent OT time source") < refreshed.index("evidence-backed current-state story")
    assert refreshed.index("evidence-backed current-state story") < refreshed.index(f'w:tblCaption w:val="{tt.CAPTION}"')


def test_place_interleaves_requirement_tables_and_removes_replaced_aspect_table():
    stories = (
        '<w:p><w:r><w:t>SEP-STOR-01 — Storage story.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>SEP-STOR-02 — Transfer story.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>SEP-STOR-03 — Direction story.</w:t></w:r></w:p>'
    )
    doc = DOC.replace(
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Discovery Information</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Discovery Information</w:t></w:r></w:p>' + stories,
    ).replace("Time Synchronisation", "Storage &amp; Data Transfer")
    tables = []
    for req, value in (("SEP-STOR-01", "Storage evidence"), ("SEP-STOR-02", "Transfer evidence"),
                       ("SEP-STOR-03", "Direction evidence")):
        tables.append({"status": "OK", "requirement": req, "replace_observation_table": True,
                       "columns": ["Role", "Hosts", "Finding"], "common": "", "markers": [],
                       "rows": [{"role": "Application", "first": True, "hosts": ["HOST1"], "cells": [value]}]})

    out, what = tt.place_xml(doc, tables, "Storage & Data Transfer")

    assert what == "inserted"
    assert ">Aspect<" not in out
    order = [out.index(x) for x in ("SEP-STOR-01 —", "Storage evidence", "SEP-STOR-02 —", "Transfer evidence",
                                     "SEP-STOR-03 —", "Direction evidence")]
    assert order == sorted(order)
    assert out.count(f'w:tblCaption w:val="{tt.CAPTION}"') == 3


def test_place_replaces_tables_a_figure_split_and_keeps_the_figure(tmp_path):
    """A figure placed among the framework tables (a drawing with text boxes, so paragraphs inside a paragraph)
    must not strand the old tables: every framework table and note before the Aspect table is replaced, and the
    figure block is kept after the new tables."""
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, "Time Synchronisation")
    first = once.index(f'<w:tbl>', once.index(">Discovery Information<"))
    end_first = once.index("</w:tbl>", first) + len("</w:tbl>")
    fig = ('<w:p><w:pPr><w:pStyle w:val="Figure"/></w:pPr><w:r><w:drawing><wps:txbx><w:txbxContent>'
           '<w:p><w:r><w:t>Box label</w:t></w:r></w:p></w:txbxContent></wps:txbx></w:drawing></w:r></w:p>'
           '<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure 1: old</w:t></w:r></w:p>')
    split = once[:end_first] + fig + once[end_first:]
    again, what = tt.place_xml(split, t, "Time Synchronisation")
    assert what == "replaced"
    assert again.count(f'w:tblCaption w:val="{tt.CAPTION}"') == once.count(f'w:tblCaption w:val="{tt.CAPTION}"')
    assert again.count("All hosts in this table") == once.count("All hosts in this table")   # no stranded note
    assert again.count("Box label") == 1 and again.count("Figure 1: old") == 1
    assert again.index("All hosts in this table") < again.index("Box label") < again.index(">Aspect<")


def test_profile_found_by_heading_text_not_number():
    assert tt.profile_for("3.4.1 Time Synchronisation")["key"] == "TIME"
    assert tt.profile_for("Something Else") is None


def test_bands_follow_role_groups(tmp_path):
    t = build(tmp_path)
    styles = ('<w:style w:type="table" w:styleId="CSATable"><w:tblStylePr w:type="band1Horz"><w:tcPr>'
              '<w:shd w:val="clear" w:color="auto" w:fill="FDE9D9"/></w:tcPr></w:tblStylePr></w:style>')
    out, _ = tt.place_xml(DOC, t, "Time Synchronisation", styles)
    ours = re.search(r"<w:tbl>.*?</w:tbl>", out, re.S).group(0)
    rows = re.findall(r"<w:tr>.*?</w:tr>", ours, re.S)[1:]
    shaded = ["FDE9D9" in r for r in rows]
    roles = [r["role"] for r in t["rows"]]
    for i in range(1, len(rows)):          # sub-rows of one role share their group's band
        if roles[i] == roles[i - 1]:
            assert shaded[i] == shaded[i - 1]
        else:
            assert shaded[i] != shaded[i - 1]
