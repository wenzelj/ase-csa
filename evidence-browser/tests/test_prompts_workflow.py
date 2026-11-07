import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands, prompts_workflow
from backend.models import CommandRequest

AGENTS = Path(__file__).resolve().parents[2]


def _project(tmp_path):
    work = tmp_path / "csa-work"
    (work / "cards").mkdir(parents=True)
    (work / "cards" / "STOR.json").write_text(json.dumps({"key": "STOR", "number": "3.7", "title": "Storage", "questions": [
        {"id": "B1", "kind": "requirement", "text": "SEP-STOR-01"}, {"id": "B4", "kind": "narrative", "text": "Drawbridge"}]}))
    return {"work_dir": str(work)}


def test_listing_save_reset_and_history(tmp_path):
    project = _project(tmp_path)
    data = prompts_workflow.listing(AGENTS, project)
    req = next(p for p in data["prompts"] if p["name"] == "requirement")
    assert req["source"] == "default" and data["sections"][0]["blocks"][0]["id"] == "B1"
    with pytest.raises(HTTPException) as e:
        prompts_workflow.save(AGENTS, project, "requirement", {"text": "x", "etag": "stale"})
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        prompts_workflow.save(AGENTS, project, "base", {"text": "no placeholder", "etag": next(p for p in data["prompts"] if p["name"] == "base")["etag"]})
    assert e.value.status_code == 422
    assert prompts_workflow.save(AGENTS, project, "requirement", {"text": "Mine.\n", "etag": req["etag"]})["saved"]
    again = prompts_workflow.listing(AGENTS, project)
    assert next(p for p in again["prompts"] if p["name"] == "requirement")["source"] == "project"
    prompts_workflow.reset(AGENTS, project, "requirement")
    assert prompts_workflow.history(AGENTS, project, "requirement")["versions"]
    assert next(p for p in prompts_workflow.listing(AGENTS, project)["prompts"] if p["name"] == "requirement")["source"] == "default"


def test_unknown_prompt_name_is_404(tmp_path):
    with pytest.raises(HTTPException) as e:
        prompts_workflow.reset(AGENTS, _project(tmp_path), "../x")
    assert e.value.status_code == 404


def test_preview_is_per_block(tmp_path):
    project = _project(tmp_path)
    b1 = prompts_workflow.preview(AGENTS, project, "STOR", "B1")
    b4 = prompts_workflow.preview(AGENTS, project, "STOR", "B4")
    assert b1["kinds"] == ["requirement"] and "Write both `Summary:` and `Story:`" in b1["text"] and "Drawbridge Impact is written function by function" not in b1["text"]
    assert b4["kinds"] == ["narrative"] and "Drawbridge Impact is written function by function" in b4["text"]
    with pytest.raises(HTTPException):
        prompts_workflow.preview(AGENTS, project, "STOR", "B9")


def test_answer_job_can_run_one_block():
    _op, argv = commands.build_argv(AGENTS, "tetra-reveloc", "answer", CommandRequest(target="3.7", options={"cli": "evo", "blocks": "B1"}))
    assert argv[-2:] == ["--blocks", "B1"]
