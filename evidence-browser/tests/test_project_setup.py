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
    assert values["lane"] == "revise"
    assert values["stage"] == "draft"
    assert values["registry"]["assessment_lane"] == "revise"
    assert values["registry"]["stage"] == "draft"
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


def test_destination_must_be_directly_under_workspace(tmp_path):
    for destination in (tmp_path.parent / "outside-app", tmp_path / "group" / "new-app"):
        result = project_setup.preview_project_setup(
            _payload(destination=str(destination)),
            agents_dir=tmp_path / ".agents", base_dir=tmp_path)
        assert result["status"] == "BLOCKED"
        assert any(e["code"] == "DESTINATION_OUTSIDE_WORKSPACE" for e in result["errors"])


def test_build_lane_requires_template_and_output(tmp_path):
    root = tmp_path / "new-app"
    missing = project_setup.preview_project_setup(
        _payload(destination=str(root), lane="build"),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert {e["code"] for e in missing["errors"]} >= {"TEMPLATE_REQUIRED", "OUTPUT_REQUIRED"}
    template = tmp_path / "template.dotx"
    template.write_bytes(b"template")
    ready = project_setup.preview_project_setup(
        _payload(destination=str(root), lane="build", template_docx=str(template),
                 build_output_docx=str(root / "assessment.docx")),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert ready["status"] == "READY", ready["errors"]
    assert ready["values"]["registry"]["assessment_lane"] == "build"
    assert ready["values"]["registry"]["build_output_docx"] == str(root / "assessment.docx")


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


def test_application_skills_render_at_context_top_level(tmp_path):
    text = project_setup._context_file_text({
        "application": "New Application", "application_skills": ["new-app-skill"]})
    assert "\napplication_skills: [\"new-app-skill\"]\n" in text
    assert "  application_skills:" not in text


def test_nested_knowledge_setting_keeps_full_relative_path(tmp_path):
    root = tmp_path / "new-app"
    result = project_setup.preview_project_setup(
        _payload(destination=str(root), knowledge=str(root / "reference" / "00 Knowlege")),
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "READY"
    assert result["values"]["registry"]["knowledge_dir"] == "reference/00 Knowlege"


def test_bad_key_shape_is_blocked(tmp_path):
    result = project_setup.preview_project_setup(
        {"key": "New App!", "label": "New Application", "destination": str(tmp_path / "new-app")},
        agents_dir=tmp_path / ".agents", base_dir=tmp_path)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_KEY" for e in result["errors"])


# ---------------------------------------------------------------------------
# S514: atomic project registration (commit_project_setup)
# ---------------------------------------------------------------------------

def _setup_agents(tmp_path, extra_projects=""):
    """A throwaway framework: agents dir with a registry and a template file."""
    agents = tmp_path / ".agents"
    context = agents / "csa-context"
    templates = agents / "csa-templates"
    context.mkdir(parents=True)
    templates.mkdir(parents=True)
    templates.joinpath("PROJECT_CONTEXT_TEMPLATE.yaml").write_text(
        "project:\n  assessment_name: \"\"\n  assessment_type: \"Current State Assessment\"\n",
        encoding="utf-8")
    context.joinpath("PROJECTS.yaml").write_text(
        "projects:\n"
        "  - key: existing-app\n"
        "    label: \"Existing Application\"\n"
        f"    project_root: \"{tmp_path / 'existing-app'}\"\n"
        "    work_dir: \"\"\n"
        "    default_source_set: \"\"\n"
        + extra_projects,
        encoding="utf-8")
    return agents


def _staged_session(tmp_path, staging_root=None, files=None, dirs=None):
    """Create and finalise a valid upload session; return (staging_root, session_id)."""
    import json
    import backend.project_upload as up
    staging_root = Path(staging_root) if staging_root else tmp_path / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, data in (files or {}).items():
        manifest.append({"path": name, "kind": "file", "size": len(data)})
    for name in dirs or []:
        manifest.append({"path": name, "kind": "dir"})
    created = up.create_session(manifest, staging_root=staging_root)
    assert created["status"] == "READY", created
    sid = created["session_id"]
    for name, data in (files or {}).items():
        result = up.write_file(sid, name, data, staging_root=staging_root)
        assert result["status"] == "OK", result
    for name in dirs or []:
        (staging_root / sid / name).mkdir(parents=True, exist_ok=True)
    final = up.finalise(sid, staging_root=staging_root)
    assert final["status"] == "READY", final
    return staging_root, sid


def _payload(key="new-app", label="New Application", **overrides):
    payload = {"key": key, "label": label, "application": label,
               "destination": "new-app",
               "context": {"program": "OT Migration Program", "environment": "AZNOPS"}}
    payload.update(overrides)
    return payload


def test_commit_registers_the_project(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(
        tmp_path, files={"notes/readme.txt": b"hello\n", "notes/deep/spec.md": b"spec\n"},
        dirs={"notes/deep", "empty-folder"})
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "READY", result
    root = tmp_path / "new-app"
    # the uploaded tree moved into place, content unchanged
    assert (root / "notes" / "readme.txt").read_bytes() == b"hello\n"
    assert (root / "notes" / "deep" / "spec.md").read_bytes() == b"spec\n"
    assert (root / "empty-folder").is_dir()
    # framework folders created
    assert (root / "csa-work").is_dir()
    assert (root / "Discovery").is_dir()
    assert (root / "00 Knowlege").is_dir()
    # no index, no DOCX anywhere under the project
    assert not (root / "csa-work" / "discovery-index.sqlite").exists()
    assert [p for p in root.rglob("*.docx")] == []
    # context file written from the template fields
    context_file = agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml"
    assert context_file.is_file()
    text = context_file.read_text(encoding="utf-8")
    assert "assessment_type" in text and "Current State Assessment" in text
    assert "program: \"OT Migration Program\"" in text
    # registry gained the entry, preserved the existing project
    registry = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert "- key: existing-app" in registry
    assert "- key: \"new-app\"" in registry
    assert "label: \"Existing Application\"" in registry
    assert "knowledge_dir: \"00 Knowlege\"" in registry
    assert "default_source_set" in registry and "Discovery" in registry
    # the staging area is gone (it was moved), and the session is marked committed
    assert not (staging_root / sid).exists()
    import json
    sessions = json.loads((staging_root / "sessions.json").read_text(encoding="utf-8"))
    assert sessions[sid]["status"] == "committed"


def test_commit_writes_knowledge_sources_json_when_selected(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"docs/ref.pdf": b"PDFDATA"})
    knowledge = {"about": "Background knowledge for New Application only. Not evidence of the current state.",
                 "documents": [{"file": "docs/ref.pdf", "title": "Reference", "type": "vendor"}],
                 "system_terms": ["NewApp"]}
    result = project_setup.commit_project_setup(
        _payload(knowledge_sources=knowledge), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "READY", result
    sources = json.loads((tmp_path / "new-app" / "00 Knowlege" / "sources.json").read_text(encoding="utf-8"))
    assert sources["documents"] == knowledge["documents"]
    assert sources["system_terms"] == knowledge["system_terms"]
    assert sources["about"] == knowledge["about"]


def test_commit_without_knowledge_writes_no_sources_json(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "READY"
    assert not (tmp_path / "new-app" / "00 Knowlege" / "sources.json").exists()


def test_commit_preserves_optional_registry_fields(tmp_path):
    agents = _setup_agents(tmp_path)
    shared = tmp_path / "shared-template.docx"
    shared.write_bytes(b"DOCX")
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(estate="corp.example", sites="ROK=Rockhampton,MKY=Mackay",
                 spec_mode="on", lane="revise", stage="v1", template_docx=str(shared)),
        agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "READY", result
    registry = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert "estate: \"corp.example\"" in registry
    assert "sites: \"ROK=Rockhampton,MKY=Mackay\"" in registry
    assert "spec_mode: \"on\"" in registry
    assert "stage: \"v1\"" in registry
    assert f"template_docx: \"{shared}\"" in registry


def test_commit_refuses_an_existing_destination(tmp_path):
    agents = _setup_agents(tmp_path)
    (tmp_path / "new-app").mkdir()
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DESTINATION_EXISTS" for e in result["errors"])
    # nothing registered, staging still recoverable
    registry = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert "- key: \"new-app\"" not in registry
    assert not (agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").exists()
    assert (staging_root / sid / "notes" / "readme.txt").exists()
    assert result["staging"]["recoverable"] is True


def test_commit_refuses_an_existing_key(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(key="existing-app"), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "DUPLICATE_KEY" for e in result["errors"])
    assert not (tmp_path / "existing-app").exists()
    assert not (agents / "csa-context" / "EXISTING_APP_PROJECT_CONTEXT.yaml").exists()


def test_commit_refuses_an_existing_context_file(tmp_path):
    agents = _setup_agents(tmp_path)
    (agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").write_text("project:\n  x: 1\n",
                                                                        encoding="utf-8")
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "CONTEXT_EXISTS" for e in result["errors"])
    assert (agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").read_text(encoding="utf-8") == "project:\n  x: 1\n"
    assert not (tmp_path / "new-app").exists()


def test_commit_refuses_a_destination_overlapping_an_existing_project(tmp_path):
    agents = _setup_agents(tmp_path, extra_projects=(
        "\n  - key: other-app\n"
        f"    project_root: \"{tmp_path / 'other-app' / 'inner'}\"\n"))
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        _payload(destination=str(tmp_path / "other-app")),
        agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] in ("DESTINATION_CONFLICTS", "DESTINATION_EXISTS") for e in result["errors"])
    assert not (tmp_path / "other-app" / "inner").exists() or not (tmp_path / "other-app" / "csa-work").exists()


def test_commit_rejects_an_invalid_configuration(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    result = project_setup.commit_project_setup(
        {"key": "Bad Key!", "label": "New Application", "destination": str(tmp_path / "new-app")},
        agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "BAD_KEY" for e in result["errors"])
    assert (staging_root / sid / "notes" / "readme.txt").exists()


def test_commit_rejects_a_staged_tree_that_does_not_match_the_manifest(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"hello\n"})
    # someone tampered with the staging area after finalise
    (staging_root / sid / "notes" / "stray.txt").write_bytes(b"surprise")
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "UNEXPECTED_FILE" for e in result["errors"])
    assert not (tmp_path / "new-app").exists()
    assert (staging_root / sid / "notes" / "stray.txt").exists()


def test_commit_rolls_back_when_the_context_write_fails(tmp_path, monkeypatch):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    original_write = Path.write_text

    def broken_write(self, *args, **kwargs):
        if self.name == "NEW_APP_PROJECT_CONTEXT.yaml":
            raise OSError("disk full")
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", broken_write)
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert result["status"] == "ERROR", result
    assert any(e["code"] == "COMMIT_FAILED" for e in result["errors"])
    # rollback: the moved tree is gone, the context file is gone, the registry
    # is byte-for-byte what it was before the commit started
    original = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert "- key: \"new-app\"" not in original
    assert "- key: existing-app" in original
    assert not (tmp_path / "new-app").exists()
    assert not (agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").exists()
    assert not list((agents / "csa-context").glob("PROJECTS.yaml.commit-*.bak"))
    # the failure is recoverable: the caller can cancel or retry
    assert result["staging"]["recoverable"] is True


def test_commit_is_atomic_under_concurrent_attempts(tmp_path):
    import threading
    import json as _json
    agents = _setup_agents(tmp_path)
    staging_a, sid_a = _staged_session(tmp_path / "a", files={"notes/readme.txt": b"one\n"})
    staging_b, sid_b = _staged_session(tmp_path / "b", files={"notes/readme.txt": b"two\n"})
    lock = threading.Barrier(2)
    results = []

    def attempt(staging_root, session_id):
        lock.wait()
        results.append(project_setup.commit_project_setup(
            _payload(), agents_dir=agents, base_dir=tmp_path,
            staging_root=staging_root, session_id=session_id))

    threads = [threading.Thread(target=attempt, args=(staging_a, sid_a)),
               threading.Thread(target=attempt, args=(staging_b, sid_b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(r["status"] for r in results)
    assert statuses == ["BLOCKED", "READY"], results
    ready = next(r for r in results if r["status"] == "READY")
    assert (Path(ready["project_root"]) / "notes" / "readme.txt").exists()
    registry = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert registry.count("- key: \"new-app\"") == 1
    assert (agents / "csa-context" / "NEW_APP_PROJECT_CONTEXT.yaml").exists()
    # exactly one registry entry was appended (the other attempt wrote nothing)
    assert "- key: existing-app" in registry


def test_cancel_commit_discards_the_staged_session(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    cancelled = project_setup.cancel_commit(sid, agents_dir=agents, staging_root=staging_root)
    assert cancelled["status"] == "OK" and cancelled["cancelled"] is True
    assert not (staging_root / sid).exists()
    assert not (tmp_path / "new-app").exists()
    # cancelling again is a no-op
    again = project_setup.cancel_commit(sid, agents_dir=agents, staging_root=staging_root)
    assert again["status"] == "OK" and again["cancelled"] is True


def test_cancel_commit_refuses_a_committed_session(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    committed = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert committed["status"] == "READY"
    refused = project_setup.cancel_commit(sid, agents_dir=agents, staging_root=staging_root)
    assert refused["status"] == "BLOCKED"
    assert any(e["code"] == "ALREADY_COMMITTED" for e in refused["errors"])
    # the registered project is untouched
    assert (tmp_path / "new-app" / "notes" / "readme.txt").exists()
    assert "- key: \"new-app\"" in (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")


def test_re_commit_of_the_same_session_is_refused(tmp_path):
    agents = _setup_agents(tmp_path)
    staging_root, sid = _staged_session(tmp_path, files={"notes/readme.txt": b"x"})
    first = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert first["status"] == "READY"
    second = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=staging_root, session_id=sid)
    assert second["status"] == "BLOCKED"
    assert any(e["code"] == "ALREADY_COMMITTED" for e in second["errors"])
    registry = (agents / "csa-context" / "PROJECTS.yaml").read_text(encoding="utf-8")
    assert registry.count("- key: \"new-app\"") == 1


def test_commit_reports_an_unknown_session_as_not_recoverable(tmp_path):
    agents = _setup_agents(tmp_path)
    result = project_setup.commit_project_setup(
        _payload(), agents_dir=agents, base_dir=tmp_path,
        staging_root=tmp_path / "staging", session_id="0" * 32)
    assert result["status"] == "BLOCKED"
    assert any(e["code"] == "UNKNOWN_SESSION" for e in result["errors"])
    assert result["staging"]["recoverable"] is False
    assert not (tmp_path / "new-app").exists()
