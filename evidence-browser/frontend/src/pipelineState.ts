import type { AssessmentState, PipelineSection } from "./types";

export function pipelineState(section: PipelineSection): AssessmentState {
  const validation = section.validation_result.toLowerCase(); const applied = section.applied_state.toLowerCase();
  const review = section.review_verdict.toLowerCase(); const cleanup = section.cleanup_state.toLowerCase();
  if ([validation, applied, review, cleanup, section.lane].some(value => value === "unknown")) return "unknown";
  if (cleanup === "complete") return "complete";
  if (review.includes("fail") || review.includes("block")) return "review-failed";
  if (["pass", "passed", "ready"].includes(review) && cleanup !== "complete") return "ready-to-clean";
  if (["partial", "partially_applied", "partial_complete"].includes(applied)) return "partially-applied";
  if (applied === "complete" && ["not_started", "not-started", "pending"].includes(review)) return "awaiting-word-decision";
  if (validation.includes("fail") || validation.includes("error") || validation.includes("not_ready")) return "validation-failed";
  if (["not_started", "not-started"].includes(applied) && ["valid", "ready", "pass", "passed"].includes(validation)) return "ready-to-apply";
  if (section.change_file || section.section_file) return "draft";
  return "not-started";
}
