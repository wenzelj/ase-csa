"""S500: TABLE_VALUE_CONFLICT warns when an Aspect row disagrees with the recorded host settings."""
from csa_docx import answer_sheet as A

CARD = {
    "questions": [{"id": "A1", "kind": "observation", "text": "x", "columns": ["Aspect", "Finding"]}],
    "host_register": {"groups": [{"role": "General Purpose Jump Host", "hosts": ["MKYPRDOPS110", "ROCPRDOPS110"],
                                  "sites": []}], "uncaptured": []},
    "host_settings": {"MKYPRDOPS110": {"time.poll": "16,384 s"}, "ROCPRDOPS110": {"time.poll": "32,768 s"}},
}


def sheet(*rows):
    return {"A1": {"summary": "", "text": "", "facts": [], "bullets": [], "rows": [["Aspect", "Finding"], *rows]}}


def found(s):
    return [f for f in A.table_value_checks(s, CARD) if f["code"] == "TABLE_VALUE_CONFLICT"]


def test_role_row_with_wrong_value_warns_for_mackay_only():
    got = found(sheet(["Time poll interval", "General Purpose Jump Hosts poll every 32,768 s"]))
    assert len(got) == 1 and got[0]["level"] == "WARN"
    m = got[0]["message"]
    assert "MKYPRDOPS110" in m and "time.poll" in m and "32768 s" in m and "16,384 s" in m


def test_matching_row_does_not_warn():
    assert not found(sheet(["Time poll interval", "MKYPRDOPS110 polls every 16,384 s"]))


def test_row_naming_no_host_or_role_is_ignored():
    assert not found(sheet(["Time poll interval", "Servers poll every 99 s"]))
