"""The author report sets the brief's questions against the records' tagged facts."""
from csa_docx import author_report as ar

FILE = """# Changes
## Section 3 Change Record

**Section:** 3 - Requirement Domain Assessments
**Status:** Proposed changes.

---

## Section brief

- **Purpose:** Explain DNS.
- **Requirements:** SEP-DNS-01
- **Questions:**
  - B1 Which resolvers does each host use?
  - B2 Which zones must resolve?
  - B3 What fails when resolvers are unreachable?
  - C1 Reviewer comment (A): "Is there a fallback?"
- **Not here:** time

## Open questions

- B2 is not answered by the captures.

## Proposed changes

### S3-E1 - DNS resolvers

**Where:** `@H3-P1`

**Do:** Replace

**Facts:**
- [B1] Every host uses the two enterprise resolvers. (E-001) {basis: observed; scope: all hosts}
- The captures do not show a fallback.

**Text:**

> Every host uses the two enterprise resolvers. The captures show no fallback.

**Why:** E-001

**Note:** Resolver list.

---
"""


def test_each_question_is_answered_open_or_unanswered():
    res = ar.build(FILE)
    t = res["text"]
    assert res["counts"] == {"ANSWERED": 1, "OPEN": 1, "UNANSWERED": 2}
    assert "## B1 ANSWERED" in t and "## B2 OPEN" in t and "## B3 UNANSWERED" in t and "## C1 UNANSWERED" in t
    assert res["untagged"] == 1


def test_an_answered_question_shows_its_evidence_and_the_sentence_that_says_it():
    t = ar.build(FILE)["text"]
    assert "S3-E1:" in t and "Evidence: E-001." in t and 'Says: "Every host uses the two enterprise resolvers."' in t


def test_a_file_without_a_brief_says_so():
    res = ar.build(FILE.replace("## Section brief", "## Notes"))
    assert res["questions"] == 0 and "no section brief questions" in res["text"]
