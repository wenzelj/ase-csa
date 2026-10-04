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
    mutating: bool = False
    output: Literal["json_or_text"] = "json_or_text"
    timeout_seconds: int
    lock: Literal["none", "docx"] = "none"


JobState = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]


class JobCreateRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=80)
    target: str | None = Field(default=None, max_length=160)
    options: dict[str, str | bool] = Field(default_factory=dict)


class JobRecord(BaseModel):
    id: str
    project_key: str
    operation: str
    display_args: list[str]
    classification: Literal["read_only", "mutating"]
    lock: str
    state: JobState
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    message: str | None = None


class PipelineIssue(BaseModel):
    code: str
    message: str
    section: str | None = None


class PipelineDocument(BaseModel):
    path: str | None = None
    name: str | None = None
    size: int | None = None
    modified_at: str | None = None


class WordSectionReview(BaseModel):
    number: str
    heading: str
    change_count: int
    comment_count: int
    status: str  # "pending" | "decided" | "has_comments"
    last_activity: str | None = None


class WordReview(BaseModel):
    document: str
    modified_at: str | None
    section_count: int
    pending_count: int
    comment_count: int
    sections: list[WordSectionReview]
    generated_at: str


class PipelineSection(BaseModel):
    visible_number: str
    stable_key: str
    stable_path: str | None = None
    heading: str
    lane: Literal["revise", "build", "unknown"]
    change_file: str | None = None
    section_file: str | None = None
    validation_result: str = "unknown"
    applied_state: str = "unknown"
    review_verdict: str = "unknown"
    cleanup_state: str = "unknown"
    open_comments: int = 0
    last_activity: str | None = None
    issues: list[PipelineIssue] = Field(default_factory=list)


class PipelineSnapshot(BaseModel):
    project_key: str
    project_label: str
    spec_mode: str
    document: PipelineDocument
    word_locked: bool
    word_lock_file: str | None = None
    next_action: dict[str, Any] | None = None
    sections: list[PipelineSection]
    issues: list[PipelineIssue] = Field(default_factory=list)
    etag: str
