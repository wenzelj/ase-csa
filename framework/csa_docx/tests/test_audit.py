"""Document audit, scripted stage: structure, requirement rows and domain checks on synthetic units."""
from csa_docx.audit import check_domains, check_requirements, check_structure


def H(level, text, path):
    return {"kind": "heading", "level": level, "text": text, "path": path + [text]}


def R(cells, row, path):
    return {"kind": "row", "cells": cells, "row": row, "path": path}


def P(text, path):
    return {"kind": "para", "text": text, "path": path}


def test_structure_flags_wrong_level_and_parent():
    u = [H(1, "3 Domains", []), H(2, "3.6 Network", ["3 Domains"]), H(3, "3.4.1 Discovery Information", ["3 Domains", "3.6 Network"]),
         H(2, "3.5.2 Drawbridge Impact", ["3 Domains"])]
    issues = {i["issue"] for i in check_structure(u)}
    assert {"NUMBER_PARENT", "NUMBER_LEVEL"} <= issues


def test_requirements_missing_empty_and_bad_rating():
    path = ["3 Domains", "3.4 Time"]
    u = [R(["Req ID", "Requirement", "Current State", "Rating"], 0, path),
         R(["SEP-TIME-01", "x", "", "Mostly"], 1, path)]
    res = check_requirements(u, ["SEP-TIME-01", "SEP-DNS-01"])
    assert res["missing"] == ["SEP-DNS-01"]
    assert set(res["rows"][0]["issues"]) == {"Current State empty", "rating 'Mostly' not a standard value"}


def test_domain_prose_is_not_missing_but_table_only_is():
    top = ["3 Domains"]
    u = [H(2, "3.8 Management & Administrative Access", top), R(["Req ID", "Requirement", "Current State", "Rating"], 0, top + ["3.8 Management & Administrative Access"]),
         P("Admin access uses RDP.", top + ["3.8 Management & Administrative Access"]),
         H(3, "3.8.1 Drawbridge Impact", top + ["3.8 Management & Administrative Access"]),
         H(2, "3.14 Vulnerability Management", top), R(["Req ID", "Requirement", "Current State", "Rating"], 0, top + ["3.14 Vulnerability Management"])]
    out = {d["domain"]: d for d in check_domains(u, [{"number": "3.8", "heading": "Management & Administrative Access"},
                                                      {"number": "3.14", "heading": "Vulnerability Management"}])}
    assert out["3.8 Management & Administrative Access"]["missing_subsections"] == []
    assert set(out["3.14 Vulnerability Management"]["missing_subsections"]) == {"Drawbridge Impact", "Discovery Information"}
