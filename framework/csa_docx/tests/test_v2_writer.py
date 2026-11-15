"""Focused tests for the separate V2 simple writer packet."""
import json

from csa_docx import v2_writer


def _card():
    return {"questions": [{"id": "B1", "kind": "requirement"}],
            "package": {"context": "v2-native", "scope": {"owned": ["APP01"]}}}


def test_packet_is_stable_and_contains_new_instructions_only():
    first = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    second = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    assert first["packet_hash"] == second["packet_hash"]
    assert first["packet_version"] == "v2-writer-packet-v1"
    assert first["instructions"].startswith("# V2 writer instructions")
    assert first["output_contract"]["version"] == "v2-output-v1"
    assert "answer-contract-v1" not in json.dumps(first["instructions"])
    assert "package" not in first["card"]
    assert "evidence" not in first["card"]


def test_packet_keeps_evidence_and_repair_inputs_separate():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card(),
                                    package={"evidence": [{"evidence_id": "E-001"}]},
                                    answer="old sheet", errors="Fix B1 scope")
    assert packet["evidence_package"]["evidence"][0]["evidence_id"] == "E-001"
    assert packet["retained_answer"] == "old sheet"
    assert packet["repair_request"] == "Fix B1 scope"


def test_prompt_is_self_contained_and_does_not_require_legacy_reading():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    prompt = v2_writer.render_prompt(packet, card_path="cards/TIME.md", sheet_path="cards/TIME.answer.md")
    assert prompt.startswith("Act as the V2 Simple Writer")
    assert "Do not load legacy agent files" in prompt
    assert "REQUIRED_READING" not in prompt
    assert "cards/TIME.answer.md" in prompt
