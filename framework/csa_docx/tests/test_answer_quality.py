"""Draft-lane answer quality: declared dependencies on isolation cards, no foreign absences offered as
established facts, no silent loss of capture evidence, one question per Unknown line."""
from csa_docx import answer_sheet as A
from csa_docx import evidence_digest as D
from csa_docx import section_card

CAPTURE = "REVELOC_discovery_IPTPRDAPP137_20260605T031609Z: 02_reveloc_expected_flow_map.txt"
PREV = "NetSeg_Current_State_Assessment_REVELOC_TETRA.docx | DNS"
MATRIX = {
    "E-001": {"evidence_id": "E-001", "status": "VERIFIED", "source_title": PREV, "question": "", "gap_or_action": "", "claim": "x"},
    "E-485": {"evidence_id": "E-485", "status": "VERIFIED", "source_title": CAPTURE, "question": "", "gap_or_action": "", "claim": "x"},
}
CARD = {"key": "DNS", "questions": [{"id": "B1", "kind": "narrative"}],
        "evidence": {"B1": {"rows": [{"id": "E-001", "status": "VERIFIED", "claim": "x"},
                                     {"id": "E-485", "status": "VERIFIED", "claim": "x"}], "cut": [], "digest_ids": []}}}


def _sheet(facts, extra=""):
    body = "\n".join(f"- {f}" for f in facts)
    return A.parse(f"## B1 Drawbridge Impact\nFacts:\n{body}\n{extra}Text:\nX.\n")


def _errors(res):
    return {f["code"] for f in res["findings"] if f["level"] == "ERROR"}


OLD = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}",
              "Reveloc sends email alerts through corporate SMTP. (E-485) {observed; MOTPRDREV101}"])


def test_dropping_capture_evidence_without_a_reason_is_refused():
    new = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}"])
    assert "CAPTURE_DROPPED" in _errors(A.validate(new, CARD, MATRIX, draft=True, previous=OLD))


def test_a_dropped_line_with_a_reason_is_accepted():
    new = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}"],
                 "Dropped: E-485 the SMTP alert path is answered in 3.17, not here.\n")
    assert "CAPTURE_DROPPED" not in _errors(A.validate(new, CARD, MATRIX, draft=True, previous=OLD))


def test_keeping_the_capture_fact_is_accepted():
    assert "CAPTURE_DROPPED" not in _errors(A.validate(OLD, CARD, MATRIX, draft=True, previous=OLD))


def test_bundled_unknown_is_refused_and_single_questions_pass():
    facts = ["Name resolution fails at activation. (E-001) {documented; all hosts}",
             "Reveloc sends email alerts through corporate SMTP. (E-485) {observed; MOTPRDREV101}"]
    bundled = _sheet(facts, "Unknown: Radlink must confirm which connections use host names, which functions stop, "
                            "whether a fallback was tested, and whether TMO voice continues.\n")
    assert "UNKNOWN_BUNDLED" in _errors(A.validate(bundled, CARD, MATRIX, draft=True))
    split = _sheet(facts, "Unknown: Radlink could confirm which connections use host names.\n"
                          "Unknown: Radlink could confirm whether TMO voice continues without the Windows servers.\n")
    res = A.validate(split, CARD, MATRIX, draft=True)
    assert "UNKNOWN_BUNDLED" not in _errors(res) and len(split["B1"]["unknown"]) == 2


def test_declared_dependencies_rank_captures_and_documents_before_the_previous_assessment():
    rows = [
        {"evidence_id": "E-016", "status": "VERIFIED", "source_title": PREV,
         "claim": "Reveloc depends on enterprise DNS for every hostname connection."},
        {"evidence_id": "E-482", "status": "VERIFIED", "source_title": CAPTURE,
         "claim": "The expected flow map records the Reveloc application path as R1: MOTPRDREV101, ROTPRDREV102 to SQL cluster."},
        {"evidence_id": "E-696", "status": "VERIFIED", "source_title": "system_matrix.xlsx",
         "claim": "The system matrix records ROTPRDREV101 with required before migration 'SQL listener, Log Servers, SMTP'."},
        {"evidence_id": "E-900", "status": "UNCONFIRMED", "source_title": CAPTURE, "claim": "The flow map records a guess."},
        {"evidence_id": "E-901", "status": "VERIFIED", "source_title": CAPTURE, "claim": "ROTPRDLOG102 uses 10.40.228.97."},
    ]
    lines, ids = D.declared_dependencies(rows, None)
    assert ids == {"E-016", "E-482", "E-696"}
    assert lines[-1].startswith("- E-016")                  # the previous assessment comes last


def test_isolation_digest_carries_the_declared_dependencies(tmp_path):
    rows = [{"evidence_id": "E-696", "status": "VERIFIED", "source_title": "system_matrix.xlsx",
             "claim": "The system matrix records ROTPRDREV101 with required before migration 'SQL listener'."}]
    d = D.digest({"kind": "narrative", "text": "Drawbridge Impact"}, "isolation", {"title": "DNS"}, rows, tmp_path)
    assert "E-696" in d["ids"] and any("Declared dependencies" in b[0] for b in d["blocks"])


def test_an_absence_found_for_another_subsection_is_not_offered():
    rows = {"E-463": {"status": "NOT_FOUND", "question": "Is a fallback recorded for the S01 storage (SEP-STOR-01)?"},
            "E-030": {"status": "VERIFIED", "question": ""}}
    assert section_card._foreign_absence({"evidence_ids": ["E-463"]}, rows, "DNS")
    assert not section_card._foreign_absence({"evidence_ids": ["E-463"]}, rows, "STOR")
    assert not section_card._foreign_absence({"evidence_ids": ["E-030"]}, rows, "DNS")


def _store(tmp_path):
    import csv, json
    work = tmp_path / "csa-work"
    (work / "facts").mkdir(parents=True)
    with (work / "evidence-matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["evidence_id", "status", "source_title", "claim", "question", "gap_or_action"])
        w.writeheader()
        w.writerow({"evidence_id": "E-456", "status": "VERIFIED", "source_title": CAPTURE, "claim": "x", "question": "", "gap_or_action": ""})
        w.writerow({"evidence_id": "E-136", "status": "VERIFIED", "source_title": CAPTURE, "claim": "x", "question": "", "gap_or_action": ""})
        w.writerow({"evidence_id": "E-001", "status": "VERIFIED", "source_title": PREV, "claim": "x", "question": "", "gap_or_action": ""})
    facts = [
        {"fact": "Old wording about the Azure endpoint.", "evidence_ids": ["E-456"], "section": "DNS", "question": "B3", "added": "2026-10-13T02:00:00Z"},
        {"fact": "RevBroadcast cannot reach the Azure Service Bus endpoint during isolation.", "evidence_ids": ["E-456"],
         "section": "DNS", "question": "B3", "added": "2026-10-13T10:31:27Z"},
        {"fact": "The Azure conduit carries PN emergency radio data.", "evidence_ids": ["E-136"], "section": "DNS", "question": "B3",
         "added": "2026-10-13T10:31:27Z"},
        {"fact": "Only the previous assessment says this.", "evidence_ids": ["E-001"], "section": "DNS", "question": "B3", "added": "x"},
        {"fact": "Another section.", "evidence_ids": ["E-456"], "section": "INET", "question": "B3", "added": "x"},
    ]
    (work / "facts" / "facts.jsonl").write_text("\n".join(json.dumps(f) for f in facts) + "\n", encoding="utf-8")
    return tmp_path


def test_facts_to_keep_are_the_newest_capture_backed_facts_of_this_subsection(tmp_path):
    keep = section_card.facts_to_keep({"key": "DNS"}, _store(tmp_path))
    assert [(k["question"], k["capture_ids"]) for k in keep] == [("B3", ["E-136"]), ("B3", ["E-456"])]
    assert keep[1]["fact"].startswith("RevBroadcast cannot reach")           # newest wording wins


def test_losing_a_fact_to_keep_is_refused_even_with_no_previous_sheet(tmp_path):
    keep = [{**k, "question": "B1"} for k in section_card.facts_to_keep({"key": "DNS"}, _store(tmp_path))]
    card = {**CARD, "keep": keep}
    lost = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}"])
    res = A.validate(lost, card, MATRIX, draft=True)
    msgs = [f["message"] for f in res["findings"] if f["code"] == "CAPTURE_DROPPED"]
    assert len(msgs) == 2 and any("PN emergency radio data" in m for m in msgs)
    kept = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}",
                   "RevBroadcast cannot reach the Azure Service Bus endpoint during isolation. (E-456) {observed; ROTPRDRBS101}"],
                  "Dropped: E-136 the conduit is described in 3.17, not under DNS.\n")
    assert "CAPTURE_DROPPED" not in _errors(A.validate(kept, card, MATRIX, draft=True))


def test_prev_based_message_names_the_fact():
    new = _sheet(["Name resolution fails at activation. (E-001) {documented; all hosts}"])
    res = A.validate(new, CARD, MATRIX, draft=True, previous=OLD)
    m = [f["message"] for f in res["findings"] if f["code"] == "CAPTURE_DROPPED"][0]
    assert "email alerts through corporate SMTP" in m


def test_every_capture_form_is_recognised():
    cap = lambda s, status="VERIFIED": A.source_class({"source_title": s, "status": status})
    assert cap("REVELOC_discovery_ROTPRDCLU101_20260709T042915Z: 03_time_status.txt") == "capture"
    assert cap("REVELOC_discovery_<host>_<timestamp>: 41_dns_query_tests.txt for IPTPRDAPP137_20260605T031609Z") == "capture"
    assert cap("REVELOC_discovery_<host>: 66_scheduled_tasks.txt (7 captures)") == "capture"
    assert cap("02_reveloc_expected_flow_map.txt in IPTPRDAPP137_20260605T031609Z") == "capture"
    assert cap("21_established_connections_raw.txt; 20_listening_ports.txt") == "capture"
    assert cap("revloc-tetra: 02_reveloc_expected_flow_map.txt") == "capture"
    assert cap("searched 02_reveloc_expected_flow_map.txt, 42_local_shares.txt") != "capture"
    assert cap("discovery index search") != "capture"
    assert cap("NetSeg_Current_State_Assessment_REVELOC_TETRA.docx") == "previous"
    assert cap("../05 Revloc Tetra/01 Current State AS Built/revloc-tetra/system_matrix.xlsx") == "document"


def test_table_rows_are_stored_and_kept_but_never_offered_to_other_sections(tmp_path):
    import csv, json
    from csa_docx import fact_store
    work = tmp_path / "csa-work"
    work.mkdir()
    with (work / "evidence-matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["evidence_id", "status", "source_title", "claim", "question", "gap_or_action"])
        w.writeheader()
        w.writerow({"evidence_id": "E-034", "status": "VERIFIED", "claim": "x", "question": "", "gap_or_action": "",
                    "source_title": "REVELOC_discovery_<host>_<timestamp>: 41_dns_query_tests.txt for IPTPRDAPP137"})
    sheet = tmp_path / "s.md"
    sheet.write_text("## B2 Discovery Information\nRows:\n| Aspect | Configuration Observed | Coverage / Source |\n"
                     "| Names resolved | Eleven hosts answered all 22 DNS name queries | 11 hosts, query tests (E-034) |\n",
                     encoding="utf-8")
    card = tmp_path / "c.json"
    card.write_text(json.dumps({"key": "DNS"}), encoding="utf-8")
    assert fact_store.add_from_sheet(work, sheet, card) == 1
    keep = section_card.facts_to_keep({"key": "DNS"}, tmp_path)
    assert keep and keep[0]["kind"] == "row" and keep[0]["question"] == "B2" and "E-034" not in keep[0]["fact"]
    assert fact_store.lookup(work, {"eleven", "hosts", "answered", "queries", "names", "resolved"}, set()) == []
    lost = A.parse("## B2 Discovery Information\nRows:\n| Aspect | Configuration Observed | Coverage / Source |\n"
                   "| Resolvers | enterprise DNS | previous assessment (E-001) |\n")
    card_d = {"key": "DNS", "keep": keep, "questions": [{"id": "B2", "kind": "observation",
                                                          "columns": ["Aspect", "Configuration Observed", "Coverage / Source"]}],
              "evidence": {"B2": {"rows": [], "cut": [], "digest_ids": []}}}
    assert "CAPTURE_DROPPED" in _errors(A.validate(lost, card_d, MATRIX, draft=True))
