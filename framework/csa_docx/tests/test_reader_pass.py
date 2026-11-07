"""The reader pass reads the whole sheet as the customer and reports; it never edits the sheet."""
import sys
from pathlib import Path

from csa_docx import prompts, reader_pass as R


def test_the_prompt_carries_the_rules_and_the_whole_sheet(tmp_path):
    text = R.build_prompt(tmp_path, "## B1 SEP-X-01\nSummary: S.\n")
    assert "## Contradictions between blocks" in text and "ANSWER SHEET" in text and "Summary: S." in text
    assert "<!--" not in text                                   # the file's own comment is not sent


def test_review_is_an_editable_project_prompt(tmp_path):
    assert "review" in prompts.REGISTRY
    mine = tmp_path / "prompts" / "answer"
    mine.mkdir(parents=True)
    (mine / "review.md").write_text("Only list jargon.\n", encoding="utf-8")
    assert "Only list jargon." in R.build_prompt(tmp_path, "x") and "Contradictions" not in R.build_prompt(tmp_path, "x")


def test_clean_drops_chat_before_the_first_heading():
    assert R.clean("Sure, here it is.\n## A\n- x") == "## A\n- x"


def test_a_second_review_replaces_the_first_in_the_result_file(tmp_path):
    res = tmp_path / "STOR.RESULT.md"
    res.write_text("# csa answer 3.7: APPLIED\n", encoding="utf-8")
    R.append_to_result(res, "## One\n- first")
    R.append_to_result(res, "## Two\n- second")
    body = res.read_text(encoding="utf-8")
    assert body.count(R.HEADING) == 1 and "second" in body and "first" not in body and body.startswith("# csa answer")


def test_review_runs_the_cli_saves_the_report_and_leaves_the_sheet_alone(tmp_path):
    sheet = tmp_path / "STOR.answer.md"
    sheet.write_text("## B1 SEP-X-01\nSummary: S.\n", encoding="utf-8")
    (tmp_path / "STOR.RESULT.md").write_text("# csa answer 3.7: APPLIED\n", encoding="utf-8")
    template = f"{sys.executable} -c \"print('chat'); print('## Contradictions between blocks'); print('- None found.')\" {{prompt}}"
    out = R.review(tmp_path, sheet, "STOR", tmp_path, template)
    assert out["status"] == "OK" and (tmp_path / "STOR.review.md").read_text().startswith("## Contradictions")
    assert sheet.read_text(encoding="utf-8") == "## B1 SEP-X-01\nSummary: S.\n"
    assert "Reader review (advisory)" in (tmp_path / "STOR.RESULT.md").read_text(encoding="utf-8")
