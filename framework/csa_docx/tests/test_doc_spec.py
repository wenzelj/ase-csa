"""The document spec: kinds from structure, identity from stamps, questions from the document (S237-S243)."""
import os
import sys
from pathlib import Path

try:
    import pytest
except ImportError:          # the story checks run these tests without pytest
    pytest = None


def _skip(msg: str):
    if pytest:
        pytest.skip(msg)
    raise RuntimeError(msg)


def _fixture(**kw):
    return pytest.fixture(**kw) if pytest else (lambda f: f)

from csa_docx import answer_sheet, doc_spec, doc_stamp, section_card, spec_cli
sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_fixtures as fx  # noqa: E402


def _template() -> Path:
    t = os.environ.get("CSA_TEST_TEMPLATE")
    p = Path(t) if t else spec_cli.find_template(None)
    if not p or not p.is_file():
        _skip("no CSA template available")
    return p


@_fixture(scope="module")
def stamped(tmp_path_factory):
    d = tmp_path_factory.mktemp("spec")
    src = fx.unstamp(_template(), d / "plain.dotx")
    pl = doc_stamp.plan(doc_spec.read(src), None, confirm=True)
    out = d / "stamped.dotx"
    doc_stamp.stamp_file(src, out, pl["stamp"])
    return out


def test_every_part_of_the_template_is_classified_by_structure():
    spec = doc_spec.read(_template())
    by_num = {n["number"]: n for n in spec["nodes"]}
    domains = [n for n in spec["nodes"] if n["kind"] == "requirement-block"]
    assert len([n for n in spec["nodes"] if n["level"] == 1]) == 8
    assert len(domains) == 17
    assert all(n["key_from"] in ("requirement family", "stamp") for n in domains)
    assert by_num["3.4"]["key"] == "TIME"
    kinds = lambda num: [p["kind"] for p in by_num[num]["parts"]]  # noqa: E731
    assert kinds("3.4") == ["requirement", "observation", "note", "narrative"]
    assert "register" in kinds("3.1") and "register" in kinds("3.2")
    for num in ("5.1", "5.2", "5.4", "5.5", "8"):
        assert "register" in kinds(num), num
    assert by_num["2.1"]["kind"] == "narrative" and kinds("2.1").count("narrative") == 3
    assert by_num["5.3"]["kind"] == "findings" and by_num["5.6"]["kind"] == "findings"
    assert by_num["6"]["kind"] == "reference" and by_num["7"]["kind"] == "reference"
    assert spec["ratings"] == ["Met", "Partially Met", "Not Met", "Not Applicable"]
    assert doc_spec.lint(spec) == []


def test_ids_match_the_stable_id_manifest_scheme():
    spec = doc_spec.read(_template())
    t = doc_spec.resolve(spec, "TIME")
    assert t["parts"][0]["table"] == "@H3.4-T1" and t["parts"][0]["requirements"][0]["row"] == 2
    assert t["parts"][1]["table"] == "@H3.4.1-T1" and t["parts"][3]["pid"] == "@H3.4.2-P1"
    es = doc_spec.resolve(spec, "Executive Summary")
    assert [p["pid"] for p in es["parts"]] == ["@H2.1-P1", "@H2.1-P2", "@H2.1-P3"]


def test_resolve_by_number_heading_family_and_key():
    spec = doc_spec.read(_template())
    for target in ("3.4", "Time Synchronisation", "TIME", "time", "_csa_TIME"):
        assert doc_spec.resolve(spec, target)["number"] == "3.4", target
    assert doc_spec.resolve(spec, "3.4.1")["number"] == "3.4"
    try:
        doc_spec.resolve(spec, "9.9")
        raise AssertionError("9.9 must not resolve")
    except doc_spec.ResolveError:
        pass


def test_stamps_survive_a_new_section_inserted_above(stamped, tmp_path):
    out = fx.insert_block(stamped, tmp_path / "inserted.dotx", copy_of="Time Synchronisation",
                          before="Identity &amp; Authentication", title="OT Remote Access",
                          req_id="SEP-RA-01", req_text="Remote access to OT shall use OT-resident jump hosts.",
                          old_req="SEP-TIME-01")
    spec = doc_spec.read(out)
    ident = doc_spec.resolve(spec, "ID")
    assert ident["number"] == "3.3" and ident["key_from"] == "stamp"
    new = doc_spec.resolve(spec, "OT Remote Access")
    assert new["number"] == "3.2" and new["key"] == "RA" and new["stamp"] is None
    assert [r["id"] for r in new["parts"][0]["requirements"]] == ["SEP-RA-01"]
    b = section_card.brief_markdown(new, spec)
    assert "SEP-RA-01" in b and "Remote access to OT shall use OT-resident jump hosts" in b
    old = section_card.brief_markdown(doc_spec.resolve(doc_spec.read(stamped), "ID"), doc_spec.read(stamped))
    assert section_card.brief_markdown(ident, spec) == old
    pl = doc_stamp.plan(spec, doc_spec.read(stamped))
    assert pl["stamp"] == {"3.2": "RA"} and not pl["ask"]


def test_a_renamed_heading_keeps_its_stamp(stamped, tmp_path):
    out = fx.rename_heading(stamped, tmp_path / "renamed.dotx", "Patch and Update Tooling", "Software Update Tooling")
    n = doc_spec.resolve(doc_spec.read(out), "Software Update Tooling")
    assert n["key"] == "PATCH_UPDATE_TOOLING" and n["key_from"] == "stamp"


def test_unstamped_rename_is_not_guessed(tmp_path):
    plain = fx.unstamp(_template(), tmp_path / "plain.dotx")
    out = fx.rename_heading(plain, tmp_path / "renamed.dotx", "Patch and Update Tooling", "Software Update Tooling")
    pl = doc_stamp.plan(doc_spec.read(out), doc_spec.read(plain))
    assert any(a["title"] == "Software Update Tooling" for a in pl["ask"])
    assert "5.4" not in pl["stamp"]


def test_a_removed_section_is_reported(stamped, tmp_path):
    out = fx.remove_block(stamped, tmp_path / "removed.dotx", "Supply Chain &amp; Third-Party / Vendor Access")
    joined = doc_spec.join(doc_spec.read(out), doc_spec.read(stamped))
    assert [r["key"] for r in joined["removed"]] == ["SUPPLY"]


def test_a_duplicate_stamp_stops(stamped, tmp_path):
    out = fx.copy_block_with_stamp(stamped, tmp_path / "copied.dotx", "DNS", "Network / Segmentation")
    codes = {f["code"] for f in doc_spec.lint(doc_spec.read(out))}
    assert "DUPLICATE_KEY" in codes and "REQ_ID_TWICE" in codes


def test_a_section_with_no_fillable_content_is_flagged(tmp_path):
    out = fx.add_empty_heading(_template(), tmp_path / "empty.dotx", "Something Else", "DNS")
    codes = {f["code"] for f in doc_spec.lint(doc_spec.read(out))}
    assert "NO_REQUIREMENT_TABLE" in codes


def test_template_guidance_is_inherited_by_every_domain():
    spec = doc_spec.read(_template())
    rules = section_card.rules(doc_spec.resolve(spec, "DNS"), spec)
    assert any("Req ID and Requirement are the OT35 checklist text" in r for r in rules)
    assert any(r.startswith("Drawbridge Impact:") for r in rules)
    assert not any("passwords" in r for r in rules)
    assert any("passwords" in r for r in section_card.rules(doc_spec.resolve(spec, "ID"), spec))


def test_card_and_answer_sheet_round_trip():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "TIME")
    card = section_card.card(node, spec, None, evidence=False)
    assert [q["kind"] for q in card["questions"]] == ["requirement", "observation", "narrative"]
    card["evidence"] = {"B1": {"rows": [{"id": "E-1"}, {"id": "E-2"}]}}
    sheet = answer_sheet.parse("""## B1 SEP-TIME-01
Facts:
- Every host uses the enterprise time servers. (E-1) {observed; all hosts}
Rating: Not Met
Rating reason: no OT-resident source.

## B2 Discovery Information
Rows:
| Aspect | Configuration Observed | Coverage / Source |
| Time source | Enterprise servers | all hosts (E-1) |

## B3 Drawbridge Impact
Facts:
- Hosts run on their own clocks when isolated. (E-2) {observed; all hosts}
""")
    res = answer_sheet.validate(sheet, card, {"E-1": {"claim": "x"}, "E-2": {"claim": "y"}})
    assert res["status"] == "OK", res
    out = answer_sheet.render_change_file(sheet, card, node, spec, app="T", docx_name="t.docx", section="3", start=1,
                                          brief=section_card.brief_markdown(node, spec))
    t = out["text"]
    assert "**Where:** `@H3.4-T1-R2`" in t and "> Assessment: Not Met" in t and "`@H3.4.1-T1-R2`" in t
    assert "`@H3.4.2-P1`" in t and "> Time source | Enterprise servers | all hosts" in t
    assert "E-1" not in t.split("**Text:**")[2].split("**Why:**")[0]


def test_answer_sheet_rules():
    spec = doc_spec.read(_template())
    node = doc_spec.resolve(spec, "TIME")
    card = section_card.card(node, spec, None, evidence=False)
    card["evidence"] = {"B1": {"rows": [{"id": "E-1"}]}}
    bad = answer_sheet.parse("""## B1
Facts:
- HOSTX0001 uses NTP. (E-9) {guessed; HOSTX0001}
Rating: Gap
## B2
Rows:
| Aspect | Value |
| a | b |
""")
    codes = {f["code"] for f in answer_sheet.validate(bad, card, {"E-1": {"claim": "x"}, "E-9": {"claim": "y"}})["findings"]}
    assert {"BAD_BASIS", "EVIDENCE_NOT_ON_CARD", "SCOPE_OUTSIDE_EVIDENCE", "RATING_INVALID", "RATING_NO_REASON",
            "COLUMNS", "QUESTION_MISSING"} <= codes
    need = answer_sheet.validate(answer_sheet.parse("## B1\nSearch: w32tm fallback\n## B2\nUnknown: x\n## B3\nUnknown: y\n"), card)
    assert need["status"] == "NEEDS_SEARCH" and need["searches"] == {"B1": ["w32tm fallback"]}
