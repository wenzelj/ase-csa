"""A Drawbridge Impact block must not say a part keeps a path isolation cuts, and must cover the functions the card lists."""
from csa_docx import answer_sheet as A
from csa_docx import drawbridge_fit as D

CARD = {
    "questions": [{"id": "B4", "kind": "narrative", "text": "Drawbridge Impact: what stops"}],
    "parts": {
        "parts": {"rbs": "RevBroadcast application server", "rev": "OT Reveloc Server"},
        "names": {"rbs": ["RevBroadcast application server"], "rev": ["OT Reveloc Server"]},
        "sides": {"rbs": "ot", "rev": "ot"},
        "isolation": {
            "rbs": {"effect": "loses monitoring with SCOM, and may lose (zone not recorded): message/API with Peers not identified",
                    "loss": ["identified", "message", "monitoring", "peers", "scom"], "safe": ["database", "cluster", "server"]},
            "rev": {"effect": "keeps working inside OT", "loss": [], "safe": ["database"]},
        }},
    "drawbridge_functions": {"B4": [
        {"domain": "Storage & Data Transfer", "function": "Voice and SDS recording", "dependency": "storage, USB Anywhere", "matched": "storage"},
        {"domain": "Storage & Data Transfer", "function": "Downstream FCC data to IAMPS", "dependency": "SQL access from IAMPS", "matched": "sql"}]},
}


def run(text, questions=()):
    s = A.parse("## B4 Drawbridge\nFacts:\n- A fact. (E-1) {observed}\nText:\n" + text + "\n" + "".join(f"QUESTION: {q}\n" for q in questions))
    return [(f["code"], f["level"]) for f in D.path_kept_checks(s, CARD, A._f) + D.function_checks(s, CARD, A._f)]


def test_a_part_that_keeps_a_path_to_a_far_end_outside_ot_is_an_error():
    out = run("With the storage and transfer path cut, the OT Reveloc Server and the RevBroadcast application server keep their SQL and "
              "Azure message bus paths to the availability groups, so the local application data stays available inside OT.")
    assert ("ISOLATION_PATH_KEPT", "ERROR") in out


def test_saying_the_path_is_lost_or_that_a_path_stays_inside_ot_is_fine():
    assert ("ISOLATION_PATH_KEPT", "ERROR") not in run("With the path cut, the RevBroadcast application server loses its Azure message bus connection.")
    assert ("ISOLATION_PATH_KEPT", "ERROR") not in run("The RevBroadcast application server SQL connections remain inside OT, while its message bus path is lost.")
    assert ("ISOLATION_PATH_KEPT", "ERROR") not in run("The RevBroadcast application server keeps its local database running.")


def test_the_functions_the_card_lists_must_be_covered_by_name_or_a_question():
    out = run("The downstream FCC data to IAMPS stops because the IAMPS application servers can no longer read the SQL database.")
    assert ("DRAWBRIDGE_FUNCTION_MISSING", "WARN") in out
    assert ("DRAWBRIDGE_FUNCTION_MISSING", "WARN") not in run(
        "FCC data to IAMPS stops.", ["Does voice and SDS recording continue when the storage path is cut?"])



def test_the_card_json_carries_the_function_list_it_prints():
    from csa_docx import section_card as S
    m = S._FN_LINE.match("  Function with an explicit Storage & Data Transfer dependency to assess: Operator view: recorded dependency: "
                         "direct SQL access from RevViewer, and the IT F5/proxy (matched: sql)")
    assert m and m["function"] == "Operator view" and m["domain"] == "Storage & Data Transfer" and m["matched"] == "sql"


FN_CARD = dict(CARD, drawbridge_functions={"B4": [
    {"domain": "Storage & Data Transfer", "function": "Operator view", "dependency": "direct SQL access", "matched": "sql",
     "parts": ["Management Jump box"], "cut": [], "may_cut": [], "kept": ["database between the Management Jump box and the SQL Server cluster node"]},
    {"domain": "Storage & Data Transfer", "function": "Voice and SDS recording", "dependency": "storage", "matched": "storage",
     "parts": ["TETRA log server"], "cut": [], "may_cut": ["database between the TETRA log server and the Peers not identified"], "kept": []},
    {"domain": "Storage & Data Transfer", "function": "Backup collection", "dependency": "storage", "matched": "storage",
     "parts": ["Dell"], "cut": ["backup agent between the Dell PowerProtect and the OT Reveloc Server"], "may_cut": [], "kept": []},
    {"domain": "Storage & Data Transfer", "function": "Radio programming", "dependency": "storage", "matched": "storage",
     "parts": [], "cut": [], "may_cut": [], "kept": []}]})


def effects(text):
    s = A.parse("## B4 Drawbridge\nFacts:\n- A fact. (E-1) {observed}\nText:\n" + text + "\n")
    return [f["code"] for f in D.effect_checks(s, FN_CARD, A._f)]


def test_a_stop_the_flows_do_not_establish_is_an_error():
    assert effects("With the storage path cut, the operator view stops because the Management Jump box can no longer reach the database.") \
        == ["FUNCTION_STOP_NOT_ESTABLISHED"]
    assert effects("The voice and SDS recording stops when the storage path is cut.") == ["FUNCTION_STOP_NOT_ESTABLISHED"]


def test_a_stop_with_a_cut_path_a_hedge_or_no_flow_verdict_passes():
    assert effects("The backup collection stops because the backup agent path is cut.") == []              # a cut path is established
    assert effects("The voice and SDS recording may stop if the peers are outside OT.") == []                # hedged: the zone is not recorded
    assert effects("The operator view keeps working because the database path stays inside OT.") == []
    assert effects("Radio programming stops when the storage path is cut.") == []                           # the flows carry nothing for it: no verdict
    assert effects("Operations lose the FCC reporting that depends on that data.") == []                    # 'operations' is not 'operator'
