"""csa resolve-gaps re-answers only the answered blocks, and the repair is told which question the evidence now answers."""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "bin" / "csa").read_text(encoding="utf-8")
ns = {"re": re}
exec(SRC[SRC.index("def answered_blocks"):SRC.index("def cmd_resolve_gaps")], ns)

Q = [
    {"verdict": "ANSWERED", "key": "SUPPLY", "number": "3.16", "title": "Supply", "qid": "B1", "text": "Which vendors support it?", "evidence_ids": ["E-2777", "E-2778"]},
    {"verdict": "ANSWERED", "key": "DNS", "number": "3.5", "title": "DNS", "qid": "F03", "text": "figure gap", "evidence_ids": ["E-1"]},
    {"verdict": "CANDIDATES", "key": "STOR", "number": "3.7", "title": "Storage", "qid": "B2", "text": "open", "evidence_ids": ["E-2"]},
    {"verdict": "ANSWERED", "key": "SUPPLY", "number": "3.16", "title": "Supply", "qid": "B3", "text": "Fallback?", "evidence_ids": ["E-9"]},
]


def test_only_answered_sheet_blocks_count_and_figure_gaps_do_not():
    res = ns["answered_blocks"](Q)
    assert list(res) == ["SUPPLY"] and res["SUPPLY"]["blocks"] == {"B1", "B3"}


def test_the_repair_line_names_the_question_and_the_rows():
    line = ns["resolved_lines"](ns["answered_blocks"](Q)["SUPPLY"]["resolved"])[0]
    assert line.startswith("- ANSWERED B1:") and "Which vendors support it?" in line and "E-2777, E-2778" in line
    assert "remove that QUESTION: line" in line


def test_a_question_with_no_evidence_gives_no_line():
    assert ns["resolved_lines"]([{"qid": "B1", "text": "x", "ids": []}]) == []


def test_only_verified_evidence_is_named_and_a_question_with_none_is_not_answered():
    q = [{"verdict": "ANSWERED", "key": "DNS", "number": "3.5", "title": "DNS", "qid": "B1", "text": "t", "evidence_ids": ["E-1", "E-2620"]},
         {"verdict": "ANSWERED", "key": "TIME", "number": "3.4", "title": "Time", "qid": "B3", "text": "t", "evidence_ids": ["E-2670"]}]
    res = ns["answered_blocks"](q, {"E-1"})
    assert list(res) == ["DNS"] and res["DNS"]["resolved"][0]["ids"] == ["E-1"]
