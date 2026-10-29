"""Only verified evidence is in the list: VERIFIED, and proven (the source check found the excerpt in the cited source, or a named
person reviewed it). A rejected row, an unchecked row and a NOT_FOUND, CONFLICTING or UNCONFIRMED row are not."""
import csv
import json

from csa_docx import answer_sheet as A
from csa_docx import evidence_live, matrix_candidates as MC, section_card as S, topic_frames as T

COLS = ["evidence_id", "csa_area", "question", "claim", "status", "source_title", "source_version", "section", "page_or_location",
        "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state"]


def row(i, status="VERIFIED", area="storage and data transfer", claim=None):
    return {c: "" for c in COLS} | {"evidence_id": i, "status": status, "csa_area": area, "section": "",
                                     "claim": claim or f"verified storage fact {i}", "review_state": "pending", "question": "q"}


ROWS = [row("E-1"), row("E-2"), row("E-3"), row("E-4", "NOT_FOUND", "discovery_required", "No evidence answers: x"),
        row("E-5", "CONFLICTING"), row("E-6"), row("E-7", "UNCONFIRMED")]
REVIEWS = [("E-1", "reviewed", "excerpt found in cited source: x.txt"), ("E-2", "reviewed", "named review"),
           ("E-3", "rejected", "retired"), ("E-4", "reviewed", "named review"), ("E-5", "reviewed", "named review")]


def project(tmp_path, with_reviews=True):
    work = tmp_path / "csa-work"
    work.mkdir(exist_ok=True)
    with open(work / "evidence-matrix.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(ROWS)
    if with_reviews:
        (work / "evidence-reviews.jsonl").write_text("\n".join(json.dumps(
            {"evidence_id": i, "state": s, "by": "t", "at": "2026-10-28", "note": n}) for i, s, n in REVIEWS) + "\n", encoding="utf-8")
    return tmp_path


def test_verified_means_verified_and_proven():
    ok = {**row("E-1"), "review_state": "reviewed"}
    assert evidence_live.is_verified(ok)
    assert not evidence_live.is_verified({**ok, "review_state": "rejected"})
    assert not evidence_live.is_verified({**ok, "review_state": "pending"})        # VERIFIED, nobody has checked it
    for status in ("NOT_FOUND", "CONFLICTING", "UNCONFIRMED", "INFERRED"):
        assert not evidence_live.is_verified({**ok, "status": status})


def test_get_verified_evidence_returns_only_verified_rows_and_all_rows_for_a_project_never_reviewed(tmp_path):
    ws = project(tmp_path)
    assert [r["evidence_id"] for r in evidence_live.get_verified_evidence(ws / "csa-work" / "evidence-matrix.csv")] == ["E-1", "E-2"]
    bare = tmp_path / "bare"
    bare.mkdir()
    ws2 = project(bare, with_reviews=False)
    assert len(evidence_live.get_verified_evidence(ws2 / "csa-work" / "evidence-matrix.csv")) == 7


def test_the_cards_reader_is_that_function(tmp_path):
    ws = project(tmp_path)
    assert [r["evidence_id"] for r in S._matrix_rows(ws)] == ["E-1", "E-2"]


def test_the_pack_offers_and_names_only_verified_rows(tmp_path, monkeypatch):
    ws = project(tmp_path)
    monkeypatch.setattr(S, "_matrix", lambda w, q, limit=8: [dict(r, score=0.9) for r in evidence_live.read(ws / "csa-work" / "evidence-matrix.csv")])
    node = {"title": "Storage and Data Transfer", "number": "3.7", "key": "STOR"}
    pack = S.evidence_pack(node, [{"id": "B1", "kind": "requirement", "text": "where is storage held"}], ws)
    assert {r["id"] for r in pack["B1"]["rows"]} | set(pack["B1"]["cut"]) == {"E-1", "E-2"}


def test_a_frame_finding_keeps_only_verified_ids(tmp_path):
    ws = project(tmp_path)
    res = {"slots": [{"findings": [{"ids": ["E-1", "E-3", "E-4", "E-6"]}, {"ids": ["E-4"]}]}]}
    T._verified_ids_only(ws / "csa-work", res)
    assert [f["ids"] for f in res["slots"][0]["findings"]] == [["E-1"]]         # the finding with no verified row is not shown


def test_the_validator_cannot_see_an_unverified_row_so_citing_one_is_unknown_evidence(tmp_path):
    m = A.load_matrix(project(tmp_path) / "csa-work" / "evidence-matrix.csv")
    assert set(m) == {"E-1", "E-2"}
    card = {"questions": [{"id": "B1", "kind": "requirement", "text": "x"}], "evidence": {}}
    text = "## B1 x\nFacts:\n- A fact. (E-4) {observed}\nRating: Met\nRating reason: r\n"
    res = A.validate(A.parse(text), card, m, draft=True, relaxed=True)
    assert "UNKNOWN_EVIDENCE" in {f["code"] for f in res["findings"]}
    assert "UNKNOWN_EVIDENCE" in A.FATAL_CODES


def test_there_is_no_separate_verified_rule_any_more():
    assert not hasattr(A, "FACT_NOT_VERIFIED")
    import inspect
    assert "FACT_NOT_VERIFIED" not in inspect.getsource(A) and "FACT_CITES_UNVERIFIED" not in inspect.getsource(A)
