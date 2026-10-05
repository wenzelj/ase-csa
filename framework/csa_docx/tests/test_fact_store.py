import json

from csa_docx import fact_store as fs

SHEET = """## B1 Time
Facts:
- The log server synchronises from the Rockhampton time server. (E-001) {observed; ROTPRDLOG102}
- Time is kept by an enterprise NTP source for the estate. (E-002) {documented; all sites}
Unknown: whether a fallback exists.
"""


def setup(tmp_path, ids=("E-001", "E-002")):
    work = tmp_path / "csa-work"
    work.mkdir()
    (work / "evidence-matrix.csv").write_text("evidence_id,claim\n" + "".join(f"{i},c\n" for i in ids), encoding="utf-8")
    sheet = tmp_path / "TIME.answer.md"
    sheet.write_text(SHEET, encoding="utf-8")
    card = tmp_path / "TIME.json"
    card.write_text(json.dumps({"key": "TIME", "number": "3.5", "title": "Time"}), encoding="utf-8")
    return work, sheet, card


def test_adding_the_same_sheet_twice_adds_nothing(tmp_path):
    work, sheet, card = setup(tmp_path)
    assert fs.add_from_sheet(work, sheet, card) == 2
    assert fs.add_from_sheet(work, sheet, card) == 0
    recs = fs._read(work)
    assert len(recs) == 2 and recs[0]["hosts"] == ["ROTPRDLOG102"] and recs[0]["section"] == "TIME"


def test_lookup_by_host(tmp_path):
    work, sheet, card = setup(tmp_path)
    fs.add_from_sheet(work, sheet, card)
    got = fs.lookup(work, set(), {"ROTPRDLOG102"})
    assert [r["evidence_ids"] for r in got] == [["E-001"]]


def test_lookup_by_three_topic_words_and_exclude_section(tmp_path):
    work, sheet, card = setup(tmp_path)
    fs.add_from_sheet(work, sheet, card)
    got = fs.lookup(work, {"enterprise", "source", "estate", "unrelated"}, set())
    assert [r["evidence_ids"] for r in got] == [["E-002"]]
    assert fs.lookup(work, {"enterprise", "source", "estate"}, set(), exclude_section="TIME") == []
    assert fs.lookup(work, {"enterprise", "source"}, set()) == []


def test_fact_with_removed_evidence_is_not_returned(tmp_path):
    work, sheet, card = setup(tmp_path)
    fs.add_from_sheet(work, sheet, card)
    (work / "evidence-matrix.csv").write_text("evidence_id,claim\nE-002,c\n", encoding="utf-8")
    assert fs.lookup(work, set(), {"ROTPRDLOG102"}) == []
    assert len(fs.lookup(work, {"enterprise", "source", "estate"}, set())) == 1
