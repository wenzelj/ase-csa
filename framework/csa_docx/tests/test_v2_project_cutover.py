"""S635: project route state is explicit and deterministic."""
from pathlib import Path

from csa_docx import v2_access
from csa_docx.v2repo import Repo


def _store(tmp_path: Path) -> Path:
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    repo.close()
    return work


def test_project_route_states_select_explicit_routes(tmp_path):
    work = _store(tmp_path)
    db = work / "csa.sqlite"
    for state, expected in (
        ("v1", "v1-native"),
        ("v2-compatibility", "v2-compatibility-adapter"),
        ("v2-native", "v2-native"),
    ):
        result = v2_access.route("answer", work_dir=work, db=db,
                                 project="test-app", route_state=state)
        assert result["route"] == expected
        assert result["route_state"] == state
        assert result["project"] == "test-app"


def test_route_state_is_rejected_when_unknown(tmp_path):
    work = _store(tmp_path)
    result = v2_access.route("answer", work_dir=work, route_state="native-maybe")
    assert result["status"] == "ERROR"
    assert result["code"] == "V2_ROUTE_STATE_INVALID"


def test_default_v2_project_remains_compatibility_until_selected(tmp_path):
    work = _store(tmp_path)
    result = v2_access.route("answer", work_dir=work, db=work / "csa.sqlite", adapter=True)
    assert result["route"] == "v2-compatibility-adapter"
    assert result["route_state"] == "v2-compatibility"
