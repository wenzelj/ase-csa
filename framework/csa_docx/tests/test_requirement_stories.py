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
Summary: The application uses local storage, but recovery testing was not established.
Story: The application keeps its operational data locally. Recovery fitness and an isolation fallback were not established.
Rating: Partially Met
Rating reason: local storage exists but recovery evidence is incomplete.
"""]
    if two:
        blocks.append("""## B2 SEP-X-02
Facts:
- Direct transfer remains in use. (E-002) {observed; application}
Summary: Direct transfer remains in use and no controlled pattern was identified.
Story: The application transfers files directly. No proxy, scanning point or approved transfer pattern was identified.
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
    assert "Observed: The application uses local storage, but recovery testing was not established." in text
    assert "SEP-X-01 — x" in text
    assert "The application keeps its operational data locally." in text
    assert "SEP-X-02 — y" in text
    assert "The application transfers files directly." in text
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
