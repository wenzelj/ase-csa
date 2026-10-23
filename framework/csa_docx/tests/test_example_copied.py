"""The worked examples appended to every card are format only: a line copied from one into a real answer is an
error (EXAMPLE_COPIED), and the examples cite E-0nnn IDs that the evidence matrix never issues."""
import re

from csa_docx import answer_sheet as A

CARD = {"key": "GEN", "questions": [{"id": "B2", "kind": "requirement", "text": "Is there an asset inventory?"}],
        "evidence": {"B2": {"rows": [{"id": "E-203", "status": "VERIFIED", "claim": "x"}]}}}
MATRIX = {"E-203": {"evidence_id": "E-203", "claim": "MKYPRDOPS110 has an attempted connection.", "status": "VERIFIED"}}


def _sheet(*facts, text=""):
    body = "## B2 SEP-GEN-01\nFacts:\n" + "\n".join(f"- {f}" for f in facts)
    if text:
        body += f"\nText: {text}"
    return A.parse(body + "\nRating: Not Met\nRating reason: no maintained inventory exists.\n")


def _codes(sheet):
    return [f["code"] for f in A.validate(sheet, CARD, MATRIX, draft=True)["findings"] if f["level"] == "ERROR"]


def test_a_fact_copied_from_the_example_is_a_hard_error():
    copied = _sheet("KVM is excluded from this CSA and will be assessed separately. (E-203) {documented; KVM}")
    assert "EXAMPLE_COPIED" not in _codes(copied)       # the old example line is gone from the examples
    copied = _sheet("The building management system is excluded from this CSA and will be assessed separately. "
                    "(E-203) {documented; building management system}")
    assert "EXAMPLE_COPIED" in _codes(copied)
    assert "EXAMPLE_COPIED" in A.HARD_CODES


def test_a_copied_sentence_inside_text_is_caught():
    s = _sheet("No inventory tool was found on MKYPRDOPS110. (E-203) {observed; MKYPRDOPS110}",
               text="No dedicated OT asset inventory or CMDB tool was identified. The application keeps its own list.")
    assert "EXAMPLE_COPIED" in _codes(s)


def test_a_real_answer_is_not_flagged():
    s = _sheet("No inventory tool was found on MKYPRDOPS110. (E-203) {observed; MKYPRDOPS110}",
               text="No inventory tool was found on the operations host.")
    assert "EXAMPLE_COPIED" not in _codes(s)


def test_the_examples_cite_ids_the_matrix_never_issues():
    for f in A.EXAMPLES.glob("*.md"):
        ids = re.findall(r"(?<![\w-])E-\d+\b", f.read_text(encoding="utf-8"))
        assert ids and all(re.fullmatch(r"E-0\d{3}", i) for i in ids), f.name
        assert "KVM" not in f.read_text(encoding="utf-8")
