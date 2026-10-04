import { renderToStaticMarkup } from "react-dom/server";
import { AssessmentShell, pipelineState } from "../App";
import type { PipelineSection, PipelineSnapshot } from "../types";


function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const base: PipelineSection = {
  visible_number: "3.1", stable_key: "ASSET", stable_path: "@H3.1", heading: "Asset inventory",
  lane: "revise", validation_result: "not_started", applied_state: "not_started",
  review_verdict: "not_started", cleanup_state: "not_started", open_comments: 0, issues: [],
};

const fixtures: [string, PipelineSection][] = [
  ["not-started", { ...base }],
  ["draft", { ...base, change_file: "Changes.md", validation_result: "draft" }],
  ["validation-failed", { ...base, change_file: "Changes.md", validation_result: "failed" }],
  ["ready-to-apply", { ...base, change_file: "Changes.md", validation_result: "valid" }],
  ["partially-applied", { ...base, change_file: "Changes.md", validation_result: "valid", applied_state: "partial" }],
  ["awaiting-word-decision", { ...base, change_file: "Changes.md", validation_result: "valid", applied_state: "complete" }],
  ["review-failed", { ...base, change_file: "Changes.md", validation_result: "valid", applied_state: "complete", review_verdict: "fail" }],
  ["ready-to-clean", { ...base, change_file: "Changes.md", validation_result: "valid", applied_state: "complete", review_verdict: "pass" }],
  ["complete", { ...base, change_file: "Changes.md", validation_result: "valid", applied_state: "complete", review_verdict: "pass", cleanup_state: "complete" }],
  ["unknown", { ...base, applied_state: "unknown" }],
];

for (const [expected, section] of fixtures) {
  assert(pipelineState(section) === expected, `expected ${expected}, got ${pipelineState(section)}`);
}

function snapshot(project: string, sections: PipelineSection[]): PipelineSnapshot {
  return { project_key: project.toLowerCase(), project_label: project, spec_mode: "on",
    document: { name: `${project}.docx` }, word_locked: false, sections, issues: [], etag: project };
}

const ordered = [
  { ...base, visible_number: "3.10", stable_key: "PATCH", heading: "Patch lifecycle" },
  { ...base, visible_number: "3.2", stable_key: "IAM", heading: "Identity" },
];
const html = renderToStaticMarkup(<AssessmentShell snapshot={snapshot("IAMPS", ordered)} selected={null} select={() => {}} readDocument={() => {}} />);
assert(html.indexOf("3.10") < html.indexOf("3.2"), "document order must not be numerically re-sorted");
assert(html.includes("aria-label=\"3.10 Patch lifecycle: Not started\""), "section rows need meaningful accessible names");
assert(html.includes("Unknown") === false, "known fixtures must not be presented as unknown");

const switched = renderToStaticMarkup(<AssessmentShell snapshot={snapshot("TETRA", [{ ...base, heading: "TETRA service" }])} selected={null} select={() => {}} readDocument={() => {}} />);
assert(switched.includes("TETRA service"), "new project content must render");
assert(!switched.includes("Patch lifecycle"), "prior project sections must not leak into a switched project");

console.log("assessment component fixtures passed");
