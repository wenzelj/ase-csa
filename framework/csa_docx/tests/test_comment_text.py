"""Word comment text: plain note first, change ID and evidence IDs in brackets.

Runs without DocxEngine (only change_parser and comment_text are imported).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx.change_parser import parse_change_records
from csa_docx.comment_text import build_comment_text, comment_warnings

RECORD = """### S9-E3 - Reconcile the Findings "no local NTP" claim

**Where:** `@H10.4.2-P4`

**Do:** Replace this paragraph.

**Text:**

> The Windows Time service runs on both servers.

**Why:**
E-082 (VERIFIED): 32_services_inventory.txt shows W32Time State=Running on ROKPRDAMP101/102 and 20_listening_ports.txt shows UDP 0.0.0.0:123.

**Note:**
Corrected: the servers do run the Windows Time service, but they still take their time from the IT domain.

---
"""

FILE_TAIL = """
## Open questions

- There are no open questions for Section 9.
- Should the stray block be raised with the document agent before any further edits to Sections 9 or 10, given it was recorded as applied but is still present?
"""


def _one(md: str):
    records = parse_change_records(md)
    assert len(records) == 1
    return records[0]


def test_note_is_parsed_and_not_swallowed_by_why():
    r = _one(RECORD)
    assert r.note.startswith("Corrected: the servers")
    assert "Corrected" not in r.why


def test_comment_is_note_plus_reference():
    text = build_comment_text(_one(RECORD))
    assert text == ("Corrected: the servers do run the Windows Time service, but they still take their time "
                    "from the IT domain. (Ref S9-E3; evidence E-082)")
    assert "Initials" not in text and ".txt" not in text


def test_no_note_falls_back_to_title_when_why_is_detailed():
    r = _one(RECORD.replace("**Note:**\nCorrected: the servers do run the Windows Time service, but they still take their time from the IT domain.\n", ""))
    text = build_comment_text(r)
    assert text.startswith('Reconcile the Findings "no local NTP" claim.')
    assert text.endswith("(Ref S9-E3; evidence E-082)")
    assert any("no **Note:**" in w for w in comment_warnings(r))


def test_file_level_open_questions_stay_out_of_the_last_edit_comment():
    r = _one(RECORD + FILE_TAIL)
    text = build_comment_text(r)
    assert "Question" not in text and "no open questions" not in text


def test_short_question_inside_the_record_is_kept():
    r = _one(RECORD.replace("---\n", "Is ROTPRDSRV122 the PDC emulator?\n\n---\n"))
    assert "Question: Is ROTPRDSRV122 the PDC emulator?" in build_comment_text(r)


def test_editorial_why_becomes_plain_note():
    md = RECORD.replace(RECORD[RECORD.index("**Why:**"):RECORD.index("---")],
                        "**Why:**\nEditorial -- Five bullets joined into one sentence.\n\n")
    text = build_comment_text(_one(md))
    assert text == "Wording tightened, no facts changed: five bullets joined into one sentence. (Ref S9-E3)"


def test_long_note_is_warned():
    long_note = " ".join(["word"] * 45)
    r = _one(RECORD.replace("Corrected: the servers do run the Windows Time service, but they still take their time from the IT domain.", long_note))
    assert any("45 words" in w for w in comment_warnings(r))


if __name__ == "__main__":  # no pytest needed
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("pass", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, e)
    sys.exit(1 if failed else 0)
