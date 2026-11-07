import json

from pathlib import Path

from backend import project_setup


def _payload(**overrides):
    payload = {
        "key": "new-app",
        "label": "New Application",
        "destination": str(tmp_destination()),
    }
    payload.update(overrides)
    return payload


def tmp_destination():
    return Path("/tmp/csastory-newapp")


def test_defaults_for_minimal_payload(tmp_path):
    result = project_setup.preview_project_setup(
        {"key": "new-app", "label": "New Application", "destination": str(tmp_path / "new-app")},
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["errors"] == []
    root = tmp_path / "new-app"
    values = result["values"]
    assert values["paths"] == {
        "project_root": str(root),
        "discovery": str(root / "Discovery"),
        "knowledge": str(root / "00 Knowlege"),
        "work_dir": str(root / "csa-work"),
    }
    assert values["registry"]["key"] == "new-app"
    assert values["registry"]["label"] == "New Application"
    assert values["registry"]["project_root"] == str(root)
    assert values["registry"]["project_context"] == str(tmp_path / ".agents" / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml")
    assert values["registry"]["work_dir"] == str(root / "csa-work")
    assert values["registry"]["default_source_set"] == str(root / "Discovery")
    assert values["knowledge"] == {"documents": [], "system_terms": []}
    assert values["lane"] == "build"
    assert values["stage"] == "draft"
    assert values["spec_mode"] == "off"
    assert values["project_context"]["assessment_type"] == "Current State Assessment"
    assert values["project_context"]["required_deliverables"] == ["detailed_current_state_assessment", "consumable_summary"]
    # nothing was written anywhere
    assert not (tmp_path / "new-app").exists()
    assert not (tmp_path / ".agents" / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").exists()


def test_explicit_discovery_and_knowledge_defaults_are_exact(tmp_path):
    root = tmp_path / "root"
    result = project_setup.preview_project_setup(
        {"key": "new-app", "label": "New Application", "destination": str(root),
         "discovery": str(root / "Discovery"), "knowledge": str(root / "00 Knowlege")},
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["paths"]["discovery"] == str(root / "Discovery")
    assert result["values"]["paths"]["knowledge"] == str(root / "00 Knowlege")


def test_duplicate_key_is_blocked(tmp_path):
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app")),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path,
        existing_keys=["new-app"])
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DUPLICATE_KEY" and e["field"] == "key" for e in result["errors"])


def test_existing_destination_is_blocked(tmp_path):
    destination = tmp_path / "taken"
    destination.mkdir()
    result = project_setup.preview_project_setup(
        _payload(destination=str(destination)),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DESTINATION_EXISTS" for e in result["errors"])


def test_destination_conflicting_an_existing_project_is_blocked(tmp_path):
    existing = tmp_path / "existing-app"
    result = project_setup.preview_project_setup(
        _payload(destination=str(existing)),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path,
        existing_project_roots=[str(existing)])
    assert result["status"] == "BLOCKED"
    assert any(e["code"] in ("DESTINATION_EXISTS", "DESTINATION_CONFLICTS") for e in result["errors"])


def test_blank_required_identity_is_blocked(tmp_path):
    result = project_setup.preview_project_setup(
        {"key": "   ", "label": "", "destination": str(tmp_path / "new-app")},
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    codes = {(e["field"], e["code"]) for e in result["errors"]}
    assert ("key", "BLANK_KEY") in codes
    assert ("label", "BLANK_LABEL") in codes


def test_traversal_paths_outside_the_new_root_are_blocked(tmp_path):
    outside = tmp_path / "elsewhere"
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"),
                 discovery=str(outside),
                 knowledge=str(outside / "know")),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    outside_fields = [e["field"] for e in result["errors"] if e["code"] == "PATH_OUTSIDE_ROOT"]
    assert "discovery" in outside_fields
    assert "knowledge" in outside_fields


def test_relative_paths_resolve_against_the_base_dir(tmp_path):
    root = tmp_path / "new-app"
    result = project_setup.preview_project_setup(
        _payload(destination="new-app", discovery="new-app/Discovery"),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["paths"]["discovery"] == str(root / "Discovery")


def test_template_and_legacy_paths_may_live_outside_the_root(tmp_path):
    shared = tmp_path / "shared-template.docx"
    legacy = tmp_path / "archive" / "old-csa.docx"
    root = tmp_path / "new-app"
    result = project_setup.preview_project_setup(
        _payload(destination=str(root), template_docx=str(shared), legacy_docx=str(legacy)),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["registry"]["template_docx"] == str(shared)
    assert result["values"]["registry"]["legacy_docx"] == str(legacy)


def test_optional_fields_and_defaults(tmp_path):
    root = tmp_path / "new-app"
    result = project_setup.preview_project_setup(
        _payload(destination=str(root), estate="corp.example", sites="ROK=Rockhampton,MKY=Mackay",
                 spec_mode="on", lane="revise", stage="v1"),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    registry = result["values"]["registry"]
    assert registry["estate"] == "corp.example"
    assert registry["sites"] == "ROK=Rockhampton,MKY=Mackay"
    assert registry["spec_mode"] == "on"
    assert registry["stage"] == "v1"
    assert result["values"]["lane"] == "revise"
    assert result["values"]["stage"] == "v1"
    assert result["values"]["spec_mode"] == "on"


def test_invalid_optional_fields_are_blocked(tmp_path):
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"), sites="ROK=Rockhampton, BAD ENTRY",
                 spec_mode="always", lane="rebuild"),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    codes = {(e["field"], e["code"]) for e in result["errors"]}
    assert ("sites", "BAD_SITES") in codes
    assert ("spec_mode", "BAD_SPEC_MODE") in codes
    assert ("lane", "BAD_LANE") in codes


def test_knowledge_sources_metadata_is_returned_verbatim(tmp_path):
    sources = {"about": "Background knowledge for New Application only. Not evidence of the current state.",
               "documents": [{"file": "vendor/product-reference.pdf", "title": "Product Reference",
                             "publisher": "Vendor", "licence": "CC BY 4.0", "type": "vendor"}],
               "system_terms": ["NewApp", "SiteOne"]}
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"), knowledge_sources=sources),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["knowledge"]["documents"] == sources["documents"]
    assert result["values"]["knowledge"]["system_terms"] == sources["system_terms"]
    assert result["values"]["knowledge"]["about"] == sources["about"]


def test_knowledge_sources_json_string_and_bad_json(tmp_path):
    good = json.dumps({"documents": [{"file": "a.pdf"}], "system_terms": ["Term"]})
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"), knowledge_sources=good),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["knowledge"]["documents"] == [{"file": "a.pdf"}]

    bad = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"), knowledge_sources="{not json"),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert bad["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_JSON" for e in bad["errors"])

    non_dict = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"), knowledge_sources=[1, 2]),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert non_dict["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_SHAPE" for e in non_dict["errors"])


def test_context_fields_override_defaults_and_unknown_fields_are_rejected(tmp_path):
    result = project_setup.preview_project_setup(
        _payload(destination=str(tmp_path / "new-app"),
                 application="New Application",
                 context={"program": "OT 3.5 Migration Program", "environment": "AZNOPS",
                          "stakeholders": ["owner"], "not_a_field": "x"}),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "UNKNOWN_FIELD" for e in result["errors"])
    context = result["values"]["project_context"]
    assert context["program"] == "OT 3.5 Migration Program"
    assert context["environment"] == "AZNOPS"
    assert context["stakeholders"] == ["owner"]
    assert context["application"] == "New Application"
    # untouched template defaults are preserved exactly
    assert context["assessment_type"] == "Current State Assessment"
    assert context["scope_in"] == []


def test_bad_key_shape_is_blocked(tmp_path):
    result = project_setup.preview_project_setup(
        {"key": "New App!", "label": "New Application", "destination": str(tmp_path / "new-app")},
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_KEY" for e in result["errors"])
