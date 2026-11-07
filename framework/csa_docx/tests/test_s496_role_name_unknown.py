"""S496: ROLE_NAME_UNKNOWN warns when a role group named in an Aspect row or story sentence is not a register role."""
from csa_docx import answer_sheet as A

ROLES = ["General Purpose Jump Host", "Domain Controller", "Application Server", "RevServer", "Historian"]
CARD = {
    "questions": [{"id": "A1", "kind": "observation", "text": "x", "columns": ["Aspect", "Finding"]},
                  {"id": "B1", "kind": "requirement", "text": "y"}],
    "host_register": {"groups": [{"role": r, "hosts": [], "sites": []} for r in ROLES], "uncaptured": []},
    "role_tables": [{"rows": [{"hosts": ["REVVIEWER01"], "cells": ["REVVIEWER01"]}]}],
}


def block(text="", rows=None):
    return {"summary": "", "text": text, "facts": [], "bullets": [], "rows": rows or []}


def found(sheet):
    return [f for f in A.role_name_checks(sheet, CARD) if f["code"] == "ROLE_NAME_UNKNOWN"]


def test_unknown_role_in_row_warns_with_suggestion():
    got = found({"A1": block(rows=[["Aspect", "Finding"], ["Sync", "RevViewer Jump Hosts poll upstream"]])})
    assert len(got) == 1 and got[0]["level"] == "WARN"
    assert "General Purpose Jump Host" in got[0]["message"]


def test_unknown_role_in_story_sentence_warns():
    assert len(found({"B1": block(text="The RevViewer Jump Hosts poll upstream.")})) == 1


def test_host_name_alone_does_not_warn():
    assert not found({"B1": block(text="RevViewer polls upstream. RevServer keeps time. REVVIEWER01 is one host.")})


def test_every_register_role_passes():
    for r in ROLES:
        for form in (r, r + "s", r + " Hosts", r + " hosts"):
            assert not found({"B1": block(text=f"The {form} poll upstream.")}), form
