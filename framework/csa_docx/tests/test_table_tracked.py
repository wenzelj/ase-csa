"""S64: table-cell edits are tracked changes when track_changes is on."""
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from csa_docx import tools

AGENTS = Path(__file__).resolve().parents[3]
TEMPLATES = sorted((AGENTS.parent / "CSA Template").glob("CSA_Template_v*.dotx"))
NEW_CSA = AGENTS / "skills" / "csa-document-template" / "scripts" / "new_csa.py"

CHANGES = """# Changes CSA Check Section 3

**Section:** 3
**Status:** Approved for implementation.

### S3-E1 - Time Synchronisation: SEP-TIME-01

**Where:** @H3.4-T1-R2
**Do:** Replace
**Text:**
> Observed: Hosts take time from two enterprise servers.
> Assessment: Not Met

**Why:** E-001

### S3-E2 - Time Synchronisation: Discovery Information 1

**Where:** @H3.4.1-T1-R2
**Do:** Replace
**Text:**
> Time source | Two enterprise time servers | All captured hosts

**Why:** E-001
"""


def _document(tmp_path, track, part="word/document.xml"):
    if not TEMPLATES or not NEW_CSA.is_file():
        pytest.skip("CSA template or new_csa.py not available")
    ws = tmp_path / "workspace"
    (ws / "CSA Template").mkdir(parents=True)
    (ws / "CSA Template" / TEMPLATES[-1].name).write_bytes(TEMPLATES[-1].read_bytes())
    out = "01 Current State AS Built/01 Final Version/Current State Assessment - Check System.docx"
    subprocess.run([sys.executable, str(NEW_CSA), "--workspace", str(ws), "--system-name", "Check System", "--out", out],
                   check=True, capture_output=True)
    reviews = ws / "01 Current State AS Built" / "01 Final Version" / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "ChangesCSA_Check_Section3.md").write_text(CHANGES, encoding="utf-8")
    assert tools.prepareDocument(workspace=ws)["status"] == "READY"
    result = tools.apply_next_batch("3", 10, workspace=ws, track_changes=track)
    assert result["status"] == "SECTION_COMPLETE", result
    with zipfile.ZipFile(ws / out) as z:
        if part == "*":
            return {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith((".xml", ".rels"))}
        return z.read(part).decode("utf-8")


def _row(xml, needle):
    i = xml.find(needle)
    assert i > 0, needle
    start = xml.rfind("<w:tr", 0, i)
    return re.findall(r"<w:tc>.*?</w:tc>", xml[start:xml.find("</w:tr>", i)], re.S)


def _accept_all(fragment):
    fragment = re.sub(r"<w:del [^>]*>.*?</w:del>", "", fragment, flags=re.S)
    fragment = re.sub(r"</?w:ins[ >][^>]*>|</w:ins>", "", fragment)
    return "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", fragment))


def test_table_cell_edits_are_tracked_changes_when_track_changes_is_on(tmp_path):
    xml = _document(tmp_path, track=True)
    req = _row(xml, "Hosts take time from two")
    current_state, rating = req[2], req[3]
    for cell in (current_state, rating):
        assert "<w:ins " in cell and "<w:del " in cell
    assert _accept_all(current_state) == "Hosts take time from two enterprise servers."
    assert _accept_all(rating) == "Not Met"
    # The rating goes inside the dropdown and is no longer shown as its placeholder.
    sdt_content = re.search(r"<w:sdtContent>(.*?)</w:sdtContent>", rating, re.S).group(1)
    assert "<w:ins " in sdt_content and "showingPlcHdr" not in rating
    assert "PlaceholderText" not in re.search(r"<w:ins .*?</w:ins>", rating, re.S).group(0)
    disc = _row(xml, "Two enterprise time servers")
    assert [_accept_all(c) for c in disc] == ["Time source", "Two enterprise time servers", "All captured hosts"]
    assert all("<w:ins " in c for c in disc)


def test_table_cell_edits_stay_untracked_when_track_changes_is_off(tmp_path):
    xml = _document(tmp_path, track=False)
    for cell in _row(xml, "Two enterprise time servers"):
        assert "<w:ins " not in cell and "<w:del " not in cell


def test_table_edits_keep_the_package_valid(tmp_path):
    """Regression (27 Sep 2026): the table-comment path round-tripped parts through
    ElementTree, dropping namespace declarations still named in mc:Ignorable and
    writing ns0: prefixes into [Content_Types].xml and .rels. Word and LibreOffice
    then refuse the file."""
    parts = _document(tmp_path, track=True, part="*")
    for name in ("[Content_Types].xml", "word/_rels/document.xml.rels"):
        assert "ns0:" not in parts[name] and re.search(r'<(Types|Relationships) xmlns="', parts[name]), name
    for name, xml in parts.items():
        root = re.search(r"<(?!\?)[^>]+>", xml).group(0)
        ignorable = re.search(r':Ignorable="([^"]*)"', root)
        if ignorable:
            for prefix in ignorable.group(1).split():
                assert f"xmlns:{prefix}=" in root, f"{name}: mc:Ignorable names undeclared prefix {prefix}"
