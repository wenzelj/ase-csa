import { deriveIntakeSteps, gapFindings, resumableJob, settleTarget } from "../components/intakeSteps";
import type { IntakeSnapshot, IntakeFile, IntakeErrors, IntakeRun, ReviewJob } from "../types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const doc = (name: string, status = "indexed"): IntakeFile => ({ rel_path: `src/${name}`, ext: name.slice(name.lastIndexOf(".")), status, reason: status === "indexed" ? "pdf text" : "binary type .png", source_class: "other", host: null });
const empty: IntakeSnapshot = {
  project_key: "tetra-reveloc", index: { built_at_utc: null, files_by_status: {}, complete: true }, intake: null, nothing_new_since: null,
  matrix: { rows: 0, evidence_rows: 0, raw_rows: 0, not_found: 0, legacy_candidate_tombstones: 0, by_status: {}, pending_review: 0, added_since_intake: [] }, graph: { nodes: 0, edges: 0 },
  leads: { by_state: {} }, open_leads: [], gap_check: null, stale: 0, agent_summary: null,
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
const oldCheck = { ...evidenced, gap_check: { schema_version: 2, checked_at: "2026-10-11T00:00:00Z", section: "", questions: [], affected: [] } };
assert(deriveIntakeSteps(oldCheck, null).next === "gaps", "gap check older than the intake: gaps current");
const recentLegacyCheck = { ...evidenced, gap_check: { schema_version: 3, checked_at: "2026-10-12T05:00:00Z", section: "", questions: [], affected: [{ number: "3.11", key: "BAK", title: "Backup", answered: 0, candidates: 1 }] },
  open_leads: [{ lead_id: "L-000510", dr_id: "DR-BAK-B1", qid: "B1", question: "q", source_title: "a.txt", source_ref: "a.txt", rel_path: "a.txt", source_version: "v1", source_class: "other", page_or_location: "line 1", excerpt: "source excerpt", found_at: "2026-10-12T04:00:00Z", state: "open" as const }] };
const recentLegacySteps = deriveIntakeSteps(recentLegacyCheck, null);
assert(recentLegacySteps.next === "gaps" && !recentLegacySteps.canResolve, "recent legacy gap check must be rerun before resolve");
assert(recentLegacySteps.steps[2].detail.includes("older format"), "legacy gap check explains why it must be rerun");

// A completed agent run may legitimately add no rows when every statement was already recorded.
const noRowsNeeded = { ...fresh, agent_summary: { path: "summary.md", text: "# Intake", modified_at: "2026-10-12T04:00:00Z" } };
assert(deriveIntakeSteps(noRowsNeeded, null).steps[1].detail === "Complete · Documents processed", "completed no-op intake is not shown as unread work");

// A completed run with many rows must not make historical totals look like pending work.
const completedLargeRun = { ...fresh, matrix: { ...fresh.matrix, added_since_intake: Array.from({ length: 33 }, (_, i) => ({ evidence_id: `E-${500 + i}` })) }, agent_summary: { path: "summary.md", text: "# Intake", modified_at: "2026-10-12T04:00:00Z" } };
const completedSteps = deriveIntakeSteps(completedLargeRun, null).steps;
assert(!completedSteps[0].detail.includes("1 new") && !completedSteps[1].detail.includes("33"), "completed steps hide historical ingest and evidence counts");

// One lead to settle.
const settle = { ...evidenced, gap_check: { schema_version: 4, checked_at: "2026-10-12T05:00:00Z", section: "", questions: [], affected: [{ number: "3.11", key: "BAK", title: "Backup", answered: 0, candidates: 1 }] },
  open_leads: [{ lead_id: "L-000510", dr_id: "DR-BAK-B1", qid: "B1", question: "q", source_title: "a.txt", source_ref: "a.txt", rel_path: "a.txt", source_version: "v1", source_class: "other", page_or_location: "line 1", excerpt: "source excerpt", found_at: "2026-10-12T04:00:00Z", state: "open" as const }] };
const settleSteps = deriveIntakeSteps(settle, null);
assert(settleSteps.next === "settle" && settleSteps.steps[3].detail === "1 lead to settle", "one lead: settle current with count");
assert(settleSteps.canResolve, "schema-4 gap check with an open lead can resolve");

// Settled, affected sections remain: use it.
const use = { ...settle, open_leads: [], gap_check: { ...settle.gap_check, affected: [settle.gap_check.affected[0], { number: "2.1", key: "EXECUTIVE_SUMMARY", title: "Executive Summary", answered: 1, candidates: 0 }] } };
const useSteps = deriveIntakeSteps(use, null);
assert(useSteps.next === "use" && useSteps.steps[4].detail === "2 subsections can be answered again", "settled: use current with count");
assert(useSteps.canResolve, "schema-4 direct answers can update the document without open leads");

// A running job blocks its step and makes the page busy.
const busy = deriveIntakeSteps(fresh, job("intake"));
assert(busy.busy && busy.steps[1].status === "blocked", "running intake job blocks documents and disables actions");
assert(!deriveIntakeSteps(fresh, job("intake", "succeeded")).busy, "a finished job does not block");

// Only unreadable files came in.
const unreadable = { ...empty, intake: { ...record, added: [doc("diagram.png", "skipped")], unreadable: [doc("diagram.png", "skipped")] } };
const u = deriveIntakeSteps(unreadable, null);
assert(u.steps[1].detail === "Complete · Nothing readable came in" && u.steps[1].status === "done", "only unreadable files: documents has nothing to do");

// Ingest ran again with nothing new.
const quiet = { ...use, nothing_new_since: "2026-10-12T03:00:00Z" };
assert(deriveIntakeSteps(quiet, null).steps[0].detail.startsWith("Complete · Nothing new since"), "nothing new is said plainly and marked complete");

// Write the fact settles only the lead it was opened for, in the same project.
const pending = { id: "L-000510", dr: "DR-BAK-B1", system: "tetra" };
assert(settleTarget(pending, { gap_or_action: "Answers DR-BAK-B1" }, "tetra") === "L-000510", "the matching draft settles its lead");
assert(settleTarget(pending, { gap_or_action: "" }, "tetra") === null, "a draft prepared from search does not settle it");
assert(settleTarget(pending, { gap_or_action: "Answers DR-BAK-B1" }, "iamps") === null, "another project never settles it");
assert(settleTarget(null, { gap_or_action: "Answers DR-BAK-B1" }, "tetra") === null, "nothing pending, nothing settled");

// Coming back to the page picks up an evidence job that is still running.
const jobs = [job("answer"), job("ingest", "succeeded"), { ...job("gap_check"), id: "g1", created_at: "2026-10-12T04:00:00Z" }];
assert(resumableJob(jobs)?.id === "g1", "the running gap check is resumed");
assert(resumableJob([{ ...job("resolve_gaps"), id: "r1" }])?.id === "r1", "the running resolve job is resumed");
assert(resumableJob([job("ingest", "failed"), job("answer")]) === null, "finished or unrelated jobs are not resumed");

console.log("intake step fixtures passed");

// The host files did not rebuild after the last sync: ingest is the step to run again.
const broken = { ...use, sync: { ok: false, failed: true, behind: false, last: { at: "x", status: "ERROR", hosts_index: "FAILED: NameError", merged_nodes: [] } } };
assert(status(broken).ingest === "current" && deriveIntakeSteps(broken, null).steps[0].detail.includes("NameError"), "a failed host rebuild sends you back to ingest");

// Rows on a changed source need the evidence agent again.
const recheck = { ...evidenced, refresh: { at: "x", retired: [], recheck: [{ evidence_id: "E-1", file: "a.xlsx", kind: "changed source", why: "quote gone", claim: "c" }] } };
assert(status(recheck).documents === "current" && deriveIntakeSteps(recheck, null).steps[1].detail.includes("1 row to re-check"), "re-check rows keep documents current");

// Stale answers from ingest alone make step 5 current.
const staleOnly = { ...use, gap_check: { ...use.gap_check, affected: [] }, stale: 3 };
assert(status(staleOnly).use === "current" && deriveIntakeSteps(staleOnly, null).steps[4].detail.startsWith("3 answers"), "stale answers are work for step 5");

const gq = { number: "3.16", title: "", key: "SUPPLY", qid: "F01", dr_id: "DR-SUPPLY-F01", text: "q" };
const current = gapFindings({ ...gq, verdict: "CANDIDATES", evidence_ids: ["E-1"], related: ["E-2"], owners: [], kind: "owner", searches: 4 });
assert(current.possible.join() === "E-1" && current.answers.length === 0 && current.related.join() === "E-2", "current shape: candidates are possible answers, not verified");
const earlier = gapFindings({ ...gq, verdict: "ANSWERED", answer_evidence_ids: ["E-3"], related_evidence_ids: [], lead_ids: [], evidence_ids: ["E-3"] });
assert(earlier.answers.join() === "E-3" && earlier.possible.length === 0, "earlier shape: answered evidence is verified");
assert(gapFindings({ ...gq, verdict: "NOT_FOUND" }).related.length === 0, "missing fields do not throw");

// Failed state from the intake errors.
const run = (over: Partial<IntakeRun>): IntakeRun => ({ id: "r1", operation: "intake", step: "documents", state: "failed", exit_code: 1, reason: "", problems: [], problem_count: 0, has_problems: true, log_truncated: false, ...over });
const errs = (...runs: IntakeRun[]): IntakeErrors => ({ generated_at: "2026-10-12T06:00:00Z", runs, warnings: [] });
const failedSteps = deriveIntakeSteps(fresh, null, errs(run({ reason: "csa: no model" })));
assert(failedSteps.steps[1].status === "failed" && failedSteps.steps[1].detail === "Last run failed: csa: no model", "failed run marks its step failed with the reason");
assert(failedSteps.next === "documents", "failed step that is also current is next");
const exitZero = deriveIntakeSteps(fresh, null, errs(run({ exit_code: 0, state: "succeeded", problem_count: 2 })));
assert(exitZero.steps[1].status === "failed" && exitZero.steps[1].detail === "Finished with 2 problems", "exit 0 with problems is reported as problems");
const cleared = deriveIntakeSteps(fresh, null, errs(run({ id: "r2", state: "succeeded", exit_code: 0, has_problems: false }), run({})));
assert(cleared.steps[1].status !== "failed", "a later clean run clears the failure");
const runningBad = deriveIntakeSteps(fresh, job("intake"), errs(run({ id: "j1", state: "running", exit_code: null, problem_count: 3 })));
assert(runningBad.steps[1].status === "blocked" && runningBad.steps[1].detail === "Running… 3 problems so far", "running with problems stays blocked");
assert(JSON.stringify(deriveIntakeSteps(fresh, null)) === JSON.stringify(deriveIntakeSteps(fresh, null, undefined)), "no errors argument is unchanged");
const warned = deriveIntakeSteps(fresh, null, { ...errs(), warnings: [{ step: "documents", severity: "warning", code: "x", message: "m", count: 1 }] });
assert(warned.steps[1].status === "current", "warnings do not change status");
const earlierFailed = deriveIntakeSteps(evidenced, null, errs(run({ step: "ingest", operation: "ingest", reason: "boom" })));
assert(earlierFailed.steps[0].status === "failed" && earlierFailed.next === "gaps", "failed step is skipped when a later step is current");

// The checks above run when the file loads (a failed one fails the suite); vitest needs at least one test.
import { it, vi } from "vitest";
import { refreshWhileRunning, runningText } from "../components/EvidenceIntake";
it("intake steps derive as expected", () => { assert(true, "loaded"); });
it("errors reload every 10 seconds only while a job runs", () => {
  vi.useFakeTimers();
  const state = { n: 0, fail: false };
  const n = (): number => state.n;
  const refresh = () => { state.n++; return state.fail ? Promise.reject(new Error("down")) : Promise.resolve(); };
  refreshWhileRunning(false, refresh);
  vi.advanceTimersByTime(30000); assert(n() === 0, "idle page never refreshes");
  const stop = refreshWhileRunning(true, refresh);
  vi.advanceTimersByTime(9999); assert(n() === 0, "nothing before 10 seconds");
  vi.advanceTimersByTime(1); assert(n() === 1, "refresh at 10 seconds");
  state.fail = true; vi.advanceTimersByTime(10000); assert(n() === 2, "a failed refresh does not stop the timer");
  state.fail = false; vi.advanceTimersByTime(10000); assert(n() === 3, "the next tick tries again");
  stop(); vi.advanceTimersByTime(60000); assert(n() === 3, "no timer left after stop");
  assert(vi.getTimerCount() === 0, "no timers pending");
  vi.useRealTimers();
});
it("running text shows problems so far", () => {
  const e = errs(run({ id: "j1", state: "running", exit_code: null, problem_count: 3 }));
  assert(runningText("j1", e) === "Running… 3 problems so far", "plural");
  assert(runningText("j1", errs(run({ id: "j1", state: "running", problem_count: 1 }))) === "Running… 1 problem so far", "singular");
  assert(runningText("j1", null) === "Running…" && runningText("zz", e) === "Running…", "no problems or no run");
});
