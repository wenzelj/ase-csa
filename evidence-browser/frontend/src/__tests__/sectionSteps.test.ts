import { deriveSteps, type StepInputs } from "../components/sectionSteps";
import type { PipelineSection, ProposalFile, ValidationResult } from "../types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const base: PipelineSection = {
  visible_number: "3.1", stable_key: "ASSET", stable_path: "@H3.1", heading: "Asset inventory",
  lane: "revise", validation_result: "not_started", applied_state: "not_started",
  review_verdict: "not_started", cleanup_state: "not_started", open_comments: 0, issues: [],
};
const withFile = { ...base, change_file: "Changes.md" };
const proposal = { etag: "h1", file: "Changes.md" } as unknown as ProposalFile;
const valid = { valid: true, errors: 0, warnings: 0, file_hash: "h1" } as unknown as ValidationResult;
const invalid = { valid: false, errors: 2, warnings: 0, file_hash: "h1" } as unknown as ValidationResult;
const job = (state: string) => ({ id: "j1", state }) as any;

const input = (over: Partial<StepInputs>): StepInputs => ({
  section: base, proposal: null, dirty: false, validationResult: null, applyJob: null, applyOutcome: null,
  authorJob: null, reviewJob: null, wordLocked: false, ...over,
});

type Case = [string, Partial<StepInputs>, string, string, string]; // name, input, current step, primary action, primary label
const cases: Case[] = [
  ["not started", {}, "author", "author", "Run authoring"],
  ["author running", { authorJob: job("running") }, "author", "none", "Authoring…"],
  ["proposal dirty", { section: withFile, proposal, dirty: true }, "validate", "save", "Save draft"],
  ["saved, not validated", { section: withFile, proposal }, "validate", "validate", "Validate"],
  ["validation failed", { section: { ...withFile, validation_result: "failed" }, proposal, validationResult: invalid }, "validate", "validate", "Re-validate"],
  ["validated", { section: { ...withFile, validation_result: "valid" }, proposal, validationResult: valid }, "apply", "apply", "Apply proposal"],
  ["validated but pipeline says ready, no local validation", { section: { ...withFile, validation_result: "valid" }, proposal }, "validate", "validate", "Validate"],
  ["partially applied", { section: { ...withFile, validation_result: "valid", applied_state: "partial" }, proposal }, "apply", "resume", "Resume remaining edits"],
  ["apply running", { section: withFile, proposal, applyJob: job("running") }, "apply", "none", "Applying…"],
  ["applied, awaiting Word", { section: { ...withFile, applied_state: "complete" }, proposal }, "review", "word", "Open Word decisions"],
  ["review running", { section: { ...withFile, applied_state: "complete" }, proposal, reviewJob: job("running") }, "review", "stop-review", "Stop review"],
  ["review failed", { section: { ...withFile, applied_state: "complete", review_verdict: "fail" }, proposal }, "review", "review", "Retry review"],
  ["ready to clean", { section: { ...withFile, applied_state: "complete", review_verdict: "pass" }, proposal }, "review", "cleanup", "Clean up"],
];
for (const [name, over, current, action, label] of cases) {
  const result = deriveSteps(input(over));
  assert(result.current === current, `${name}: current ${result.current} !== ${current}`);
  assert(result.primary.action === action, `${name}: action ${result.primary.action} !== ${action}`);
  assert(result.primary.label === label, `${name}: label ${result.primary.label} !== ${label}`);
}

const complete = deriveSteps(input({ section: { ...withFile, applied_state: "complete", review_verdict: "pass", cleanup_state: "complete" } }));
assert(complete.current === null && complete.steps.every(step => step.status === "done"), "complete: every step done");
assert(complete.primary.action === "none", "complete: no action");

// Validate is its own step; cleanup stays under Review.
const ready = deriveSteps(input({ section: withFile, proposal, validationResult: valid }));
assert(ready.steps.map(step => step.key).join() === "author,validate,apply,review", "four steps in order");
assert(ready.steps[1].status === "done" && ready.steps[2].status === "current", "validated: validate done, apply current");
const clean = deriveSteps(input({ section: { ...withFile, applied_state: "complete", review_verdict: "pass" } }));
assert(clean.steps[3].detail === "Passed · cleanup pending", "cleanup pending is shown on Review");

// Blocked reasons.
const locked = deriveSteps(input({ section: withFile, proposal, validationResult: valid, wordLocked: true }));
assert(locked.steps[2].status === "blocked" && locked.steps[2].detail.includes("Word"), "word lock blocks apply");
assert(Boolean(locked.primary.disabledReason?.includes("Word")), "word lock disables the primary action with a reason");
const dirtyApply = deriveSteps(input({ section: { ...withFile, applied_state: "partial" }, proposal, dirty: true }));
assert(Boolean(dirtyApply.primary.disabledReason?.includes("save")), "unsaved changes block resume with a reason");
const failed = deriveSteps(input({ section: withFile, proposal, validationResult: invalid }));
assert(failed.steps[1].status === "failed" && failed.steps[1].detail === "2 errors", "validation errors reported");
const refused = deriveSteps(input({ section: { ...withFile, applied_state: "complete" }, proposal, reviewBlocked: "Save and close the Word document before review." }));
assert(refused.steps[3].detail.includes("Word document"), "review refusal reason is shown on Review");

console.log("section step fixtures passed");
