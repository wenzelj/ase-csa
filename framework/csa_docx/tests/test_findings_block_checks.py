from csa_docx import answer_sheet as A

MATRIX = {"E-3600": {"claim": "Who may open the shares on ROKPRDOPS110: CAcom: Everyone Read; CNMS-NG R7 Archive: INTERNAL\\A Full; Music: Everyone Read"},
          "E-3603": {"claim": "Who may open the shares on IPTPRDAPP137: Temp: Everyone Full"}}
CARD = {"questions": [{"id": "B1", "kind": "findings"}]}


def _codes(*bullets):
    sheet = {"B1": {"bullets": list(bullets)}}
    return [(f["code"], f["message"]) for f in A.findings_block_checks(sheet, CARD, MATRIX)]


def test_read_share_called_full_is_an_error():
    got = _codes("Everyone has full read, change and delete rights on the Temp and Music shares. (E-3600, E-3603)")
    assert [c for c, _ in got] == ["SHARE_ACCESS_MISMATCH"] and "Music" in got[0][1]


def test_matching_levels_pass():
    assert _codes("Everyone has full rights on the Temp share, and read-only rights on the CAcom and Music shares. (E-3600, E-3603)") == []


def test_unnamed_peer_and_name_not_recorded_are_errors():
    assert [c for c, _ in _codes("Connections to an unnamed internal peer. (E-1)")] == ["UNNAMED_PEER"]
    assert [c for c, _ in _codes("Traffic to OTPROXY, whose hostname, zone and role are not recorded. (E-1)")] == ["NAME_NOT_RECORDED"]
    assert _codes("Connections to the peer at 10.89.163.66. (E-1)") == []


def test_zone_or_role_not_recorded_is_an_error():
    assert [c for c, _ in _codes("ROTPRDCLU103 opens a file share connection to the peer at 10.89.163.73. The zone of that far end is not recorded. (E-1)")] == ["NAME_NOT_RECORDED"]
    assert [c for c, _ in _codes("Web connections to OTPROXY, whose specific role is not established. (E-1)")] == ["NAME_NOT_RECORDED"]


MATRIX2 = {"E-1": {"claim": "Who may open the shares on ROTPRDLOG102: Log102Share: INTERNAL\\_sTetraLog Full, Everyone Read; Newfolder: INTERNAL\\A Full, Everyone Read"},
           "E-2": {"claim": "Who may open the shares on MOTPRDLOG103: Test: Everyone Full; MOTPRDLOG103: Everyone Full"}}


def _codes2(*bullets):
    return [f["code"] for f in A.findings_block_checks({"B1": {"bullets": list(bullets)}}, CARD, MATRIX2)]


def test_everyone_with_full_access_after_the_share_name_is_checked():
    assert _codes2("The server offers the Newfolder share to INTERNAL\\A and Everyone with full access. (E-1)") == ["SHARE_ACCESS_MISMATCH"]


def test_correct_wording_after_the_share_name_passes():
    assert _codes2("The server offers the Newfolder share to INTERNAL\\A with full access and to Everyone with read access. (E-1)") == []
    assert _codes2("The server offers the MOTPRDLOG103 and Test shares to Everyone with full access. (E-2)") == []
