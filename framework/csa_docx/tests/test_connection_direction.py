"""A connection is opened by one side: the Facts, and the prose built from them, must say which."""
from csa_docx import answer_sheet as A
from csa_docx import connection_direction as D

CARD = {
    "parts": {
        "names": {"log": ["TETRA log server", "OT TETRA Log Server"], "cluster": ["SQL Server cluster nodes"],
                  "pdm": ["MOTPRDPDM101", "Mackay Dell PowerProtect Data Manager"], "rev": ["Reveloc application / TGOIP server"]},
        "sides": {"log": "ot", "cluster": "ot", "pdm": "unknown", "rev": "ot"},
        "hosts": {"ROTPRDLOG102": "log", "MOTPRDCLU103": "cluster", "ROTPRDCLU104": "cluster", "MOTPRDREV101": "rev"},
    },
    "evidence": {"B3": {"rows": [
        {"id": "E-988", "claim": "10.129.11.10 opened database connections on TCP 3306 to ROTPRDLOG102 (mysqld)"},
        {"id": "E-989", "claim": "MOTPRDCLU103 and ROTPRDCLU104 opened file share connections on TCP 445 to 10.89.163.66 (System)"},
        {"id": "E-1558", "claim": "MOTPRDPDM101 opened backup agent connections on TCP 7000 to MOTPRDREV101 (agentService)"},
    ]}},
    "questions": [{"id": "B3", "kind": "requirement"}],
}


def run(sheet_text):
    out = D.direction_checks(A.parse(sheet_text), CARD, {}, A._f)
    return [(f["code"], f["question"]) for f in out], out


def block(facts, **prose):
    body = "\n".join(f"- {f}" for f in facts)
    return "## B3 SEP-STOR-03\nFacts:\n" + body + "\n" + "\n".join(f"{k}: {v}" for k, v in prose.items()) + "\n"


def test_edges_read_who_opened_to_whom():
    pl = D.Places(CARD)
    e = D.edges("10.129.11.10 opened database connections on TCP 3306 to ROTPRDLOG102 (mysqld)", pl)[0]
    assert e["kind"] == "SQL Server" or e["kind"] == "MySQL"
    assert "10.129.11.10" in e["opener"] and "ROTPRDLOG102" in e["target"] and e["dir"] == "inbound"
    f = D.edges("MOTPRDCLU103 opened file share connections on TCP 445 to 10.89.163.66 (System)", pl)[0]
    assert f["dir"] == "outbound" and f["kind"] == "file share"


def test_a_fact_with_the_ends_swapped_is_reversed():
    codes, out = run(block(["The OT TETRA Log Server opens a MySQL connection to an unidentified internal peer at 10.129.11.10. (E-988) {observed; ROTPRDLOG102}"]))
    assert codes == [("DIRECTION_REVERSED", "B3")] and "E-988" in out[0]["message"]


def test_a_fact_with_the_right_direction_passes():
    codes, _ = run(block(["An unidentified internal peer at 10.129.11.10 opens a MySQL connection into the TETRA log server. (E-988) {observed; ROTPRDLOG102}"]))
    assert codes == []


def test_prose_saying_into_ot_for_connections_ot_opens_is_reversed():
    facts = ["The SQL Server cluster nodes open file-share connections to 10.89.163.66. (E-989) {observed; MOTPRDCLU103}"]
    codes, _ = run(block(facts, Summary="File-share connections are opened into OT from far-end peers 10.89.163.66."))
    assert ("DIRECTION_REVERSED", "B3") in codes
    codes, _ = run(block(facts, Summary="File-share connections are opened outward from OT to the peer 10.89.163.66."))
    assert codes == []


def test_a_sentence_with_both_directions_is_judged_clause_by_clause():
    facts = ["The SQL Server cluster nodes open file-share connections to 10.89.163.66. (E-989) {observed; MOTPRDCLU103}"]
    codes, _ = run(block(facts, Story="Far ends open backup connections into OT, even though file-share connections go into OT."))
    assert ("DIRECTION_REVERSED", "B3") in codes          # the file-share clause is wrong; the backup clause has no row here


def test_backup_agent_into_ot_is_right_when_the_rows_say_so():
    facts = ["MOTPRDPDM101 opens a backup-agent connection into the Reveloc application / TGOIP server. (E-1558) {observed; MOTPRDREV101}"]
    codes, _ = run(block(facts, Summary="The Mackay Dell PowerProtect Data Manager opens backup-agent connections into OT."))
    assert codes == []


def test_prose_naming_what_no_fact_states_is_flagged():
    facts = ["The SQL Server cluster nodes open file-share connections to 10.89.163.66. (E-989) {observed; MOTPRDCLU103}"]
    codes, out = run(block(facts, Summary="MOTPRDPDM101 opens backup-agent connections and 10.45.229.194 is another peer."))
    assert ("PROSE_NOT_IN_FACTS", "B3") in codes
    msg = next(f["message"] for f in out if f["code"] == "PROSE_NOT_IN_FACTS")
    assert "MOTPRDPDM101" in msg and "backup agent connections" in msg and "10.45.229.194" in msg
    codes, _ = run(block(facts, Summary="The cluster nodes open file-share connections to 10.89.163.66."))
    assert codes == []



def test_a_card_without_parts_is_left_alone():
    assert D.direction_checks(A.parse(block(["x. (E-988) {observed}"])), {"evidence": {}}, {}, A._f) == []
