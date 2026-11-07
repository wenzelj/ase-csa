from csa_docx import host_settings as H

XML = """Rsop
ComputerResults
Name INTERNAL\\\\H1$
GPO
Name {A0A31511-09ED-4256-AE7E-3F3428CBEE56}
IsValid false
FilterAllowed false
AccessDenied false
GPO
Name 2019 Prod - Baseline GPO
Path
IsValid true
FilterAllowed true
AccessDenied false
GPO
Name Filtered Out GPO
IsValid true
FilterAllowed false
AccessDenied false
ExtensionData
"""
VERBOSE = """COMPUTER SETTINGS
    Applied Group Policy Objects
    -----------------------------
        Default Trust Store
        Baseline GPO

    The following GPOs were not applied
"""


def _caps(fname, text):
    return {"gpo": {"H1": {"folder": "f", "fname": fname, "start": 1, "text": text}}}


def test_xml_gpresult_gives_applied_and_not_applied():
    rows = {r["attribute"]: r["value"] for r in H.gpo_settings(_caps("64_gpresult.xml", XML))}
    assert rows == {"gpo.applied": "2019 Prod - Baseline GPO", "gpo.not_applied": "Filtered Out GPO"}


def test_verbose_gpresult_lists_applied_objects():
    rows = {r["attribute"]: r["value"] for r in H.gpo_settings(_caps("61_gpresult_verbose.txt", VERBOSE))}
    assert rows["gpo.applied"] == "Default Trust Store, Baseline GPO"


def test_verbose_gpresult_without_the_list_proves_nothing():
    assert H.gpo_settings(_caps("61_gpresult_verbose.txt", "nothing here")) == []


def test_register_names_lists_every_applied_object(tmp_path):
    import csv
    from csa_docx import topic_frames as T
    (tmp_path / "hosts").mkdir()
    with (tmp_path / "hosts" / "host_settings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=H.FIELDS)
        w.writeheader()
        for host, val in (("H1", "A GPO, B GPO"), ("H2", "B GPO, C GPO"), ("H3", "None found")):
            w.writerow({"host": host, "topic": "group_policy", "attribute": "gpo.applied", "value": val})
    assert T.register_names(tmp_path, "gpo.applied") == ["A GPO", "B GPO", "C GPO"]
    assert T.register_names(tmp_path, "") == []
