"""Application-level coverage: a topic answer must speak for every application component, not the best-evidenced one.

Phase 0: an application whose review lapses on a rebuild is reported, with why, and the card says it is left out.
"""
import json

from csa_docx import parts as P

HEAD = ("host,in_scope,system,role,site,system_source,role_source,site_source,conflicts,fqdn,ips,ou,capture,"
        "captured_in,listening,sources,ad_site\n")


def _hosts(wd, rows):
    (wd / "hosts").mkdir(parents=True, exist_ok=True)
    (wd / "hosts" / "hosts.csv").write_text(HEAD + "".join(
        f"{h},Yes,Reveloc,{role},{site},register,register,register,,,{h}.fqdn,{ip},cap,,,listening,source,,\n"
        for h, role, site, ip in rows), encoding="utf-8")
    (wd / "hosts" / "unrecorded-peers.csv").write_text("peer,side,ports,mechanisms,processes,talks_to,flows,flow_ids,hint\n",
                                                       encoding="utf-8")


def _reviewed(tmp, rows):
    wd = tmp / "csa-work"
    _hosts(wd, rows)
    doc = P.build(wd)
    ids = {p["name"]: p["id"] for p in doc["parts"]}
    doc["applications"] = [{"id": "reveloc", "name": "Reveloc", "purpose": "Tracks radios.", "reviewed": True,
                            "parts": [ids["Reveloc application / TGOIP server"], ids["OT Reveloc Server"]]},
                           {"id": "sepura", "name": "Sepura Radio Manager", "purpose": "Programs radios.", "reviewed": True,
                            "parts": [ids["Sepura Radio Manager server"]]}]
    doc["reviewed"] = True
    P.path(wd).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return wd


ROWS = [("MOTPRDREV101", "Reveloc application / TGOIP server", "Mackay", "10.1.1.1"),
        ("ROTPRDREV102", "OT Reveloc Server", "Rockhampton", "10.1.1.2"),
        ("IPTPRDAPP137", "Sepura Radio Manager server", "IPT", "10.1.1.3")]


def test_no_drift_while_the_parts_are_unchanged(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    assert P.application_drift(wd) == []


def test_a_new_member_lapses_the_review_and_says_which_part(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    _hosts(wd, ROWS + [("ROTPRDREV101", "Reveloc application / TGOIP server", "Rockhampton", "10.1.1.4")])
    drift = P.application_drift(wd)
    assert [d["name"] for d in drift] == ["Reveloc"]
    assert drift[0]["was_reviewed"] is True
    assert "joined: ROTPRDREV101" in " ".join(drift[0]["reasons"])


def test_a_renamed_part_is_reported_with_the_likely_new_id(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    doc = P.load(wd)
    doc["applications"][0]["parts"] = [("reveloc-application-tgoip-servers" if x == "reveloc-application-tgoip-server" else x)
                                       for x in doc["applications"][0]["parts"]]
    P.path(wd).write_text(json.dumps(doc), encoding="utf-8")
    reasons = " ".join(P.application_drift(wd)[0]["reasons"])
    assert "no longer a part" in reasons and "reveloc-application-tgoip-server" in reasons


def test_show_applications_lists_what_is_off_the_cards():
    doc = {"parts": [], "applications": [{"name": "Reveloc", "parts": [], "reviewed": False}]}
    text = P.show_applications(doc, [{"name": "Reveloc", "reasons": ["members of 'x' changed"]}])
    assert "Not on the section cards until reviewed again" in text and "Reveloc: members of 'x' changed" in text


# ---- Phases 1 to 3: the coverage block says what the findings cover and leaves the rest unknown -------------------------

def _frame(coverage_settings=("agent.backup", "storage.database")):
    """A frame with a backup-agent finding for MOTPRDREV101 only and a database finding for ROTPRDREV102 only."""
    return {"coverage_settings": list(coverage_settings), "component_prompt": "Say it for each component.",
            "slots": [{"id": "S1", "findings": [
                {"attr": "agent.backup", "text": "Backup agent on MOTPRDREV101: Dell PowerProtect agent", "hosts": ["MOTPRDREV101"],
                 "ids": ["E-1"], "requirements": ["SEP-BAK-01"], "evidence": [{"status": "VERIFIED"}]},
                {"attr": "storage.database", "text": "Database service on ROTPRDREV102: MySQL", "hosts": ["ROTPRDREV102"],
                 "ids": ["E-2"], "requirements": ["SEP-BAK-01"], "evidence": [{"status": "VERIFIED"}]},
                {"attr": "backup.vss", "text": "Shadow copies on MOTPRDREV101", "hosts": ["MOTPRDREV101"],
                 "ids": ["E-3"], "requirements": ["SEP-BAK-01"], "evidence": [{"status": "VERIFIED"}]}]}]}


def _cov(wd, fr, appview=None):
    doc = P.assemble(wd)
    return P.coverage(wd, doc, fr, P.grid(doc, fr), appview), doc


def _captured(wd, hosts):
    (wd / "hosts").mkdir(parents=True, exist_ok=True)
    (wd / "hosts" / "host_settings.csv").write_text(
        "host,attribute,value,source,excerpt\n" + "".join(f"{h},net.address,1.1.1.1,x.txt line 1,x\n" for h in hosts),
        encoding="utf-8")


def test_a_part_without_a_finding_is_not_evidenced_not_absent(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    _captured(wd, ["MOTPRDREV101", "ROTPRDREV102", "IPTPRDAPP137"])
    cov, doc = _cov(wd, _frame())
    ids = {p["name"]: p["id"] for p in doc["parts"]}
    tgoip, ot_rev, sepura = (cov["parts"][ids[n]] for n in ("Reveloc application / TGOIP server", "OT Reveloc Server",
                                                           "Sepura Radio Manager server"))
    assert tgoip["found"] == ["agent.backup"] and tgoip["gaps"] == ["storage.database"]
    assert ot_rev["found"] == ["storage.database"] and ot_rev["gaps"] == ["agent.backup"]
    assert sepura["found"] == [] and set(sepura["gaps"]) == {"agent.backup", "storage.database"}
    text = "\n".join(P.coverage_lines(cov))
    assert "Not evidenced: Backup agent" in text and "NOT evidence that the part lacks the thing" in text
    assert "Say it for each component." in text


def test_only_the_settings_the_frame_names_decide_the_gaps(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    _captured(wd, ["MOTPRDREV101", "ROTPRDREV102", "IPTPRDAPP137"])
    cov, _ = _cov(wd, _frame())
    assert set(cov["units"]) == {"agent.backup", "storage.database"}      # backup.vss is not a deciding setting


def test_a_part_with_no_captured_host_says_nothing_is_evidenced(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    _captured(wd, ["MOTPRDREV101"])
    cov, _ = _cov(wd, _frame())
    assert "no host of this part was captured" in "\n".join(P.coverage_lines(cov))


def test_the_block_is_opt_in_per_frame(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    assert _cov(wd, _frame(coverage_settings=()))[0] is None
    fr = _frame()
    fr["coverage"] = False
    assert _cov(wd, fr)[0] is None
    assert P.coverage_lines(None) == []


def test_parts_are_grouped_by_reviewed_application_and_shared_ones_say_so(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    _captured(wd, ["MOTPRDREV101", "ROTPRDREV102", "IPTPRDAPP137"])
    doc = P.assemble(wd)
    ids = {p["name"]: p["id"] for p in doc["parts"]}
    doc["applications"][0]["role_in"] = {ids["OT Reveloc Server"]: "shared"}
    view = P.application_view(wd, doc, {})
    cov = P.coverage(wd, doc, _frame(), P.grid(doc, _frame()), view)
    assert [g["title"] for g in cov["groups"]][:2] == ["Reveloc", "Sepura Radio Manager"]
    text = "\n".join(P.coverage_lines(cov))
    assert "### Reveloc" in text and "OT Reveloc Server (shared)" in text


def test_the_card_names_the_applications_it_cannot_describe(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    doc = P.assemble(wd)
    doc["applications"][0]["reviewed"] = False
    view = P.application_view(wd, doc, {})
    assert view["left_out"] == ["Reveloc"]
    assert any("not reviewed, so not described here: Reveloc" in ln for ln in view["lines"])
    assert any("do not let another application's evidence stand for them" in ln for ln in view["lines"])


# ---- Phase 5: the answer checks -----------------------------------------------------------------------------------------
from csa_docx import answer_sheet as A  # noqa: E402

CARD = {
    "questions": [{"id": "B1", "kind": "requirement", "req_id": "SEP-BAK-01"},
                  {"id": "B2", "kind": "requirement", "req_id": "SEP-BAK-02"}],
    "frame": {"strict": False},
    "parts": {
        "names": {"cl": ["SQL Server cluster node (instance S01)"], "tg": ["Reveloc application / TGOIP server"],
                  "rb": ["RevBroadcast System Application Server"], "dr": ["OT Digital Radio Management Server"]},
        "parts": {"cl": "SQL Server cluster node (instance S01)", "tg": "Reveloc application / TGOIP server",
                  "rb": "RevBroadcast System Application Server", "dr": "OT Digital Radio Management Server"},
        "hosts": {"C1": "cl", "T1": "tg", "R1": "rb", "D1": "dr"}, "sides": {}, "owed": {}, "isolation": {},
        "features": {"database backups": ["cl", "dr"]},
        "coverage": {
            "units": {"agent.backup": "Backup agent", "storage.backup_windows": "Windows Server Backup history"},
            "units_req": {"agent.backup": ["SEP-BAK-01"], "storage.backup_windows": ["SEP-BAK-02"]},
            "parts": {"cl": {"name": "SQL Server cluster node (instance S01)", "captured": True, "found": ["agent.backup"],
                             "gaps": ["storage.backup_windows"]},
                      "tg": {"name": "Reveloc application / TGOIP server", "captured": True, "found": ["agent.backup"],
                             "gaps": []},
                      "rb": {"name": "RevBroadcast System Application Server", "captured": True, "found": [],
                             "gaps": ["agent.backup", "storage.backup_windows"]},
                      "dr": {"name": "OT Digital Radio Management Server", "captured": False, "found": [],
                             "gaps": ["agent.backup"]}}}}}


def _cov_codes(text):
    return [(f["question"], f["code"], f["message"]) for f in A.part_checks(A.parse(text), CARD)
            if f["code"] == "APPLICATION_COVERAGE"]


def test_a_part_with_a_gap_that_the_block_leaves_out_is_flagged():
    hit = _cov_codes("## B1 SEP-BAK-01\nSummary: The SQL Server cluster node (instance S01) runs a backup agent.\n")
    assert len(hit) == 1 and hit[0][0] == "B1"
    assert "RevBroadcast System Application Server (Backup agent)" in hit[0][2] and "never absent" in hit[0][2]


def test_naming_the_part_or_asking_about_it_clears_the_flag():
    named_in_story = ("## B1 SEP-BAK-01\nStory: A backup agent is evidenced on the SQL Server cluster node (instance S01). "
                      "None is evidenced for the RevBroadcast System Application Server.\n")
    assert _cov_codes(named_in_story) == []
    asked = ("## B1 SEP-BAK-01\nSummary: The SQL Server cluster node (instance S01) runs a backup agent.\n"
             "QUESTION: What backs up the data on the RevBroadcast System Application Server?\n")
    assert _cov_codes(asked) == []


def test_only_the_settings_that_decide_this_requirement_count():
    # B2's deciding setting is the Windows Server Backup history: the backup agent gap of the RevBroadcast server is B1's
    hit = _cov_codes("## B2 SEP-BAK-02\nSummary: The SQL Server cluster node (instance S01) keeps no restore record.\n")
    assert len(hit) == 1 and "Windows Server Backup history" in hit[0][2] and "Backup agent" not in hit[0][2]


def test_a_part_whose_hosts_were_not_captured_is_not_flagged():
    hit = _cov_codes("## B1 SEP-BAK-01\nSummary: The RevBroadcast System Application Server has an agent.\n")
    assert hit == []                       # the Digital Radio Management Server has no captured host: nothing to cover


def test_no_coverage_block_no_check():
    card = dict(CARD, parts={k: v for k, v in CARD["parts"].items() if k != "coverage"})
    assert [f for f in A.part_checks(A.parse("## B1 SEP-BAK-01\nSummary: x.\n"), card) if f["code"] == "APPLICATION_COVERAGE"] == []


def test_database_backups_are_not_credited_to_a_part_with_no_database():
    bad = A.part_checks(A.parse("## B1 SEP-BAK-01\nSummary: Full and log database backups run on the SQL Server cluster node "
                                "(instance S01) and the Reveloc application / TGOIP server.\n"), CARD)
    wrong = [f for f in bad if f["code"] == "PART_MISATTRIBUTED"]
    assert len(wrong) == 1 and "Reveloc application / TGOIP server" in wrong[0]["message"]
    ok = A.part_checks(A.parse("## B1 SEP-BAK-01\nSummary: Full and log database backups run on the SQL Server cluster node "
                               "(instance S01).\n"), CARD)
    assert [f for f in ok if f["code"] == "PART_MISATTRIBUTED"] == []


def test_the_new_check_is_a_content_warning_not_a_blocker():
    assert "APPLICATION_COVERAGE" in A.CONTENT_CODES
    assert "APPLICATION_COVERAGE" not in A.HARD_CODES and "APPLICATION_COVERAGE" not in A.RELAXED_HARD


def test_the_size_cap_never_cuts_the_lines_the_answer_needs(tmp_path):
    wd = _reviewed(tmp_path, ROWS)
    doc = P.assemble(wd)
    ids = {p["name"]: p["id"] for p in doc["parts"]}
    doc["applications"][0]["purpose"] = "x" * 300
    doc["chains"] = [{"id": "c", "application": "reveloc", "function": "f" * 80, "reviewed": True,
                      "steps": [{"from": ids["Reveloc application / TGOIP server"], "to": ids["OT Reveloc Server"],
                                 "flows": ["R%d" % i]} for i in range(60)]}]
    doc["applications"].append({"id": "late", "name": "Late application", "parts": [], "reviewed": False})
    view = P.application_view(wd, doc, {"B1": [ids["Reveloc application / TGOIP server"]]})
    text = "\n".join(view["lines"])
    assert len(text) <= P.APPLICATION_BLOCK_CHARS + 200
    assert "more steps are listed in csa-work/parts.json" in text
    assert "Applications behind each requirement: B1: reveloc" in text
    assert "not reviewed, so not described here: Late application" in text
