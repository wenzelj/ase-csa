"""PART_MISATTRIBUTED: a sentence that names a system part with a kind of fact no finding shows on that part's machines
is refused (the 20/10/2026 3.7 fault: shares put on the jump box that holds none). Parts are named by their roles."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import answer_sheet as A, parts as P  # noqa: E402

CARD = {
    "questions": [{"id": "B1", "kind": "requirement"}, {"id": "B3", "kind": "requirement"}],
    "frame": {"strict": True},
    "parts": {
        "names": {"gp": ["General Purpose Jump Host"], "mj": ["Management Jump box"], "log": ["TETRA Log Server"],
                  "rb": ["RevBroadcast Always On Availability Group", "RevBroadcast"],
                  "rbs": ["RevBroadcast System Application Server"]},
        "parts": {"gp": "General Purpose Jump Host", "mj": "Management Jump box", "log": "TETRA Log Server",
                  "rb": "RevBroadcast Always On Availability Group", "rbs": "RevBroadcast System Application Server"},
        "hosts": {"J1": "gp", "J2": "mj", "L1": "log", "C1": "rb", "A1": "rbs"},
        "sides": {}, "owed": {}, "isolation": {},
        "features": {"shares": ["gp", "rb"], "SMB": ["rb", "log"], "backup agent": ["rb"]},
    },
}


def codes(text):
    return [f["question"] for f in A.part_checks(A.parse(text), CARD) if f["code"] == "PART_MISATTRIBUTED"]


def test_shares_on_a_part_with_none_are_refused():
    assert codes("## B1 SEP-STOR-01\nText: The Management Jump box exposes a whole-drive share at C:\\.\n") == ["B1"]
    assert codes("## B1 SEP-STOR-01\nText: The General Purpose Jump Host exposes a whole-drive share at C:\\.\n") == []


def test_each_clause_is_judged_on_its_own():
    ok = ("## B3 SEP-STOR-03\nText: The TETRA Log Server opens SMB connections to a peer, while backup agent "
          "connections reach the RevBroadcast Always On Availability Group.\n")
    assert codes(ok) == []
    bad = "## B3 SEP-STOR-03\nText: The General Purpose Jump Host and the TETRA Log Server open SMB connections.\n"
    assert codes(bad) == ["B3"]


def test_share_transfer_is_not_a_claim_about_shares():
    assert codes("## B1 SEP-STOR-01\nText: The flow map defines no file or share transfer for the Management Jump box.\n") == []


def test_a_longer_name_is_not_also_its_short_name():
    # names the application server only, which holds no shares: the cluster's short name inside it does not count
    assert P.parts_in("the RevBroadcast System Application Server", CARD["parts"]["names"]) == {"rbs"}
    assert codes("## B1 SEP-STOR-01\nText: The RevBroadcast System Application Server exposes shares.\n") == ["B1"]


def test_not_strict_warns():
    loose = dict(CARD, frame={"strict": False})
    f = A.part_checks(A.parse("## B1 SEP-STOR-01\nText: The Management Jump box exposes shares.\n"), loose)
    assert [x["level"] for x in f if x["code"] == "PART_MISATTRIBUTED"] == ["WARN"]


def test_unidentified_peers_label():
    assert P.dependency_of("10.9.9.9", "Internal, zone not recorded", {}, set())[0] == "Unidentified internal peers"
