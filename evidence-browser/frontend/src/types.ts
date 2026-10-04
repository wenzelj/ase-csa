export type PipelineIssue = { code: string; message: string; section?: string };
export type PipelineSection = {
  visible_number: string; stable_key: string; stable_path?: string; heading: string;
  lane: "revise" | "build" | "unknown"; change_file?: string; section_file?: string;
  validation_result: string; applied_state: string; review_verdict: string; cleanup_state: string;
  open_comments: number; last_activity?: string; issues: PipelineIssue[];
  evidence_count?: number; open_question_count?: number; proposed_edits?: number; next_action?: string;
};
export type PipelineSnapshot = {
  project_key: string; project_label: string; spec_mode: string;
  document: { path?: string; name?: string; size?: number; modified_at?: string };
  word_locked: boolean; word_lock_file?: string; next_action?: Record<string, unknown>;
  sections: PipelineSection[]; issues: PipelineIssue[]; etag: string;
};

export type AssessmentState = "not-started" | "draft" | "validation-failed" | "ready-to-apply" |
  "partially-applied" | "awaiting-word-decision" | "review-failed" | "ready-to-clean" | "complete" | "unknown";
