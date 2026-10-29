"""Gap lookup: matrix first, then the index; index hits become leads, never evidence."""
import json

from csa_docx import gap_lookup as gl
from csa_docx import leads


def _workspace(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "csa-work").mkdir(parents=True, exist_ok=True)
    return ws


def test_queries_use_hosts_in_documents_and_topic_words_not_host_fragments():
    text = "Role of MKYPRDOPS110 and ROKPRDOPS110, including whether they are the RevViewer jump hosts."
    assert gl.hosts_in(text) == ["MKYPRDOPS110", "ROKPRDOPS110"]
    assert gl.topic_words(text) == ["revviewer", "jump", "hosts"]
    q = gl.queries(text)
    assert ("MKYPRDOPS110", ".xlsx") in q and ("MKYPRDOPS110 jump", None) in q
    pairs = [q for q, _ in gl.queries("Confirm whether an OT DNS service or isolation fallback exists")]
    assert "dns fallback" in pairs and "service isolation" in pairs and len(pairs) <= 12


def _fake_run(matrix_matches, hits, written_ids, dup_of=None, index_ok=True):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if "lookup" in cmd:
            return {"status": "OK", "matches": matrix_matches}
        if "search" in cmd:
            return {"status": "OK", "results": hits} if index_ok else {"status": "ERROR"}
        if "append" in cmd:
            if dup_of:
                return {"status": "NOTHING_TO_WRITE", "skipped_duplicates": [{"duplicate_of": dup_of}]}
            return {"status": "APPENDED", "written": [{"evidence_id": written_ids.pop(0)}]}
        return None
    return run, calls


HIT = {"rel_path": "RevLoc/system_matrix.xlsx", "page_or_location": "system_matrix.xlsx sheet!row Sheet2!7",
       "source_title": "RevLoc/system_matrix.xlsx", "source_version": "", "evidence_excerpt": "MKYPRDOPS110 RevViewer Jump Host RDP to OT only"}


def test_index_hits_are_added_as_leads_and_leave_the_matrix_unchanged(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    run, calls = _fake_run([], [HIT], ["E-100"])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(ws, "DR-OPS-B1", "Role of MKYPRDOPS110 and the RevViewer jump hosts")
    assert res["verdict"] == "CANDIDATES" and res["lead_ids"] == ["L-000001"]
    assert res["answer_evidence_ids"] == res["evidence_ids"] == []
    assert not [c for c in calls if "append" in c]
    saved = leads.open_leads(ws, "DR-OPS-B1")
    assert saved[0]["source_ref"] == HIT["source_title"] and saved[0]["excerpt"].startswith("MKYPRDOPS110")


def test_a_matrix_row_that_answers_it_wins_and_legacy_or_not_found_rows_do_not_count(tmp_path, monkeypatch):
    answer = {"evidence_id": "E-043", "status": "VERIFIED", "review_state": "reviewed", "score": 0.8, "coverage": 1.0, "gap_or_action": ""}
    legacy = {"evidence_id": "E-016", "status": "VERIFIED", "review_state": "reviewed", "score": 0.9, "coverage": 1.0, "gap_or_action": "legacy L-0100"}
    earlier = {"evidence_id": "E-014", "status": "NOT_FOUND", "score": 0.9, "coverage": 1.0, "gap_or_action": "ask"}
    run, _ = _fake_run([legacy, earlier, answer], [], [])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-01", "Role of the jump hosts")
    assert res["verdict"] == "ANSWERED" and res["answer_evidence_ids"] == ["E-043"] and res["lead_ids"] == []
    run, _ = _fake_run([legacy, earlier], [], [])
    monkeypatch.setattr(gl, "_run", run)
    assert gl.lookup_gap(tmp_path, "DR-01", "Role of the jump hosts")["verdict"] == "NOT_FOUND"


def test_a_terminal_lead_is_not_offered_again_and_the_scope_is_reported(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    lead_id = leads.add_leads(ws, "DR-OPS-B1", "B1", "Role of MKYPRDOPS110", [HIT])[0]
    leads.review(ws, [lead_id], "not_an_answer", "tester", "source read")
    run, _ = _fake_run([], [HIT], [])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(ws, "DR-OPS-B1", "Role of MKYPRDOPS110")
    assert res["verdict"] == "NOT_FOUND" and "discovery index" in res["searched"] and "MKYPRDOPS110" in res["searched"]
    run, _ = _fake_run([], [], [], index_ok=False)
    monkeypatch.setattr(gl, "_run", run)
    assert "no index built" in gl.lookup_gap(ws, "DR-OPS-B1", "Role of MKYPRDOPS110")["searched"]


def test_only_source_checked_verified_rows_answer_and_related_rows_stay_separate(tmp_path, monkeypatch):
    checked = {"evidence_id": "E-006", "status": "VERIFIED", "review_state": "reviewed", "score": 0.7, "coverage": 0.9, "gap_or_action": ""}
    pending = {"evidence_id": "E-007", "status": "VERIFIED", "review_state": "pending", "score": 0.9, "coverage": 1.0, "gap_or_action": ""}
    inferred = {"evidence_id": "E-008", "status": "INFERRED", "review_state": "reviewed", "score": 0.9, "coverage": 1.0, "gap_or_action": ""}
    run, _ = _fake_run([pending, inferred, checked], [], [])
    monkeypatch.setattr(gl, "_run", run)
    result = gl.lookup_gap(tmp_path, "DR-X-01", "Where are the domain controllers")
    assert result["verdict"] == "ANSWERED"
    assert result["answer_evidence_ids"] == ["E-006"]
    assert result["related_evidence_ids"] == ["E-007", "E-008"]


def test_a_hit_must_be_about_the_gap_not_just_share_a_generic_word():
    dns02 = ("Confirm the network zone of the domain controllers used as resolvers and the names of the IPT resolvers. "
             "The network zone of the site domain controllers used as resolvers is not established by the captures.")
    junk = [
        "Description : Maintains date and time synchronization on all clients and servers in the network. If this service is stopped",
        "Profile : Domain, Public | DisplayName : Network Discovery (UPnP-In) | DisplayName : Network Discovery (UPnP-Out)",
        "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Microsoft SQL Server\\160 | HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Microsoft SQL Server\\160\\Bootstrap",
        "Detailed Zones and Conduits | Analyse network policies to enable enforcement of OT35 authentication and access requirements",
    ]
    assert not any(gl.relevant(x, dns02) for x in junk)
    good = "Resolvers for the site domain controllers: the IPT resolvers sit in the OT network zone and are named IPTPRDDNS01."
    assert gl.relevant(good, dns02)
    # a host named in the gap ties the hit to the gap
    assert gl.relevant("ROKPRDOPS110 RevViewer Jump Host RDP to OT only", "Role of ROKPRDOPS110")
    assert not gl.relevant("MOTPRDREV101 Reveloc application", "Role of ROKPRDOPS110")


def test_hits_that_are_not_about_the_gap_are_not_added_to_the_matrix(tmp_path, monkeypatch):
    off = dict(HIT, evidence_excerpt="Profile : Domain, Public | DisplayName : Network Discovery (UPnP-In) | DisplayName : x")
    run, calls = _fake_run([], [off], ["E-100"])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-DNS-02", "Confirm the network zone of the domain controllers used as resolvers")
    assert res["verdict"] == "NOT_FOUND" and not [c for c in calls if "append" in c]


# ---- stronger answer-seeking: owners, kinds of gap, vocabulary-led queries, spelling

def test_the_gap_names_who_can_confirm_it_and_is_classified():
    t = "what retention policy applies to the backup copies, which the application owner or backup service owner could confirm."
    assert gl.owners_in(t) == ["application owner", "backup service owner"]
    assert gl.classify_gap(t) == "document"                  # the question asks for a policy; the owners are who to ask
    assert gl.classify_gap("which accounts administer the boundary firewalls.") == "owner"
    assert gl.classify_gap("whether a fallback restore procedure exists for isolation events") == "document"
    assert gl.classify_gap("which time servers the captured hosts use, which the network owner could confirm.") == "system"
    assert gl.owners_in("what role MOTPRDREV101 performs") == []


def test_owner_and_document_gaps_are_searched_in_documents_only():
    q = gl.queries("what retention policy applies to the backup copies", "document", ["backup job", "retention"])
    assert q and all(path_like in gl._DOC_EXTS for _, path_like in q)
    system = gl.queries("which time servers the captured hosts use", "system", ["time source", "time server"])
    assert ("time server", None) in system


def test_queries_lead_with_the_sections_vocabulary_and_both_spellings():
    q = [t for t, _ in gl.queries("how are the hosts synchronised to the time source", "system", ["time source", "synchronise"])]
    assert "time source" in q[:2] and "synchronise" in q and "synchronize" in q
    assert gl.spelling_variant("synchronise") == "synchronize" and gl.spelling_variant("organization") == "organisation"
    assert gl.spelling_variant("source") is None


def test_with_section_vocabulary_a_hit_must_use_it_not_share_two_common_words():
    gap = "which time connections were observed to which servers"
    vocab = ["time source", "time server"]
    assert not gl.relevant("Next Run Time: N/A | Connections: 0 | servers", gap, vocab)
    assert gl.relevant("Time source on MKYPRDOPS110: MOTPRDSRV122", gap, vocab)


def test_a_gap_that_needs_a_person_is_looked_up_in_documents_and_says_so(tmp_path, monkeypatch):
    run, calls = _fake_run([], [], [])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-BAK-01", "what retention policy applies to the backup copies, which the backup service owner could confirm.")
    assert res["kind"] == "document" and res["owners"] == ["backup service owner"]
    assert "documents only" in res["searched"] and "policy, procedure or test" in res["searched"]
    searches = [c for c in calls if "search" in c]
    assert searches and all(any(e in c for e in gl._DOC_EXTS) for c in searches)


def test_the_most_specific_phrase_leads_and_generic_ones_are_not_searched():
    vocab = ["backup server", "retention", "host name", "zone", "security level", "IP address"]
    assert gl._phrases("what retention policy applies to the backup copies", vocab)[0] == "retention"
    assert gl._phrases("what Security Level Target is assigned to each security zone", vocab)[0] == "security level"
    assert not set(gl._phrases("which host name and zone and IP address", vocab)) & {"host name", "zone", "IP address"}


def test_a_gap_that_names_a_host_is_answered_only_by_something_about_that_host():
    gap = "IPTPRDLIC201: not in the discovery captures, so its time source is not known"
    vocab = ["time source", "time peer", "synchronis"]
    assert not gl.relevant("TaskName : ForceSynchronizeTime | Description : This task performs time synchronization.", gap, vocab)
    assert not gl.relevant("MOTPRDREV101 time source ROTPRDSRV122", gap, vocab)
    assert gl.relevant("IPTPRDLIC201 time source is IPTPRDSRV224", gap, vocab)


def test_the_scheduled_task_inventory_is_searched_only_for_gaps_about_tasks(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    task_hit = dict(HIT, rel_path="REVELOC_discovery_ROKPRDOPS110_20260607/66_scheduled_tasks.txt",
                    evidence_excerpt="TaskName : ForceSynchronizeTime | Description : This task performs time synchronization.")
    run, _ = _fake_run([], [task_hit], ["E-100"])
    monkeypatch.setattr(gl, "_run", run)
    assert gl.lookup_gap(ws, "DR-TIME-01", "which time servers synchronise the hosts")["verdict"] == "NOT_FOUND"
    run, _ = _fake_run([], [task_hit], ["E-101"])
    monkeypatch.setattr(gl, "_run", run)
    assert gl.lookup_gap(ws, "DR-TIME-02", "which scheduled task synchronises the time on the hosts")["verdict"] == "CANDIDATES"


def _confirm_setup(tmp_path, monkeypatch, with_verified):
    ws = _workspace(tmp_path)
    work = ws / "csa-work"
    (work / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,source_version,section,page_or_location,evidence_excerpt,"
        "inference_reason,confidence,gap_or_action,review_state\n"
        "E-006,ops,q,Citrix is the vendor route,VERIFIED,x,,,,y,,high,,pending\n"
        "E-052,gap_lookup,q,Possible answer to DR-X-01: noise,UNCONFIRMED,x,,,,y,,low,found,pending\n", encoding="utf-8")
    if with_verified:
        (work / "evidence-reviews.jsonl").write_text(json.dumps({"evidence_id": "E-006", "state": "reviewed", "by": "t", "at": "x", "note": ""}) + "\n")
    calls = []

    def run(cmd):
        calls.append(cmd)
        if "append" in cmd:
            return {"status": "APPENDED", "written": [{"evidence_id": "E-100"}]}
        return {"status": "OK", "matches": [], "results": []}
    monkeypatch.setattr(gl, "_run", run)
    lead_id = leads.add_leads(ws, "DR-X-01", "01", "Which vendors support it, and how", [HIT])[0]
    return ws, lead_id, calls


def _claim(calls):
    appended = [c for c in calls if "append" in c][0]
    return json.loads(appended[appended.index("--row-json") + 1])["claim"]


def test_a_not_found_record_names_the_verified_rows_that_bear_on_the_question(tmp_path, monkeypatch):
    ws, lead_id, calls = _confirm_setup(tmp_path, monkeypatch, with_verified=True)
    gl.confirm_gap(ws, "DR-X-01", "Which vendors support it, and how", [lead_id], searched="saved scope",
                   ask="ask the vendor", related_evidence_ids=["E-006", "E-052"])
    claim = _claim(calls)
    assert claim.startswith("No evidence answers all of: Which vendors support it, and how.")
    assert "E-006" in claim and "E-052" not in claim                      # an unverified candidate is never named
    assert leads.open_leads(ws, "DR-X-01") == []
    assert not [c for c in calls if "lookup" in c or "search" in c]


def test_a_not_found_record_with_no_verified_row_keeps_the_plain_sentence(tmp_path, monkeypatch):
    ws, lead_id, calls = _confirm_setup(tmp_path, monkeypatch, with_verified=True)
    gl.confirm_gap(ws, "DR-X-01", "Where is the gateway", [lead_id], searched="saved scope", ask="ask")
    assert _claim(calls) == "No evidence in the matrix or the discovery index answers: Where is the gateway"
