"""Never infer: facts cite evidence, state a basis, carry only evidenced terms, and keep the evidence's scope."""
from csa_docx.change_parser import parse_change_records
from csa_docx.check_change import finding
from csa_docx.fact_checks import fact_findings, parse_sites

MATRIX = {
    "E-011": {"evidence_id": "E-011", "claim": "OIA keeps log and replay files on the TCSI machines (C:\\OIA\\Replays). "
              "The TCS Backup Script rules copy yesterday's OIA replay file to \\\\internal.qr.com.au\\OT\\UTC_LOG; "
              "the scheduled task 'TCS Backup Script' is present on ROKTCSILEFT.",
              "evidence_excerpt": "OIA Replays | C:\\OIA\\Replays | Copy yesterday's replay file.", "page_or_location": "",
              "section": "", "source_title": "TCS Backup Script", "review_state": "pending"},
}
SITES = parse_sites("ROK=Rockhampton,MKY=Mackay")
REC = """### S4-E7 - OIA replay

**Where:** `@H5.9.2-P1` -- currently: "x"

**Do:** Replace

**Facts:**
{facts}

**Text:**

> {text}

**Why:**
E-011.
"""
# The sentence that reached 3.7.1: 'daily' is inferred and the Rockhampton-only scope is dropped.
BAD_FACT = "- [B5] OIA writes a replay file; a daily task copies yesterday's file to a file share in the IT domain. (E-011) {basis: documented; scope: ROKTCSILEFT}"
BAD_TEXT = "OIA also writes a replay file of what it sends, and a daily task copies yesterday's file to a file share in the IT domain."
GOOD_FACT = "- [B5] OIA records a replay file; a scheduled backup task copies yesterday's replay file to a file share in the IT domain. (E-011) {basis: documented; scope: ROKTCSILEFT}"
GOOD_TEXT = ("OIA also records a replay file on the TCSI machines, and a scheduled backup task copies the previous day's "
             "replay file to a file share in the IT domain. The task was found on the Rockhampton machines; "
             "whether Mackay does the same is still to be confirmed.")


def codes(facts, text, matrix=MATRIX):
    recs = parse_change_records(REC.format(facts=facts, text=text))
    return {(f["level"], f["code"]) for f in fact_findings(recs, matrix, SITES, finding)}


def test_inferred_frequency_and_widened_scope_fail():
    c = codes(BAD_FACT, BAD_TEXT)
    assert ("ERROR", "FACT_NOT_IN_EVIDENCE") in c
    assert ("ERROR", "UNSUPPORTED_QUALIFIER") in c
    assert ("ERROR", "SCOPE_WIDENED") in c


def test_corrected_sentence_passes():
    c = codes(GOOD_FACT, GOOD_TEXT)
    assert not [x for x in c if x[0] == "ERROR"], c


def test_fact_without_evidence_is_an_error():
    assert ("ERROR", "FACT_NO_EVIDENCE") in codes("- [B5] OIA records a replay file. {basis: observed}", GOOD_TEXT)


def test_inferred_basis_is_an_error_and_missing_basis_warns():
    assert ("ERROR", "FACT_INFERRED") in codes("- [B5] OIA records a replay file. (E-011) {basis: inferred}", GOOD_TEXT)
    assert ("WARN", "FACT_NO_BASIS") in codes("- [B5] OIA records a replay file. (E-011)", GOOD_TEXT)


def test_unknown_evidence_row_is_an_error():
    assert ("ERROR", "FACT_EVIDENCE_MISSING") in codes("- [B5] OIA records a replay file. (E-999) {basis: observed}", GOOD_TEXT)


def test_host_not_in_evidence_is_an_error():
    c = codes("- [B5] The task runs on MKYTCSILEFT. (E-011) {basis: observed}", "The task runs on the Mackay machine.")
    assert ("ERROR", "FACT_NOT_IN_EVIDENCE") in c


def test_requirement_ids_are_not_treated_as_hosts():
    c = codes("- [B5] OIA replay copy answers SEP-STOR-03. (E-011) {basis: documented; scope: ROKTCSILEFT}", GOOD_TEXT)
    assert ("ERROR", "FACT_NOT_IN_EVIDENCE") not in c


def test_pending_rows_are_listed():
    assert ("INFO", "EVIDENCE_PENDING") in codes(GOOD_FACT, GOOD_TEXT)


def test_no_matrix_skips_with_info():
    assert codes(GOOD_FACT, GOOD_TEXT, matrix={}) == {("INFO", "FACT_CHECK_SKIPPED")}
