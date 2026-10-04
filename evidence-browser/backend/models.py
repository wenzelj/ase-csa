from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    target: str | None = Field(default=None, max_length=160)
    options: dict[str, str | bool] = Field(default_factory=dict)


class CommandResult(BaseModel):
    correlation_id: str
    operation: str
    project_key: str
    classification: Literal["read_only"] = "read_only"
    started_at: str
    finished_at: str
    duration_ms: int
    exit_code: int
    stdout: str
    stderr: str
    parsed: Any | None = None
    parsed_json: bool = False


class CommandDescriptor(BaseModel):
    key: str
    title: str
    description: str
    target: Literal["none", "optional", "required"]
    options: dict[str, Literal["boolean", "identifier"]]
    mutating: Literal[False] = False
    output: Literal["json_or_text"] = "json_or_text"
    timeout_seconds: int
    lock: Literal["none"] = "none"

