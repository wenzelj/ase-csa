"""Knowledge: background documents indexed apart from the evidence, shown on cards, never cited as evidence."""
import json
import sqlite3
from pathlib import Path

import pytest

from csa_docx import answer_sheet as A
from csa_docx import fact_store, knowledge as K, section_card

LISTENER = """---
title: What is an Availability Group Listener?
ms.date: 08/17/2026
---
# What is an availability group listener?

[!INCLUDE [SQL Server](../includes/x.md)]

An availability group listener is a virtual network name (VNN) that clients can connect to in order to access a
database in a primary or secondary replica of an Always On availability group. A client uses DNS to resolve the VNN
into multiple IP addresses and then tries to connect to each address, until a connection request succeeds.

## Listener port

You can connect to the listener by using the name and port. Connect to the listener by using the IP address and port.
This connection is successful even when the name cannot be resolved by the client in this example setup today.
"""

DERIVED = """# System reference

## Reveloc

Reveloc reads radio positions through the DAMM API and stores them in a SQL Server database for replay and alerts
across many different deployments of the product in mining and rail operations around the world today.

## Installation

At Aurizon the Reveloc servers ROTPRDREV101 and MOTPRDREV101 connect to the RevServer availability group listener
for every position they store, and the listener name is resolved through enterprise DNS servers today.
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    shared = tmp_path / "Knowledge"
    (shared / "ms").mkdir(parents=True)
    (shared / "ms" / "listener.md").write_text(LISTENER, encoding="utf-8")
    (shared / "sources.json").write_text(json.dumps({"documents": [{"file": "ms/listener.md", "publisher": "Microsoft",
                                                                    "type": "vendor"}]}), encoding="utf-8")
    monkeypatch.setattr(K, "SHARED", shared)
    root = tmp_path / "proj"
    kn = root / K.PROJECT_DIR
    kn.mkdir(parents=True)
    (root / "csa-work").mkdir()
    (kn / "reference.md").write_text(DERIVED, encoding="utf-8")
    (kn / "sources.json").write_text(json.dumps({"system_terms": ["Aurizon"], "documents": [
        {"file": "reference.md", "title": "System reference", "type": "derived"}]}), encoding="utf-8")
    (kn / K.MODEL).write_text(json.dumps({"functions": [{"function": "Alerts", "delivered_by": "the app servers",
                                                         "depends_on": "SQL", "it_dependencies": "SMTP"}],
                                          "open_questions": [{"question": "Does voice need a server?", "isolation": True},
                                                             {"question": "Is OPS116 in use?", "sections": ["GEN"]}],
                                          "domains": {"DNS": {"checks": ["Names or IP addresses in connection strings."],
                                                              "terms": ["DNS", "listener"]}}}), encoding="utf-8")
    return root


def test_build_indexes_both_folders_and_skips_when_unchanged(project):
    first = K.build(project)
    assert first["rebuilt"] and first["documents"] == 2 and first["passages"] >= 3
    assert K.build(project)["rebuilt"] is False
    assert sorted(p.name for p in (project / "csa-work").iterdir()) == [K.INDEX]   # nothing else, no evidence


def test_passages_drop_front_matter_and_includes():
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.md"
        f.write_text(LISTENER, encoding="utf-8")
        meta, ps = K.passages(f)
    assert meta["ms.date"] == "08/17/2026"
    assert all("INCLUDE" not in t and "ms.date" not in t for _, t in ps)
    assert ps[-1][0].endswith("Listener port")


def test_search_finds_the_listener_passage(project):
    hits = K.search(project, "listener IP address port connect")
    assert hits and K.KID.fullmatch(hits[0]["kid"]) and "listener" in hits[0]["text"].lower()


def test_card_section_labels_background_and_hides_second_hand_system_statements(project):
    qs = [{"id": "B3", "kind": "narrative", "text": "Drawbridge Impact: which functions depend on DNS"}]
    lines, ids = K.card_section("DNS", "DNS", qs, "Whether connections use host names or IP addresses", project)
    text = "\n".join(lines)
    assert "Background knowledge (not evidence)" in text and "System model" in text
    assert "Alerts: delivered by the app servers" in text and "Open question" in text
    assert "Look for: Names or IP addresses" in text
    assert "Look for (second-hand, from System reference" in text           # a derived document is never citable
    assert ids and all(K.KID.fullmatch(i) for i in ids)
    assert not any("Reveloc" in l for l in lines if l.startswith("- K-"))   # neither derived passage is citable


def test_no_knowledge_means_no_section(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "SHARED", tmp_path / "none")
    assert K.card_section("DNS", "DNS", [], "", tmp_path) == ([], [])


def _registered_project(tmp_path, monkeypatch, knowledge_dir: str | None):
    """A throwaway project registered in its own PROJECTS.yaml, with one derived knowledge document."""
    root = tmp_path / "proj"
    kn = root / "00 Knowlege" if knowledge_dir == "00 Knowlege" else root / K.PROJECT_DIR
    kn.mkdir(parents=True)
    (root / "csa-work").mkdir()
    (kn / "reference.md").write_text(DERIVED, encoding="utf-8")
    (kn / "sources.json").write_text(json.dumps({"system_terms": ["Aurizon"], "documents": [
        {"file": "reference.md", "title": "System reference", "type": "derived"}]}), encoding="utf-8")
    (kn / K.MODEL).write_text(json.dumps({"functions": [{"function": "Alerts", "delivered_by": "the app servers",
                                                         "depends_on": "SQL", "it_dependencies": "SMTP"}]}),
                              encoding="utf-8")
    entry = [
        f'  - key: knowleg-{root.name}',
        f'    label: "Knowlege {root.name}"',
        f'    project_root: "{root}"',
        '    project_context: ""',
        f'    work_dir: "{root / "csa-work"}"',
        '    default_source_set: ""',
    ]
    if knowledge_dir is not None:
        entry.insert(3, f'    knowledge_dir: "{knowledge_dir}"')
    import os
    reg = Path(os.environ["CSA_PROJECTS_FILE"])
    reg.write_text("\n".join(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "SHARED", tmp_path / "none")
    return root, kn


def test_registered_knowledge_dir_spelling_is_used(tmp_path, monkeypatch):
    root, kn = _registered_project(tmp_path, monkeypatch, "00 Knowlege")
    assert K.knowledge_dir(root) == "00 Knowlege"
    assert K.folders(root) == [("project", kn)]
    first = K.build(root)
    assert first["rebuilt"] and first["documents"] == 1 and first["passages"] >= 2
    with sqlite3.connect(f"file:{K.index_path(root)}?mode=ro", uri=True) as con:
        assert con.execute("SELECT scope, title, type FROM docs").fetchall() == [
            ("project", "System reference", "derived")]
    assert K.system_model(root)["functions"][0]["function"] == "Alerts"
    lines, _ = K.card_section("DNS", "DNS", [], "", root)
    assert "System model" in "\n".join(lines) and "Look for (second-hand, from System reference" in "\n".join(lines)


def test_no_knowledge_dir_setting_keeps_the_historic_folder(tmp_path, monkeypatch):
    root, kn = _registered_project(tmp_path, monkeypatch, None)
    assert K.knowledge_dir(root) == K.PROJECT_DIR
    assert K.folders(root) == [("project", kn)]
    assert K.build(root)["documents"] == 1
    assert K.build(root)["rebuilt"] is False


def test_knowledge_dir_signatures_differ_across_spellings(tmp_path, monkeypatch):
    a, _ = _registered_project(tmp_path, monkeypatch, "00 Knowledge")
    b, _ = _registered_project(tmp_path / "separate", monkeypatch, "00 Knowlege")
    assert K._signature(a) != K._signature(b)


def test_knowledge_dir_escaping_the_project_root_is_rejected(tmp_path, monkeypatch):
    import os
    root, _ = _registered_project(tmp_path, monkeypatch, None)
    reg = Path(os.environ["CSA_PROJECTS_FILE"])
    base = reg.read_text(encoding="utf-8")
    for bad in ("../outside", "/private/tmp/knowledge-outside", "a/b/../../c"):
        reg.write_text(base + f'    knowledge_dir: "{bad}"\n', encoding="utf-8")
        with pytest.raises(ValueError):
            K.knowledge_dir(root)
        reg.write_text(base, encoding="utf-8")
    assert K.knowledge_dir(root) == K.PROJECT_DIR


MATRIX = {"E-001": {"evidence_id": "E-001", "status": "VERIFIED", "question": "", "gap_or_action": "",
                    "source_title": "REVELOC_discovery_ROTPRDCLU101_20260709T042915Z: 05_dns.txt", "claim": "x"}}
EVID = "The SQL nodes resolve through enterprise DNS. (E-001) {observed; all hosts}"
BG = "A client uses DNS to resolve the listener name. (K-1A2B3C) {background; general}"


def _card(kind):
    return {"key": "DNS", "questions": [{"id": "B1", "kind": kind}], "background_ids": ["K-1A2B3C"],
            "evidence": {"B1": {"rows": [{"id": "E-001", "status": "VERIFIED", "claim": "x"}], "cut": [], "digest_ids": []}}}


def _sheet(*facts):
    body = "\n".join(f"- {f}" for f in facts)
    return A.parse(f"## B1 Drawbridge Impact\nFacts:\n{body}\nText:\nThe application loses its database.\n")


def _errors(res):
    return {f["code"] for f in res["findings"] if f["level"] == "ERROR"}


def test_background_next_to_evidence_in_a_narrative_is_accepted():
    res = A.validate(_sheet(EVID, BG), _card("narrative"), MATRIX, draft=True)
    assert res["status"] != "ERROR", res["findings"]


def test_background_alone_is_refused():
    assert "BACKGROUND_ALONE" in _errors(A.validate(_sheet(BG), _card("narrative"), MATRIX, draft=True))


def test_background_cannot_support_a_requirement():
    sh = A.parse(f"## B1 SEP-DNS-01\nFacts:\n- {EVID}\n- {BG}\nText:\nX.\nRating: Not Met\nRating reason: none.\n")
    assert "BACKGROUND_AS_EVIDENCE" in _errors(A.validate(sh, _card("requirement"), MATRIX, draft=True))


def test_background_cannot_sit_in_a_table_row():
    sh = A.parse("## B1 Discovery Information\nRows:\n| Aspect | Configuration Observed | Coverage / Source |\n"
                 "| Listener | resolves through DNS | Microsoft (K-1A2B3C) |\n")
    card = {**_card("observation"), "questions": [{"id": "B1", "kind": "observation",
                                                    "columns": ["Aspect", "Configuration Observed", "Coverage / Source"]}]}
    assert "BACKGROUND_AS_EVIDENCE" in _errors(A.validate(sh, card, MATRIX, draft=True))


def test_background_and_evidence_ids_are_never_mixed():
    mixed = "Listeners resolve through DNS here. (E-001, K-1A2B3C) {background; general}"
    assert "BACKGROUND_MIXED" in _errors(A.validate(_sheet(EVID, mixed), _card("narrative"), MATRIX, draft=True))
    wrong = "A client uses DNS to resolve the listener name. (K-1A2B3C) {documented; general}"
    assert "BACKGROUND_MIXED" in _errors(A.validate(_sheet(EVID, wrong), _card("narrative"), MATRIX, draft=True))


def test_background_must_be_on_the_card():
    other = "Something else. (K-FFFFFF) {background; general}"
    assert "BACKGROUND_NOT_ON_CARD" in _errors(A.validate(_sheet(EVID, other), _card("narrative"), MATRIX, draft=True))


def test_background_never_becomes_an_established_fact(tmp_path):
    sheet = tmp_path / "s.md"
    sheet.write_text(f"## B1 Drawbridge Impact\nFacts:\n- {EVID}\n- {BG}\nText:\nX.\n", encoding="utf-8")
    card = tmp_path / "c.json"
    card.write_text(json.dumps({"key": "DNS"}), encoding="utf-8")
    assert fact_store.add_from_sheet(tmp_path, sheet, card) == 1      # only the evidence fact


def test_render_note_keeps_background_apart_from_evidence():
    assert "Background knowledge (not evidence)" in open(A.__file__, encoding="utf-8").read()


def test_drawbridge_question_asks_about_functions():
    node = {"title": "DNS", "parts": [{"kind": "narrative", "facet": "Drawbridge Impact",
                                       "question": "What happens to this capability during an isolation event"}],
            "comments": []}
    q = section_card.questions(node)[0]["text"]
    assert "functions depend on DNS" in q and "isolation event" in q and "operations" in q


def test_heading_directly_above_text_is_split_off(tmp_path):
    f = tmp_path / "h.md"
    f.write_text("# Top\n\nIntro text that is long enough to make a passage of its own for the test here today.\n"
                 "## Child\nChild text that is long enough to make a passage of its own for the test here today ok.\n",
                 encoding="utf-8")
    _, ps = K.passages(f)
    assert [h for h, _ in ps] == ["Top", "Top > Child"] and not any("#" in t for _, t in ps)


def test_open_questions_appear_only_where_they_belong():
    model = {"open_questions": [{"question": "Does voice need a server?", "isolation": True, "sections": ["ISO"]},
                                {"question": "Is OPS116 in use?", "sections": ["GEN"]},
                                {"question": "Where do base stations take time from?", "sections": ["TIME"]},
                                "An untagged question"]}
    drawbridge = [{"kind": "narrative", "text": "Drawbridge Impact: which functions stop during an isolation event"}]
    assert K.open_questions(model, "DNS", drawbridge) == ["Does voice need a server?"]
    assert K.open_questions(model, "GEN", []) == ["Is OPS116 in use?"]
    assert K.open_questions(model, "TIME", []) == ["Where do base stations take time from?"]
    assert K.open_questions(model, "PKI", []) == []


def test_card_never_shows_another_sections_open_question(project):
    qs = [{"id": "B3", "kind": "narrative", "text": "Drawbridge Impact: which functions depend on DNS during isolation"}]
    text = "\n".join(K.card_section("DNS", "DNS", qs, "", project)[0])
    assert "Does voice need a server?" in text and "OPS116" not in text


def test_card_wording_in_the_answer_is_refused():
    sheet = A.parse("## B1 Drawbridge Impact\nFacts:\n- " + EVID + "\n"
                    "Unknown: Can Aurizon OT confirm the resolvers for the ten hosts not stated on the card?\nText:\nX.\n")
    assert "PROCESS_AS_SUBJECT" in _errors(A.validate(sheet, _card("narrative"), MATRIX, draft=True))
