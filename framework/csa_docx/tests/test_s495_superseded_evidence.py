"""S495: the card offers the newest capture's rows first, lists older ones under 'superseded' with the newer row's ID,
and the answer check warns when a block cites a superseded row without its newer one."""
import csv

from csa_docx import answer_sheet as A
from csa_docx import evidence_live, section_card as S

COLS = ["evidence_id", "csa_area", "question", "claim", "status", "source_title", "source_version", "section", "page_or_location",
        "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state"]


def row(i, claim, source):
    return {c: "" for c in COLS} | {"evidence_id": i, "status": "VERIFIED", "csa_area": "time synchronisation", "section": "",
                                     "claim": claim, "source_title": source, "review_state": "reviewed", "question": "q"}


OLD = row("E-081", "Every host is at stratum 4", "discovery_HOST1_20260605T010000Z/03_time_status.txt")
NEW = row("E-3173", "Source stratum 5 for most hosts", "discovery_HOST1_20261029T010000Z/03_time_status.txt")
OTHER = row("E-090", "Jump host polls at 32768 s", "discovery_HOST2_20260605T010000Z/05_other.txt")


def project(tmp_path):
    work = tmp_path / "csa-work"
    work.mkdir(exist_ok=True)
    with open(work / "evidence-matrix.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows([OLD, NEW, OTHER])
    return tmp_path


def pack(tmp_path, monkeypatch):
    ws = project(tmp_path)
    monkeypatch.setattr(S, "_matrix", lambda w, q, limit=8: [dict(r, score=0.9) for r in evidence_live.read(ws / "csa-work" / "evidence-matrix.csv")])
    node = {"title": "Time Synchronisation", "number": "3.4", "key": "TIME"}
    return S.evidence_pack(node, [{"id": "B1", "kind": "requirement", "text": "how is time kept"}], ws)["B1"]


def test_older_row_is_marked_and_newer_comes_first(tmp_path, monkeypatch):
    p = pack(tmp_path, monkeypatch)
    ids = [r["id"] for r in p["rows"]]
    assert ids.index("E-3173") < ids.index("E-081")
    old = next(r for r in p["rows"] if r["id"] == "E-081")
    assert old["superseded_by"] == ["E-3173"]
    assert "superseded_by" not in next(r for r in p["rows"] if r["id"] == "E-3173")
    assert "superseded_by" not in next(r for r in p["rows"] if r["id"] == "E-090")   # a different host and capture file
    assert p["superseded"] == {"E-081": ["E-3173"]}


def warns(tmp_path, monkeypatch, ids):
    p = pack(tmp_path, monkeypatch)
    m = A.load_matrix(tmp_path / "csa-work" / "evidence-matrix.csv")
    card = {"questions": [{"id": "B1", "kind": "requirement", "text": "x"}], "evidence": {"B1": p}}
    text = "## B1 x\nFacts:\n- A fact. (" + ", ".join(ids) + ") {observed}\nRating: Met\nRating reason: r\n"
    res = A.validate(A.parse(text), card, m, relaxed=True)
    return [f for f in res["findings"] if f["code"] == "SUPERSEDED_EVIDENCE"]


def test_citing_the_older_row_alone_warns(tmp_path, monkeypatch):
    got = warns(tmp_path, monkeypatch, ["E-081"])
    assert len(got) == 1 and got[0]["level"] == "WARN" and "E-3173" in got[0]["message"]


def test_citing_both_or_the_newer_does_not_warn(tmp_path, monkeypatch):
    assert not warns(tmp_path, monkeypatch, ["E-081", "E-3173"])
    assert not warns(tmp_path, monkeypatch, ["E-3173"])
