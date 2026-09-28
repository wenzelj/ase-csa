"""Section brief gates: brief present, facts tagged with brief items, items answered, section fit."""
from csa_docx.change_parser import parse_change_records
from csa_docx.check_change import brief_findings, section_fit_findings

BRIEF = """## Section brief

- **Purpose:** how data moves between the historian and the reporting server, and where it is held.
- **Requirements:** SEP-STOR-01, SEP-STOR-02, SEP-STOR-03
- **Questions:**
  - B1 What data moves, and which side starts the transfer?
  - B2 Where is the data held on each side?

---
"""
REC = """### S4-E9 - Example

**Where:** `@H5.9.2-P1` -- currently: "x"

**Do:** Replace

**Facts:**
{facts}

**Text:**

> {text}

**Why:**
E-001.

**Note:**
Rewritten around data transfer.
"""
GOOD_FACTS = "- [B1] The reporting server pulls hourly totals from the historian (E-001)\n- [B2] Totals are held only on the historian (E-002)\n- Table detail: ports (E-001)"
STORY = "The reporting server pulls hourly totals from the historian, and the totals are held only on the historian."


def _codes(fn, text):
    return [f["code"] for f in fn(text, parse_change_records(text))]


def test_good_brief_passes():
    t = BRIEF + REC.format(facts=GOOD_FACTS, text=STORY)
    assert _codes(brief_findings, t) == []


def test_missing_brief_warns():
    assert _codes(brief_findings, REC.format(facts=GOOD_FACTS, text=STORY)) == ["NO_BRIEF"]


def test_untagged_fact_and_unanswered_item():
    t = BRIEF + REC.format(facts="- The reporting server pulls hourly totals (E-001)", text=STORY)
    codes = _codes(brief_findings, t)
    assert "UNTAGGED_FACT" in codes and codes.count("BRIEF_ITEM_UNANSWERED") == 2


def test_section_fit_flags_network_story_in_storage_section():
    net = ("The historian sits on its own subnet in a separate zone behind the conduit; segmentation and routing "
           "keep the vlan apart, and the inter-zone route to the reporting subnet crosses the zone boundary.")
    t = BRIEF + REC.format(facts=GOOD_FACTS, text=net)
    assert "SECTION_FIT" in _codes(section_fit_findings, t)
    assert _codes(section_fit_findings, BRIEF + REC.format(facts=GOOD_FACTS, text=STORY)) == []
