import json

from backend import improve_workflow
from csa_docx import improve_state


def _project(tmp_path):
    return {"key": "demo", "work_dir": str(tmp_path), "project_root": str(tmp_path), "label": "Demo", "stage": "draft"}


def test_check_proposal_reads_only_improve_state(tmp_path):
    project = _project(tmp_path)
    root = improve_state.improve_root(tmp_path)
    context = {"section_key": "3.4", "document_hash": "sha256:doc", "answer_text": "Existing answer.", "supporting_evidence_ids": ["E-1"]}
    proposal = {"contract_version": "improve-contract-v1", "section_key": "3.4", "base_document_hash": "sha256:doc", "status": "improve", "rating_decision": "keep", "evidence_ids": ["E-1"], "edits": [{"block_id": "b1", "operation": "replace_sentence", "before": "Existing answer.", "after": "Improved answer.", "reason": "fills the named gap", "evidence_ids": ["E-1"]}]}
    (root / "3.4").mkdir(parents=True)
    (root / "3.4" / "context.json").write_text(json.dumps(context), encoding="utf-8")
    improve_state.write_proposal(root, "3.4", proposal)
    result = improve_workflow.check_proposal(project, "3.4")
    assert result["valid"] is True


def test_discard_removes_pending_proposal_but_keeps_run_history(tmp_path):
    project = _project(tmp_path)
    root = improve_state.improve_root(tmp_path)
    improve_state.write_proposal(root, "3.4", {"section_key": "3.4"})
    run = improve_state.new_run("3.4")
    run["status"] = "proposed"
    improve_state.write_run(root, run)
    result = improve_workflow.discard_proposal(project, "3.4")
    assert result["discarded"] is True
    assert improve_state.read_proposal(root, "3.4") is None
    assert improve_state.latest_run(root, "3.4")["status"] == "discarded"
