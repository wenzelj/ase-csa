"""Gap lookup: matrix first, then the index; what it finds goes into the matrix; rejected rows are not offered again."""
import json

from csa_docx import gap_lookup as gl


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


def test_index_hits_are_added_to_the_matrix_as_unconfirmed_candidates(tmp_path, monkeypatch):
    run, calls = _fake_run([], [HIT], ["E-100"])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-01", "Role of MKYPRDOPS110 and the RevViewer jump hosts")
    assert res["verdict"] == "CANDIDATES" and res["index"] == ["E-100"] and res["matrix"] == []
    appended = [c for c in calls if "append" in c][0]
    row = json.loads(appended[appended.index("--row-json") + 1])
    assert row["status"] == "UNCONFIRMED" and row["evidence_excerpt"].startswith("MKYPRDOPS110")


def test_a_matrix_row_that_answers_it_wins_and_legacy_or_not_found_rows_do_not_count(tmp_path, monkeypatch):
    answer = {"evidence_id": "E-043", "status": "VERIFIED", "score": 0.8, "coverage": 1.0, "gap_or_action": ""}
    legacy = {"evidence_id": "E-016", "status": "VERIFIED", "score": 0.9, "coverage": 1.0, "gap_or_action": "legacy L-0100"}
    earlier = {"evidence_id": "E-014", "status": "NOT_FOUND", "score": 0.9, "coverage": 1.0, "gap_or_action": "ask"}
    run, _ = _fake_run([legacy, earlier, answer], [], [])
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-01", "Role of the jump hosts")
    assert res["verdict"] == "ANSWERED" and res["matrix"] == ["E-043"]
    run, _ = _fake_run([legacy, earlier], [], [])
    monkeypatch.setattr(gl, "_run", run)
    assert gl.lookup_gap(tmp_path, "DR-01", "Role of the jump hosts")["verdict"] == "NOT_FOUND"


def test_a_rejected_candidate_is_not_offered_again_and_the_scope_is_reported(tmp_path, monkeypatch):
    (tmp_path / "csa-work").mkdir()
    (tmp_path / "csa-work" / "evidence-reviews.jsonl").write_text(
        json.dumps({"evidence_id": "E-100", "state": "rejected"}) + "\n", encoding="utf-8")
    run, _ = _fake_run([], [HIT], [], dup_of="E-100")
    monkeypatch.setattr(gl, "_run", run)
    res = gl.lookup_gap(tmp_path, "DR-01", "Role of MKYPRDOPS110")
    assert res["verdict"] == "NOT_FOUND" and "discovery index" in res["searched"] and "MKYPRDOPS110" in res["searched"]
    run, _ = _fake_run([], [], [], index_ok=False)
    monkeypatch.setattr(gl, "_run", run)
    assert "no index built" in gl.lookup_gap(tmp_path, "DR-01", "Role of MKYPRDOPS110")["searched"]


def test_a_confirmed_gap_lists_what_was_considered_and_is_not_offered_again(tmp_path, monkeypatch):
    (tmp_path / "csa-work").mkdir()
    (tmp_path / "csa-work" / "evidence-matrix.csv").write_text(
        "evidence_id,csa_area,question,claim,status,source_title,source_version,section,page_or_location,evidence_excerpt,"
        "inference_reason,confidence,gap_or_action,review_state\n"
        "E-006,net,q,DC answers,VERIFIED,x,,,,y,,high,,pending\n"
        "E-052,gap_lookup,q,Possible answer to DR-X-01: noise,UNCONFIRMED,x,,,,y,,low,found,pending\n"
        "E-070,discovery_required,q,c,NOT_FOUND,x,,,,,\"read and considered, not an answer to DR-X-01: E-006 E-052\",low,DR-X-01 ask,pending\n",
        encoding="utf-8")
    assert gl._acknowledged(tmp_path, "DR-X-01") == {"E-006", "E-052"}
    row = {"evidence_id": "E-006", "status": "VERIFIED", "score": 0.7, "coverage": 0.9, "gap_or_action": ""}
    run, _ = _fake_run([row], [], [])
    monkeypatch.setattr(gl, "_run", run)
    assert gl.lookup_gap(tmp_path, "DR-X-01", "Where are the domain controllers")["verdict"] == "NOT_FOUND"


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
