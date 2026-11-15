"""S638: compatibility and quarantine are explicit route states."""
from pathlib import Path

from csa_docx import v2_access
from csa_docx.v2repo import Repo


def _v2(tmp_path: Path) -> Path:
    work = tmp_path / "csa-work-v2"
    repo = Repo(work)
    repo.close()
    return work


def test_compatibility_route_is_explicit_and_warns(tmp_path):
    work = _v2(tmp_path)
    result = v2_access.route("answer", work_dir=work, db=work / "csa.sqlite",
                             project="test-app", route_state="v2-compatibility")
    assert result["route"] == "v2-compatibility-adapter"
    assert result["route_state"] == "v2-compatibility"
    assert "compatibility adapter" in result["warning"]


def test_quarantine_is_observable_and_never_native(tmp_path):
    work = _v2(tmp_path)
    result = v2_access.route("answer", work_dir=work, db=work / "csa.sqlite",
                             project="test-app", route_state="v2-quarantine")
    assert result["route"] == "v2-compatibility-adapter"
    assert result["route_state"] == "v2-quarantine"
    assert result["status"] == "QUARANTINED"
    assert "native fallback is refused" in result["warning"]


def test_quarantine_does_not_open_legacy_files(tmp_path, monkeypatch):
    work = _v2(tmp_path)
    legacy = work.parent / "csa-work"
    legacy.mkdir()
    sentinel = legacy / "evidence-matrix.csv"
    sentinel.write_text("sentinel\n", encoding="utf-8")
    original = sentinel.read_text(encoding="utf-8")
    result = v2_access.route("answer", work_dir=work, db=work / "csa.sqlite",
                             project="test-app", route_state="v2-quarantine")
    assert result["status"] == "QUARANTINED"
    assert sentinel.read_text(encoding="utf-8") == original


def test_retirement_is_refused_while_a_v1_project_is_active(tmp_path):
    snapshot = tmp_path / "legacy-snapshot.json"
    snapshot.write_text("retained\n", encoding="utf-8")
    result = v2_access.retirement_gate(
        ["v2-native", "v1"], legacy_snapshot=snapshot,
        native_audit={"route": "v2-native", "package_hash": "abc", "validation_result": "OK"})
    assert result["status"] == "BLOCKED"
    assert result["checks"]["no_active_v1"] is False


def test_retirement_requires_retained_snapshot_and_native_audit(tmp_path):
    result = v2_access.retirement_gate(
        ["v2-native"], legacy_snapshot=tmp_path / "missing.json",
        native_audit={"route": "v2-native", "package_hash": "abc", "validation_result": "OK"})
    assert result["status"] == "BLOCKED"
    assert result["checks"]["legacy_snapshot_retained"] is False

    snapshot = tmp_path / "legacy-snapshot.json"
    snapshot.write_text("retained\n", encoding="utf-8")
    ready = v2_access.retirement_gate(
        ["v2-native"], legacy_snapshot=snapshot,
        native_audit={"route": "v2-native", "package_hash": "abc", "validation_result": "OK"})
    assert ready["status"] == "READY"
    assert snapshot.read_text(encoding="utf-8") == "retained\n"


def test_native_audit_metadata_survives_quarantine_and_retirement_gate(tmp_path):
    snapshot = tmp_path / "legacy-snapshot.json"
    snapshot.write_text('{"retained": true}\n', encoding="utf-8")
    audit = {
        "route": "v2-native", "package_hash": "pkg-abc123",
        "database_revision": {"modified_ns": 123},
        "contract_version": "answer-contract-v1", "validation_result": "OK",
    }
    result = v2_access.retirement_gate(["v2-quarantine", "v2-native"],
                                       legacy_snapshot=snapshot, native_audit=audit)
    assert result["status"] == "READY"
    assert audit["route"] == "v2-native"
    assert audit["package_hash"] == "pkg-abc123"
    assert audit["validation_result"] == "OK"
    assert snapshot.read_text(encoding="utf-8") == '{"retained": true}\n'
