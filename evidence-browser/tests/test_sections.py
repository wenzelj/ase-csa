from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import sections


SPEC = {"nodes": [{"number": "3.1", "key": "ASSET", "path": "3.1", "hid": "@H3.1", "level": 2,
                   "title": "Asset Inventory", "kind": "requirement-block", "status": {"open": 1, "total": 2},
                   "comments": [{"author": "Reviewer", "text": "Confirm owner"}], "guidance": [],
                   "parts": [{"kind": "text", "pid": "@H3.1-P1", "current": "Observed TETRA hosts cite E-042."},
                             {"kind": "requirement", "table": "@H3.1-T1", "ratings": ["Met", "Not Met"],
                              "requirements": [{"id": "SEP-ASSET-01", "text": "Record assets", "row": 2,
                                                "current_state": "Known hosts", "rating": "Met"}]}]}],
        "removed": [{"key": "OLD", "title": "Retired template topic"}]}


def runner(name):
    return {"spec_status": SPEC, "status": [{"subsection": "3.1", "change_file": None,
                                               "review": "PASS"}], "sections": []}[name]


def revision_reader(_project):
    return {"paragraphs": [{"index": 7, "style": "Heading 2", "tokens": [{"kind": "normal", "text": "Asset Inventory"}]},
                           {"index": 8, "style": "Normal", "tokens": [{"kind": "normal", "text": "Current"},
                                                                            {"kind": "delete", "text": "Removed claim"}]},
                           {"index": 9, "style": "Heading 2", "tokens": [{"kind": "normal", "text": "Next"}]}]}


def test_inspector_preserves_structural_and_evidence_ids(tmp_path):
    result = sections.inspect(Path(__file__).parents[2], {"key": "tetra-reveloc", "work_dir": str(tmp_path)},
                              "ASSET", [{"evidence_id": "E-042", "claim": "Hosts are recorded",
                                         "status": "VERIFIED", "review_state": "accepted"}], runner=runner,
                              revision_reader=revision_reader)
    assert result["identity"]["visible_number"] == "3.1"
    assert result["identity"]["stable_id"] == "@H3.1"
    assert result["current"]["parts"][0]["pid"] == "@H3.1-P1"
    assert result["requirements"][0]["id"] == "SEP-ASSET-01"
    assert result["requirements"][0]["table_id"] == "@H3.1-T1"
    assert result["evidence"][0]["evidence_id"] == "E-042"
    assert result["comments"][0]["text"] == "Confirm owner"
    assert result["removed"] == [{"paragraph_id": 8, "text": "Removed claim"}]


def test_inspector_resolves_visible_number_and_rejects_unknown(tmp_path):
    project = {"key": "tetra-reveloc", "work_dir": str(tmp_path)}
    assert sections.inspect(Path(__file__).parents[2], project, "3.1", [], runner=runner,
                            revision_reader=revision_reader)["identity"]["stable_key"] == "ASSET"
    with pytest.raises(HTTPException) as error:
        sections.inspect(Path(__file__).parents[2], project, "9.9", [], runner=runner,
                         revision_reader=revision_reader)
    assert error.value.status_code == 404
