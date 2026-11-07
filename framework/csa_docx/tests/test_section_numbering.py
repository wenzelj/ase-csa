"""Placement keys edits by the visible number of the Heading 1 (S223), not the ordinal minus 1."""
from csa_docx import build_plan


def h1(ordinal, text):
    return {"kind": "heading", "level": 1, "section_path": str(ordinal), "text": text, "id": f"@H{ordinal}"}


V15 = [h1(1, "Document Control"), h1(2, "Executive Overview"), h1(3, "Requirement Domain Assessments"),
       h1(4, "Governance Note and Next Steps"), h1(5, "Migration Discovery"),
       h1(6, "OT 3.5 Destination Boundary Reference Table"), h1(7, "Glossary and Acronyms"),
       h1(8, "Discovery Required")]


def test_v15_domains_are_section_3():
    assert build_plan._framework_section("3.4", V15) == "3"
    assert build_plan._framework_section("2.1", V15) == "2"
    assert build_plan._framework_section("8.1", V15) == "8"


def test_old_layout_with_an_extra_heading_still_resolves_by_name():
    old = [h1(1, "Document Control"), h1(2, "Executive Overview"), h1(3, "System Assessment Overview"),
           h1(4, "Requirement Domain Assessments")]
    assert build_plan._framework_section("4.2", old) == "3"
    assert build_plan._framework_section("3.1", old) == "2"      # unknown heading: ordinal minus 1


def test_heading_match_ignores_case():
    assert build_plan._framework_section("3.2", [h1(3, "REQUIREMENT DOMAIN ASSESSMENTS")]) == "3"


def test_without_entries_the_old_rule_applies():
    assert build_plan._framework_section("4.5") == "3"
