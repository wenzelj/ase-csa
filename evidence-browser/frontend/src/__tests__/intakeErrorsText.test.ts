import { runSummaryText } from "../intakeErrorsText";
import type { IntakeRun } from "../types";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const vt = (await import("vitest" as any)) as { it: (n: string, f: () => void | Promise<void>) => void; expect: (a: unknown) => any };
const { it, expect } = vt;

const base = (problems: IntakeRun["problems"]): IntakeRun => ({
  id: "job7", operation: "intake", step: "documents", state: "failed", exit_code: 2,
  started_at: "2026-10-31T02:00:00Z", finished_at: "2026-10-31T02:05:00Z", reason: "Agent stopped", problems,
  problem_count: 0, has_problems: problems.length > 0, log_truncated: false,
});
const g = (kind: string, signature: string, count: number, first_line: number, sample: string) => ({ kind, signature, count, first_line, last_line: first_line, sample, stream: "stderr" as const });

it("summarises a run with two groups", () => {
  const t = runSummaryText(base([g("Traceback", "ValueError: x", 4, 12, "s1"), g("Timeout", "timed out", 2, 30, "s2")]));
  for (const s of ["intake", "job7", "failed", "Exit code: 2", "2026-10-31T02:00:00Z", "2026-10-31T02:05:00Z", "Agent stopped",
    "×4 Traceback: ValueError: x (first line 12)", "×2 Timeout: timed out (first line 30)", "csa-work/ui-jobs/job7/stderr.log"]) expect(t.includes(s)).toBe(true);
  expect(t.includes("|")).toBe(false);
});

it("summarises a run with no groups", () => {
  const t = runSummaryText(base([]));
  expect(t.includes("none")).toBe(true);
  expect(t.includes("csa-work/ui-jobs/job7/stderr.log")).toBe(true);
});

it("never includes sample text", () => {
  const t = runSummaryText(base([g("Traceback", "ValueError: x", 1, 1, "password=hunter2")]));
  expect(t.includes("hunter2")).toBe(false);
});
