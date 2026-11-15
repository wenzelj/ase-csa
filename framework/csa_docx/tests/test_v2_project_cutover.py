"""S635: project route state is explicit and deterministic."""
from pathlib import Path
import json
import os
import subprocess
import sys

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


def _gate_project(tmp_path: Path, accepted: bool) -> tuple[Path, Path]:
    workspace = tmp_path / "gate-project"
    work = workspace / "csa-work-v2"
    repo = Repo(work)
    with repo.tx():
        repo.hosts.create("APP01", role="application")
        repo.application_scope.add("test-app", "APP01", "owned", basis="inventory", review_state="accepted")
        repo.evidence.create(claim="APP01 is evidenced.", question="What is APP01?", area="test",
                             source_title="capture.txt", excerpt="APP01", status="VERIFIED")
        repo.con.execute("INSERT INTO indexed_file(rel_path, sha256, size) VALUES ('capture.txt','x',1)")
    repo.close()
    if accepted:
        acceptance = work / "acceptance"
        acceptance.mkdir()
        for name in ("dual-run.json", "draft-lane.json"):
            (acceptance / name).write_text(json.dumps({"status": "OK", "recorded_at": "2026-11-15T00:00:00Z"}))
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text("projects:\n"
                        "  - key: test-app\n"
                        "    label: Test App\n"
                        f"    project_root: {workspace}\n"
                        f"    work_dir: {work}\n"
                        "    application: test-app\n")
    return registry, work


def test_cutover_gate_blocks_until_dual_run_and_draft_lane_are_recorded(tmp_path):
    registry, _work = _gate_project(tmp_path, accepted=False)
    env = {**os.environ, "CSA_PROJECTS_FILE": str(registry)}
    result = subprocess.run([sys.executable, str(Path(__file__).parents[3] / "bin" / "csa"),
                             "--project", "test-app", "cutover-gate", "--json"],
                            capture_output=True, text=True, env=env)
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "BLOCKED"
    assert payload["checks"]["schema"] is True
    assert payload["checks"]["sources"] is True
    assert payload["checks"]["provenance"] is True
    assert payload["checks"]["scope"] is True
    assert payload["checks"]["dual_run"] is False
    assert payload["checks"]["draft_lane"] is False
    assert payload["rollback"]["route"] == "v2-compatibility"


def test_cutover_gate_is_ready_only_when_every_check_passes(tmp_path):
    registry, work = _gate_project(tmp_path, accepted=True)
    env = {**os.environ, "CSA_PROJECTS_FILE": str(registry)}
    result = subprocess.run([sys.executable, str(Path(__file__).parents[3] / "bin" / "csa"),
                             "--project", "test-app", "cutover-gate", "--json"],
                            capture_output=True, text=True, env=env)
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "READY"
    assert payload["route"] == "v2-native"
    assert all(payload["checks"].values())
    assert not (work / "csa-work" / "evidence-matrix.csv").exists()


def test_native_pilot_and_non_migrated_v1_project_are_isolated(tmp_path):
    registry, work = _gate_project(tmp_path, accepted=True)
    legacy = tmp_path / "legacy-project" / "csa-work"
    legacy.mkdir(parents=True)
    text = registry.read_text(encoding="utf-8").replace("    application: test-app\n",
                                                           "    application: test-app\n"
                                                           "    answer_route: v2-native\n")
    registry.write_text(text +
                        f"  - key: legacy-app\n"
                        f"    label: Legacy App\n"
                        f"    project_root: {legacy.parent}\n"
                        f"    work_dir: {legacy}\n"
                        "    answer_route: v1\n")
    env = {**os.environ, "CSA_PROJECTS_FILE": str(registry)}
    csa = str(Path(__file__).parents[3] / "bin" / "csa")
    native = subprocess.run([sys.executable, csa, "--project", "test-app", "route", "answer", "--json"],
                            capture_output=True, text=True, env=env)
    legacy_result = subprocess.run([sys.executable, csa, "--project", "legacy-app", "route", "answer", "--json"],
                                   capture_output=True, text=True, env=env)
    native_payload = json.loads(native.stdout)
    legacy_payload = json.loads(legacy_result.stdout)
    assert native_payload["route"] == "v2-native"
    assert native_payload["project_route_state"] == "v2-native"
    assert legacy_payload["route"] == "v1-native"
    assert legacy_payload["project_route_state"] == "v1"
    assert native_payload["store"] == str(work / "csa.sqlite")
