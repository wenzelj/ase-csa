"""A question is looked up with the topic's own words before it is asked."""
from csa_docx import gap_lookup as G
from csa_docx import matrix_candidates as M

ROWS = [
    {"evidence_id": "E-1249", "csa_area": "time_synchronisation", "status": "VERIFIED",
     "claim": "Time source on MOTPRDCLU101, MOTPRDREV101 and ROKPRDOPS110: ROTPRDSRV122 (10.40.228.97)"},
    {"evidence_id": "E-1251", "csa_area": "time_synchronisation", "status": "VERIFIED",
     "claim": "Time source on MKYPRDOPS110 and MOTPRDCLU103: MOTPRDSRV122 (10.45.228.97)"},
    {"evidence_id": "E-010", "csa_area": "identity_and_access", "status": "VERIFIED",
     "claim": "IPTPRDSRV123.internal.qr.com.au holds the PDC emulator role for the INTERNAL domain"},
    {"evidence_id": "E-2377", "csa_area": "discovery_required", "status": "NOT_FOUND",
     "claim": "No evidence in the matrix or the discovery index answers: which time connections were observed to which servers"},
    {"evidence_id": "E-1416", "csa_area": "gap_lookup", "status": "UNCONFIRMED",
     "claim": "Possible answer to DR-TIME-F1: the source reads: time source ROTPRDSRV122"},
    {"evidence_id": "E-488", "csa_area": "dependencies", "status": "VERIFIED",
     "claim": "Every captured host declares the dependency Corporate Email / SMTP on connections to servers"},
    {"evidence_id": "E-9", "csa_area": "time_synchronisation", "status": "VERIFIED", "gap_or_action": "legacy L-4",
     "claim": "Time source from the previous assessment"},
]
Q = "Which time connections were seen, to which servers, and do they cross from OT into IT?"


def ids(found):
    return [c["id"] for c in found]


def test_the_topic_vocabulary_finds_the_rows_the_question_words_miss():
    found = M.candidates(ROWS, Q, ["time source", "synchronis", "NTP"], "time_synchronisation")
    assert ids(found) == ["E-1249", "E-1251"]


def test_our_own_gap_rows_and_unrelated_rows_are_never_offered():
    assert not set(ids(M.candidates(ROWS, Q, ["time source"]))) & {"E-2377", "E-1416", "E-488", "E-9"}
    assert M.candidates(ROWS, Q) == []                       # no vocabulary: three question words are needed


def test_a_row_must_hold_a_topic_phrase_and_a_word_of_the_question():
    found = M.candidates(ROWS, "What hierarchy sits above it, with a PDC emulator?", ["PDC emulator"])
    assert ids(found) == ["E-010"]


def test_the_who_could_confirm_tail_is_not_part_of_the_search():
    t = "which time connections were observed to which servers, which the network owner could confirm."
    assert G.strip_confirmers(t) == "which time connections were observed to which servers"
    assert G.strip_confirmers("whether the zone is known, which the OT network owner and the Reveloc owner could confirm") \
        == "whether the zone is known"
    assert G.strip_confirmers("what role HOST1 performs") == "what role HOST1 performs"


def test_a_dr_id_finds_its_frames_vocabulary():
    vocab, area = G.section_vocabulary("DR-TIME-F1")
    assert "time source" in vocab and "PDC emulator" not in vocab and area == "time_synchronisation"   # S4 (what sits above the source) is retired: the boundary ends at IT
    assert area == "time_synchronisation"
    assert G.section_vocabulary("DR-NOPE-F1") == ([], "")


def test_every_profile_slot_the_captures_may_leave_empty_has_evidence_vocabulary():
    from csa_docx import topic_frames
    frames = topic_frames.all_frames()
    assert len(frames) >= 17
    missing = [f"{fr['key']}.{s['id']}" for fr in frames for s in fr["slots"]
               if not s.get("source", {}).get("settings") and not M.natural_terms(s.get("look_for"))]
    assert not missing, f"no look_for phrases that evidence claims can contain: {missing}"


def test_capture_file_terms_are_not_vocabulary_but_plain_phrases_are():
    assert M.natural_terms(["Get-LocalUser", "NtpServer", "Cert:\\LocalMachine\\My", "Win32_ComputerSystem", "PDC emulator",
                            "backup job", "port 53"]) == ["PDC emulator", "backup job", "port 53"]


def test_one_weak_single_word_does_not_qualify_a_row():
    rows = [{"evidence_id": "E-1", "csa_area": "x", "status": "VERIFIED", "claim": "The manual start service WdNisSvc is running"}]
    assert M.candidates(rows, "Which manual processes replace the automated interactions?", ["manual process", "workaround"]) == []
    rows[0]["claim"] = "The operators follow a manual process when the link is lost"
    assert [c["id"] for c in M.candidates(rows, "Which manual processes replace the automated interactions?",
                                          ["manual process", "workaround"])] == ["E-1"]


def test_related_rows_never_change_a_gaps_verdict(tmp_path, monkeypatch):
    """A row that only reads like the question must not remove the gap from Discovery Required."""
    import csv
    work = tmp_path / "csa-work"
    work.mkdir()
    with open(work / "evidence-matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["evidence_id", "csa_area", "status", "claim", "gap_or_action", "review_state"])
        w.writeheader()
        w.writerow(ROWS[0] | {"gap_or_action": "", "review_state": "reviewed"})
    monkeypatch.setattr(G, "_matrix_stage", lambda *a: ("NONE", [], []))
    monkeypatch.setattr(G, "_index_stage", lambda *a: ([], ["q"], True))
    res = G.lookup_gap(tmp_path, "DR-TIME-B1", "which time connections were observed to which servers, which the owner could confirm")
    assert res["verdict"] == "NOT_FOUND" and res["related"] == ["E-1249"]
