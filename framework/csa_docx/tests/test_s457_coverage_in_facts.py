"""S457: part coverage lives in the Facts - the card line names display names only, and PART_NOT_NAMED
checks the block's Facts, never its Story."""
from csa_docx import answer_sheet as A
from csa_docx import parts as P


def _view(part):
    return {"owed": {"B1": ["p1"]}, "parts": {"p1": part}}


def _card(names, strict=True):
    return {"questions": [{"id": "B1", "kind": "requirement"}], "frame": {"strict": strict},
            "parts": {"owed": {"B1": ["p1"]}, "parts": {"p1": "OT TETRA Log Server, DAAM Node Controller"},
                      "names": {"p1": names}, "hosts": {}, "features": {}, "sides": {"p1": "ot"}, "isolation": {}}}


def test_the_card_line_is_about_the_facts_and_lists_display_names():
    lines = P.owed_lines(_view({"display": "", "name": "OT TETRA Log Server, DAAM Node Controller"}), "B1")
    assert len(lines) == 1
    assert "Parts to name in the Text" not in lines[0]
    assert lines[0].startswith(
        "  Parts these findings are about (name them in the Facts; in the Story name only the parts that decide the rating, by their display name): ")
    assert lines[0].endswith(": OT TETRA Log Server")
    assert "DAAM Node Controller" not in lines[0]
    assert "A, B" not in lines[0]


def test_a_two_role_part_names_only_its_first_role():
    lines = P.owed_lines(_view({"display": "", "name": "AppServer Always On Availability Group, DAAM Node Controller"}), "B1")
    assert lines[0].endswith(": AppServer Always On Availability Group")
    assert "DAAM Node Controller" not in lines[0]


def test_no_owed_parts_gives_no_line():
    assert P.owed_lines({"owed": {"B1": []}, "parts": {}}, "B1") == []


def test_facts_naming_every_part_pass_even_when_the_story_names_only_two():
    card = _card({"TETRA Log Server": None, "DAAM Node Controller": None})
    sheet = {"B1": {"text": "The TETRA log server keeps the recordings.",
                    "facts": [{"text": "The TETRA Log Server writes the recordings.", "ids": ["E-1"]},
                              {"text": "The DAAM Node Controller holds the node data.", "ids": ["E-2"]}]}}
    codes = [f["code"] for f in A.part_checks(sheet, card)]
    assert "PART_NOT_NAMED" not in codes


def test_facts_missing_an_owed_part_fails_whatsoever_the_story_says():
    card = _card({"TETRA log server": None})
    sheet = {"B1": {"text": "The TETRA log server keeps the recordings.",
                    "facts": [{"text": "The recording volume is 2 TB.", "ids": ["E-1"]}]}}
    out = A.part_checks(sheet, card)
    assert any(f["code"] == "PART_NOT_NAMED" and f["level"] == "ERROR" for f in out)
    assert not any("every other part" in f["message"] for f in out if f["code"] == "PART_NOT_NAMED")


def test_no_facts_at_all_fails():
    card = _card({"TETRA log server": None}, strict=False)
    sheet = {"B1": {"text": "The TETRA log server keeps the recordings.", "facts": []}}
    out = A.part_checks(sheet, card)
    assert any(f["code"] == "PART_NOT_NAMED" and f["level"] == "WARN" for f in out)
