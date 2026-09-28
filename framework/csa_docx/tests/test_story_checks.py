"""Readability gates: IP addresses in prose Text are an ERROR; a missing Facts list is a WARN."""
from csa_docx.change_parser import parse_change_records
from csa_docx.check_change import hygiene_findings

REC = """### S4-E9 - Example

**Where:** `@H5.9.2-P1` -- currently: "x"

**Do:** Replace

{facts}**Text:**

> {text}

**Why:**
E-001.

**Note:**
Rewritten for readability with the same facts.
"""


def _codes(text, facts="**Facts:**\n- A fact (E-001)\n\n"):
    recs = parse_change_records(REC.format(text=text, facts=facts))
    assert recs[0].action.startswith("Replace")
    return {f["code"]: f["level"] for f in hygiene_findings(recs)}


def test_ip_in_prose_is_error():
    assert _codes("The historian at 10.20.4.11 collects the data.")["IP_IN_TEXT"] == "ERROR"


def test_ip_in_table_row_is_allowed():
    assert "IP_IN_TEXT" not in _codes("HIST01 | 10.20.4.11 | Historian")


def test_story_text_passes():
    assert _codes("All three plant networks send their data to the historian pair.") == {}


def test_missing_facts_warns_and_facts_parse():
    assert _codes("The historian pair collects the data.", facts="")["NO_FACTS"] == "WARN"
    recs = parse_change_records(REC.format(text="x", facts="**Facts:**\n- A fact (E-001)\n\n"))
    assert "A fact" in recs[0].facts and recs[0].text == "x"
