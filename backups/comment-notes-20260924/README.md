# Plain-language Word comments (24 Sep 2026)

Problem: every applied edit's Word comment was `<edit ID>: <entire Why field>` plus `Initials: WJ`, and the last record in a file also carried the file's Open questions. IAMPS: 43 comments, median 81 words, longest 492, 37 over 60 words, full of file names and host lists.

Change:
- New `**Note:**` field in change records (models.py `note`, change_parser.py). The authoring agent writes it to the new "Comment notes" rules in `skills/csa-writing-style/SKILL.md`.
- New `framework/csa_docx/comment_text.py` builds every comment: `<Note> (Ref S9-E3; evidence E-082)`. Fallback without a Note: first sentence of Why if short and plain, else the record title. Preview CLI: `python3 -m csa_docx.comment_text <change file>`.
- ooxml.py and engines/docxengine_adapter.py (3 places) now call it; the initials line is gone.
- change_parser.py: a field that ends a record no longer keeps the closing `---` (770 of 1,034 existing Why values had it); "no open questions" lines are no longer treated as questions.
- Docs: csa-change-authoring.md (Note in the template and Review Method step 5), current-state-assessment-document.md (Word Comments format), csa-change-review.md (step 9 readability check), framework/csa_docx/README.md.

Checked: all 98 existing change files (1,034 records) parse the same except the `---` removal and filtered non-questions. Existing IAMPS records without a Note: comment length median 75 -> 14 words, max 794 -> 45. New tests pass (7/7). Existing tests in test_change_parser.py need DocxEngine (Python 3.11+) and were not run here; run `python3 -m pytest csa_docx/tests` on the Mac.

Rollback: copy the files in this folder back, delete comment_text.py and tests/test_comment_text.py.
