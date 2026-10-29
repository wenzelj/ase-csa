"""The draft lane always produces: QUESTION: lines, the small blocking set, and the carry-forward of kept facts."""
from csa_docx import answer_sheet as A

SHEET = """## B1 Requirement
Facts:
- The TETRA log server runs MySQL. (E-1277) {observed}
Question: Which zone is 10.86.160.4 in?
QUESTION: Who owns the 10.40.254.6 host?
Rating: Not Met

## B2 Discovery Information
Facts:
- A second fact. (E-5) {observed}

## F1 Analysis frame
- S1: B1
- S2: QUESTION: How long are the recordings kept?
"""


def test_question_lines_are_the_unknown_lines():
    s = A.parse(SHEET)
    assert s["B1"]["unknown"] == ["Which zone is 10.86.160.4 in?", "Who owns the 10.40.254.6 host?"]
    assert s["F1"]["unknown"] == ["How long are the recordings kept?"]
    assert A.parse("## B1 x\nUnknown: still accepted\n")["B1"]["unknown"] == ["still accepted"]


def test_blocking_set_has_no_conflicting_pair_and_fatal_is_part_of_it():
    for code in ("CAPTURE_DROPPED", "DRAWBRIDGE_CAUSAL_SCOPE", "SLOT_NOT_ANSWERED", "SUMMARY_TOO_LONG"):
        assert code not in A.RELAXED_HARD
    assert (A.FATAL_CODES - {"NO_SHEET"}) <= A.RELAXED_HARD


def test_carry_forward_puts_back_a_lost_capture_fact_once():
    card = {"keep": [{"question": "B1", "fact": "The TETRA log server stores logs locally.",
                      "evidence_ids": ["E-1007"], "capture_ids": ["E-1007"]}]}
    new, restored = A.carry_forward(SHEET, card)
    assert restored == ["E-1007"]
    assert "E-1007" in A.block_ids(A.parse(new)["B1"])
    again, restored2 = A.carry_forward(new, card)
    assert restored2 == [] and again == new


def test_carry_forward_respects_dropped_and_cited():
    card = {"keep": [{"question": "B1", "fact": "x", "evidence_ids": ["E-1277"], "capture_ids": ["E-1277"]},
                     {"question": "B1", "fact": "y", "evidence_ids": ["E-9"], "capture_ids": ["E-9"]}]}
    text = SHEET.replace("Rating: Not Met", "Dropped: E-9 no longer applies\nRating: Not Met")
    assert A.carry_forward(text, card) == (text, [])


def test_gap_shows_in_the_document_as_a_question():
    assert A.question_lines(["Which zone is 10.86.160.4 in."]) == "QUESTION: Which zone is 10.86.160.4 in?"
    assert A.question_lines(["the zone of the peer at 10.1.1.1 is not recorded, and the OT network owner could confirm it."]) \
        == "QUESTION: What is the zone of the peer at 10.1.1.1?"


def test_questions_are_coloured_red_once(tmp_path):
    import zipfile
    from csa_docx import draft_lane
    xml = ('<w:document><w:body><w:p><w:r><w:rPr><w:rFonts w:ascii="Arial"/><w:sz w:val="20"/></w:rPr>'
           '<w:t>The host runs MySQL. QUESTION: Which zone is it in? QUESTION: Who owns it? More text.</w:t></w:r></w:p></w:body></w:document>')
    f = tmp_path / "d.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", xml)
    assert draft_lane.colour_questions(f)["questions"] == 2
    out = zipfile.ZipFile(f).read("word/document.xml").decode()
    assert '<w:color w:val="FF0000"/><w:sz' in out and "QUESTION: Which zone is it in?</w:t>" in out and "QUESTION: Who owns it?</w:t>" in out
    assert "The host runs MySQL. </w:t>" in out and " More text.</w:t>" in out
    assert draft_lane.colour_questions(f)["questions"] == 0


def test_who_could_confirm_tail_is_not_part_of_the_question():
    assert A.as_question("Which zone does 10.60.252.48 sit in, which the OT network owner could confirm?") == \
        "Which zone does 10.60.252.48 sit in?"
