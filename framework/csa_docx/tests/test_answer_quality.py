"""Draft-lane answer quality: declared dependencies on isolation cards, no foreign absences offered as
established facts, no silent loss of capture evidence, one question per Unknown line."""
from csa_docx import answer_sheet as A
from csa_docx import evidence_digest as D
from csa_docx import section_card

CAPTURE = "REVELOC_discovery_IPTPRDAPP137_20260605T031609Z: 23_process_connection_mapping.txt"
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


def test_mixed_verified_and_unverified_fact_is_not_carried_forward(tmp_path):
    """Removing an ineligible ID must remove its whole old claim, not only the citation."""
    import json
    root = _store(tmp_path)
    facts = root / "csa-work" / "facts" / "facts.jsonl"
    mixed = {"fact": "RevBroadcast reaches Azure, and no fallback exists.",
             "evidence_ids": ["E-456", "E-999"], "section": "DNS", "question": "B3",
             "added": "2026-10-14T10:31:27Z"}
    with facts.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(mixed) + "\n")

    keep = section_card.facts_to_keep({"key": "DNS"}, root)

    assert all("no fallback exists" not in k["fact"] for k in keep)
    assert all("E-999" not in k["evidence_ids"] for k in keep)
    assert any(k["fact"].startswith("RevBroadcast cannot reach") for k in keep)


def test_sanitised_negative_fact_needs_negative_verified_support(tmp_path):
    """A prior run may already have stripped the NOT_FOUND ID before storing the fact again."""
    import json
    root = _store(tmp_path)
    facts = root / "csa-work" / "facts" / "facts.jsonl"
    unsupported = {"fact": "The expected path is declared, but no matching connection appeared.",
                   "evidence_ids": ["E-456"], "section": "DNS", "question": "B3",
                   "added": "2026-10-15T10:31:27Z"}
    with facts.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(unsupported) + "\n")

    keep = section_card.facts_to_keep({"key": "DNS"}, root)

    assert all("no matching connection" not in k["fact"] for k in keep)


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


def test_count_mismatch_ignores_drive_letters_and_counts_of_other_things():
    from csa_docx import answer_sheet as A
    assert A.count_mismatch("The Rockhampton Reveloc application server holds 228 Windows Server Backup versions on its own C: drive, the latest from November 2018.") is None
    assert A.count_mismatch("The host keeps 40 scheduled tasks: two for backup, one for logs.") is None
    assert A.count_mismatch("Twelve hosts: two jump hosts, one server, six nodes") == "the parts add up to 9, not 12"


def test_a_peer_known_only_by_address_is_named_by_its_address_without_a_warning():
    from csa_docx import answer_sheet as A
    card = {"parts": {"hosts": {"10.40.228.180": "general-purpose-jump-host", "ROKPRDOPS110": "general-purpose-jump-host"}}}
    assert A.named_host_addresses(card) == {"10.40.228.180"}
    sheet = {"B1": {"summary": "The nodes open SMB to 10.89.163.66.", "story": "", "text": ""}}
    q = {"id": "B1", "kind": "requirement", "text": "Where is the data held?"}
    out = A.plain_language_checks(sheet, {"questions": [q], **card})
    assert not [f for f in out if f["code"] == "HOST_IN_PROSE"]
    sheet = {"B1": {"summary": "The jump host 10.40.228.180 opens it.", "story": "", "text": ""}}
    out = A.plain_language_checks(sheet, {"questions": [q], **card})
    assert [f for f in out if f["code"] == "HOST_IN_PROSE"]


def test_rating_reason_and_closing_paragraph_that_repeat_the_summary_are_flagged():
    from csa_docx import answer_sheet as A
    import inspect
    src = inspect.getsource(A)
    assert "REASON_REPEATS_SUMMARY" in src and "STORY_ENDS_BY_REPEATING" in src
    assert {"REASON_REPEATS_SUMMARY", "STORY_ENDS_BY_REPEATING"} <= A.CONTENT_CODES


def test_rows_quoting_the_scripts_expected_flow_list_are_not_offered_but_stay_in_the_matrix(tmp_path):
    import csv
    from csa_docx import evidence_live
    m = tmp_path / "evidence-matrix.csv"
    cols = ["evidence_id", "status", "review_state", "source_title", "page_or_location", "claim"]
    rows = [["E-1", "VERIFIED", "reviewed", "REVELOC_discovery_A_20260605T010000Z: 02_reveloc_expected_flow_map.txt", "", "The expected flow map records R1."],
            ["E-2", "VERIFIED", "reviewed", "REVELOC_discovery_A_20260605T010000Z: 23_process_connection_mapping.txt", "", "A opened a connection."],
            ["E-3", "VERIFIED", "reviewed", "x.docx", "02_reveloc_expected_flow_map.txt, R1 entries", "R1 is core."]]
    with m.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
    assert [r["evidence_id"] for r in evidence_live.get_verified_evidence(m)] == ["E-2"]
    assert [r["evidence_id"] for r in evidence_live.read(m)] == ["E-1", "E-2", "E-3"]          # still in the matrix for every other reader


def test_an_absence_claim_needs_a_fact_that_names_the_thing():
    from csa_docx import answer_sheet as A
    q = {"id": "B2", "kind": "requirement", "text": "Is there a controlled transfer pattern?"}
    card = {"questions": [q]}
    base = {"summary": "S.", "story": "No proxy, scanning service or other defined transfer path was identified.", "rating_reason": "", "unknown": []}
    bad = {"B2": {**base, "facts": [{"text": "The jump host has WinSCP installed."}]}}
    good = {"B2": {**base, "facts": [{"text": "No host has a proxy configured."}, {"text": "The scanning service is absent."}]}}
    assert [f["code"] for f in A.absence_checks(bad, card)] == ["ABSENCE_WITHOUT_FACT"]
    assert "proxy" in A.absence_checks(bad, card)[0]["message"]
    assert A.absence_checks(good, card) == []


def _block(story="", facts=(), summary="S.", reason=""):
    return {"summary": summary, "story": story, "rating_reason": reason, "unknown": [], "dropped": [], "covers": [],
            "facts": [{"text": t, "ids": i} for t, i in facts], "bullets": [], "rows": []}


def test_a_must_state_setting_finding_left_out_is_an_error_and_stating_it_clears_it():
    from csa_docx import answer_sheet as A
    item = {"slot": "S8", "text": "Proxy setting on A, B: Direct, no WinHTTP proxy", "ids": ["E-2995"], "direction": "", "tokens": [],
            "empty": False, "must_state": True, "far_unknown": False}
    fr = {"must_address": {"B2": [item]}}
    left_out = {"B2": _block(facts=[("A host has WinSCP.", ["E-1"])])}
    stated = {"B2": _block(facts=[("No host has a proxy configured.", ["E-2995"])])}
    assert [f["code"] for f in A.slot_answers(left_out, fr) if f["level"] == "ERROR"] == ["SETTING_NOT_STATED"]
    assert not [f for f in A.slot_answers(stated, fr) if f["level"] == "ERROR"]
    assert "SETTING_NOT_STATED" in A.RELAXED_HARD


def test_saying_data_leaves_ot_while_the_far_end_zone_is_unknown_is_flagged():
    from csa_docx import answer_sheet as A
    q = {"id": "B3", "kind": "requirement", "text": "Does data only go outward?"}
    card = {"questions": [q], "frame": {"must_address": {"B3": [{"slot": "S3", "far_unknown": True}]}}}
    assert [f["code"] for f in A.direction_checks({"B3": _block(story="Some of that data leaves OT at the nodes' initiative.")}, card)] == ["DIRECTION_ASSUMED"]
    assert A.direction_checks({"B3": _block(story="The nodes open the connection; the zone of 10.89.163.66 is not recorded.")}, card) == []
    card_known = {"questions": [q], "frame": {"must_address": {"B3": [{"slot": "S3", "far_unknown": False}]}}}
    assert A.direction_checks({"B3": _block(story="Some of that data leaves OT.")}, card_known) == []


def test_a_glossary_term_must_be_explained_beside_its_first_mention_in_the_story():
    from csa_docx import answer_sheet as A
    q = {"id": "B2", "kind": "requirement", "text": "q"}
    card = {"questions": [q]}
    bare = {"B2": _block(story="Several servers hold connections open to the SysVol share on another server.")}
    done = {"B2": _block(story="Several servers hold connections open to the SysVol share, the domain share that holds login scripts and policies.")}
    summary_only = {"B2": _block(summary="They use Server Message Block.", story="Files sit in local shares.")}
    assert [f["code"] for f in A.glossary_checks(bare, card)] == ["TERM_NOT_EXPLAINED"] and "SysVol" in A.glossary_checks(bare, card)[0]["message"]
    assert A.glossary_checks(done, card) == [] and A.glossary_checks(summary_only, card) == []
    assert "TERM_NOT_EXPLAINED" in A.RELAXED_HARD


def test_saying_what_is_not_recorded_four_times_in_one_block_is_flagged():
    from csa_docx import answer_sheet as A
    q = {"id": "B3", "kind": "requirement", "text": "q"}
    card = {"questions": [q]}
    many = {"B3": _block(summary="The zone is not recorded.", story="The name is not recorded. The role is not known. Nothing more is established.", reason="The zone is not recorded.")}
    once = {"B3": _block(summary="Partly met.", story="The nodes open the connection. The zone is not recorded.", reason="The zone decides it.")}
    assert [f["code"] for f in A.repeated_unknown_checks(many, card)] == ["REPEATED_UNKNOWN"] and A.repeated_unknown_checks(once, card) == []


def test_a_rating_reason_on_a_different_ground_from_the_summary_is_flagged():
    from csa_docx import answer_sheet as A
    import inspect
    assert "REASON_DIFFERS_FROM_SUMMARY" in inspect.getsource(A) and "REASON_DIFFERS_FROM_SUMMARY" in A.CONTENT_CODES


def test_settings_that_say_nothing_is_configured_are_worded_so_they_cannot_be_misread():
    from csa_docx import topic_frames as T
    assert T._finding_claim("Proxy setting", "transfer.proxy", "Direct, no WinHTTP proxy", "A and B") == \
        "No web proxy is configured on A and B (WinHTTP uses direct access)"
    assert T._finding_claim("Removable storage policy", "transfer.removable", "Not set in applied Group Policy", "A") == \
        "No removable storage restriction is set in the applied Group Policy of A"
    assert T._finding_claim("Shares", "storage.shares", "TetraFlex", "A") == "Shares on A: TetraFlex"
