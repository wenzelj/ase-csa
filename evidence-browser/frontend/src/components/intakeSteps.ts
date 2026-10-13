import type { IntakeSnapshot, ReviewJob } from "../types";

export type StepKey = "ingest" | "documents" | "gaps" | "settle" | "use";
export type IntakeStep = { key: StepKey; title: string; status: "done" | "current" | "waiting" | "blocked"; detail: string };

const TERMINAL = ["succeeded", "failed", "cancelled", "interrupted"];
const STEP_FOR_JOB: Record<string, StepKey> = { ingest: "ingest", intake: "documents", gap_check: "gaps" };
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
export function deriveIntakeSteps(snap: IntakeSnapshot, job: ReviewJob | null): { steps: IntakeStep[]; next: StepKey; busy: boolean } {
  const rec = snap.intake;
  const readable = rec ? [...rec.added, ...rec.changed].filter(f => f.status === "indexed" && f.source_class !== "capture") : [];
  const added = snap.matrix.added_since_intake.length;
  const evidenceDone = !!rec && (readable.length === 0 || added > 0 || !!snap.agent_summary);
  const newest = [rec?.built_at_utc, snap.agent_summary?.modified_at].filter(Boolean).sort().pop() || "";
  const checkCurrent = !!snap.gap_check && snap.gap_check.checked_at >= newest;
  const affected = snap.gap_check?.affected.length || 0;

  const status: Record<StepKey, IntakeStep["status"]> = {
    ingest: rec ? "done" : "current",
    documents: !rec ? "waiting" : evidenceDone ? "done" : "current",
    gaps: !evidenceDone ? "waiting" : checkCurrent ? "done" : "current",
    settle: !checkCurrent ? "waiting" : snap.candidates.length ? "current" : "done",
    use: !checkCurrent || snap.candidates.length ? "waiting" : affected ? "current" : "done",
  };
  const detail: Record<StepKey, string> = {
    ingest: !rec ? "Nothing ingested yet"
      : snap.nothing_new_since ? `Nothing new since ${when(snap.nothing_new_since)}`
      : `${rec.added.length} new · ${rec.changed.length} changed · ${rec.removed.length} removed` + (rec.unreadable.length ? ` · ${rec.unreadable.length} not readable` : ""),
    documents: !rec ? "" : readable.length === 0 ? "Nothing readable came in"
      : added ? `${plural(added, "evidence row")} added` : `${plural(readable.length, "document")} to read`,
    gaps: snap.gap_check ? `Checked ${when(snap.gap_check.checked_at)} · ${plural(snap.gap_check.questions.length, "question")}` : "Not checked yet",
    settle: snap.candidates.length ? `${snap.candidates.length} to settle` : checkCurrent ? "Nothing to settle" : "",
    use: affected ? `${affected} subsection${affected === 1 ? "" : "s"} can be answered again` : checkCurrent ? "Nothing new to answer" : "",
  };
  const running = !!job && !TERMINAL.includes(job.state);
  const runningStep = running ? STEP_FOR_JOB[job!.operation] : undefined;
  if (runningStep) { status[runningStep] = "blocked"; detail[runningStep] = "Running…"; }
  const order: StepKey[] = ["ingest", "documents", "gaps", "settle", "use"];
  const steps = order.map(key => ({ key, title: TITLES[key], status: status[key], detail: detail[key] }));
  const next = order.find(k => status[k] === "current") || "use";
  return { steps, next, busy: running };
}

export type PendingSettle = { id: string; dr: string; system: string };

/** The candidate a just-committed evidence row settles: only the one "Write the fact" was opened for, in the same
 *  project, and only while the draft still says it answers that question. Anything else settles nothing. */
export function settleTarget(pending: PendingSettle | null, draft: { gap_or_action: string } | null, system: string): string | null {
  if (!pending || !draft || pending.system !== system) return null;
  return draft.gap_or_action === `Answers ${pending.dr}` ? pending.id : null;
}

/** The newest ingest, intake or gap-check job that is still queued or running (to pick up again after leaving the page). */
export function resumableJob(jobs: ReviewJob[]): ReviewJob | null {
  const live = jobs.filter(j => j.operation in STEP_FOR_JOB && !TERMINAL.includes(j.state));
  return live.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null;
}
