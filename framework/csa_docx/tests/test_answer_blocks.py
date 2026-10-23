"""answer_blocks: a failed check costs only the blocks that failed."""

import json

from csa_docx import answer_blocks as ab

BASE = """## B1 SEP-TIME-01
Facts:
- old b1 fact. (E-001) {observed; ROTPRDLOG102}
Text: Ten of the captured hosts take time from the enterprise.

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed | Coverage / Source |
| Time | NTP | log servers (E-001) |

## B3 Drawbridge Impact
Unknown: which functions keep working, and whether the clock holds

## F1 Analysis frame
- S1: B1
"""

PATCH = """## B1 SEP-TIME-01
Facts:
- new b1 fact. (E-001) {observed; ROTPRDLOG102}
Text: The log servers take time from the enterprise.

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed | Coverage / Source |
| CHANGED | must not be copied | x |

## B3 Drawbridge Impact
Unknown: which functions keep working during isolation
Unknown: whether the clock holds
"""


def test_merge_takes_only_requested_blocks():
    res = ab.merge_text(BASE, PATCH, {"B1", "B3"})
    _, blocks = ab.split(res["text"])
    got = dict(blocks)
    assert [b for b, _ in blocks] == ["B1", "B2", "B3", "F1"]
    assert "new b1 fact" in got["B1"] and "old b1 fact" not in got["B1"]
    assert "CHANGED" not in got["B2"]                      # a passing block is never touched
    assert got["B3"].count("Unknown:") == 2
    assert res["merged"] == ["B1", "B3"] and res["ignored"] == ["B2"] and res["missing"] == []


def test_merge_reports_missing_and_adds_new_block_before_frame():
    res = ab.merge_text(BASE, "## B4 Note\nNone: the table shows it\n", {"B4", "B1"})
    order = [b for b, _ in ab.split(res["text"])[1]]
    assert order == ["B1", "B2", "B3", "B4", "F1"]
    assert res["added"] == ["B4"] and res["missing"] == ["B1"]
    assert "old b1 fact" in res["text"]


def test_failing_blocks():
    f = [{"level": "ERROR", "code": "NO_TOTALS", "question": "B1"},
         {"level": "ERROR", "code": "UNKNOWN_BUNDLED", "question": "B3"},
         {"level": "WARN", "code": "EVIDENCE_UNUSED", "question": "B2"}]
    assert ab.failing(f) == {"B1", "B3"}
    assert ab.failing(f + [{"level": "ERROR", "code": "FRAME_UNCOVERED", "question": None}]) == {"B1", "B3", "F1"}
    assert ab.WHOLE in ab.failing([{"level": "ERROR", "code": "NO_SHEET", "question": None}])


def test_focus_cuts_evidence_pack():
    card = "# Card\n\n## Questions\n- B1\n- B2\n\n## Evidence pack\n\n### B1\nrow b1\n\n### B2\nrow b2\n\n## Example answer\nx\n"
    out = ab.focus(card, {"B2"})
    assert "row b2" in out and "row b1" not in out and "## Example answer" in out and "Fix round" in out


def test_wip_roundtrip(tmp_path):
    sheet = tmp_path / "TIME.answer.md"
    sheet.write_text(BASE, encoding="utf-8")
    fp = {"questions": {"B1": "a", "B2": "b", "B3": "c"}, "matrix": "m", "hosts": "h"}
    ab.wip_write(sheet, fp, ["B3", "B1"], ["NO_TOTALS"])
    assert json.loads(ab.wip_path(sheet).read_text())["failed"] == ["B1", "B3"]
    assert ab.wip_check(sheet, fp)["status"] == "RESUME"
    assert ab.wip_check(sheet, {**fp, "questions": {**fp["questions"], "B2": "z"}})["changed"] == ["B2"]
    assert ab.wip_check(sheet, {**fp, "hosts": "other"})["status"] == "STALE"
    ab.wip_clear(sheet)
    assert ab.wip_check(sheet, fp)["status"] == "NONE"
