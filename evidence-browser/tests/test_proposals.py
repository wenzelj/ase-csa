import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import proposals


def fixture(tmp_path: Path, *, lane="revise"):
    root, work = tmp_path / "project", tmp_path / "project" / "csa-work"
    root.mkdir(); work.mkdir()
    if lane == "revise":
        path = root / "reviews" / "ChangesCSA_App_Section3_3-1.md"
        path.parent.mkdir()
        path.write_text("""# Changes
**Section:** 3.1 - Assets
**Status:** Proposed changes for approval.

### S3-E2 - Existing change

**Where:** @H3.1-P1

**Do:** Replace

**Facts:** Existing fact. Evidence: E-001

**Text:**

> Existing replacement.

**Why:** Correct the current description.

---

## Open questions

- Confirm the application owner.
""", encoding="utf-8")
        status, builds = [{"subsection": "3.1", "change_file": str(path)}], []
    else:
        path = work / "sections" / "03-assets.md"; path.parent.mkdir()
        path.write_text("---\nbuild_id: test\nblock: migration\nheading: Assets\nstatus: draft\n---\n\n## Table\n\n| Host | Role |\n| --- | --- |\n| A | App |\n", encoding="utf-8")
        status, builds = [], [{"heading": "Assets", "file": path.name}]
    spec = {"nodes": [{"number": "3.1", "level": 2, "key": "ASSET", "path": "3.1", "hid": "@H3.1",
                       "title": "Assets", "parts": [{"kind": "text", "pid": "@H3.1-P1"},
                                                       {"kind": "requirement", "table": "@H3.1-T1",
                                                        "requirements": [{"id": "SEP-ASSET-01", "row": 2}]}]}]}
    def runner(name): return {"spec_status": spec, "status": status, "sections": builds}[name]
    return {"key": "test", "project_root": str(root), "work_dir": str(work)}, path, runner


def test_revise_load_allocates_across_labelled_files_and_preserves_ids(tmp_path):
    project, path, runner = fixture(tmp_path)
    (path.parent / "ChangesCSA_App_Section3_other.md").write_text("### S3-E9 - Other\n", encoding="utf-8")
    result = proposals.load(Path(__file__).parents[2], project, "ASSET", runner=runner)
    assert result["next_edit_id"] == "S3-E10"
    assert result["records"][0]["edit_id"] == "S3-E2"
    assert "@H3.1-T1-R2" in result["stable_ids"]


def test_stale_save_and_invalid_stable_id_are_rejected(tmp_path):
    project, path, runner = fixture(tmp_path)
    loaded = proposals.load(Path(__file__).parents[2], project, "3.1", runner=runner)
    path.write_text(path.read_text() + "\nexternal change\n", encoding="utf-8")
    with pytest.raises(HTTPException) as stale:
        proposals.save(Path(__file__).parents[2], project, "3.1", loaded, runner=runner)
    assert stale.value.status_code == 409
    loaded = proposals.load(Path(__file__).parents[2], project, "3.1", runner=runner)
    loaded["records"][0]["target"] = "@H9-P9"
    with pytest.raises(HTTPException) as invalid:
        proposals.save(Path(__file__).parents[2], project, "3.1", loaded, runner=runner)
    assert invalid.value.status_code == 422


def test_save_backs_up_adds_evidence_and_revokes_approval(tmp_path):
    project, path, runner = fixture(tmp_path)
    approval = path.with_name(path.stem + ".approval.json")
    approval.write_text(json.dumps({"hashes": {"S3-E2": "old"}}), encoding="utf-8")
    loaded = proposals.load(Path(__file__).parents[2], project, "3.1", runner=runner)
    loaded["records"][0].update(replacement="Updated replacement.", evidence_ids=["E-042"])
    result = proposals.save(Path(__file__).parents[2], project, "3.1", loaded, runner=runner)
    assert result["saved"] and result["approval_revoked"]
    assert Path(result["backup"]).read_text(encoding="utf-8").startswith("# Changes")
    assert not approval.exists()
    assert "Evidence: E-042" in path.read_text(encoding="utf-8")
    assert "Revalidation and approval are required" in path.read_text(encoding="utf-8")
    assert "Confirm the application owner" in path.read_text(encoding="utf-8")


def test_build_lane_table_edit_is_atomic_and_backed_up(tmp_path):
    project, path, runner = fixture(tmp_path, lane="build")
    loaded = proposals.load(Path(__file__).parents[2], project, "Assets", runner=runner)
    loaded["content"] = loaded["content"].replace("| A | App |", "| A | Application server |")
    result = proposals.save(Path(__file__).parents[2], project, "Assets", loaded, runner=runner)
    assert result["saved"] and Path(result["backup"]).is_file()
    assert "Application server" in path.read_text(encoding="utf-8")


def test_selected_path_outside_project_is_rejected(tmp_path):
    project, _, runner = fixture(tmp_path)
    outside = tmp_path / "outside.md"; outside.write_text("x", encoding="utf-8")
    def unsafe(name):
        if name == "status": return [{"subsection": "3.1", "change_file": str(outside)}]
        return runner(name)
    with pytest.raises(HTTPException) as error:
        proposals.load(Path(__file__).parents[2], project, "3.1", runner=unsafe)
    assert error.value.status_code == 409
