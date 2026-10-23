from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands, draft_workflow
from backend.models import CommandRequest

AGENTS = Path(__file__).resolve().parents[2]


def test_answer_runs_in_a_visible_window_with_the_chosen_model():
    op, argv = commands.build_argv(AGENTS, "tetra-reveloc", "answer", CommandRequest(target="3.4", options={"cli": "evo", "fresh": True}))
    assert argv[3:] == ["answer", "--window", "3.4", "--cli", "evo", "--fresh"]
    assert op.lock == "docx" and op.closes_word


def test_answer_refuses_an_unknown_model_and_freeze_only_takes_v1():
    with pytest.raises(HTTPException):
        commands.build_argv(AGENTS, "tetra-reveloc", "answer", CommandRequest(target="3.4", options={"cli": "gpt"}))
    with pytest.raises(HTTPException):
        commands.build_argv(AGENTS, "tetra-reveloc", "freeze", CommandRequest(target="v2"))


def test_snapshot_marks_answered_stale_and_open(tmp_path, monkeypatch):
    work = tmp_path / "csa-work"
    (work / "cards").mkdir(parents=True)
    (work / "cards" / "TIME.manifest.json").write_text("{}")
    (work / "cards" / "TIME.answer.md").write_text("## B1 x\nUnknown: a\nUnknown: b\n")
    (work / "draft").mkdir()
    (work / "draft" / "changes-2026-10-08.md").write_text("| Time | Subsection | Change | Open questions |\n| --- | --- | --- | --- |\n| 08:25 | 3.4 Time (TIME) | 2 part(s) rewritten | 2 |\n")
    (work / "draft" / "open-questions.md").write_text("# Open\n\n## 3.4 Time (TIME)\n\n- [B1] a\n- [B1] b\n")

    class Result:
        parsed = {"nodes": [{"number": "3", "key": "C", "kind": "container", "title": "Domains"},
                            {"number": "3.4", "key": "TIME", "kind": "requirement-block", "title": "Time"},
                            {"number": "3.5", "key": "DNS", "kind": "requirement-block", "title": "DNS"}]}
        stderr = ""
    monkeypatch.setattr(commands, "execute", lambda *a, **k: Result())
    snap = draft_workflow.snapshot(AGENTS, {"key": "tetra-reveloc", "work_dir": str(work)})
    rows = {r["key"]: r for r in snap["sections"]}
    assert set(rows) == {"TIME", "DNS"}
    assert rows["TIME"]["state"] == "answered" and rows["TIME"]["open"] == 2
    assert rows["DNS"]["state"] == "not-answered"
    assert snap["changes"]["rows"][0]["subsection"] == "3.4 Time (TIME)"
    assert snap["open_questions"]["total"] == 2 and snap["stage"] == "draft"
