"""Register formatting and failed repair must never silently lose the table."""
import ast
from pathlib import Path
import sys

import pytest

from csa_docx import answer_sheet as A


COLUMNS = ["Host(s) / scope", "Update collection", "Deployment", "Settings", "Maintenance window"]
CARD = {"questions": [{"id": "B1", "kind": "register", "columns": COLUMNS, "text": "Patch tooling"}]}


def _errors(text):
    result = A.validate(A.parse(text), CARD, draft=True, relaxed=True)
    return {f["code"] for f in result["findings"] if f["level"] == "ERROR"}


def test_five_column_rows_without_outer_pipes_keep_every_cell():
    text = "## B1 Patch tooling\nRows:\n" + " | ".join(COLUMNS) + "\n"
    text += "Server A | Collection A | Deployment A | Manual | Unknown\n"
    rows = A.parse(text)["B1"]["rows"]
    assert rows == [COLUMNS, ["Server A", "Collection A", "Deployment A", "Manual", "Unknown"]]
    assert not (_errors(text) & {"COLUMNS", "ROW_WIDTH", "NO_ROWS"})


@pytest.mark.parametrize("body", [
    "Text: The servers use the patching service.\n",
    "Facts:\n- The servers use the patching service. (E-1) {observed; servers}\n",
    "QUESTION: Which patching service is used?\n",
    "Rows:\n" + " | ".join(COLUMNS) + "\n",
])
def test_register_requires_data_rows_even_with_other_content(body):
    assert "NO_ROWS" in _errors("## B1 Patch tooling\n" + body)


def test_unparseable_line_among_valid_rows_blocks_instead_of_disappearing():
    text = "## B1 Patch tooling\nRows:\n| " + " | ".join(COLUMNS) + " |\n"
    text += "| Server A | Collection A | Deployment A | Manual | Unknown |\n"
    text += "Server B, Collection B, Deployment B, Manual, Unknown\n"
    assert "ROW_WIDTH" in _errors(text)


def test_short_row_is_parsed_then_rejected_for_width():
    text = "## B1 Patch tooling\nRows:\n" + " | ".join(COLUMNS) + "\nServer A | Unknown\n"
    assert "ROW_WIDTH" in _errors(text)


@pytest.mark.parametrize("body", ["Keep: unchanged\n", "Search: patch settings\n"])
def test_keep_and_search_do_not_require_replacement_rows(body):
    assert "NO_ROWS" not in _errors("## B1 Patch tooling\n" + body)


def test_empty_table_regression_reports_zero_not_negative_rows():
    old = A.parse("## B1 table\nRows:\n| Name | Value |\n| A | x |\n| B | y |\n")
    new = A.parse("## B1 table\nText: Missing table.\n")
    finding = next(f for f in A.regression(old, new) if f["code"] == "ROWS_DROPPED")
    assert "table has 0 row(s)" in finding["message"]


@pytest.mark.parametrize("code", ["NO_ROWS", "ROWS_DROPPED", "ZONE_CONTRADICTED"])
def test_exhausted_cli_repairs_fail_before_apply(tmp_path, code):
    # Execute the actual CLI's exhausted-repair branch with no model or DOCX.
    # This covers blocking errors outside the former small fatal-code allowlist.
    source = Path(__file__).resolve().parents[3] / "bin/csa"
    tree = ast.parse(source.read_text())
    branch = next(n.orelse for n in ast.walk(tree)
                  if isinstance(n, ast.If) and ast.unparse(n.test) == "fixes < fix_max")
    statements = ast.Module(body=[ast.For(target=ast.Name(id="attempt", ctx=ast.Store()),
                            iter=ast.List(elts=[ast.Constant(0)], ctx=ast.Load()),
                            body=branch, orelse=[])], type_ignores=[])
    calls = []

    def die(message):
        calls.append(("exit", message))
        raise SystemExit(1)

    def unexpected(*args, **kwargs):
        pytest.fail("failed validation reached a post-validation step")

    env = dict(res2={"status": "ERROR", "findings": [
                   {"level": "ERROR", "code": code, "question": "B1", "message": "invalid"}]},
               p={}, number="4.4", searched=False, fixes=2, timing={}, draft=True, bad={"B1"},
               repair_cli_override=None, a=type("Args", (), {"cli": "evo"})(),
               settings=lambda: {}, cards=tmp_path, key="PATCH", sheet=tmp_path / "PATCH.answer.md",
               card_json=tmp_path / "PATCH.json", work=tmp_path, sys=sys, die=die,
               _record_author_run=lambda *a, **k: None,
               draft_run=lambda status, *a, **k: calls.append(("state", status)),
               _write_answer_result=lambda path, number, outcome, *a: calls.append(("report", outcome)),
               _remember_tables=unexpected, _reader_pass=unexpected, _rating_pass=unexpected)
    with pytest.raises(SystemExit) as exc:
        exec(compile(ast.fix_missing_locations(statements), str(source), "exec"), env)
    assert exc.value.code != 0
    assert ("state", "FAILED") in calls
    assert ("report", "NOT APPLIED") in calls
    assert code in calls[-1][1]
