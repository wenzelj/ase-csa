"""Regression coverage for evidence-based requirement assessment decisions."""
from copy import deepcopy

from csa_docx.assessment_checks import assessment_findings, validate_assessment
from csa_docx.change_parser import parse_change_records
from csa_docx.check_change import finding


def basis(**overrides):
    value = {
        "requirement_id": "CTRL-01",
        "requirement_text": "File transfers between IT and OT shall use an approved proxy with antivirus scanning.",
        "requirement_intent": "Control malware exposure from cross-boundary file transfer.",
        "mandatory_obligations": ["file transfers use an approved proxy", "transferred files are antivirus scanned"],
        "application_function": "Exchange operational data between application tiers.",
        "observed_architecture": "The application exchanges records through an API and database connection.",
        "communication_mechanisms": ["rest_api", "database"],
        "evidence_references": ["E-101", "E-102"],
        "confirmed_facts": ["API and database paths are documented."],
        "evidence_gaps": [],
        "applicability": "does_not_apply",
        "applicability_justification": "The requirement is expressly limited to file transfers, which are conclusively absent.",
        "obligation_assessments": [
            {"obligation": "file transfers use an approved proxy", "applicability": "does_not_apply",
             "evidence_references": ["E-101"], "result": "not_applicable", "justification": "No file-transfer function exists."},
            {"obligation": "transferred files are antivirus scanned", "applicability": "does_not_apply",
             "evidence_references": ["E-101"], "result": "not_applicable", "justification": "No transferred files exist."},
        ],
        "compliance_status": "not_applicable",
        "document_status": "Not Applicable",
        "compliance_justification": "The addressed feature is absent and the wording creates no obligation for other exchanges.",
        "recommendations": [],
        "confidence": "high",
    }
    value.update(overrides)
    return value


def codes(value):
    return {code for code, _ in validate_assessment(value)}


def test_scenario_a_api_and_database_are_not_file_transfer():
    assert codes(basis()) == set()


def test_scenario_b_unproven_approved_conduit_remains_undetermined():
    value = basis(
        requirement_text="All IT/OT data exchanges shall use an approved conduit.",
        mandatory_obligations=["all IT/OT data exchanges use an approved conduit"],
        applicability="applies",
        applicability_justification="The API and database paths exchange data across the boundary.",
        evidence_gaps=["Boundary enforcement and conduit approval were not provided."],
        obligation_assessments=[{"obligation": "all IT/OT data exchanges use an approved conduit", "applicability": "applies",
                                 "evidence_references": ["E-102"], "result": "unable_to_determine",
                                 "justification": "The path is known but enforcement is not demonstrated."}],
        compliance_status="unable_to_determine",
        document_status="",
        compliance_justification="Enforcement is not demonstrated; bypass is not positively established.",
        recommendations=["Confirm the boundary rule and approved-conduit configuration."],
        confidence="low",
    )
    assert codes(value) == set()


def test_scenario_c_confirmed_proxy_bypass_is_not_met():
    value = basis(
        observed_architecture="A file transfer bypasses the mandatory approved proxy.",
        communication_mechanisms=["file_transfer"], applicability="applies",
        applicability_justification="The application performs the file-transfer activity.",
        obligation_assessments=[
            {"obligation": "file transfers use an approved proxy", "applicability": "applies", "evidence_references": ["E-101"],
             "result": "not_met", "justification": "The recorded path bypasses the proxy."},
            {"obligation": "transferred files are antivirus scanned", "applicability": "applies", "evidence_references": ["E-102"],
             "result": "unable_to_determine", "justification": "Scanning was not established."}],
        compliance_status="not_met", document_status="Not Met",
        confirmed_noncompliance_evidence=["E-101"],
        compliance_justification="Positive evidence establishes bypass of an applicable mandatory control.",
    )
    assert codes(value) == set()


def test_scenario_d_missing_firewall_material_cannot_prove_not_met():
    value = basis(compliance_status="not_met", document_status="Not Met",
                  applicability="applies", applicability_justification="A boundary path exists.",
                  evidence_gaps=["No firewall configuration or network diagram was provided."],
                  confirmed_noncompliance_evidence=[])
    assert "NOT_MET_NOT_PROVEN" in codes(value)


def test_scenario_e_compound_control_requires_each_obligation():
    value = basis(obligation_assessments=basis()["obligation_assessments"][:1])
    assert "OBLIGATIONS_UNASSESSED" in codes(value)


def test_scenario_f_smtp_does_not_establish_attachment_transfer():
    value = basis(
        observed_architecture="SMTP is documented; message bodies and attachment handling are unknown.",
        communication_mechanisms=["smtp"], applicability="unable_to_determine",
        applicability_justification="SMTP alone does not prove whether files are transferred.",
        evidence_gaps=["Message content and attachment handling were not observed."],
        obligation_assessments=[
            {"obligation": item, "applicability": "unable_to_determine", "evidence_references": ["E-101"],
             "result": "unable_to_determine", "justification": "Attachment handling is unknown."}
            for item in basis()["mandatory_obligations"]
        ],
        compliance_status="unable_to_determine", document_status="",
        compliance_justification="File-transfer applicability cannot be determined from SMTP use alone.", confidence="low")
    assert codes(value) == set()


def test_scenario_g_not_applicable_requires_evidence_based_justification():
    value = deepcopy(basis())
    value["applicability"] = "applies"
    assert "NA_APPLICABILITY_MISMATCH" in codes(value)


def test_requirement_gate_warns_during_drafting_and_fails_strict_apply():
    record = parse_change_records("""### S3-E1 - Requirement
**Where:** `@H3.1-T1-R2`
**Do:** Replace
**Text:**
> Observed: An API path is documented.\n> Assessment: Partially Met
**Why:** E-101.
""")[0]
    node = {"parts": [{"kind": "requirement", "table": "@H3.1-T1"}]}
    assert assessment_findings([record], finding, require=False, node=node)[0]["level"] == "WARN"
    assert assessment_findings([record], finding, require=True, node=node)[0]["level"] == "ERROR"


def test_non_requirement_table_edit_does_not_require_assessment_basis():
    record = parse_change_records("""### S3-E2 - Discovery row
**Where:** `@H3.1-T2-R2`
**Do:** Replace
**Text:**
> API | documented | E-101
**Why:** E-101.
""")[0]
    node = {"parts": [{"kind": "discovery", "table": "@H3.1-T2"}]}
    assert assessment_findings([record], finding, require=True, node=node) == []
