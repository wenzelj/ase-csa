import csv
from pathlib import Path

from csa_docx import legacy_map


def _blocks(*items):
    return [{"id": f"L-{i:04d}", "path": path.split(" > "), "kind": "para", "text": text}
            for i, (path, text) in enumerate(items, 1)]


def test_default_map_uses_current_migration_section_numbers(monkeypatch):
    monkeypatch.setenv("CSA_SPEC_MODE", "off")
    rows = legacy_map.map_blocks(_blocks(
        ("System Assessment Overview > Assessment Approach and Evidence > Discovery Activity", "Discovery was performed on five hosts."),
        ("Architectural Review > Observed > Confirmed > Installed RMS and related Software", "GeoSCADA is installed."),
        ("Patch and Update Tooling", "Configuration Manager deploys updates."),
        ("Group Policy Observations", "The policy applies to the hosts."),
        ("File Transfer and Local Storage", "A local share is used."),
    ))
    assert [r["target"] for r in rows] == ["4.1", "4.2", "4.4", "4.5", "4.6"]


def test_network_specialist_headings_route_to_313_and_317(monkeypatch):
    monkeypatch.setenv("CSA_SPEC_MODE", "off")
    rules = legacy_map.load_rules(legacy_map.DEFAULT_MAP)
    rows = legacy_map.map_blocks(_blocks(
        ("Network > Perimeter", "Firewall and NAT configuration was not supplied."),
        ("Network > Proxy and Internet Access", "WinHTTP and public destinations were observed."),
    ), default_rules=rules)
    assert [r["target"] for r in rows] == ["3.13", "3.17"]


def test_specific_default_exception_beats_broad_project_section_rule(monkeypatch):
    monkeypatch.setenv("CSA_SPEC_MODE", "off")
    project = [{"row": 1, "pattern": __import__("re").compile(r"^Network Segmentation", __import__("re").I),
                "target": "3.6", "job": "convert", "note": ""}]
    rows = legacy_map.map_blocks(_blocks(
        ("Network Segmentation, Perimeter & Internet Access > Observed > Confirmed > Proxy and Internet Access", "Public destinations were observed."),
        ("Network Segmentation, Perimeter & Internet Access > Observed > Confirmed > Network Segmentation and F5 Access", "F5 access was observed."),
    ), project_rules=project)
    assert [r["target"] for r in rows] == ["3.17", "3.6"]


def test_project_rule_can_override_a_default_for_nested_group_policy(monkeypatch):
    monkeypatch.setenv("CSA_SPEC_MODE", "off")
    project = [{"row": 1, "pattern": __import__("re").compile(r"^Identity.*Group Policy", __import__("re").I),
                "target": "4.5", "job": "convert", "note": ""}]
    rows = legacy_map.map_blocks(_blocks(
        ("Identity & Access Management > Observed > Group Policy", "The policy applies to the hosts."),
    ), project_rules=project)
    assert rows[0]["target"] == "4.5"


def test_missing_targets_are_reported():
    rows = [{"job": "convert", "target": "3.6"}, {"job": "skip", "target": ""}]
    assert legacy_map.missing_targets(rows, ["3.6", "3.13", "3.17", "4.1"]) == ["3.13", "3.17", "4.1"]
