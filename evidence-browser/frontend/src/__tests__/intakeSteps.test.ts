import { deriveIntakeSteps, resumableJob, settleTarget } from "../components/intakeSteps";
import type { IntakeSnapshot, IntakeFile, ReviewJob } from "../types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const doc = (name: string, status = "indexed"): IntakeFile => ({ rel_path: `src/${name}`, ext: name.slice(name.lastIndexOf(".")), status, reason: status === "indexed" ? "pdf text" : "binary type .png", source_class: "other", host: null });
const empty: IntakeSnapshot = {
  project_key: "tetra-reveloc", index: { built_at_utc: null, files_by_status: {}, complete: true }, intake: null, nothing_new_since: null,
  matrix: { rows: 0, by_status: {}, pending_review: 0, added_since_intake: [] }, graph: { nodes: 0, edges: 0 },
  candidates: [], gap_check: null, stale: 0, agent_summary: null,
};
const record = { id: "20261012T030000Z", built_at_utc: "2026-10-12T03:00:00Z", matrix_last_id: "E-493", added: [doc("IS-REVELOC.pdf")], changed: [], removed: [], unreadable: [] };
const job = (operation: string, state = "running"): ReviewJob => ({ id: "j1", project_key: "tetra-reveloc", operation, state, created_at: "2026-10-12T03:00:00Z" });
const status = (snap: IntakeSnapshot, j: ReviewJob | null = null) => Object.fromEntries(deriveIntakeSteps(snap, j).steps.map(s => [s.key, s.status]));

// Nothing ingested yet.
const start = deriveIntakeSteps(empty, null);
assert(start.steps.map(s => s.key).join() === "ingest,documents,gaps,settle,use", "five steps in order");
assert(start.next === "ingest" && status(empty).ingest === "current" && status(empty).documents === "waiting", "no record: ingest is current, the rest wait");

// New readable documents, no evidence yet.
const fresh = { ...empty, intake: record };
assert(deriveIntakeSteps(fresh, null).next === "documents" && status(fresh).ingest === "done", "added readable files: documents current");
assert(deriveIntakeSteps(fresh, null).steps[0].detail === "Complete · Last intake with changes: 1 new · 0 changed · 0 removed", "completed ingest is labelled as processed history");
assert(deriveIntakeSteps(fresh, null).steps[1].detail === "1 document to read", "unprocessed documents remain explicit work");

// Rows added, no gap check (or an older one): check open questions.
const evidenced = { ...fresh, matrix: { ...fresh.matrix, added_since_intake: [{ evidence_id: "E-494" }] } };
assert(deriveIntakeSteps(evidenced, null).next === "gaps", "rows added and no gap check: gaps current");
assert(deriveIntakeSteps(evidenced, null).steps[0].detail === "Complete · Indexed changes processed", "completed intake does not present old file counts as outstanding");
assert(deriveIntakeSteps(evidenced, null).steps[1].detail === "Complete · Documents processed", "completed evidence intake does not present old row counts as outstanding");
const oldCheck = { ...evidenced, gap_check: { checked_at: "2026-10-11T00:00:00Z", section: "", questions: [], affected: [] } };
assert(deriveIntakeSteps(oldCheck, null).next === "gaps", "gap check older than the intake: gaps current");

// A completed agent run may legitimately add no rows when every statement was already recorded.
const noRowsNeeded = { ...fresh, agent_summary: { path: "summary.md", text: "# Intake", modified_at: "2026-10-12T04:00:00Z" } };
assert(deriveIntakeSteps(noRowsNeeded, null).steps[1].detail === "Complete · Documents processed", "completed no-op intake is not shown as unread work");

// A completed run with many rows must not make historical totals look like pending work.
const completedLargeRun = { ...fresh, matrix: { ...fresh.matrix, added_since_intake: Array.from({ length: 33 }, (_, i) => ({ evidence_id: `E-${500 + i}` })) }, agent_summary: { path: "summary.md", text: "# Intake", modified_at: "2026-10-12T04:00:00Z" } };
const completedSteps = deriveIntakeSteps(completedLargeRun, null).steps;
assert(!completedSteps[0].detail.includes("1 new") && !completedSteps[1].detail.includes("33"), "completed steps hide historical ingest and evidence counts");

// One candidate to settle.
const settle = { ...evidenced, gap_check: { checked_at: "2026-10-12T05:00:00Z", section: "", questions: [], affected: [{ number: "3.11", key: "BAK", title: "Backup", answered: 0, candidates: 1 }] },
  candidates: [{ evidence_id: "E-510", dr_id: "DR-BAK-B1" }] };
const settleSteps = deriveIntakeSteps(settle, null);
assert(settleSteps.next === "settle" && settleSteps.steps[3].detail === "1 to settle", "one candidate: settle current with count");

// Settled, affected sections remain: use it.
const use = { ...settle, candidates: [], gap_check: { ...settle.gap_check, affected: [settle.gap_check.affected[0], { number: "2.1", key: "EXECUTIVE_SUMMARY", title: "Executive Summary", answered: 1, candidates: 0 }] } };
const useSteps = deriveIntakeSteps(use, null);
assert(useSteps.next === "use" && useSteps.steps[4].detail === "2 subsections can be answered again", "settled: use current with count");

// A running job blocks its step and makes the page busy.
const busy = deriveIntakeSteps(fresh, job("intake"));
assert(busy.busy && busy.steps[1].status === "blocked", "running intake job blocks documents and disables actions");
assert(!deriveIntakeSteps(fresh, job("intake", "succeeded")).busy, "a finished job does not block");

// Only unreadable files came in.
const unreadable = { ...empty, intake: { ...record, added: [doc("diagram.png", "skipped")], unreadable: [doc("diagram.png", "skipped")] } };
const u = deriveIntakeSteps(unreadable, null);
assert(u.steps[1].detail === "Nothing readable came in" && u.steps[1].status === "done", "only unreadable files: documents has nothing to do");

// Ingest ran again with nothing new.
const quiet = { ...use, nothing_new_since: "2026-10-12T03:00:00Z" };
assert(deriveIntakeSteps(quiet, null).steps[0].detail.startsWith("Complete · Nothing new since"), "nothing new is said plainly and marked complete");

// Write the fact settles only the candidate it was opened for, in the same project.
const pending = { id: "E-510", dr: "DR-BAK-B1", system: "tetra" };
assert(settleTarget(pending, { gap_or_action: "Answers DR-BAK-B1" }, "tetra") === "E-510", "the matching draft settles its candidate");
assert(settleTarget(pending, { gap_or_action: "" }, "tetra") === null, "a draft prepared from search does not settle it");
assert(settleTarget(pending, { gap_or_action: "Answers DR-BAK-B1" }, "iamps") === null, "another project never settles it");
assert(settleTarget(null, { gap_or_action: "Answers DR-BAK-B1" }, "tetra") === null, "nothing pending, nothing settled");

// Coming back to the page picks up an evidence job that is still running.
const jobs = [job("answer"), job("ingest", "succeeded"), { ...job("gap_check"), id: "g1", created_at: "2026-10-12T04:00:00Z" }];
assert(resumableJob(jobs)?.id === "g1", "the running gap check is resumed");
assert(resumableJob([job("ingest", "failed"), job("answer")]) === null, "finished or unrelated jobs are not resumed");

console.log("intake step fixtures passed");
