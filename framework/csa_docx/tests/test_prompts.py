"""The per-kind answer prompts (framework/csa_docx/prompts.py): nothing is lost against the draft digest, a call gets
only the kinds it writes, and a project's own copy wins and is checked, backed up and reversible."""
import json
from pathlib import Path

import pytest

from csa_docx import prompts, rules_digest

ALL = set(prompts.KIND_FILE)


def _lines(text):
    return {l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")}


def test_all_kinds_together_keep_every_line_of_the_draft_digest(tmp_path):
    text, _ = prompts.assemble(ALL, tmp_path, frame=True)
    # phase 2 replaced the first two by the full Story rules; the Drawbridge lines were rewritten to work function by function
    replaced = ("- Split requirements:", "- Story rules:", "- Drawbridge Impact names the system's functions", "- Drawbridge Impact: one short paragraph",
                "- A card line \"Rows disagree:\"")      # widened to cover a row that gives only the default value
    missing = {l for l in _lines(rules_digest.digest("draft")) - _lines(text) if not l.startswith(replaced)}
    assert not missing, sorted(missing)[:3]


def test_a_requirement_call_gets_no_table_or_drawbridge_rules(tmp_path):
    text, sources = prompts.assemble({"requirement"}, tmp_path)
    assert [n for n, _ in sources] == ["base", "requirement"]
    assert "Write both `Summary:` and `Story:`" in text and "- Table blocks:" not in text and "Drawbridge Impact names" not in text
    assert "Rows:" not in "".join(l for l in text.splitlines() if l.startswith("- Table"))


def test_kinds_come_from_the_card_json(tmp_path):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "STOR.json").write_text(json.dumps({"questions": [
        {"id": "B1", "kind": "requirement"}, {"id": "B4", "kind": "narrative"}, {"id": "B5", "kind": "note"}]}))
    assert prompts.kinds_for_call(tmp_path, "STOR.focus.md", "B1") == {"requirement"}
    assert prompts.kinds_for_call(tmp_path, "STOR.md", "") == {"requirement", "narrative", "note"}
    assert prompts.kinds_for_call(tmp_path / "none", "X.md", "B1") == ALL        # no card json: every rule


def test_project_copy_wins_is_checked_backed_up_and_resettable(tmp_path):
    text, source = prompts.resolve("requirement", tmp_path)
    assert source == "default"
    tag = prompts.etag(text)
    assert prompts.save("requirement", tmp_path, "Mine.\n", "stale")["conflict"]
    assert prompts.save("base", tmp_path, "no placeholder", prompts.etag(prompts.resolve("base", tmp_path)[0]))["problems"]
    assert prompts.save("requirement", tmp_path, "x" * 13000, tag)["problems"]
    assert prompts.save("requirement", tmp_path, "Mine.\n", tag)["saved"]
    assert prompts.resolve("requirement", tmp_path) == ("Mine.\n", "project")
    assert "Mine." in prompts.assemble({"requirement"}, tmp_path)[0]
    r = prompts.save("requirement", tmp_path, "Mine two.\n", prompts.etag("Mine.\n"))
    assert r["saved"] and r["backup"] and Path(r["backup"]).read_text() == "Mine.\n"
    prompts.reset("requirement", tmp_path)
    assert prompts.resolve("requirement", tmp_path)[1] == "default"
    assert prompts.history("requirement", tmp_path)


def test_unknown_prompt_name_is_refused(tmp_path):
    with pytest.raises(KeyError):
        prompts.save("../../etc/passwd", tmp_path, "x", "")


def test_every_blocking_validator_rule_is_in_a_prompt():
    """The agent writes from the prompts alone, so each code the draft lane treats as a hard error must be named in the
    text of some prompt, next to the rule in words (the codes sit in brackets after the rule)."""
    from csa_docx import answer_sheet, prompts
    text = "\n".join(prompts.assemble(set(prompts.KIND_FILE), None, fix=True, frame=True)[0] for _ in [0])
    missing = sorted(c for c in answer_sheet.RELAXED_HARD if c not in text)
    assert not missing, f"blocking validator codes with no rule in any prompt: {missing}"


def test_the_drawbridge_prompt_asks_for_every_listed_function_by_name(tmp_path):
    text, _ = prompts.assemble({"narrative"}, tmp_path)
    assert "Function with an explicit ... dependency to assess" in text and "DRAWBRIDGE_FUNCTION_MISSING" in text
    assert "Declared dependencies and flows" not in text and "one short paragraph" not in text


def test_an_old_answers_wording_of_a_setting_finding_is_not_carried_forward():
    from csa_docx import section_card
    fr = {"slots": [{"id": "S8", "findings": [{"ids": ["E-2995", "E-2996"], "from_setting": True, "value": "Direct, no WinHTTP proxy",
                                               "text": "Proxy setting on A, B: Direct, no WinHTTP proxy"}]},
                    {"id": "S3", "findings": [{"ids": ["E-1007"], "text": "PDM opens TCP 7000"}]}]}
    stale = {"question": "B2", "fact": "Proxy settings are configured on the hosts.", "capture_ids": ["E-2995", "E-2996"], "evidence_ids": ["E-2995"]}
    mixed = {"question": "B2", "fact": "Shares are limited.", "capture_ids": ["E-147", "E-2995", "E-2996"], "evidence_ids": []}
    other = {"question": "B3", "fact": "PDM opens TCP 7000.", "capture_ids": ["E-1007"], "evidence_ids": ["E-1007"]}
    keep, correct = section_card.filter_keep([stale, mixed, other], fr)
    assert [k["fact"] for k in keep] == ["PDM opens TCP 7000."] and correct == []


def test_a_row_that_says_only_the_default_is_marked_as_disagreeing_with_the_frame():
    from csa_docx import topic_frames
    fr = {"slots": [{"id": "S2", "findings": [
        {"value": "Default and administrative shares only", "ids": ["E-1"], "hosts": ["A"]},
        {"value": "Temp: Everyone Full", "ids": ["E-3156"], "hosts": ["IPTPRDAPP137"], "requirements": ["SEP-STOR-02"]}]}]}
    rows = [{"id": "E-147", "claim": "Across all hosts the local SMB shares are limited to default and administrative shares."},
            {"id": "E-9", "claim": "A host opened a connection."}]
    out = topic_frames.row_disagreements(fr, rows)
    assert len(out) == 1 and out[0].startswith("Rows disagree: E-147") and "IPTPRDAPP137" in out[0]


def test_the_drawbridge_prompt_says_the_cause_once_and_never_claims_a_function_works():
    text, _ = prompts.assemble({"narrative"}, None)
    assert "say the cause once at the start" in text and "without repeating the cause" in text
    assert 'Do not write that the function "keeps working"' in text and "the evidence does not test the function" in text


def test_the_card_glossary_explains_standard_terms_found_in_the_card_and_invents_no_acronyms():
    import json
    from pathlib import Path
    from csa_docx import section_card
    text = "\n".join(section_card.glossary_lines("The nodes open Server Message Block connections and a SQL Server availability group."))
    assert "Server Message Block: the Windows file-sharing protocol" in text and "availability group:" in text and "SysVol" not in text
    assert section_card.glossary_lines("Nothing technical here.") == []
    terms = json.loads((Path(section_card.__file__).resolve().parents[2] / "references" / "glossary.json").read_text())["terms"]
    assert not {"tgoip", "iamps", "fcc", "sds", "daam"} & {t["term"].lower() for t in terms}      # the sources do not define them


def test_the_base_prompt_asks_to_explain_terms_and_not_to_guess_acronyms():
    text, _ = prompts.assemble({"requirement"}, None)
    assert "Plain-words glossary" in text and "never invent what an acronym stands for" in text
    assert "ABSENCE_WITHOUT_FACT" in text


def test_a_focused_card_gets_its_own_json_so_the_agents_validate_line_works(tmp_path):
    import json
    from csa_docx import answer_blocks
    card = {"questions": [{"id": "B1"}, {"id": "B2"}, {"id": "B4"}], "evidence": {"B1": 1, "B2": 2, "B4": 4},
            "frame": {"must_address": {"B1": 1, "B2": 2}}, "parts": {"owed": {"B1": 1, "B2": 2}, "owed_applications": {"B2": 2}},
            "drawbridge_functions": {"B4": [1]}}
    out = answer_blocks.focus_card_json(card, {"B2"})
    assert [q["id"] for q in out["questions"]] == ["B2"] and out["evidence"] == {"B2": 2} and out["parts"]["owed"] == {"B2": 2}
    assert out["drawbridge_functions"] == {} and out["frame"]["must_address"] == {"B2": 2}
    assert [q["id"] for q in answer_blocks.focus_card_json(card, {"F1"})["questions"]] == ["B1", "B2", "B4"]      # the frame call keeps all
    assert len(card["questions"]) == 3                                                                          # the full card is untouched
    md = tmp_path / "STOR.md"
    md.write_text("# Card\n\n### B2 q\n", encoding="utf-8")
    (tmp_path / "STOR.json").write_text(json.dumps(card), encoding="utf-8")
    assert answer_blocks.main(["focus", str(md), "--only", "B2", "--out", str(tmp_path / "STOR.focus.md")]) == 0
    assert [q["id"] for q in json.loads((tmp_path / "STOR.focus.json").read_text())["questions"]] == ["B2"]
