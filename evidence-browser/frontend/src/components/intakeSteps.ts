import type { GapQuestion, IntakeErrors, IntakeRun, IntakeSnapshot, ReviewJob } from "../types";
import { terminalReason } from "../jobReason";

export type StepKey = "ingest" | "documents" | "gaps" | "settle" | "use";
export type IntakeStep = { key: StepKey; title: string; status: "done" | "current" | "waiting" | "blocked" | "failed"; detail: string };

const TERMINAL = ["succeeded", "failed", "cancelled", "interrupted"];
const STEP_FOR_JOB: Record<string, StepKey> = { ingest: "ingest", intake: "documents", gap_check: "gaps", resolve_gaps: "settle" };
const TITLES: Record<StepKey, string> = {
  ingest: "Bring in new data", documents: "Turn new documents into evidence", gaps: "Check open questions",
  settle: "Settle what was found", use: "Use it in the document",
};

function when(value: string): string {
  const d = new Date(value);
  return isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Where the Evidence intake page stands, step by step, and which step is next. */
export function deriveIntakeSteps(snap: IntakeSnapshot, job: ReviewJob | null, errors?: IntakeErrors | null): { steps: IntakeStep[]; next: StepKey; busy: boolean; canResolve: boolean } {
  const rec = snap.intake;
  const readable = rec ? [...rec.added, ...rec.changed].filter(f => f.status === "indexed" && f.source_class !== "capture") : [];
  const added = snap.matrix.added_since_intake.length;
  const evidenceDone = !!rec && (readable.length === 0 || added > 0 || !!snap.agent_summary);
  const newest = [rec?.built_at_utc, snap.agent_summary?.modified_at].filter(Boolean).sort().pop() || "";
  const checkSupported = snap.gap_check?.schema_version === 4;
  const checkCurrent = !!snap.gap_check && checkSupported && snap.gap_check.checked_at >= newest;
  const affected = snap.gap_check?.affected.length || 0;
  const recheck = snap.refresh?.recheck.length || 0;
  const syncBad = !!snap.sync && !snap.sync.ok;

  const status: Record<StepKey, IntakeStep["status"]> = {
    ingest: rec && !syncBad ? "done" : "current",
    documents: !rec ? "waiting" : evidenceDone && !recheck ? "done" : "current",
    gaps: !evidenceDone ? "waiting" : checkCurrent ? "done" : "current",
    settle: !checkCurrent ? "waiting" : snap.open_leads.length ? "current" : "done",
    use: !checkCurrent || snap.open_leads.length ? "waiting" : affected || snap.stale ? "current" : "done",
  };
  const detail: Record<StepKey, string> = {
    ingest: syncBad ? (snap.sync!.failed ? `Host files not rebuilt: ${snap.sync!.last?.hosts_index || "graph sync failed"}` : "Host files are older than the evidence · run Ingest new data")
      : !rec ? "Nothing ingested yet"
      : snap.nothing_new_since ? `Complete · Nothing new since ${when(snap.nothing_new_since)}`
      : evidenceDone ? "Complete · Indexed changes processed"
      : `Complete · Last intake with changes: ${rec.added.length} new · ${rec.changed.length} changed · ${rec.removed.length} removed` + (rec.unreadable.length ? ` · ${rec.unreadable.length} not readable` : ""),
    documents: !rec ? "" : evidenceDone && recheck ? `${plural(recheck, "row")} to re-check against changed sources`
      : readable.length === 0 ? "Complete · Nothing readable came in"
      : evidenceDone ? "Complete · Documents processed"
      : `${plural(readable.length, "document")} to read` + (recheck ? ` · ${plural(recheck, "row")} to re-check` : ""),
    gaps: snap.gap_check && !checkSupported ? "Saved check uses an older format · run Check open questions again"
      : snap.gap_check ? `Checked ${when(snap.gap_check.checked_at)} · ${plural(snap.gap_check.questions.length, "question")}` : "Not checked yet",
    settle: snap.open_leads.length ? `${snap.open_leads.length} lead${snap.open_leads.length === 1 ? "" : "s"} to settle` : checkCurrent ? "Nothing to settle" : "",
    use: affected ? `${affected} subsection${affected === 1 ? "" : "s"} can be answered again`
      : snap.stale ? `${plural(snap.stale, "answer")} built on changed evidence · refresh on Draft answers` : checkCurrent ? "Nothing new to answer" : "",
  };
  const running = !!job && !TERMINAL.includes(job.state);
  const runningStep = running ? STEP_FOR_JOB[job!.operation] : undefined;
  const order: StepKey[] = ["ingest", "documents", "gaps", "settle", "use"];
  const runs = errors?.runs || [];
  const finished = (r: IntakeRun) => !!r.state && TERMINAL.includes(r.state);
  for (const key of order) {
    const newest = runs.find(r => r.step === key && finished(r));
    if (!newest || !newest.has_problems) continue;
    const reason = newest.reason || (job && job.id === newest.id ? terminalReason(job) : "");
    status[key] = "failed";
    detail[key] = newest.exit_code === 0 ? `Finished with ${plural(newest.problem_count, "problem")}` : `Last run failed: ${reason || newest.state}`;
  }
  if (runningStep) {
    status[runningStep] = "blocked";
    const live = runs.find(r => r.id === job!.id);
    detail[runningStep] = live && live.problem_count > 0 ? `Running… ${plural(live.problem_count, "problem")} so far` : "Running…";
  }
  const steps = order.map(key => ({ key, title: TITLES[key], status: status[key], detail: detail[key] }));
  const next = order.find((k, i) => status[k] === "current" || (status[k] === "failed" && !order.slice(i + 1).some(o => status[o] === "current"))) || "use";
  const canResolve = checkCurrent && (snap.open_leads.length > 0 || affected > 0);
  return { steps, next, busy: running, canResolve };
}

export type PendingSettle = { id: string; dr: string; system: string };

/** The lead a just-committed evidence row settles: only the one "Write the fact" was opened for, in the same
 *  project, and only while the draft still says it answers that question. Anything else settles nothing. */
export function settleTarget(pending: PendingSettle | null, draft: { gap_or_action: string } | null, system: string): string | null {
  if (!pending || !draft || pending.system !== system) return null;
  return draft.gap_or_action === `Answers ${pending.dr}` ? pending.id : null;
}

/** The newest intake-workflow job that is still queued or running (to pick up again after leaving the page). */
export function resumableJob(jobs: ReviewJob[]): ReviewJob | null {
  const live = jobs.filter(j => j.operation in STEP_FOR_JOB && !TERMINAL.includes(j.state));
  return live.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null;
}

/** What a gap-check question found, read from either result shape: `evidence_ids`/`related` (current) or
 *  `answer_evidence_ids`/`related_evidence_ids`/`lead_ids` (earlier). Evidence IDs count as an answer only when the
 *  verdict is ANSWERED; for CANDIDATES they are possible answers still to be read. */
export function gapFindings(q: GapQuestion): { answers: string[]; possible: string[]; related: string[] } {
  const ids = q.answer_evidence_ids ?? q.evidence_ids ?? [];
  const leads = q.lead_ids ?? [];
  return {
    answers: q.verdict === "ANSWERED" ? ids : [],
    possible: q.verdict === "CANDIDATES" ? [...leads, ...ids.filter(i => !leads.includes(i))] : [],
    related: q.related_evidence_ids ?? q.related ?? [],
  };
}
