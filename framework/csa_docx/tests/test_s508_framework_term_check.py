"""S508: framework terms in CSA text are an error (FRAMEWORK_TERM); QUESTION and Unknown lines are not counted."""
from csa_docx import answer_sheet as A

CARD = {"questions": [{"id": "B1", "kind": "requirement", "text": "y"}]}


def run(**kw):
    block = {"summary": "", "text": "", "facts": [], "bullets": [], "rows": []}
    block.update(kw)
    return [f for f in A.framework_term_checks({"B1": block}, CARD) if f["code"] == "FRAMEWORK_TERM"]


def test_text_not_captured():
    got = run(text="The setting is not captured for this host.")
    assert len(got) == 1 and got[0]["level"] == "ERROR" and "not captured" in got[0]["message"]
    assert "Say instead" in got[0]["message"]


def test_fact_discovery_data():
    got = run(facts=[{"text": "The discovery data shows one time source.", "ids": [], "tag": ""}])
    assert len(got) == 1 and got[0]["level"] == "ERROR"


def test_table_cell():
    assert run(rows=[["Aspect", "Finding"], ["Source", "Host register lists it"]])


def test_question_line_ignored():
    assert not run(text="QUESTION: Which captured hosts have no fallback peer?")


def test_unknown_line_ignored():
    assert not run(text="Unknown: whether captured hosts use a fallback peer.")


def test_clean_text():
    assert not run(text="The hosts take their time from one enterprise server.")


def test_missing_term_lint_does_not_crash(monkeypatch):
    monkeypatch.setattr(A, "_load_framework_terms", lambda: [])
    assert not run(text="The captured hosts follow one source.")


def test_missing_file_returns_no_terms(monkeypatch):
    import importlib.util
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: None)
    assert A._load_framework_terms() == []
