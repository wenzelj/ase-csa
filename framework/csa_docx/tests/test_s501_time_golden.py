"""S501: golden test for 3.4 (Time Synchronisation). One good sheet passes clean; each known fault is caught with its code;
a document with the duplicate table and the duplicate note is reported by the audit and repaired by one place and one apply."""
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csa_docx import answer_sheet as A  # noqa: E402
from csa_docx import audit, topic_tables as tt  # noqa: E402
from test_s489_time_duplicate_table import HEADING, _marked, _with_stale_table  # noqa: E402
from test_s492_note_identity import FACTS, NOTE, _do, _node, _plain, _note, _render, _where, OBS  # noqa: E402
from test_topic_tables import DOC, build  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
CARD = json.loads((FIX / "time_card.json").read_text(encoding="utf-8"))
GOOD = (FIX / "time_sheet_good.md").read_text(encoding="utf-8")


def check(text):
    res = A.validate(A.parse(text), CARD)
    return res, {(f["code"], f["level"]) for f in res["findings"]}


def fault(old, new, count=1):
    assert GOOD.count(old) >= 1, old
    return GOOD.replace(old, new, count)


def test_good_sheet_has_no_errors_and_no_warnings():
    res, _ = check(GOOD)
    assert res["status"] == "OK" and res["errors"] == 0 and res["warnings"] == 0, A.errors_text(res)
    assert "domain controllers hosted in the OT network" in GOOD and "Rockhampton" in GOOD


def test_superseded_evidence():
    _, got = check(fault("(E-3173)", "(E-081)"))
    assert ("SUPERSEDED_EVIDENCE", "WARN") in got


def test_role_name_unknown():
    _, got = check(fault("General Purpose Jump Hosts poll", "RevViewer Jump Hosts poll"))
    assert ("ROLE_NAME_UNKNOWN", "WARN") in got


def test_table_value_conflict():
    _, got = check(fault("poll every 16,384 s at Mackay", "poll every 32,768 s at Mackay"))
    assert ("TABLE_VALUE_CONFLICT", "WARN") in got


def test_rating_from_absence():
    text = fault("Rating reason: The sources are domain controllers hosted in OT (E-003, E-004), but the Mackay hosts depend on a source at Rockhampton (E-005).",
                 "Rating reason: No OT-resident time source was identified.\nQUESTION: Which side of OT are the sources on?")
    _, got = check(text)
    assert ("RATING_FROM_ABSENCE", "WARN") in got


def test_story_infers():
    _, got = check(fault("Most hosts show stratum 5.",
                         "Most hosts show stratum 5, so their time comes from a domain controller rather than a local source."))
    assert ("STORY_INFERS", "WARN") in got


def test_story_states_rating():
    _, got = check(fault("Most hosts show stratum 5.",
                         "The missing OT-resident source is the gap that decided this rating."))
    assert ("STORY_STATES_RATING", "WARN") in got


def test_note_repeats_text():
    _, got = check(fault("Every captured host runs the Windows Time service.",
                         "MOTPRDREV101 and MOTPRDLOG103 at Mackay take their time from ROTPRDSRV122 at Rockhampton.", 1)
                   .replace("(E-004) {observed; all captured hosts}", "(E-005) {observed; MOTPRDREV101, MOTPRDLOG103}"))
    assert ("NOTE_REPEATS_TEXT", "WARN") in got


def test_missing_cross_site_finding():
    res, got = check(fault("- MOTPRDREV101 and MOTPRDLOG103 at Mackay take their time from ROTPRDSRV122 at Rockhampton. (E-005) {observed; MOTPRDREV101, MOTPRDLOG103}\n", ""))
    assert ("SLOT_NOT_ANSWERED", "ERROR") in got and res["status"] == "ERROR"


# ------------------------------------------------------------------ the document: duplicate table and duplicate note


def _docx(path, xml):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def test_duplicate_table_is_reported_and_one_place_repairs_it(tmp_path):
    t = build(tmp_path)
    once, _ = tt.place_xml(DOC, t, HEADING)
    messy = _with_stale_table(once)
    out = audit.check_duplicate_topic_tables(_docx(tmp_path / "messy.docx", messy))
    assert [o["issue"] for o in out] == ["DUPLICATE_TOPIC_TABLE"]
    fixed, _ = tt.place_xml(messy, t, HEADING)
    assert _marked(fixed) == 1
    assert audit.check_duplicate_topic_tables(_docx(tmp_path / "fixed.docx", fixed)) == []


def test_duplicate_note_is_reported_and_one_apply_repairs_it():
    path = ["3.4 Time Synchronisation", "3.4.1 Discovery Information"]
    units = [{"kind": "heading", "level": 2, "text": path[0], "path": path[:1]},
             {"kind": "heading", "level": 3, "text": path[1], "path": path},
             {"kind": "para", "text": NOTE + " The nodes were captured on one day.", "path": path},
             {"kind": "para", "text": NOTE + " The remaining nodes use ROTPRDSRV122.", "path": path}]
    out = audit.check_duplicate_prose(units)
    assert [o["issue"] for o in out] == ["DUPLICATE_PROSE"]
    recs = _render(_node([_plain("@H3.4.1-P1", NOTE), OBS, _note("@H3.4.1-P2", NOTE, True)]), FACTS)
    assert sorted((_where(r), _do(r)) for r in recs) == [("@H3.4.1-P1", "Replace"), ("@H3.4.1-P2", "Delete")]
