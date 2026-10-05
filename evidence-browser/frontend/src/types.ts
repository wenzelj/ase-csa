export type PipelineIssue = { code: string; message: string; section?: string };
export type PipelineSection = {
  visible_number: string; stable_key: string; stable_path?: string; heading: string;
  lane: "revise" | "build" | "unknown"; change_file?: string; section_file?: string;
  validation_result: string; applied_state: string; review_verdict: string; cleanup_state: string;
  open_comments: number; last_activity?: string; issues: PipelineIssue[];
  evidence_count?: number; open_question_count?: number; proposed_edits?: number; next_action?: string;
};
export type PipelineSnapshot = {
  project_key: string; project_label: string; spec_mode: string; assessment_lane?: "revise" | "build";
  document: { path?: string; name?: string; size?: number; modified_at?: string };
  word_locked: boolean; word_lock_file?: string; next_action?: Record<string, unknown>;
  sections: PipelineSection[]; issues: PipelineIssue[]; etag: string;
};

export type WordSectionReview = {
  number: string; heading: string; change_count: number; comment_count: number;
  status: "pending" | "decided" | "has_comments"; last_activity?: string;
};
export type WordReview = {
  gate: "awaiting_word_save" | "word_locked" | "ready_for_review" | "blocked";
  document: string; authoritative_path: string; modified_at?: string; section_count: number;
  pending_count: number; comment_count: number; sections: WordSectionReview[]; generated_at: string;
  sha256: string; baseline_hash: string; tracked_changes: { insertions: number; deletions: number; total: number };
  word_lock?: { owner: string; file?: string; since: string } | null; reason: string; review_enabled: boolean;
  apply_job_id?: string; backup_path?: string; applied_edit_ids: string[];
};

export type ReviewJob = {
  id: string; project_key: string; operation: string; state: string;
  created_at: string; started_at?: string; finished_at?: string;
  exit_code?: number; stdout_tail?: string; stderr_tail?: string; message?: string;
  classification?: "read_only" | "workspace_write" | "document_write"; lock?: string; resource?: string | null;
};

export type ReviewOutcome = {
  state: string; review_signoff?: string;
  section_breakdown?: Record<string, unknown>[]; findings?: Record<string, unknown>[];
  breaking?: { area: string; detail: string }; report_path?: string;
  failure_reason?: string; raw?: Record<string, unknown>;
};

export type ReviewSubmit = { job: ReviewJob; section: string; document: string; document_name: string };
export type ReviewJobResponse = { job: ReviewJob; outcome: ReviewOutcome };
export type ReviewLatest = {
  job_id: string; state: string; section: string;
  created_at?: string; finished_at?: string; exit_code?: number; report_dir?: string;
};

export type AuthorArtifact = {
  key: string; label: string; exists: boolean; hash?: string | null; size?: number | null;
};
export type AuthorEvidence = {
  evidence_id: string; status: string; review_state: string; question: string; claim: string;
  source_title: string; page_or_location: string;
};
export type AuthorQuestionDecision = { question_id: string; question: string; decision: "reuse" | "regenerate"; reason: string };
export type EstablishedFact = { fact: string; origin_section: string; question_id: string; basis: string; evidence_ids: string[]; sources: { evidence_id: string; status: string; source_title: string; page_or_location: string }[]; validation_state: "valid" | "invalidated"; reuse_status: "reused" | "unavailable" };
export type AuthorSetup = {
  project_key: string; section: string; visible_number: string; stable_key: string;
  lane: string; document_hash: string; input_hash: string; no_apply: true; cards_available: boolean;
  model_route: { default: string; cards: string; legacy: string };
  supported_modes: { legacy: boolean; fresh: boolean; check_answers: boolean; writer_policies: WriterPolicy[] };
  default_route: "cards";
  selected_cards: { id: string; question: string }[];
  author_brief: AuthorArtifact; answer_sheet: AuthorArtifact; evidence: AuthorEvidence[];
  artifacts: AuthorArtifact[]; stages: { key: string; label: string; state: string }[];
  existing_proposal: { exists: boolean; file?: string | null; hash?: string | null; validation: string };
  prior_runs: number;
  cache_status: "NONE" | "REUSE" | "PARTIAL" | "STALE"; cache_reason: string;
  question_decisions: AuthorQuestionDecision[]; established_facts: EstablishedFact[];
  freshness: { status: string; fingerprint: string; reason: string };
  autofixes: { code: string; edit_id?: string | null; message: string }[];
  writer_decision: { state: string; reason: string }; run_metrics: Record<string, string | number | boolean>;
  rules_digest: { name: string; sha256: string; bytes: number };
};
export type AuthorOutcome = {
  state: string; section: string; lane: string; current: boolean; input_hash: string; document_hash: string;
  proposal: AuthorSetup["existing_proposal"]; artifacts: AuthorArtifact[];
  stages: AuthorSetup["stages"]; evidence: AuthorEvidence[];
  routed_to_editor: boolean; routed_to_validation: boolean;
  warnings: string[]; non_success_reasons: string[];
  actual_route: "cards" | "legacy"; writer_policy: WriterPolicy;
  cache_status: AuthorSetup["cache_status"]; question_decisions: AuthorQuestionDecision[];
  established_facts: EstablishedFact[]; freshness: AuthorSetup["freshness"];
  autofixes: AuthorSetup["autofixes"]; writer_decision: AuthorSetup["writer_decision"];
  run_metrics: AuthorSetup["run_metrics"]; rules_digest: AuthorSetup["rules_digest"];
  artifact_changes: { key: string; label: string; change: "created" | "modified" }[];
};
export type WriterPolicy = "auto" | "force" | "skip";
export type AuthorOptions = { legacy: boolean; fresh: boolean; check_answers: boolean; writer_policy: WriterPolicy };
export type AuthorSubmit = { job: ReviewJob; section: string; cards: true; actual_route: "cards" | "legacy"; writer_policy: WriterPolicy; no_apply: true; input_hash: string };
export type AuthorJobResponse = { job: ReviewJob; outcome: AuthorOutcome };

export type CleanupGate = { key: string; required: boolean; satisfied: boolean; detail: string };

export type CleanupPreflight = {
  system: string; project_key: string; section: string;
  document: string; document_hash: string;
  review_signoff: string; review_signoff_satisfied: boolean;
  word_locked: boolean; framework_locked: boolean;
  unresolved_revisions: string; unresolved_revisions_satisfied: boolean;
  gates: CleanupGate[]; backup_destination: string | null; confirmation_required: boolean;
};

export type CleanupSubmit = {
  job: ReviewJob; section: string; document: string; document_hash: string;
  backup_destination: string | null; preflight: CleanupPreflight;
};

export type CleanupOutcome = {
  state: string; result: "FINALISED" | "STOPPED" | "UNKNOWN";
  backup?: string | null; document_hash?: string | null;
  revisions_before?: number | null; revisions_after?: number | null;
  accepted_revisions?: number | null;
  removed_artifacts?: string[]; retained_artifacts?: string[];
  section_state: string;
  validation: Record<string, unknown>;
  recovery_instructions: string[];
  failure_reason?: string | null;
  raw?: Record<string, unknown>;
};

export type CleanupJobResponse = { job: ReviewJob; outcome: CleanupOutcome };
export type CleanupLatest = {
  job_id: string; state: string; section: string;
  created_at?: string; finished_at?: string; exit_code?: number;
};

export type AssessmentState = "not-started" | "draft" | "validation-failed" | "ready-to-apply" |
  "partially-applied" | "awaiting-word-decision" | "review-failed" | "ready-to-clean" | "complete" | "unknown";

export type BuildSetup = { lane: "build"; project_key: string; template?: string; template_version?: string; output?: string; document_properties: Record<string, unknown>; sections: { stable_key: string; number: string; heading: string; file?: string; valid: boolean; issues: unknown[] }[]; gaps: { section: string; reason: string }[]; gates: { key: string; satisfied: boolean; detail: string }[]; ready_for_preview: boolean; ready_for_build: boolean };
export type BuildOutcome = { state: string; preview: boolean; document?: string; document_hash?: string; backup?: string; section_map: Record<string, unknown>[]; warnings: string[]; integrity: Record<string, unknown> };
export type AuditFinding = { id: string; section: string; severity: string; requirement: string; claim: string; evidence_ids: string[]; location: string; disposition: "OPEN" | "PARTIAL" | "CONFLICT" | "NOT_FOUND" | "DISCOVERY_REQUIRED" | "ANSWERED"; action: string };
export type AuditSnapshot = { state: string; audit_id?: string; document?: string; document_hash?: string; generated_at?: string; report?: string; findings: AuditFinding[]; history: { audit_id: string; generated_at?: string }[] };
