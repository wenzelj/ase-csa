"""Register each test's temporary workspace as a CSA project.

The framework refuses to work on a workspace that is not listed in
csa-context/PROJECTS.yaml (WORKSPACE_NOT_REGISTERED). The tests build their
workspace under tmp_path / "workspace", so every test gets a one-project
registry pointing there, through the CSA_PROJECTS_FILE override.
"""
import pytest


@pytest.fixture(autouse=True)
def _register_test_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    registry = tmp_path / "PROJECTS.yaml"
    registry.write_text(
        "projects:\n"
        "  - key: test\n"
        '    label: "Test"\n'
        f'    project_root: "{workspace}"\n'
        '    project_context: ""\n'
        f'    work_dir: "{workspace / "csa-work"}"\n'
        '    default_source_set: ""\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(registry))


@pytest.fixture(autouse=True)
def _comments_on_by_default(monkeypatch):
    """Word comments can be switched off in .agents/cli.yaml. Pin them on so the tests
    do not depend on that setting; the comments-off behaviour has its own test."""
    monkeypatch.setenv("CSA_COMMENTS", "on")
