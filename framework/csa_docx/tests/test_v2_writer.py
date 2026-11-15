"""Focused tests for the separate V2 simple writer packet."""
import json

from csa_docx import v2_writer
from csa_docx.answer_sheet import _pkg_evidence


def _card():
    return {"questions": [{"id": "B1", "kind": "requirement"}],
            "package": {"context": "v2-native", "hosts": {"owned": ["APP01"]},
                        "evidence": [{"evidence_id": "E-001", "text": "base"}]},
            "evidence": {"B1": {"rows": [{"id": "E-999", "claim": "card addition"}],
                                  "cut": ["E-998"], "digest_ids": ["E-997"]}}}


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
    assert first["card_evidence_additions"]["B1"]["rows"][0]["id"] == "E-999"
    assert first["card_evidence_additions"]["B1"]["cut_ids"] == ["E-998"]


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
    assert len(prompt) < 60000


def test_validator_accepts_card_bounded_additions_once():
    packet = v2_writer.build_packet(project="test", subsection="TIME", card=_card())
    rows, hosts = _pkg_evidence(packet["evidence_package"] | {"card_evidence_additions": packet["card_evidence_additions"]})
    assert {"E-001", "E-997", "E-998", "E-999"}.issubset(rows)
    assert hosts == {"APP01"}


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
