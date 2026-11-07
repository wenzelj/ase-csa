"""Answer checks: a SYN_SENT-only attempt is not 'established'; a frame's own NOT_FOUND row is never off-topic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import answer_sheet  # noqa: E402

MATRIX = {
    "E-001": {"evidence_id": "E-001", "status": "VERIFIED", "question": "SEP-INET-01: internet",
              "claim": "HOSTAA101 has an attempted (SYN_SENT) connection from svchost to 20.190.167.66 on port 443.",
              "source_title": "X_discovery_HOSTAA101_20260101T000000Z: 25_netstat_tcp_samples.txt"},
    "E-002": {"evidence_id": "E-002", "status": "NOT_FOUND", "question": "SEP-MON-01: antivirus on HOSTAA101",
              "claim": "Antivirus on HOSTAA101: None found (searched 32_services_inventory.txt)",
              "source_title": "searched: 32_services_inventory.txt in the captures of HOSTAA101"},
}


def _codes(text, frame_ids=()):
    card = {"key": "VULN", "questions": [{"id": "B1", "kind": "requirement"}], "evidence": {},
            "frame": {"ids": list(frame_ids)}}
    res = answer_sheet.validate(answer_sheet.parse(text), card, MATRIX, draft=True)
    return {f["code"] for f in res["findings"]}


def test_an_attempt_called_established_is_an_error():
    bad = "## B1 SEP-VULN-01\nFacts:\n- HOSTAA101 lost its established internet endpoints. (E-001) {observed; HOSTAA101}\n"
    good = "## B1 SEP-VULN-01\nFacts:\n- HOSTAA101 attempted internet connections and no reply was seen. (E-001) {observed; HOSTAA101}\n"
    assert "ATTEMPT_AS_ESTABLISHED" in _codes(bad)
    assert "ATTEMPT_AS_ESTABLISHED" not in _codes(good)


def test_a_frame_row_from_another_topic_is_allowed():
    text = "## B1 SEP-VULN-01\nFacts:\n- No antivirus was found on HOSTAA101. (E-002) {observed; HOSTAA101}\n"
    assert "CITATION_OFF_TOPIC" in _codes(text)
    assert "CITATION_OFF_TOPIC" not in _codes(text, frame_ids=["E-002"])


def test_a_per_host_fact_the_role_table_states_is_not_dropped():
    matrix = {"E-010": {"evidence_id": "E-010", "status": "VERIFIED", "question": "SEP-DNS-01",
                        "claim": "HOSTAA101 is configured to resolve names through DNSSRV00122 (10.40.228.97) first.",
                        "source_title": "X_discovery_HOSTAA101_20260101T000000Z: 14_resolver.txt"},
              "E-011": {"evidence_id": "E-011", "status": "VERIFIED", "question": "SEP-DNS-01",
                        "claim": "HOSTAA101 runs the RevServer application against SQLSRV00101.",
                        "source_title": "X_discovery_HOSTAA101_20260101T000000Z: 32_services_inventory.txt"}}
    card = {"role_tables": [{"rows": [{"hosts": ["HOSTAA101"], "cells": ["DNSSRV00122 (10.40.228.97)"]}], "common": ""}]}
    old = answer_sheet.parse("## B2 Discovery Information\nFacts:\n- a. (E-010) {observed; HOSTAA101}\n- b. (E-011) {observed; HOSTAA101}\n")
    new = answer_sheet.parse("## B2 Discovery Information\nFacts:\n- c. (E-012) {observed; HOSTAA101}\n")
    found = answer_sheet.regression(old, new, matrix, card)
    codes = [(f["code"], f["message"].split(" ")[0]) for f in found if f["code"] in ("CAPTURE_DROPPED", "CAPTURE_IN_TABLE")]
    assert ("CAPTURE_IN_TABLE", "E-010") in codes                    # the table states the resolver
    assert any(c == "CAPTURE_DROPPED" and "E-011" in m for c, m in codes)   # the application fact is still guarded
