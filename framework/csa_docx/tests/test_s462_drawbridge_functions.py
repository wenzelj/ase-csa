"""S462: the Drawbridge Impact question lists the system model's functions, one line per function
with what delivers it and its isolation effect (lost / may be lost / keeps working), and the
write instruction. A card without a system model is unchanged."""
import json
import tempfile
from pathlib import Path

from csa_docx import doc_spec, section_card, spec_cli

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


def test_the_stor_drawbridge_question_lists_the_functions_with_their_isolation_effect():
    # the live STOR card: the model's functions that the parts view covers are listed with their effect
    ws = Path(__file__).resolve().parents[4] / "TETRA" / "06 REVELOC TETRA"
    if not ws.is_dir():
        raise RuntimeError("TETRA project not present; the STOR fixture check needs it")
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "STOR")
    text = section_card.card(node, spec, ws, evidence=False)["text"]
    assert "Functions to write about (from the system model): Broadcast and external data" in text
    assert "Broadcast and external data" in text and ("isolation effect: lost" in text
                                                      or "isolation effect: may be lost" in text)
    assert "Functions to write about (from the system model): Downstream FCC data to IAMPS" in text
    assert "Functions to write about (from the system model): Location, geofence (Channel Assist), speed and keep-alive alerts" in text
    # the write instruction is on the card
    assert ("Write: one sentence on what keeps working, by function; one sentence for each function lost "
            "or at risk, saying what stops; one sentence on any fallback and what is unknown. Name "
            "functions, not lists of parts.") in text


def test_the_fixture_functions_carry_their_isolation_effects(monkeypatch):
    # a card with a system model and a parts view: each function's effect comes from the parts it names, from the
    # parts view's isolation (lost when a part loses a path, may be lost when one only may).
    import csa_docx.parts as parts_mod
    monkeypatch.setattr(parts_mod, "isolation", lambda work_dir, doc=None: ISOLATION)
    with tempfile.TemporaryDirectory() as d:
        ws = _model_workspace(Path(d))
        spec = doc_spec.read(_template())
        node = doc_spec.resolve(spec, "STOR")
        text = section_card.card(node, spec, ws, evidence=False)["text"]
    assert "Functions to write about (from the system model): Broadcast and external data" in text
    assert "Broadcast and external data" in text and "isolation effect: lost" in text
    assert "Downstream FCC data to IAMPS" in text and "isolation effect: may be lost" in text
    assert "Location, geofence, speed and keep-alive alerts" in text and "isolation effect: may be lost" in text


def test_a_card_without_a_system_model_is_unchanged():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        (ws / "csa-work").mkdir()
        spec = doc_spec.read(_template())
        node = doc_spec.resolve(spec, "STOR")
        text = section_card.card(node, spec, ws, evidence=False)["text"]
        assert "Functions to write about (from the system model)" not in text
        assert "Write: one sentence on what keeps working, by function" not in text
