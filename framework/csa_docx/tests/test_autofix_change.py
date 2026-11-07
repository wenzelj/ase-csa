from pathlib import Path

from csa_docx import autofix_change as af
from csa_docx.check_change import check

CLEAN = """# Changes to Test Document
## Section 1 Test Change Record

**File reviewed:** Test Document
**Section:** 1 - Test
**Suggested change set:** S1-E1 to S1-E2
**Status:** Proposed changes for approval. This file is an approval record only.

---

## Proposed changes

### S1-E1 - Correct the time source

**Where:** `@H1-P2` -- currently: "The hosts use a local time source."

**Do:** Replace

**Text:**

> The hosts take time from two enterprise time servers.

**Why:**
Evidence E-001 shows both hosts take time from the enterprise servers.

**Note:**
Corrected the time source.

---

### S1-E2 - Add a sentence

**Where:** `@H1-P3`

**Do:** Insert after

**Text:**

> The servers are in Rockhampton.

**Why:**
Evidence E-002.

**Note:**
Added the site.

---
"""


def write(tmp_path, text, name="ChangesCSA_Test_Section1.md"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def test_clean_file_is_unchanged(tmp_path):
    f = write(tmp_path, CLEAN)
    res = af.autofix(f, write=True)
    assert res["status"] == "CLEAN" and res["fixes"] == []
    assert f.read_text(encoding="utf-8") == CLEAN


def test_markdown_is_stripped(tmp_path):
    bad = CLEAN.replace("> The hosts take time from two enterprise time servers.",
                        "> # The **hosts** take time from `two` enterprise time servers.")
    f = write(tmp_path, bad)
    res = af.autofix(f, write=True)
    assert [x["code"] for x in res["fixes"]] == ["MARKDOWN_IN_TEXT"]
    assert "> The hosts take time from two enterprise time servers." in f.read_text(encoding="utf-8")


def test_ids_move_to_why(tmp_path):
    bad = CLEAN.replace("servers.\n\n**Why:**", "servers (@H1-P2) (E-001, E-077).\n\n**Why:**")
    f = write(tmp_path, bad)
    res = af.autofix(f, write=True)
    codes = [x["code"] for x in res["fixes"]]
    assert "EID_IN_TEXT" in codes and "STABLE_ID_IN_TEXT" in codes
    text = f.read_text(encoding="utf-8")
    assert "> The hosts take time from two enterprise time servers." in text
    why = text.split("**Why:**")[1]
    assert "E-077" in why and "@H1-P2" in why and why.count("E-001") == 1


def test_duplicate_and_colliding_ids_are_renumbered(tmp_path):
    other = write(tmp_path, CLEAN.replace("S1-E2", "S1-E7"), "ChangesCSA_Test_Section1_Other.md")
    f = write(tmp_path, CLEAN.replace("S1-E2", "S1-E1"))
    res = af.autofix(f, write=True)
    ids = [x["message"] for x in res["fixes"] if x["code"] == "DUPLICATE_ID"]
    assert len(ids) == 2
    text = f.read_text(encoding="utf-8")
    assert "### S1-E8 - " in text and "### S1-E9 - " in text and "### S1-E1 - " not in text
    assert other.read_text(encoding="utf-8").count("S1-E7") >= 1
    assert not [x for x in check(f, anchors=False, lint=False)["findings"] if x["code"] == "DUPLICATE_ID"]


def test_dry_run_changes_nothing(tmp_path):
    bad = CLEAN.replace("> The hosts take", "> **The** hosts take")
    f = write(tmp_path, bad)
    res = af.autofix(f, write=False)
    assert res["status"] == "WOULD_FIX" and f.read_text(encoding="utf-8") == bad


def test_currently_added_when_the_id_resolves(tmp_path, monkeypatch):
    from csa_docx import tools
    monkeypatch.setattr(tools, "lookupStableId", lambda sid, workspace=".": {
        "status": "OK", "unique_id": sid, "matches": [{"id": sid, "text": 'The "hosts" use a local time source and more'}]})
    bad = CLEAN.replace(' -- currently: "The hosts use a local time source."', "")
    f = write(tmp_path, bad)
    res = af.autofix(f, workspace=str(tmp_path), write=True)
    assert [x["code"] for x in res["fixes"]] == ["NO_CURRENTLY"]
    assert "-- currently: \"The 'hosts' use a local time source and more\"" in f.read_text(encoding="utf-8")
