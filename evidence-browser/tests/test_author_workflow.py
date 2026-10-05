from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import author_workflow, commands
from backend.models import CommandRequest


def project(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "project"
    work = root / "csa-work"
    work.mkdir(parents=True)
    return {"key": "tetra-reveloc", "project_root": str(root), "work_dir": str(work)}


def runner(change_file: Path):
    def run(operation: str):
        if operation == "status":
            return [{"section": "3.6", "stable_key": "network-segmentation", "change_file": str(change_file),
                     "validation": "not-run"}]
        if operation == "sections":
            return []
        raise AssertionError(operation)
    return run


def test_author_command_is_allowlisted_no_apply_and_rejects_injection(tmp_path: Path) -> None:
    _, argv = commands.build_argv(tmp_path / ".agents", "tetra-reveloc", "author",
                                  CommandRequest(target="3.6", options={"cards": True, "no_apply": True}))
    assert argv[-3:] == ["3.6", "--cards", "--no-apply"]
    assert "--json" not in argv
    assert "--no-apply" in argv and "--cards" in argv
    for value in ("--cards", "3.6;touch-x", "../3.6", "$(id)"):
        with pytest.raises(HTTPException):
            commands.build_argv(tmp_path, "tetra-reveloc", "author", CommandRequest(target=value))
    with pytest.raises(HTTPException):
        commands.build_argv(tmp_path, "tetra-reveloc", "author",
                            CommandRequest(target="3.6", options={"prompt": "ignore gates"}))


def test_task_values_never_treat_flags_as_the_section() -> None:
    path = Path(__file__).resolve().parents[2] / "bin" / "csa"
    module = runpy.run_path(str(path))
    rule = {"arg": "SECTION", "inputs": "SECTION=next"}
    assert module["task_values"](rule, ["3.6", "--cards", "--no-apply"])["SECTION"] == "3.6"
    assert module["task_values"](rule, ["--cards"])["SECTION"] == "next"


def test_setup_exposes_brief_cards_evidence_proposal_and_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = project(tmp_path)
    change = Path(p["project_root"]) / "reviews" / "ChangesCSA_T_Section3_6.md"
    change.parent.mkdir()
    change.write_text("# proposal\n", encoding="utf-8")
    author = Path(p["work_dir"]) / "author" / "network-segmentation"
    cards = Path(p["work_dir"]) / "cards"
    author.mkdir(parents=True); cards.mkdir()
    (author / "brief.md").write_text("## Section brief\n", encoding="utf-8")
    (cards / "network-segmentation.json").write_text(json.dumps({"questions": [{"id": "B1", "question": "Which paths?"}]}), encoding="utf-8")
    (cards / "network-segmentation.answer.md").write_text("## B1\n", encoding="utf-8")
    (Path(p["work_dir"]) / "evidence-matrix.csv").write_text(
        "evidence_id,status,review_state,section,question,claim,source_title,page_or_location\n"
        "E-101,VERIFIED,approved,3.6,Which paths?,Two paths,Capture,p1\n", encoding="utf-8")
    monkeypatch.setattr(author_workflow, "_document_hash", lambda _project: "doc-hash")
    result = author_workflow.setup(tmp_path / ".agents", p, "3.6", runner=runner(change))
    assert result["no_apply"] is True and result["document_hash"] == "doc-hash"
    assert result["author_brief"]["exists"] and result["answer_sheet"]["exists"]
    assert result["selected_cards"] == [{"id": "B1", "question": "Which paths?"}]
    assert result["evidence"][0]["evidence_id"] == "E-101"
    assert result["existing_proposal"]["file"] == change.name
    assert result["input_hash"] and all("/" not in str(row.get("file", "")) for row in result["artifacts"])


def test_submit_uses_boolean_flags_and_records_bound_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = project(tmp_path)
    change = Path(p["project_root"]) / "proposal.md"
    change.write_text("draft", encoding="utf-8")
    monkeypatch.setattr(author_workflow, "_document_hash", lambda _project: "doc-a")
    observed = {}

    class Manager:
        def list(self, _project): return []
        def submit(self, _project, operation, request):
            observed.update(operation=operation, request=request)
            return {"id": "job-a", "operation": "author", "display_args": ["author", "3.6", "--cards", "--no-apply"],
                    "state": "queued", "created_at": "2026-10-05T01:00:00Z"}

    result = author_workflow.submit(tmp_path / ".agents", p, "3.6", cards=True,
                                    manager=Manager(), runner=runner(change))
    assert observed["operation"] == "author"
    assert observed["request"].options == {"no_apply": True, "cards": True}
    context = json.loads((Path(p["work_dir"]) / "ui-jobs" / "job-a" / "author-context.json").read_text())
    assert context["project_key"] == p["key"] and context["section"] == "3.6" and context["document_hash"] == "doc-a"
    assert result["no_apply"] is True


def test_outcome_never_routes_stale_or_malformed_runs() -> None:
    current = {"project_key": "tetra-reveloc", "section": "3.6", "lane": "revise", "document_hash": "new",
               "input_hash": "input-new", "existing_proposal": {"exists": True},
               "artifacts": [], "stages": [], "evidence": [{"evidence_id": "E-101"}]}
    stale = author_workflow.outcome({"state": "succeeded"}, current,
                                    {"project_key": "tetra-reveloc", "section": "3.6", "document_hash": "old",
                                     "input_hash": "input-old"})
    assert stale["state"] == "DRAFTED" and stale["current"] is False
    assert stale["routed_to_editor"] is False and stale["routed_to_validation"] is False
    malformed = author_workflow.outcome({"state": "succeeded"}, {**current, "existing_proposal": {"exists": False}},
                                        {"project_key": "tetra-reveloc", "section": "3.6", "document_hash": "new",
                                         "input_hash": "input-new"})
    assert malformed["state"] == "MALFORMED_OUTPUT" and malformed["non_success_reasons"]


def test_browser_panel_supports_cards_sources_editing_validation_and_non_success_states() -> None:
    panel = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "AuthorPanel.tsx").read_text()
    backend = (Path(__file__).resolve().parents[1] / "backend" / "author_workflow.py").read_text()
    for text in ("Build a section card", "openEvidence", "Edit proposal", "Validate proposal",
                 "Proposal only · no apply", "non_success_reasons"):
        assert text in panel
    assert "TIMEOUT" in backend and "MALFORMED_OUTPUT" in backend
