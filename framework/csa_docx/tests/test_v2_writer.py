"""Focused tests for the separate V2 simple writer packet."""
import json

from csa_docx import v2_writer


def _card():
    return {"questions": [{"id": "B1", "kind": "requirement"}],
            "obligations": {"blocks": {"B1": {"evidence_ids": ["E-001"]}}},
            "package": {"context": "v2-native", "hosts": {"owned": ["APP01"]},
                        "evidence": [{"evidence_id": "E-001", "text": "base"}]},
            "evidence": {"B1": {"rows": [{"id": "E-999", "claim": "card addition"}],
                                  "cut": ["E-998"], "digest_ids": ["E-997"]}}}


def test_packet_is_stable_and_contains_new_instructions_only():
    first = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    second = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    assert first["packet_hash"] == second["packet_hash"]
    assert first["packet_version"] == "v2-writer-packet-v2"
    assert first["instructions"].startswith("# V2 writer instructions")
    assert first["output_contract"]["version"] == "v2-output-v1"
    assert "answer-contract-v1" not in json.dumps(first["instructions"])
    assert "package" not in first["card"]
    assert "evidence" not in first["card"]
    assert "evidence_package" not in first
    assert "card_evidence_additions" not in first
    assert first["evidence_slices"]["B1"]["allowed_evidence_ids"] == ["E-001"]
    assert first["evidence_slices"]["B1"]["evidence"][0]["evidence_id"] == "E-001"
    assert first["answer_plan"]["B1"]["allowed_evidence_ids"] == ["E-001"]


def test_packet_keeps_evidence_and_repair_inputs_separate():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card(),
                                    package={"evidence": [{"evidence_id": "E-001"}]},
                                    answer="old sheet", errors="Fix B1 scope")
    assert packet["evidence_slices"]["B1"]["evidence"][0]["evidence_id"] == "E-001"
    assert packet["retained_answer"] == "old sheet"
    assert packet["repair_request"] == "Fix B1 scope"


def test_focused_packet_contains_only_the_requested_block():
    card = {"questions": [{"id": "B1", "kind": "requirement"}, {"id": "B2", "kind": "requirement"}],
            "obligations": {"blocks": {"B1": {"evidence_ids": ["E-001"]},
                                           "B2": {"evidence_ids": ["E-002"]}}},
            "package": {"evidence": [{"evidence_id": "E-001", "text": "one"},
                                       {"evidence_id": "E-002", "text": "two"}]},
            "evidence": {"B1": {"rows": []}, "B2": {"rows": []}}}
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=card, only="B2")
    assert [q["id"] for q in packet["card"]["questions"]] == ["B2"]
    assert set(packet["answer_plan"]) == {"B2"}
    assert set(packet["evidence_slices"]) == {"B2"}
    assert packet["output_contract"]["blocks"][0]["id"] == "B2"


def test_prompt_is_self_contained_and_does_not_require_legacy_reading():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    prompt = v2_writer.render_prompt(packet, card_path="cards/TIME.md", sheet_path="cards/TIME.answer.md")
    assert prompt.startswith("Act as the V2 Simple Writer")
    assert "Do not load legacy agent files" in prompt
    assert "REQUIRED_READING" not in prompt
    assert "cards/TIME.answer.md" in prompt
    assert len(prompt) < 60000


def test_slice_does_not_include_cut_or_digest_ids_without_claims():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    assert packet["evidence_slices"]["B1"]["allowed_evidence_ids"] == ["E-001"]


def test_stale_cached_plan_ids_are_not_sent_to_writer():
    card = _card()
    card["v2_evidence_slices"] = {"B1": {"allowed_evidence_ids": ["E-989"], "evidence": []}}
    card["v2_answer_plan"] = {"B1": {"allowed_evidence_ids": ["E-989"]}}
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=card)
    assert "E-989" not in packet["evidence_slices"]["B1"]["allowed_evidence_ids"]
    assert "E-989" not in packet["answer_plan"]["B1"]["allowed_evidence_ids"]


def test_slice_artifacts_are_inspectable(tmp_path):
    from csa_docx.v2_evidence_slice import build_slices, write_slices
    slices = build_slices(_card())
    paths = write_slices(tmp_path / "TIME.evidence", slices)
    assert paths["B1"].endswith("B1.json")
    assert (tmp_path / "TIME.evidence" / "B1.md").read_text().startswith("# B1 evidence slice")


def test_answer_plan_artifact_is_inspectable(tmp_path):
    from csa_docx.v2_answer_plan import build_plan, write_plan
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    paths = write_plan(tmp_path / "TIME.plan", build_plan(_card(), packet["evidence_slices"]))
    assert paths[0].endswith("answer-plan.json")
    assert (tmp_path / "TIME.plan" / "answer-plan.md").read_text().startswith("# V2 answer plan")


def test_stale_unknown_evidence_repair_lines_are_removed_only_when_now_valid():
    packet = v2_writer.build_packet(
        project="test", subsection="TIME", card=_card(),
        errors=("ERROR UNKNOWN_EVIDENCE B1: E-12345 is not in the subsection evidence package\n"
                "ERROR UNKNOWN_EVIDENCE B1: E-001 is not in the subsection evidence package\n"
                "CHECK EVIDENCE_DROPPED B1: E-001, E-12345"))
    assert "E-001 is not" not in packet["repair_request"]
    assert "E-12345 is not" in packet["repair_request"]
    assert "EVIDENCE_DROPPED B1: E-12345" in packet["repair_request"]
    assert "EVIDENCE_DROPPED B1: E-001" not in packet["repair_request"]
