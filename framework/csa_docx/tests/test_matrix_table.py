import csv

from csa_docx import host_settings as H
from csa_docx import topic_tables as T


def _work(tmp_path, applied, not_applied=None):
    (tmp_path / "hosts").mkdir()
    with (tmp_path / "hosts" / "hosts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "role", "site", "in_scope", "capture"])
        for h, role in (("H1", "Log Server, DAAM"), ("H2", "Log Server, DAAM"), ("H3", "Jump Host")):
            w.writerow([h, role, "A", "yes", "x"])
    with (tmp_path / "hosts" / "host_settings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=H.FIELDS)
        w.writeheader()
        for h, v in applied.items():
            w.writerow({"host": h, "topic": "group_policy", "attribute": "gpo.applied", "value": v})
        for h, v in (not_applied or {}).items():
            w.writerow({"host": h, "topic": "group_policy", "attribute": "gpo.not_applied", "value": v})
    return tmp_path


PROFILE = {"kind": "matrix", "attribute": "gpo.applied", "attribute_not": "gpo.not_applied", "key": "GPO", "columns": []}


def test_matrix_has_a_row_per_name_that_differs_and_a_sentence_for_the_rest(tmp_path):
    w = _work(tmp_path, {"H1": "Base, Log GPO", "H2": "Base, Log GPO", "H3": "Base, Jump GPO"}, {"H3": "Audit GPO"})
    t = T.build_matrix(w, "Group Policy Observations", "", PROFILE)
    assert t["columns"] == ["Group Policy object", "Jump Host", "Log Server"]
    got = {r["role"]: r["cells"] for r in t["rows"]}
    assert got == {"Jump GPO": ["●", ""], "Log GPO": ["", "●"], "Audit GPO": ["○", ""]}
    assert t["common"] == "Applied by all 3 hosts: Base."


def test_a_name_on_some_hosts_of_a_role_group_shows_a_fraction_and_a_note(tmp_path):
    w = _work(tmp_path, {"H1": "Base, Log GPO", "H2": "Base", "H3": "Base"})
    t = T.build_matrix(w, "Group Policy Observations", "", PROFILE)
    assert t["rows"][0]["cells"] == ["", "1/2"]
    assert any("H1" in m and "not on H2" in m for m in t["markers"])


def test_matrix_xml_has_vertical_headings_and_one_row_per_name(tmp_path):
    w = _work(tmp_path, {"H1": "Base, Log GPO", "H2": "Base, Log GPO", "H3": "Base, Jump GPO"})
    t = T.build_matrix(w, "Group Policy Observations", "", PROFILE)
    ref = '<w:tbl><w:tblPr><w:tblStyle w:val="CSATable"/></w:tblPr><w:tblGrid><w:gridCol w:w="9000"/></w:tblGrid><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>'
    xml = T.matrix_xml(t, ref)
    assert xml.count("btLr") == 2 and xml.count("<w:tr>") == 3
