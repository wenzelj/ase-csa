"""Drawbridge card prompts are causal to their requirement domain.

Ordinary domains receive only functions with an explicit matching dependency. The overall isolation-validation
domain receives the whole-system isolation effects. A card without a system model is unchanged.
"""
import json
import tempfile
from pathlib import Path

from csa_docx import answer_sheet, doc_spec, section_card, spec_cli

FUNCTIONS = {
    "functions": [
        {"function": "Broadcast and external data",
         "delivered_by": "RevBroadcast (ROTPRDRBS101)",
         "depends_on": "the SQL availability group",
         "it_dependencies": "Azure over the internet"},
        {"function": "Downstream FCC data to IAMPS",
         "delivered_by": "the Reveloc SQL database",
         "depends_on": "SQL access from IAMPS",
         "it_dependencies": "a cross-zone data path"},
        {"function": "Location, geofence, speed and keep-alive alerts",
         "delivered_by": "the Reveloc servers",
         "depends_on": "the SQL availability group (zone not recorded)",
         "it_dependencies": "AD"},
        {"function": "Telephone interconnect",
         "delivered_by": "a SIP gateway",
         "depends_on": "IT CUCM",
         "it_dependencies": "fully IT-dependent"},
    ],
}

# two parts the framework will build from the host register: one named by "RevBroadcast (ROTPRDRBS101)" and one by
# the "Reveloc" functions. Their isolation effects (what isolating OT loses) are supplied by the test.
HOSTS = "host,role,site,capture,in_scope\nROTPRDRBS101,RevBroadcast application server,RO,,yes\nROTPRDREV101,Reveloc,RO,,yes\n"

ISOLATION = {
    "revbroadcast-application-server": {"effect": "loses its paths into OT: monitoring", "cut": ["monitoring"],
                                        "may_cut": [], "unaffected": [], "kept": []},
    "reveloc": {"effect": "may lose (zone not recorded): database", "cut": [], "may_cut": ["database"],
                "unaffected": [], "kept": []},
}



def _template() -> Path:
    p = Path(__file__).resolve().parents[3] / "CSA Template" / "CSA_Template_v1.6.dotx"
    if not p.is_file():
        p = spec_cli.find_template(None)
    if not p or not p.is_file():
        raise RuntimeError("no CSA template available")
    return p


def _model_workspace(tmp: Path) -> Path:
    ws = tmp / "workspace"
    kn = ws / "00 Knowledge"
    kn.mkdir(parents=True)
    (kn / "system-model.json").write_text(json.dumps(FUNCTIONS), encoding="utf-8")
    hosts = ws / "csa-work" / "hosts"
    hosts.mkdir(parents=True)
    (hosts / "hosts.csv").write_text(HOSTS, encoding="utf-8")
    return ws


def test_the_stor_drawbridge_question_lists_only_storage_dependent_functions():
    # STOR sees only functions whose declared dependency is storage/data-transfer specific.
    ws = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
    if not ws.is_dir():
        raise RuntimeError("TETRA project not present; the STOR fixture check needs it")
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    text = section_card.card(node, spec, ws, evidence=False)["text"]
    assert "Function with an explicit Storage & Data Transfer dependency to assess: Voice and SDS recording" in text
    assert "Function with an explicit Storage & Data Transfer dependency to assess: Downstream FCC data to IAMPS" in text
    assert "Function with an explicit Storage & Data Transfer dependency to assess: Location, geofence" in text
    assert "Function with an explicit Storage & Data Transfer dependency to assess: Operator view" in text
    assert "Function with an explicit Storage & Data Transfer dependency to assess: Broadcast and external data" not in text
    assert "isolation effect:" not in text
    assert "A function stops only where this section's evidence establishes" in text


def test_function_names_and_generic_apis_do_not_create_network_or_monitoring_dependencies():
    ws = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
    spec = doc_spec.read(_template())
    network = section_card.card(doc_spec.resolve(spec, "NET"), spec, ws, evidence=False)["text"]
    monitoring = section_card.card(doc_spec.resolve(spec, "MON"), spec, ws, evidence=False)["text"]
    assert "Voice group and emergency calls (TMO)" in network  # its dependency explicitly names MPLS
    assert "Radio-to-radio fallback (DMO)" not in network       # its dependency says no network service is needed
    assert "Location, geofence (Channel Assist)" not in network # API alone is not a segmentation dependency
    assert "Voice and SDS recording" not in monitoring          # a function name is not a monitoring dependency


def test_only_the_overall_isolation_domain_carries_whole_system_effects(monkeypatch):
    import csa_docx.parts as parts_mod
    monkeypatch.setattr(parts_mod, "isolation", lambda work_dir, doc=None: ISOLATION)
    with tempfile.TemporaryDirectory() as d:
        ws = _model_workspace(Path(d))
        spec = doc_spec.read(_template())
        node = doc_spec.resolve(spec, "ISO")
        text = section_card.card(node, spec, ws, evidence=False)["text"]
    assert "Functions to write about (from the system model): Broadcast and external data" in text
    assert "Broadcast and external data" in text and "isolation effect: lost" in text
    assert "Downstream FCC data to IAMPS" in text and "isolation effect: may be lost" in text
    assert "Location, geofence, speed and keep-alive alerts" in text and "isolation effect: may be lost" in text
    assert "whole-system view is permitted here" in text


def test_a_card_without_a_system_model_is_unchanged():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        (ws / "csa-work").mkdir()
        spec = doc_spec.read(_template())
        node = doc_spec.resolve(spec, "STOR")
        text = section_card.card(node, spec, ws, evidence=False)["text"]
        assert "Functions to write about (from the system model)" not in text
        assert "Write: one sentence on what keeps working, by function" not in text


def test_time_card_lists_only_explicit_time_dependencies_without_generic_isolation_effects():
    ws = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
    if not ws.is_dir():
        raise RuntimeError("TETRA project not present; the TIME fixture check needs it")
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "TIME")
    text = section_card.card(node, spec, ws, evidence=False)["text"]
    question = text[text.index("B3 Drawbridge Impact"):text.index("## Requirement summaries")]
    assert "Function with an explicit Time Synchronisation dependency to assess: Voice and SDS recording" in question
    assert "NTP for timestamps" in question
    assert "Analogue radio interconnect" not in question
    assert "Operator view" not in question
    assert "isolation effect: lost" not in question
    assert "Write only consequences caused by loss or unavailability of Time Synchronisation" in question


def test_every_requirement_domain_drawbridge_card_states_its_own_scope():
    ws = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
    spec = doc_spec.read(_template())
    nodes = [n for n in spec.get("nodes", []) if str(n.get("number") or "").startswith("3.")]
    assert {str(n.get("number")) for n in nodes} == {f"3.{i}" for i in range(1, 18)}
    for node in nodes:
        text = section_card.card(node, spec, ws, evidence=False)["text"]
        title = node["title"]
        assert f"Which of the system's functions depend on {title}?" in text
        if str(node["number"]) == "3.12":
            assert "whole-system view is permitted here" in text
            continue
        assert (f"Function with an explicit {title} dependency to assess:" in text or
                f"No function in the system model declares an explicit {title} dependency." in text)
        assert (f"Write only consequences caused by loss or unavailability of {title}." in text or
                "Do not infer one from shared servers or from a whole-system isolation outcome." in text)


def test_drawbridge_validation_uses_the_subsection_point_of_view():
    card = {"key": "TIME", "number": "3.4", "title": "Time Synchronisation",
            "questions": [{"id": "B3", "kind": "narrative", "text": "Drawbridge Impact"},
                          {"id": "B4", "kind": "narrative", "text": "Another narrative"}]}
    sheet = answer_sheet.parse(
        "## B3 Drawbridge Impact\n"
        "Text:\nTelephone interconnect stops, preventing calls through the IT gateway. "
        "The hosts continue on local clocks after losing their time source.\n"
    )
    findings = answer_sheet.drawbridge_topic_checks(sheet, card)
    assert [f["code"] for f in findings] == ["DRAWBRIDGE_CAUSAL_SCOPE"]
    assert "Telephone interconnect stops" in findings[0]["message"]

    focused = answer_sheet.parse(
        "## B3 Drawbridge Impact\n"
        "Text:\nThe hosts lose time synchronisation and continue on their local clocks. "
        "The evidence does not establish which functions stop because clock drift exceeds tolerance.\n"
    )
    assert answer_sheet.drawbridge_topic_checks(focused, card) == []

    other_narrative = answer_sheet.parse(
        "## B4 Another narrative\nText:\nTelephone interconnect stops when the IT gateway is cut.\n"
    )
    assert answer_sheet.drawbridge_topic_checks(other_narrative, card) == []

    dns = {**card, "key": "DNS", "number": "3.5", "title": "DNS"}
    network = {**card, "key": "NET", "number": "3.6", "title": "Network / Segmentation"}
    link_effect = answer_sheet.parse(
        "## B3 Drawbridge Impact\nText:\nTelephone interconnect stops when its SIP gateway route is cut.\n"
    )
    assert [f["code"] for f in answer_sheet.drawbridge_topic_checks(link_effect, dns)] == [
        "DRAWBRIDGE_CAUSAL_SCOPE"
    ]
    assert answer_sheet.drawbridge_topic_checks(link_effect, network) == []
