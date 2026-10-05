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
    mutation_class: Literal["read_only", "workspace_write", "document_write"] = "read_only"
    output: Literal["json_or_text"] = "json_or_text"
    timeout_seconds: int
    lock: Literal["none", "section", "docx"] = "none"


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
    classification: Literal["read_only", "workspace_write", "document_write"]
    lock: str
    resource: str | None = None
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


class ReviewBreakingChange(BaseModel):
    area: str = "none"
    detail: str = ""


class ReviewSectionBreakdown(BaseModel):
    key: str = ""
    heading: str = ""
    verdict: str = "unknown"
    findings: list[str] = Field(default_factory=list)
    breaking: bool = False


class ReviewFinding(BaseModel):
    id: str = ""
    area: str = "content"
    severity: str = "info"
    detail: str = ""


class ReviewReport(BaseModel):
    project_key: str
    section: str
    job_id: str
    state: str
    review_signoff: ReviewSectionBreakdown | None = None
    breaking: ReviewBreakingChange = Field(default_factory=ReviewBreakingChange)
    section_breakdown: list[ReviewSectionBreakdown] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    report_path: str | None = None
    generated_at: str


class AuthorPreflight(BaseModel):
    section: str
    stable_key: str
    lane: str = "revise"
    cards: bool = False
    no_apply: bool = True
    document_hash: str
    input_hash: str
    existing_proposal: dict[str, Any] = Field(default_factory=dict)
    prior_author_jobs: int = 0


class AuthorOutcomeSummary(BaseModel):
    state: str
    section: str
    lane: str = "revise"
    current: bool = False
    input_hash: str = ""
    document_hash: str = ""
    proposal: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    stages: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    routed_to_editor: bool = False
    routed_to_validation: bool = False
    warnings: list[str] = Field(default_factory=list)
    non_success_reasons: list[str] = Field(default_factory=list)
    actual_route: Literal["cards", "legacy"] = "cards"
    writer_policy: Literal["auto", "force", "skip"] = "auto"
    cache_status: Literal["NONE", "REUSE", "PARTIAL", "STALE"] = "NONE"
    question_decisions: list[dict[str, Any]] = Field(default_factory=list)
    established_facts: list[dict[str, Any]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)
    autofixes: list[dict[str, Any]] = Field(default_factory=list)
    writer_decision: dict[str, Any] = Field(default_factory=dict)
    run_metrics: dict[str, Any] = Field(default_factory=dict)
    rules_digest: dict[str, Any] = Field(default_factory=dict)
    artifact_changes: list[dict[str, Any]] = Field(default_factory=list)


class CleanupGate(BaseModel):
    key: str
    required: bool
    satisfied: bool
    detail: str = ""


class CleanupPreflight(BaseModel):
    system: str
    project_key: str
    section: str
    document: str
    document_hash: str
    review_signoff: str = "unknown"
    review_signoff_satisfied: bool = False
    word_locked: bool = False
    framework_locked: bool = False
    unresolved_revisions: str = "unknown"
    unresolved_revisions_satisfied: bool = False
    gates: list[CleanupGate] = Field(default_factory=list)
    backup_destination: str | None = None
    confirmation_required: bool = True


class CleanupOutcomeSummary(BaseModel):
    state: str
    result: str = "unknown"
    backup: str | None = None
    document_hash: str | None = None
    revisions_before: int | None = None
    revisions_after: int | None = None
    accepted_revisions: int | None = None
    removed_artifacts: list[str] = Field(default_factory=list)
    retained_artifacts: list[str] = Field(default_factory=list)
    section_state: str = "unknown"
    validation: dict[str, Any] = {}
    recovery_instructions: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    raw: dict[str, Any] = {}


class BuildGate(BaseModel):
    key: str
    satisfied: bool
    detail: str = ""


class BuildSetup(BaseModel):
    lane: Literal["build"] = "build"
    project_key: str
    template: str | None = None
    template_version: str | None = None
    output: str | None = None
    document_properties: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    gates: list[BuildGate] = Field(default_factory=list)
    ready_for_preview: bool = False
    ready_for_build: bool = False


class BuildOutcome(BaseModel):
    state: str
    preview: bool = False
    document: str | None = None
    document_hash: str | None = None
    backup: str | None = None
    section_map: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    integrity: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class AuditFinding(BaseModel):
    id: str
    section: str = ""
    severity: str = "unknown"
    requirement: str = ""
    claim: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    location: str = ""
    disposition: Literal["OPEN", "PARTIAL", "CONFLICT", "NOT_FOUND", "DISCOVERY_REQUIRED", "ANSWERED"] = "OPEN"
    action: str = ""


class AuditSnapshot(BaseModel):
    state: str
    audit_id: str | None = None
    document: str | None = None
    document_hash: str | None = None
    generated_at: str | None = None
    report: str | None = None
    findings: list[AuditFinding] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


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
    assessment_lane: Literal["revise", "build"] = "revise"
    document: PipelineDocument
    word_locked: bool
    word_lock_file: str | None = None
    next_action: dict[str, Any] | None = None
    sections: list[PipelineSection]
    issues: list[PipelineIssue] = Field(default_factory=list)
    etag: str
