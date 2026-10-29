"""answer_blocks: a failed check costs only the blocks that failed."""

import json

from csa_docx import answer_blocks as ab, section_card

BASE = """## B1 SEP-TIME-01
Facts:
- old b1 fact. (E-001) {observed; ROTPRDLOG102}
Text: Ten of the captured hosts take time from the enterprise.

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed | Coverage / Source |
| Time | NTP | log servers (E-001) |

## B3 Drawbridge Impact
Unknown: which functions keep working, and whether the clock holds

## F1 Analysis frame
- S1: B1
"""

PATCH = """## B1 SEP-TIME-01
Facts:
- new b1 fact. (E-001) {observed; ROTPRDLOG102}
Text: The log servers take time from the enterprise.

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed | Coverage / Source |
| CHANGED | must not be copied | x |

## B3 Drawbridge Impact
Unknown: which functions keep working during isolation
Unknown: whether the clock holds
"""


def test_merge_takes_only_requested_blocks():
    res = ab.merge_text(BASE, PATCH, {"B1", "B3"})
    _, blocks = ab.split(res["text"])
    got = dict(blocks)
    assert [b for b, _ in blocks] == ["B1", "B2", "B3", "F1"]
    assert "new b1 fact" in got["B1"] and "old b1 fact" not in got["B1"]
    assert "CHANGED" not in got["B2"]                      # a passing block is never touched
    assert got["B3"].count("Unknown:") == 2
    assert res["merged"] == ["B1", "B3"] and res["ignored"] == ["B2"] and res["missing"] == []


def test_merge_reports_missing_and_adds_new_block_before_frame():
    res = ab.merge_text(BASE, "## B4 Note\nNone: the table shows it\n", {"B4", "B1"})
    order = [b for b, _ in ab.split(res["text"])[1]]
    assert order == ["B1", "B2", "B3", "B4", "F1"]
    assert res["added"] == ["B4"] and res["missing"] == ["B1"]
    assert "old b1 fact" in res["text"]


def test_merge_normalizes_single_hash_heading_for_requested_block():
    patch = "# b1 SEP-TIME-01\nFacts:\n- repaired output. (E-001) {observed; host}\n\n# Notes\nkeep me\n"

    res = ab.merge_text(BASE, patch, {"B1"})
    got = dict(ab.split(res["text"])[1])

    assert res["merged"] == ["B1"] and res["missing"] == []
    assert res["normalized"] == ["B1"]
    assert got["B1"].startswith("## B1 SEP-TIME-01")
    assert "# Notes\nkeep me" in got["B1"]


def test_merge_does_not_normalize_unrequested_single_hash_block():
    res = ab.merge_text(BASE, "# B2 Discovery Information\nchanged\n", {"B1"})

    assert res["normalized"] == []
    assert res["missing"] == ["B1"]
    assert "changed" not in res["text"]


def test_failing_blocks():
    f = [{"level": "ERROR", "code": "NO_TOTALS", "question": "B1"},
         {"level": "ERROR", "code": "UNKNOWN_BUNDLED", "question": "B3"},
         {"level": "WARN", "code": "EVIDENCE_UNUSED", "question": "B2"}]
    assert ab.failing(f) == {"B1", "B3"}
    assert ab.failing(f + [{"level": "ERROR", "code": "FRAME_UNCOVERED", "question": None}]) == {"B1", "B3", "F1"}
    assert ab.WHOLE in ab.failing([{"level": "ERROR", "code": "NO_SHEET", "question": None}])


def test_focus_routes_question_and_evidence_pack():
    card = "# Card\n\n## Questions\n- B1 SEP-X-01: first\n  - S1: one\n- B2: second\n\n" \
           "## Analysis frame (built by the framework from the captures)\n\n### S1 First\nslot one\n\n" \
           "## Evidence pack\n\n### B1\nrow b1\n\n### B2\nrow b2\n"
    out = ab.focus(card, {"B2"})
    assert "- B2: second" in out and "- B1" not in out
    assert "row b2" in out and "row b1" not in out and "Fix round" in out


def test_focus_keeps_referenced_evidence_pack_dependency():
    card = "# Card\n\n## Questions\n- B1 SEP-X-01: first\n- B4: impact\n\n" \
           "## Evidence pack\n\n### B1\nsource rows\n\n### B4\n- Connections: shown under B1 above; may cite them.\n"
    out = ab.focus(card, {"B4"}, first_pass=True)
    assert "source rows" in out and "shown under B1" in out
    assert "- B4: impact" in out and "- B1 SEP" not in out


def test_focus_filters_routed_facts_slots_hosts_parts_and_examples():
    card = """# Card

## Questions
- B1 SEP-STOR-01: storage
  - S1: local database
  Parts these findings are about: SQL Server
- B2 SEP-STOR-02: transfer
  - S2: file shares

## Facts to keep

Keep these:

- B1: database fact (E-001)
- B2: transfer fact (E-002)

## Host register (captured hosts, grouped by role)

- SQL Server: SQL1
- Jump Host: JUMP1

Named in the sources for this system but not captured (scope to be confirmed):
- CONTROLLER1: Controller workstation

Peers seen only by address (name not captured):
- 10.0.0.1 (private): inbound

## Analysis frame (built by the framework from the captures)

### S1 Storage
SQL Server stores data

### S2 Transfer
JUMP1 moves files

## System parts (built by the framework from the host register and the flows)

### SQL Server
Hosts the database.

### Jump Host
Moves files.

## Evidence pack

### B1
- E-001 VERIFIED: SQL Server stores data.

### B2
- E-002 VERIFIED: JUMP1 moves files.

## Example answer (narrative): format only, not evidence

## B3 Drawbridge Impact
Facts:
- narrative example

## Example answer (requirement): format only, not evidence

## B1 SEP-TIME-01
Facts:
- requirement example
"""
    out = ab.focus(card, {"B1"}, first_pass=True)
    assert "database fact" in out and "transfer fact" not in out
    assert "- S1: local database" in out and "### S1 Storage" not in out and "### S2 Transfer" not in out
    assert "### SQL Server" in out and "### Jump Host" not in out
    assert "CONTROLLER1" not in out and "10.0.0.1" not in out
    assert "requirement example" in out and "narrative example" not in out
    assert ab.focus_metrics(card, out)["reduction_pct"] > 20


def test_wip_roundtrip(tmp_path):
    sheet = tmp_path / "TIME.answer.md"
    sheet.write_text(BASE, encoding="utf-8")
    fp = {"questions": {"B1": "a", "B2": "b", "B3": "c"}, "matrix": "m", "hosts": "h"}
    ab.wip_write(sheet, fp, ["B3", "B1"], ["NO_TOTALS"])
    assert json.loads(ab.wip_path(sheet).read_text())["failed"] == ["B1", "B3"]
    assert ab.wip_check(sheet, fp)["status"] == "RESUME"
    assert ab.wip_check(sheet, {**fp, "questions": {**fp["questions"], "B2": "z"}})["changed"] == ["B2"]
    assert ab.wip_check(sheet, {**fp, "hosts": "other"})["status"] == "STALE"
    ab.wip_clear(sheet)
    assert ab.wip_check(sheet, fp)["status"] == "NONE"


def test_unknown_evidence_wip_is_regenerated_from_verified_card(tmp_path):
    sheet = tmp_path / "MGT.answer.md"
    sheet.write_text(BASE, encoding="utf-8")
    fp = {"questions": {"B1": "a"}, "matrix": "m", "hosts": "h"}
    ab.wip_write(sheet, fp, ["B1"], ["UNKNOWN_EVIDENCE"])

    result = ab.wip_check(sheet, fp)

    assert result["status"] == "STALE"
    assert "not verified" in result["reason"]


def test_host_register_does_not_call_neighbour_inventory_this_system(tmp_path):
    hosts = tmp_path / "csa-work" / "hosts"
    hosts.mkdir(parents=True)
    (hosts / "hosts.csv").write_text(
        "host,in_scope,system,role,site,role_source,capture,sources\n"
        "APP1,yes,Reveloc,Application server,Rockhampton,evidence,cap1,local\n"
        "APP2,peer,Reveloc,Application server,Mackay,inventory,,local peer\n"
        "CONTROLLER1,peer,,Controller workstation,,neighbour utcdtc,,neighbour:utcdtc\n",
        encoding="utf-8",
    )
    (hosts / "roles.csv").write_text("kind,match,role,basis\n", encoding="utf-8")
    (hosts / "addresses.csv").write_text(
        "address,kind,host_count,seen_from,directions,ports,evidence_ids\n", encoding="utf-8"
    )

    register = section_card.host_register(tmp_path)

    assert [u["host"] for u in register["uncaptured"]] == ["APP2"]
    assert "CONTROLLER1" not in "\n".join(section_card._register_lines(register))
