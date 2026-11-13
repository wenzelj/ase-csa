import runpy
from pathlib import Path


CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def finding(level, code, question=None):
    return {"level": level, "code": code, "question": question, "message": code}


def test_warning_only_findings_are_not_repairable():
    res = {"findings": [finding("WARN", "STORY_SENTENCE_LONG", "B1")]}
    assert CSA["repair_findings"](res) == []
    assert CSA["answer_blocks_failing"](res) == set()


def test_focused_repair_contains_only_errors_for_failed_block():
    res = {"findings": [
        finding("ERROR", "FACT_NO_EVIDENCE", "B1"),
        finding("ERROR", "SLOT_NOT_ANSWERED", "B2"),
        finding("WARN", "STORY_SENTENCE_LONG", "B1"),
        finding("ERROR", "FRAME_UNCOVERED"),
    ]}
    selected = CSA["repair_findings"](res, {"B1"})
    assert [f["code"] for f in selected] == ["FACT_NO_EVIDENCE", "FRAME_UNCOVERED"]


def test_repeated_signature_stops_without_another_model_call():
    repeated = (("FACT_NO_EVIDENCE", "B1", "same"),)
    assert CSA["repeated_repair_action"](repeated, None, "small", "fallback", False) == (None, False)
    assert CSA["repeated_repair_action"](repeated, repeated, "small", "fallback", False) == ("fallback", False)
    assert CSA["repeated_repair_action"](repeated, repeated, "small", "fallback", True) == (None, True)
