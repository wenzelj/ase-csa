import { pipelineState } from "../pipelineState";
import type { ApplyJob, ApplyOutcome, PipelineSection, ProposalFile, ReviewJob, ValidationResult } from "../types";

export type StepKey = "author" | "validate" | "apply" | "review";
export type StepStatus = "done" | "current" | "blocked" | "waiting" | "running" | "failed";
export type RailAction = "author" | "save" | "validate" | "apply" | "resume" | "review" | "stop-review" | "word" | "cleanup" | "none";

export type RailStep = { key: StepKey; label: string; status: StepStatus; detail: string };
export type RailPrimary = { label: string; action: RailAction; disabledReason?: string };
export type RailSteps = { steps: RailStep[]; current: StepKey | null; primary: RailPrimary; area: Record<StepKey, string> };

export type StepInputs = {
  section: PipelineSection;
  proposal: ProposalFile | null;
  dirty: boolean;
  validating?: boolean;
  validationResult: ValidationResult | null;
  applyJob: ApplyJob | null;
  applyOutcome: ApplyOutcome | null;
  authorJob: ReviewJob | null;
  reviewJob: ReviewJob | null;
  wordLocked: boolean;
  authorLocked?: boolean;
  /** Review start was refused (for example the Word gate); shown on the Review step. */
  reviewBlocked?: string;
};

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
const active = (job: { state: string } | null) => Boolean(job && !TERMINAL.has(job.state));
export const STEP_LABELS: Record<StepKey, string> = { author: "Author", validate: "Validate", apply: "Apply", review: "Review" };
// Which inspector area each step chip jumps to.
const AREA: Record<StepKey, string> = { author: "author", validate: "proposal", apply: "proposal", review: "review" };
const ORDER: StepKey[] = ["author", "validate", "apply", "review"];

export function deriveSteps(input: StepInputs): RailSteps {
  const { section, proposal, dirty, validationResult, applyJob, applyOutcome, authorJob, reviewJob, wordLocked } = input;
  const state = pipelineState(section);
  const hasProposal = Boolean(proposal) || state !== "not-started";
  const authorRunning = active(authorJob), applyRunning = active(applyJob), reviewRunning = active(reviewJob);
  const locallyValid = Boolean(proposal && !dirty && validationResult?.valid && validationResult.file_hash === proposal.etag);
  const validationFailed = state === "validation-failed" || Boolean(validationResult && !validationResult.valid);
  const applied = state === "partially-applied" ? "partial" : ["awaiting-word-decision", "review-failed", "ready-to-clean", "complete"].includes(state) ? "done" : "none";

  // Index of the step the section is on.
  let current: StepKey | null;
  if (state === "complete") current = null;
  else if (applied === "done") current = "review";
  else if (applied === "partial" || locallyValid) current = "apply";
  else if (hasProposal) current = "validate";
  else current = "author";
  if (authorRunning) current = "author";
  if (applyRunning) current = "apply";
  if (reviewRunning) current = "review";

  const at = current ? ORDER.indexOf(current) : ORDER.length;
  const steps: RailStep[] = ORDER.map((key, index) => {
    let status: StepStatus = index < at ? "done" : index === at ? "current" : "waiting";
    let detail = status === "done" ? "Done" : status === "current" ? "Next" : "Waiting";
    if (key === "author" && authorRunning) { status = "running"; detail = "Authoring…"; }
    else if (key === "author" && authorJob && authorJob.state === "failed" && !hasProposal) { status = "failed"; detail = "Last run failed"; }
    if (key === "validate" && status === "current") {
      if (dirty) detail = "Unsaved changes";
      else if (input.validating) { status = "running"; detail = "Validating…"; }
      else if (validationFailed) { status = "failed"; detail = validationResult ? `${validationResult.errors} error${validationResult.errors === 1 ? "" : "s"}` : "Validation failed"; }
      else detail = "Not validated";
    }
    if (key === "validate" && status === "done") detail = "Passed";
    if (key === "apply") {
      if (applyRunning) { status = "running"; detail = "Applying…"; }
      else if (status === "current" && wordLocked) { status = "blocked"; detail = "Word has the document open"; }
      else if (applyOutcome?.state === "failed" || (applyJob && applyJob.state === "failed")) { status = "failed"; detail = "Apply failed"; }
      else if (status === "current") detail = applied === "partial" ? "Partly applied" : "Ready";
      else if (status === "done") detail = "Applied";
    }
    if (key === "review") {
      if (reviewRunning) { status = "running"; detail = "Reviewing…"; }
      else if (state === "review-failed") { status = "failed"; detail = "Review failed"; }
      else if (state === "ready-to-clean") detail = "Passed · cleanup pending";
      else if (state === "awaiting-word-decision") detail = input.reviewBlocked || "Awaiting Word decision";
      else if (state === "complete") { status = "done"; detail = "Complete"; }
    }
    return { key, label: STEP_LABELS[key], status, detail };
  });

  return { steps, current, primary: primaryFor({ ...input, state, current, locallyValid, authorRunning, applyRunning, reviewRunning, validationFailed }), area: AREA };
}

function primaryFor(c: StepInputs & { state: ReturnType<typeof pipelineState>; current: StepKey | null; locallyValid: boolean; authorRunning: boolean; applyRunning: boolean; reviewRunning: boolean; validationFailed: boolean }): RailPrimary {
  if (c.state === "complete" && !c.reviewRunning) return { label: "Complete", action: "none", disabledReason: "This section is complete." };
  if (c.reviewRunning) return { label: "Stop review", action: "stop-review" };
  if (c.authorRunning) return { label: "Authoring…", action: "none", disabledReason: "Authoring is running." };
  if (c.applyRunning) return { label: "Applying…", action: "none", disabledReason: "The apply job is running." };
  switch (c.current) {
    case "author": return { label: "Run authoring", action: "author", disabledReason: c.authorLocked ? "Another authoring run holds the lock." : undefined };
    case "validate":
      if (c.dirty) return { label: "Save draft", action: "save" };
      if (!c.proposal) return { label: "Validate", action: "validate", disabledReason: "The proposal is still loading." };
      return { label: c.validationFailed ? "Re-validate" : "Validate", action: "validate", disabledReason: c.validating ? "Validation is running." : undefined };
    case "apply": {
      const resume = c.state === "partially-applied";
      return { label: resume ? "Resume remaining edits" : "Apply proposal", action: resume ? "resume" : "apply", disabledReason: c.wordLocked ? "Word has the document open. Close it first." : !c.proposal ? "The proposal is still loading." : c.dirty ? "Unsaved changes — save first." : undefined };
    }
    case "review":
      if (c.state === "awaiting-word-decision") return { label: "Open Word decisions", action: "word" };
      if (c.state === "review-failed") return { label: "Retry review", action: "review" };
      if (c.state === "ready-to-clean") return { label: "Clean up", action: "cleanup" };
      return { label: "Run review", action: "review" };
    default: return { label: "Complete", action: "none" };
  }
}
