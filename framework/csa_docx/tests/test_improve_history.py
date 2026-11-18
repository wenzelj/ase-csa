from csa_docx.improve_state import new_run, proposal_hash, repeated_proposal, write_run


def test_identical_proposal_is_detected_after_a_prior_apply(tmp_path):
    root = tmp_path / "csa-work" / "improve"
    proposal = {"section_key": "3.4", "status": "no_material_change", "evidence_ids": ["E-1"]}
    run = new_run("3.4")
    run.update({"status": "applied", "proposal_hash": proposal_hash(proposal)})
    write_run(root, run)
    assert repeated_proposal(root, "3.4", proposal)


def test_a_different_second_pass_remains_eligible(tmp_path):
    root = tmp_path / "csa-work" / "improve"
    first = {"section_key": "3.4", "status": "no_material_change", "evidence_ids": ["E-1"]}
    run = new_run("3.4")
    run.update({"status": "proposed", "proposal_hash": proposal_hash(first)})
    write_run(root, run)
    assert not repeated_proposal(root, "3.4", {**first, "evidence_ids": ["E-2"]})


def test_pending_proposal_is_eligible_for_first_apply(tmp_path):
    root = tmp_path / "csa-work" / "improve"
    proposal = {"section_key": "3.4", "status": "improve", "evidence_ids": ["E-1"]}
    run = new_run("3.4")
    run.update({"status": "proposed", "proposal_hash": proposal_hash(proposal)})
    write_run(root, run)
    assert not repeated_proposal(root, "3.4", proposal)


def test_applied_proposal_is_detected_as_a_repeat(tmp_path):
    root = tmp_path / "csa-work" / "improve"
    proposal = {"section_key": "3.4", "status": "improve", "evidence_ids": ["E-1"]}
    run = new_run("3.4")
    run.update({"status": "applied", "proposal_hash": proposal_hash(proposal)})
    write_run(root, run)
    assert repeated_proposal(root, "3.4", proposal)
