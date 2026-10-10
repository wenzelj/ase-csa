"""Validate the internal requirement assessment used before CSA finding prose.

The object is stored in a change record's ``Assessment basis`` field as JSON.  It
is an audit artefact only: it is not inserted into the DOCX and does not expose
chain-of-thought.  The checks enforce the decision inputs and evidence boundary.
"""
from __future__ import annotations

import json
import re


REQUIRED_FIELDS = (
    "requirement_id", "requirement_text", "requirement_intent",
    "mandatory_obligations", "application_function", "observed_architecture",
    "evidence_references", "confirmed_facts", "evidence_gaps", "applicability",
    "applicability_justification", "obligation_assessments", "compliance_status",
    "compliance_justification", "recommendations", "confidence",
)
APPLICABILITY = {"applies", "does_not_apply", "unable_to_determine"}
INTERNAL_STATUSES = {
    "met", "partially_met", "not_met", "not_applicable", "unable_to_determine"
}
DOCUMENT_STATUS = {
    "met": "Met", "partially_met": "Partially Met", "not_met": "Not Met",
    "not_applicable": "Not Applicable",
}
MECHANISMS = {
    "file_transfer", "smb_share", "database", "rest_api", "soap_api",
    "application_protocol", "smtp", "message_queue", "replication",
    "interactive_remote_access", "infrastructure_management", "unknown",
}
EID = re.compile(r"^E-\d{2,}$")


def parse_assessment(value: str) -> tuple[dict | None, str | None]:
    if not value.strip():
        return None, "missing"
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg}"
    return (obj, None) if isinstance(obj, dict) else (None, "must be a JSON object")


def validate_assessment(obj: dict) -> list[tuple[str, str]]:
    """Return ``(code, message)`` errors for one assessment object."""
    errors: list[tuple[str, str]] = []
    missing = [k for k in REQUIRED_FIELDS if k not in obj]
    if missing:
        errors.append(("ASSESSMENT_FIELDS_MISSING", "missing fields: " + ", ".join(missing)))
        return errors

    applicability = str(obj["applicability"]).strip().lower()
    status = str(obj["compliance_status"]).strip().lower()
    if applicability not in APPLICABILITY:
        errors.append(("APPLICABILITY_INVALID", f"applicability must be one of {sorted(APPLICABILITY)}"))
    if status not in INTERNAL_STATUSES:
        errors.append(("COMPLIANCE_STATUS_INVALID", f"compliance_status must be one of {sorted(INTERNAL_STATUSES)}"))
    if not isinstance(obj["mandatory_obligations"], list) or not obj["mandatory_obligations"]:
        errors.append(("OBLIGATIONS_MISSING", "mandatory_obligations must be a non-empty list"))
    assessments = obj["obligation_assessments"]
    if not isinstance(assessments, list) or len(assessments) != len(obj.get("mandatory_obligations", [])):
        errors.append(("OBLIGATIONS_UNASSESSED", "assess every mandatory obligation individually"))
    else:
        for index, item in enumerate(assessments, 1):
            needed = {"obligation", "applicability", "evidence_references", "result", "justification"}
            if not isinstance(item, dict) or not needed.issubset(item):
                errors.append(("OBLIGATION_ASSESSMENT_INCOMPLETE", f"obligation {index} lacks {sorted(needed)}"))
                continue
            if str(item["applicability"]).lower() not in APPLICABILITY:
                errors.append(("OBLIGATION_APPLICABILITY_INVALID", f"obligation {index} has an invalid applicability"))
            if str(item["result"]).lower() not in INTERNAL_STATUSES:
                errors.append(("OBLIGATION_RESULT_INVALID", f"obligation {index} has an invalid result"))

    refs = obj["evidence_references"]
    if not isinstance(refs, list) or any(not EID.match(str(x)) for x in refs):
        errors.append(("EVIDENCE_REFERENCES_INVALID", "evidence_references must contain only existing-format E-nnn IDs"))
    if str(obj["confidence"]).lower() not in {"high", "medium", "low"}:
        errors.append(("CONFIDENCE_INVALID", "confidence must be high, medium or low and supported by the recorded evidence"))
    for field in ("confirmed_facts", "evidence_gaps", "recommendations"):
        if not isinstance(obj[field], list):
            errors.append(("ASSESSMENT_FIELD_TYPE", f"{field} must be a list"))
    mechanisms = obj.get("communication_mechanisms", [])
    if mechanisms and (not isinstance(mechanisms, list) or any(x not in MECHANISMS for x in mechanisms)):
        errors.append(("COMMUNICATION_MECHANISM_INVALID", f"communication_mechanisms must use {sorted(MECHANISMS)}"))

    if applicability == "does_not_apply" and status != "not_applicable":
        errors.append(("NA_STATUS_MISMATCH", "does_not_apply requires not_applicable"))
    if status == "not_applicable" and applicability != "does_not_apply":
        errors.append(("NA_APPLICABILITY_MISMATCH", "not_applicable requires does_not_apply"))
    if status == "not_met" and not obj.get("confirmed_noncompliance_evidence"):
        errors.append(("NOT_MET_NOT_PROVEN", "not_met requires confirmed_noncompliance_evidence"))
    noncompliance_refs = obj.get("confirmed_noncompliance_evidence", [])
    if noncompliance_refs and (
        not isinstance(noncompliance_refs, list)
        or any(not EID.match(str(x)) or x not in refs for x in noncompliance_refs)
    ):
        errors.append(("NONCOMPLIANCE_EVIDENCE_INVALID", "confirmed_noncompliance_evidence must cite an evidence_references E-nnn ID"))
    if status == "unable_to_determine" and not obj["evidence_gaps"]:
        errors.append(("UNDETERMINED_WITHOUT_GAP", "unable_to_determine requires a stated evidence gap"))
    if status == "unable_to_determine" and obj.get("document_status"):
        errors.append(("UNSUPPORTED_STATUS_MAPPING", "unable_to_determine has no document status; retain it as an open question"))
    if status in DOCUMENT_STATUS and obj.get("document_status") != DOCUMENT_STATUS[status]:
        errors.append(("DOCUMENT_STATUS_MISMATCH", f"document_status must be {DOCUMENT_STATUS[status]!r}"))
    return errors


def assessment_findings(records, finding, require: bool = False, node: dict | None = None) -> list[dict]:
    out = []
    requirement_tables = {
        part["table"] for part in (node or {}).get("parts", [])
        if part.get("kind") == "requirement" and part.get("table")
    }
    for record in records:
        anchor = re.search(r"(@H[\d.]+-T\d+)-R\d+", record.where or "")
        # Prefer the document spec. Labelled Assessment text and an explicitly supplied
        # basis remain safe fallbacks for direct/unit invocation without a spec node.
        is_requirement = bool(
            (anchor and anchor.group(1) in requirement_tables)
            or "Assessment:" in (record.text or "")
            or record.assessment_basis
        )
        if not is_requirement:
            continue
        obj, error = parse_assessment(record.assessment_basis)
        if error:
            level = "ERROR" if require else "WARN"
            out.append(finding(level, "ASSESSMENT_BASIS_MISSING" if error == "missing" else "ASSESSMENT_BASIS_INVALID",
                               "requirement-row edit needs an Assessment basis JSON object: " + error, record.edit_id))
            continue
        for code, message in validate_assessment(obj):
            out.append(finding("ERROR", code, message, record.edit_id))
    return out
