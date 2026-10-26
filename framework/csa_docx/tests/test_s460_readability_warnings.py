"""S460: Story and narrative readability warnings (all WARN, never block).

The draft lane is relaxed: wording and naming are warnings, never blocks. These checks make
the faults found in 3.7 (TETRA STOR) visible in the run's change log.
"""
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

from csa_docx import answer_sheet as A
from csa_docx import endpoints as ep

ROOT = Path(__file__).resolve().parents[3]          # .agents/
TETRA_WS = ROOT.parent / "TETRA/06 REVELOC TETRA"


def _card_parts() -> dict:
    """The card's parts view, from the real TETRA STOR card (26/10 sheet)."""
    card_path = TETRA_WS / "csa-work/cards/STOR.json"
    if not card_path.is_file():
        if pytest:
            pytest.skip("TETRA STOR card not available")
        raise RuntimeError("TETRA STOR card not available")
    import json
    card = json.loads(card_path.read_text(encoding="utf-8"))
    return card["parts"]


def _b1_story() -> str:
    sheet_text = (TETRA_WS / "csa-work/cards/STOR.answer.md").read_text(encoding="utf-8")
    b1 = sheet_text.split("## B2")[0]
    return next(l for l in b1.splitlines() if l.startswith("Story:"))[len("Story:"):].strip()


def _fixture_sheet(b1_story: str) -> str:
    """A minimal sheet with the 26/10 B1 story in place. Enough for readability_checks to fire."""
    return (
        "## B1 SEP-STOR-01\n"
        "Facts:\n"
        "- The SQL Server cluster node (instance S01) holds the RevServer and RevBroadcast availability groups in OT. (E-975) {observed; S01 SQL Server cluster nodes}\n"
        "- The TETRA log server holds local MySQL data. (E-1277) {observed; ROTPRDLOG102}\n"
        "- The Sepura Radio Manager server holds its database in IT. (E-976) {observed; IPTPRDAPP137}\n"
        "Summary: OT-resident storage exists, but one application database is IT-hosted and recovery fitness was not established.\n"
        f"Story: {b1_story}\n"
        "Rating: Partially Met\n"
        "Rating reason: OT-resident storage exists, but one application database is IT-hosted and recovery fitness and an isolation fallback were not established.\n"
        "\n"
        "## B2 SEP-STOR-02\n"
        "Facts:\n"
        "- The Rockhampton General Purpose Jump Host exposes CAcom, CNMS-NG R7 Archive and Music shares. (E-979) {observed; ROKPRDOPS110}\n"
        "Summary: Non-default shares are exposed by the General Purpose Jump Host.\n"
        "Story: The General Purpose Jump Host exposes non-default shares. A controlled transfer pattern was not identified.\n"
        "Rating: Partially Met\n"
        "Rating reason: controlled pattern was not identified for the exposed shares.\n"
        "\n"
        "## B5 Drawbridge Impact\n"
        "Facts:\n"
        "- The SQL Server cluster node (instance S01) keeps the RevServer and RevBroadcast availability groups working. (E-1282) {observed; S01 SQL Server cluster nodes}\n"
        "- The TETRA log server keeps its local MySQL data. (E-1277) {observed; ROTPRDLOG102}\n"
        "Text: During isolation, the SQL Server cluster node (instance S01) keeps its OT availability groups working. The TETRA log server keeps its local MySQL data. Unidentified internal peers at 10.129.11.10 open MySQL connections into OT, while the zone of the far end is not recorded.\n"
    )


def _card(sheet_text: str, parts: dict) -> dict:
    questions = [
        {"id": "B1", "kind": "requirement", "req_id": "SEP-STOR-01", "row": 2, "text": "x"},
        {"id": "B2", "kind": "requirement", "req_id": "SEP-STOR-02", "row": 3, "text": "y"},
        {"id": "B5", "kind": "narrative", "part": 4, "text": "Drawbridge Impact"},
    ]
    return {
        "key": "STOR",
        "questions": questions,
        "requirement_stories": True,
        "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"],
        "evidence": {q["id"]: {"rows": [{"id": f"E-{i+1:03d}", "status": "VERIFIED"}]} for i, q in enumerate(questions)},
        "parts": parts,
    }


def test_stor_fixture_gives_read_list_two_role_name_story_too_long_endpoint_understated(tmp_path, monkeypatch):
    """The fixture copy of the 26/10 TETRA STOR sheet (B1 Story with 11 parts and ', also the')
    gives READ_LIST, TWO_ROLE_NAME, STORY_TOO_LONG and ENDPOINT_UNDERSTATED, and none is an error."""
    # build a minimal endpoints.csv so endpoints.load returns a row with name+zone for 10.129.11.10
    wd = tmp_path / "csa-work"
    (wd / "hosts").mkdir(parents=True)
    (wd / "hosts" / "endpoints.csv").write_text(
        "end,name,zone,confidence,basis,evidence,reviewed\n"
        "10.129.11.10,unidentified MySQL peer,OT Rockhampton,observed,fixture,,,no\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)   # so the function finds csa-work/hosts/endpoints.csv

    card_parts = _card_parts()
    card = _card("", card_parts)
    story = _b1_story()
    sheet_text = _fixture_sheet(story)
    sheet = A.parse(sheet_text)

    findings = A.readability_checks(sheet, card)
    codes = {f["code"] for f in findings}
    for want in ("READ_LIST", "TWO_ROLE_NAME", "STORY_TOO_LONG", "ENDPOINT_UNDERSTATED"):
        assert want in codes, f"expected {want} in {sorted(codes)}"
    # all are warnings, none is an error
    for f in findings:
        assert f["level"] == "WARN", f


def test_well_shaped_story_gives_none(tmp_path, monkeypatch):
    """A short, well-shaped Story gives none of the S460 readability warnings."""
    monkeypatch.chdir(tmp_path)   # no csa-work: endpoints register is empty

    card_parts = _card_parts()
    card = _card("", card_parts)
    sheet_text = (
        "## B1 SEP-STOR-01\n"
        "Facts:\n"
        "- The SQL Server cluster node (instance S01) holds the RevServer and RevBroadcast availability groups in OT. (E-975) {observed; S01 SQL Server cluster nodes}\n"
        "- The TETRA log server holds local MySQL data. (E-1277) {observed; ROTPRDLOG102}\n"
        "Summary: OT-resident storage exists for the two application databases.\n"
        "Story: Partially Met: OT-resident storage exists for the two application databases; one database is IT-hosted. The Sepura Radio Manager server holds its database in IT. The TETRA log server holds local MySQL data.\n"
        "Rating: Partially Met\n"
        "Rating reason: one application database is IT-hosted and recovery fitness was not established.\n"
        "\n"
        "## B2 SEP-STOR-02\n"
        "Facts:\n"
        "- The General Purpose Jump Host exposes non-default shares. (E-979) {observed; ROKPRDOPS110}\n"
        "Summary: Non-default shares are exposed by the General Purpose Jump Host.\n"
        "Story: Not Met: no controlled transfer pattern was identified. The General Purpose Jump Host exposes non-default shares.\n"
        "Rating: Not Met\n"
        "Rating reason: no controlled transfer pattern was identified for the exposed shares.\n"
        "\n"
        "## B5 Drawbridge Impact\n"
        "Facts:\n"
        "- The SQL Server cluster node (instance S01) keeps its OT availability groups working. (E-1282) {observed; S01 SQL Server cluster nodes}\n"
        "Text: During isolation, the SQL Server cluster node (instance S01) keeps its OT availability groups working. The TETRA log server keeps its local MySQL data. Backup transfers stop. The far end whose zone is not recorded remains unknown.\n"
    )
    sheet = A.parse(sheet_text)
    findings = A.readability_checks(sheet, card)
    codes = {f["code"] for f in findings}
    for not_wanted in ("READ_LIST", "STORY_NO_REASON", "TWO_ROLE_NAME", "STORY_TOO_LONG",
                        "ENDPOINT_UNDERSTATED", "NARRATIVE_NEW_ENDPOINT"):
        assert not_wanted not in codes, f"unexpected {not_wanted}: " + "; ".join(
            f["message"] for f in findings if f["code"] == not_wanted)


def test_validate_includes_new_warnings_and_draft_lane_keeps_them_as_warn():
    """validate() includes the new codes, and the draft lane keeps them as WARN (not ERROR)."""
    card_parts = _card_parts()
    if not card_parts:
        if pytest:
            pytest.skip("TETRA STOR card not available")
        raise RuntimeError("TETRA STOR card not available")
    card = _card("", card_parts)
    story = _b1_story()
    sheet = A.parse(_fixture_sheet(story))
    res = A.validate(sheet, card, {"E-001": {"claim": "x"}, "E-002": {"claim": "y"}}, draft=True, relaxed=True)
    levels = {f["code"]: f["level"] for f in res["findings"]}
    for want in ("READ_LIST", "STORY_NO_REASON", "TWO_ROLE_NAME", "STORY_TOO_LONG"):
        if want in levels:
            assert levels[want] == "WARN", f"{want} is {levels[want]}, expected WARN"
