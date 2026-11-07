"""Another estate project's evidence is citable as <project>:E-nnn, as context only."""
import csv

import pytest

from csa_docx import answer_sheet as A
from csa_docx import fact_checks

HDR = ["evidence_id", "csa_area", "question", "claim", "status", "source_title", "source_version", "section",
       "page_or_location", "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state"]


def _matrix(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HDR, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


@pytest.fixture()
def two(tmp_path, monkeypatch):
    lines = ["projects:"]
    for key in ("mine", "peer", "alone"):
        wd = tmp_path / key / "csa-work"
        wd.mkdir(parents=True)
        lines += [f"  - key: {key}", f'    label: "{key}"', f'    project_root: "{tmp_path / key}"', f'    work_dir: "{wd}"']
        if key != "alone":
            lines.append('    estate: "corp.test"')
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    _matrix(tmp_path / "mine" / "csa-work" / "evidence-matrix.csv", [
        {"evidence_id": "E-001", "question": "Which DNS servers is HOSTMINE01 configured to use?",
         "claim": "HOSTMINE01 is configured to resolve names through DNS1 first.", "status": "VERIFIED"}])
    _matrix(tmp_path / "peer" / "csa-work" / "evidence-matrix.csv", [
        {"evidence_id": "E-001", "question": "Which ports does HOSTPEER01 listen on?", "claim": "HOSTPEER01 listens on 6050.",
         "status": "VERIFIED"},
        {"evidence_id": "E-002", "question": "Which DNS servers is HOSTPEER01 configured to use?",
         "claim": "HOSTPEER01 is configured to resolve names through DNS1 first.", "status": "VERIFIED"}])
    _matrix(tmp_path / "alone" / "csa-work" / "evidence-matrix.csv", [
        {"evidence_id": "E-009", "question": "x", "claim": "y", "status": "VERIFIED"}])
    return tmp_path


def _card():
    rows = [{"id": "E-001", "status": "VERIFIED", "claim": "", "note": ""},
            {"id": "peer:E-002", "status": "VERIFIED", "claim": "", "note": ""}]
    return {"key": "DNS", "ratings": ["Met", "Partially Met", "Not Met", "Not Applicable"],
            "questions": [{"id": "B1", "kind": "requirement", "req_id": "SEP-DNS-01", "text": "?"},
                          {"id": "B2", "kind": "observation", "columns": ["Aspect", "Configuration Observed", "Coverage / Source"], "text": "?"},
                          {"id": "B3", "kind": "narrative", "text": "?"}],
            "evidence": {q: {"rows": rows} for q in ("B1", "B2", "B3")}}


OWN = "- HOSTMINE01 resolves names through DNS1 first. (E-001) {observed; HOSTMINE01}"
PEER = "- HOSTPEER01 resolves names through the same server. (peer:E-002) {observed; peer: HOSTPEER01}"
ROW_OWN = "| Resolver | DNS1 first | HOSTMINE01 (E-001) |"


def _sheet(b1=OWN, row=ROW_OWN, b3=OWN + "\n" + PEER):
    return A.parse(f"## B1 SEP-DNS-01\nFacts:\n{b1}\nRating: Not Met\nRating reason: no OT resolver.\n\n"
                   f"## B2 Discovery Information\nRows:\n| Aspect | Configuration Observed | Coverage / Source |\n{row}\n\n"
                   f"## B3 Drawbridge Impact\nFacts:\n{b3}\n")


def _codes(res):
    return {f["code"] for f in res["findings"] if f["level"] == "ERROR"}


def _m(tmp):
    return A.load_matrix(tmp / "mine" / "csa-work" / "evidence-matrix.csv")


def test_the_matrix_holds_own_rows_bare_and_peer_rows_prefixed(two):
    m = _m(two)
    assert m["E-001"]["question"].startswith("Which DNS servers is HOSTMINE01")
    assert m["PEER:E-001"]["question"].startswith("Which ports")
    assert not any(k.startswith("ALONE:") for k in m)
    assert "peer:E-002" in fact_checks.load_matrix(two / "mine" / "csa-work" / "evidence-matrix.csv")


def test_a_scoped_peer_fact_in_a_narrative_is_accepted(two):
    res = A.validate(_sheet(), _card(), _m(two))
    assert res["status"] == "OK", res["findings"]


def test_a_current_state_on_peer_evidence_only_is_refused_even_in_the_draft_lane(two):
    assert "CROSS_PROJECT_ONLY" in _codes(A.validate(_sheet(b1=PEER), _card(), _m(two), draft=True))


def test_a_table_row_on_peer_evidence_only_is_refused(two):
    row = "| Resolver | DNS1 first | HOSTPEER01 (peer:E-002) |"
    assert "CROSS_PROJECT_ONLY" in _codes(A.validate(_sheet(row=row), _card(), _m(two)))


def test_a_peer_fact_must_name_the_project_in_its_scope(two):
    bad = PEER.replace("{observed; peer: HOSTPEER01}", "{observed; HOSTPEER01}")
    assert "CROSS_PROJECT_SCOPE" in _codes(A.validate(_sheet(b3=OWN + "\n" + bad), _card(), _m(two)))


def test_an_unknown_prefix_is_unknown_evidence(two):
    bad = "- Something. (nobody:E-001) {observed; nobody: X}"
    assert "UNKNOWN_EVIDENCE" in _codes(A.validate(_sheet(b3=OWN + "\n" + bad), _card(), _m(two)))


def test_no_ids_strips_prefixed_ids_whole():
    assert A.no_ids("The peer hosts use it (peer:E-002).") == "The peer hosts use it."
    assert A.no_ids("pair peer:E-002, E-001 here") == "pair here"
    assert A.no_ids("hosts [E-043, E-097]") == "hosts"
