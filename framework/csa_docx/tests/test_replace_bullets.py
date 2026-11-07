from csa_docx import answer_sheet as A


def _card():
    return {"key": "X", "questions": [{"id": "B1", "kind": "findings", "part": 0, "text": "x"}], "ratings": []}


def _node(bullets):
    pids = [f"@H5.6-P{i}" for i in range(1, len(bullets) + 1)]
    return {"title": "Example", "hid": "@H5.6",
            "parts": [{"kind": "findings", "pids": pids, "bullets": bullets, "facet": "Example"}]}


def _sheet(n):
    b = {"facts": [{"text": f"Fact {i}.", "ids": ["E-001"], "basis": "observed", "scope": ""} for i in range(n)],
         "bullets": [f"Bullet {i}." for i in range(n)], "unknown": [], "keep": "", "rating": "", "rating_reason": "",
         "none": "", "search": "", "answer": ""}
    return {"B1": b}


def test_rerun_replaces_old_bullets_and_removes_the_excess():
    old = ["Old text.", "Old text two.", "Old three.", "Old four."]
    r = A.render_records(_sheet(2), _card(), _node(old), "5", 1, replace_bullets=True)
    assert len(r["records"]) == 4 and r["scaffold"] == []
    assert sum("**Do:** Delete" in x for x in r["records"]) == 2
    assert sum("**Do:** Replace" in x for x in r["records"]) == 2


def test_default_keeps_filled_bullets():
    r = A.render_records(_sheet(2), _card(), _node(["Standard text.", "[Finding]"]), "5", 1)
    assert len(r["records"]) == 1


def test_more_bullets_than_holders_scaffolds_to_the_new_total():
    r = A.render_records(_sheet(3), _card(), _node(["Old."]), "5", 1, replace_bullets=True)
    assert r["scaffold"][0]["set_count"] == 3


def test_excess_bullets_are_deleted_last_first():
    old = ["A.", "B.", "C.", "D.", "E."]
    r = A.render_records(_sheet(2), _card(), _node(old), "5", 1, replace_bullets=True)
    deletes = [x.split("`")[1] for x in r["records"] if "**Do:** Delete" in x]
    assert deletes == ["@H5.6-P5", "@H5.6-P4", "@H5.6-P3"]
