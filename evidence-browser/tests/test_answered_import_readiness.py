from pathlib import Path
import sys

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
sys.path.insert(0, str(FRAMEWORK))

from csa_docx.section_state import project


def test_browser_readiness_projection_accepts_imported_state(tmp_path: Path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "NET.IMPORT.json").write_text('{"state":"ready-for-improve","provenance":{"label":"document-imported baseline"}}')
    value = project(tmp_path, "NET")
    assert value["eligible_for_improve"] is True
    assert value["draft_state"] == "answered-imported"
