import json
from csa_docx import evidence_stale as ES


def test_a_sheet_citing_a_superseded_row_is_listed_with_the_row_that_replaces_it(tmp_path):
    (tmp_path / "cards").mkdir()
    head = "evidence_id,csa_area,question,claim,status,source_title,review_state\n"
    (tmp_path / "evidence-matrix.csv").write_text(
        head + "E-1,a,What does H run?,old,VERIFIED,REVELOC_discovery_HOSTAAA111_2026_old,pending\n"
               "E-2,a,What does H run?,new,VERIFIED,REVELOC_discovery_HOSTAAA111_2026_new,reviewed\n", encoding="utf-8")
    (tmp_path / "evidence-reviews.jsonl").write_text(
        json.dumps({"evidence_id": "E-1", "state": "rejected", "note": "superseded: HOSTAAA111 has a newer capture"}) + "\n"
        + json.dumps({"evidence_id": "E-2", "state": "reviewed", "note": "ok"}) + "\n", encoding="utf-8")
    (tmp_path / "cards" / "K.answer.md").write_text("- H runs x. (E-1, E-2) {observed; H}\n", encoding="utf-8")
    got = ES.stale_rows(tmp_path)
    assert list(got) == ["K"] and got["K"][0]["id"] == "E-1" and got["K"][0]["replacements"] == ["E-2"]
