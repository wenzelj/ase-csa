from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import commands
from backend.models import CommandRequest


AGENTS = Path(__file__).resolve().parents[2]


def test_improve_is_a_distinct_section_scoped_workspace_operation():
    operation, argv = commands.build_argv(AGENTS, "tetra-reveloc", "improve", CommandRequest(target="3.4", options={"cli": "codex"}))
    assert operation.key == "improve"
    assert operation.lock == "section"
    assert operation.mutation_class == "workspace_write"
    assert argv[3:] == ["improve", "3.4", "--cli", "codex", "--headless"]


def test_improve_rejects_unknown_model():
    with pytest.raises(HTTPException):
        commands.build_argv(AGENTS, "tetra-reveloc", "improve", CommandRequest(target="3.4", options={"cli": "unknown"}))
