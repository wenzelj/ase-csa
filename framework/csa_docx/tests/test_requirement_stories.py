from pathlib import Path
from csa_docx import answer_sheet as A, doc_spec
from csa_docx.engines.docxengine_adapter import Document


def _card(two=True):
    questions = [
        {"id": "B1", "kind": "requirement", "part": 0, "req_id": "SEP-X-01", "row": 2, "text": "x"},
    ]
    if two:
        questions.append(
            {"id": "B2", "kind": "requirement", "part": 0, "req_id": "SEP-X-02", "row": 3, "text": "y"}
        )
    return {
        "key": "X", "questions": questions, "requirement_stories": True,
        "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"],
        "evidence": {q["id"]: {"rows": [{"id": f"E-{i + 1:03d}", "status": "VERIFIED"}]}
                     for i, q in enumerate(questions)},
    }


def _node(existing=False, two=True):
    reqs = [
        {"id": "SEP-X-01", "row": 2},
        *([{"id": "SEP-X-02", "row": 3}] if two else []),
    ]
    parts = [{"kind": "requirement", "table": "@H3.1-T1", "requirements": reqs,
              "row_texts": ["SEP-X-01", "SEP-X-02"]}]
    if existing:
        parts.append({"kind": "requirement-story", "req_id": "SEP-X-01", "pid": "@H3.1.1-P1",
                      "current": "SEP-X-01 — Old story.", "text": "Old story.",
                      "facet": "Discovery Information"})
    return {"title": "Example", "hid": "@H3.1", "parts": parts,
            "facets": {"Discovery Information": {"title": "Discovery Information", "hid": "@H3.1.1"}}}


def _sheet(two=True):
    blocks = ["""## B1 SEP-X-01
Facts:
- The application uses local storage. (E-001) {observed; application}
Summary: The application uses local storage. The requirement is Partially Met because recovery testing was not established.
Story: Operational data is kept on a disk inside the server. A second copy of that data sits on the same machine.
Rating: Partially Met
Rating reason: local storage exists but recovery evidence is incomplete.
"""]
    if two:
        blocks.append("""## B2 SEP-X-02
Facts:
- Direct transfer remains in use. (E-002) {observed; application}
Summary: Direct transfer remains in use. The requirement is Not Met because no controlled transfer pattern was identified.
Story: The application transfers files directly between its parts. The transfer runs over a shared folder. Whether any file is scanned before it reaches OT was not established.
Rating: Not Met
Rating reason: the observed transfer does not use a defined controlled pattern.
""")
    return A.parse("\n".join(blocks))


def test_split_requirement_fields_validate_and_render_to_two_destinations():
    card = _card()
    sheet = _sheet()
    matrix = {"E-001": {"claim": "local storage"}, "E-002": {"claim": "direct transfer"}}
    result = A.validate(sheet, card, matrix)
    assert result["status"] == "OK", result

    rendered = A.render_records(sheet, card, _node(), "3", 1)
    text = "\n".join(rendered["records"])
    assert "Observed: The application uses local storage. The requirement is Partially Met because recovery testing was not established." in text
    assert "SEP-X-01 — x" in text
    assert "Operational data is kept on a disk inside the server." in text
    assert "SEP-X-02 — y" in text
    assert "The application transfers files directly between its parts." in text
    assert text.index("SEP-X-02 discovery story") < text.index("SEP-X-01 discovery story")
    assert text.count("**Do:** Insert After") == 2
    assert "`@H3.1.1`" in text


def test_stories_only_render_does_not_rewrite_requirement_rows():
    rendered = A.render_records(_sheet(), _card(), _node(), "3", 1, stories_only=True)
    text = "\n".join(rendered["records"])
    assert len(rendered["records"]) == 2
    assert "discovery story" in text
    assert "current state and rating" not in text


def test_existing_requirement_story_is_replaced_in_place():
    rendered = A.render_records(_sheet(two=False), _card(two=False), _node(existing=True, two=False), "3", 1)
    story = next(r for r in rendered["records"] if "discovery story" in r)
    assert "**Where:** `@H3.1.1-P1`" in story
    assert "**Do:** Replace" in story


def test_existing_split_requirement_story_replaces_title_and_body():
    node = _node(existing=True, two=False)
    node["parts"][-1]["body_pid"] = "@H3.1.1-P2"
    rendered = A.render_records(_sheet(two=False), _card(two=False), node, "3", 1)
    story = next(r for r in rendered["records"] if "discovery story" in r)
    assert "**Do:** Replace this paragraph and the following line" in story


def test_document_spec_keeps_split_story_title_and_body_as_one_managed_part(tmp_path):
    docx = tmp_path / "split-story.docx"
    Document.create(content_md=(
        "# Domains\n\n## Time Synchronisation\n\n### Discovery Information\n\n"
        "**SEP-TIME-01 — Independent OT time source**\n\n"
        "The current-state story starts underneath the title."
    )).save(docx)

    spec = doc_spec.read(docx)
    node = next(n for n in spec["nodes"] if n["title"] == "Time Synchronisation")
    story = next(p for p in node["parts"] if p["kind"] == "requirement-story")
    assert story["title"] == "Independent OT time source"
    assert story["text"] == "The current-state story starts underneath the title."
    assert story["body_pid"]


def test_requirement_story_contract_rejects_missing_or_oversized_summary():
    card = _card(two=False)
    raw = """## B1 SEP-X-01
Facts:
- The application uses local storage. (E-001) {observed; application}
Story: The application keeps its operational data locally.
Rating: Partially Met
Rating reason: recovery was not established.
"""
    missing = A.validate(A.parse(raw), card, {"E-001": {"claim": "local storage"}})
    assert "SUMMARY_MISSING" in {f["code"] for f in missing["findings"]}

    words = " ".join(["word"] * 81) + "."
    oversized = A.validate(A.parse(raw.replace("Story:", f"Summary: {words}\nStory:")), card,
                           {"E-001": {"claim": "local storage"}})
    assert "SUMMARY_TOO_LONG" in {f["code"] for f in oversized["findings"]}


def test_split_requirement_contract_separates_decision_summary_from_evidence_story():
    card = _card(two=False)
    matrix = {"E-001": {"claim": "local storage"}}
    raw = """## B1 SEP-X-01
Facts:
- The application uses local storage. (E-001) {observed; application}
Summary: The application uses local storage but recovery was not established.
Story: Partially Met because local storage exists but recovery was not established.
Rating: Partially Met
Rating reason: recovery was not established.
"""
    res = A.validate(A.parse(raw), card, matrix, draft=True, relaxed=True)
    codes = {f["code"] for f in res["findings"] if f["level"] == "ERROR"}
    assert "SUMMARY_NO_RATING_BASIS" in codes
    assert "STORY_STARTS_WITH_RATING" in codes
    assert "STORY_NO_EVIDENCE_PATH" in codes
    restates = raw.replace(
        "Story: Partially Met because local storage exists but recovery was not established.",
        "Story: The application uses local storage on one disk. The requirement is Partially Met because recovery was not established.",
    )
    res2 = A.validate(A.parse(restates), card, matrix, draft=True, relaxed=True)
    assert "STORY_RESTATES_RATING" in {f["code"] for f in res2["findings"] if f["level"] == "ERROR"}


def test_near_duplicate_summary_and_story_are_rejected():
    card = _card(two=False)
    matrix = {"E-001": {"claim": "local storage"}}
    raw = """## B1 SEP-X-01
Facts:
- The application uses local storage. (E-001) {observed; application}
Summary: The application uses local storage. The requirement is Partially Met because recovery testing was not established.
Story: The application uses local storage for its data. Recovery testing was not established.
Rating: Partially Met
Rating reason: recovery testing was not established.
"""
    res = A.validate(A.parse(raw), card, matrix, draft=True, relaxed=True)
    assert "SUMMARY_STORY_OVERLAP" in {f["code"] for f in res["findings"] if f["level"] == "ERROR"}


def test_discovery_question_is_not_rendered_into_current_state_cell():
    card = _card(two=False)
    sheet = _sheet(two=False)
    sheet["B1"]["unknown"] = ["Has recovery been tested?"]
    rendered = A.render_records(sheet, card, _node(two=False), "3", 1)
    current_state = next(r for r in rendered["records"] if "current state and rating" in r)
    current_state_text = current_state.split("**Text:**", 1)[1].split("**Why:**", 1)[0]
    assert "QUESTION:" not in current_state_text
    assert any("Has recovery been tested?" in q for q in rendered["open"])


def _story_codes(story):
    card = _card(two=False)
    matrix = {"E-001": {"claim": "local storage"}}
    raw = f"""## B1 SEP-X-01
Facts:
- The application uses local storage. (E-001) {{observed; application}}
Summary: Data stays on local disks. The requirement is Partially Met because recovery was not established.
Story: {story}
Rating: Partially Met
Rating reason: recovery was not established.
"""
    res = A.validate(A.parse(raw), card, matrix, draft=True, relaxed=True)
    return {f["code"] for f in res["findings"] if f["level"] == "ERROR"}


def test_long_story_sentence_is_an_error():
    long_s = " ".join(["The nightly job writes a copy of the files to a second disk"] * 1 + ["and then a further copy to a third disk on another server"] * 6) + "."
    assert "STORY_SENTENCE_LONG" in _story_codes(long_s + " Restore was not tested.")
    assert "STORY_SENTENCE_LONG" not in _story_codes("The nightly job copies the files to a second disk. Restore was not tested.")


def test_same_long_phrase_twice_in_a_story_is_an_error():
    s = "Nothing in the evidence reviewed shows that a restore was tested. Nothing in the evidence reviewed shows that a fallback was written down."
    assert "STORY_PHRASE_REPEAT" in _story_codes(s)
    assert "STORY_PHRASE_REPEAT" not in _story_codes("Nothing in the evidence reviewed shows that a restore was tested. No written fallback was found either.")


def test_a_parts_name_and_a_short_parallel_phrase_are_not_a_repeated_phrase():
    from csa_docx import story_shape
    names = {"app": ["Reveloc application / TGOIP server"]}
    s = ("The Reveloc application / TGOIP server at Mackay shares Users. The Reveloc application / TGOIP server at Rockhampton shares Tetra Share. "
         "The Mackay host shares a Test folder with full access for everyone. Another shares a Temp folder with full access for everyone.")
    assert not [c for c, _ in story_shape.findings(s, names) if c == "STORY_PHRASE_REPEAT"]


def test_requirement_prompt_asks_for_a_readable_story():
    from csa_docx import prompts
    rules = prompts.assemble({"requirement"}, None)[0]
    assert "Each paragraph covers one point" in rules and "What is true now, in plain words" in rules
    assert "merge related points instead of adding paragraphs" in rules and "REASON_REPEATS_SUMMARY" in rules
    assert "about 25 words" not in rules


def test_discovery_story_record_gets_the_story_errors():
    from csa_docx import check_change
    from types import SimpleNamespace as NS
    long_s = " ".join(f"w{i}" for i in range(65)) + "."
    rec = NS(title="SEP-X-01 discovery story", text=long_s, edit_id="S3-E1")
    assert {f["code"] for f in check_change.story_findings([rec])} == {"STORY_SENTENCE_LONG"}
    assert check_change.story_findings([NS(title="SEP-X-01 row", text=long_s, edit_id="S3-E2")]) == []


def test_one_block_story_must_be_paragraphed_and_paragraphs_are_kept():
    one = " ".join(f"Sentence number {i} says something about item{i} here." for i in range(8))
    assert "STORY_NOT_PARAGRAPHED" in _story_codes(one)
    ok = "\nStory: ".join([" ".join(f"Sentence number {i} says something about item{i} here." for i in range(3)),
                          "The second paragraph names a different thing entirely. It is short."])
    assert "STORY_NOT_PARAGRAPHED" not in _story_codes(ok)
    raw = f"## B1 SEP-X-01\nFacts:\n- Data sits on local disks. (E-001) {{observed; application}}\nSummary: S.\nStory: First para here.\nStory: Second para here.\n"
    assert A.parse(raw)["B1"]["story"] == "First para here.\n\nSecond para here."


def test_multi_paragraph_story_is_rendered_as_paragraphs_and_replaced_as_a_range():
    from csa_docx import answer_sheet as AS
    assert AS.no_ids("A (E-001).") == "A."
    assert "\n\n".join(AS.no_ids(" ".join(x.split())) for x in "One two.\n\nThree four.".split("\n\n")) == "One two.\n\nThree four."
    from csa_docx.engines import docxengine_adapter as ad
    from types import SimpleNamespace as NS
    assert ad._following_line_count(NS(action="Replace this paragraph and the following 3 lines")) == 3
    assert ad._following_line_count(NS(action="Replace this paragraph and the following line")) == 1
    assert ad._has_paragraph_plus_following_line_replacement(NS(action="Replace this paragraph and the following 3 lines"))


def test_misspelled_slash_name_in_a_kept_fact_is_put_back():
    from collections import Counter
    from csa_docx import section_card
    vocab = Counter({"TETRA/Reveloc": 50, "Tetra/Reveloc": 3, "TCP/IP": 9})
    assert section_card._repair_slash_names("all 2ETRA/Reveloc data over TCP/IP", vocab) == "all TETRA/Reveloc data over TCP/IP"


def test_a_sentence_naming_many_parts_is_no_longer_an_error():
    from csa_docx import story_shape
    names = {"a": ["OT Reveloc Server"], "b": ["Reveloc application"], "c": ["RevBroadcast Server"], "d": ["SQL Server"]}
    s2 = "The OT Reveloc Server, the Reveloc application, the RevBroadcast Server and SQL Server share a path."
    assert not [c for c, _ in story_shape.findings(s2, names)]


def test_story_paragraphs_that_all_open_alike_are_flagged():
    from csa_docx import story_shape
    same = "\n\n".join(f"The item{i} sits on its own host here. It has one job." for i in range(3))
    assert "STORY_SAME_OPENING" in {c for c, _ in story_shape.findings(same)}
    varied = "\n\n".join(["At Mackay the data sits on one host. It has one job.", "Backups run nightly. They go to a second disk.",
                          "Nothing shows a tested restore. That is still open."])
    assert "STORY_SAME_OPENING" not in {c for c, _ in story_shape.findings(varied)}


def test_story_of_one_sentence_paragraphs_is_rejected():
    from csa_docx import story_shape
    eight = "\n\n".join(f"Item{i} sits on its own host here." for i in range(8))
    assert "STORY_NOT_PARAGRAPHED" in {c for c, _ in story_shape.findings(eight)}
    six = "\n\n".join(f"Item{i} sits on its own host here. It has one job." for i in range(6))
    assert "STORY_NOT_PARAGRAPHED" not in {c for c, _ in story_shape.findings(six)}


def test_story_paragraph_opening_with_a_label_is_flagged():
    from csa_docx import story_shape
    assert "STORY_LABEL" in {c for c, _ in story_shape.findings("Where the data sits. The data is on local disks.")}
    assert "STORY_LABEL" not in {c for c, _ in story_shape.findings("At Mackay the data sits on local disks. Backups run nightly.")}
