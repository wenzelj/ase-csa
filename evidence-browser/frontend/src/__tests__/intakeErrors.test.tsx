import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IntakeErrors, LogError, LogLines, loadLogPage, logStartFor, earlierStart, laterStart } from "../components/IntakeErrors";
import type { IntakeRun, IntakeWarning, JobLogPage } from "../types";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const vt = (await import("vitest" as any)) as { it: (n: string, f: () => void | Promise<void>) => void; expect: (a: unknown) => any };
const { it, expect } = vt;

const run = (id: string, started_at: string, problems: IntakeRun["problems"]): IntakeRun => ({
  id, operation: "intake", step: "documents", state: "failed", started_at, reason: "Agent stopped", problems,
  problem_count: problems.reduce((n, p) => n + p.count, 0), has_problems: problems.length > 0, log_truncated: false,
});
const group = (kind: string, signature: string, count: number, first_line: number, sample: string) => ({ kind, signature, count, first_line, last_line: first_line, sample, stream: "stderr" as const });
const warning: IntakeWarning = { step: "documents", severity: "warning", code: "slow", message: "Index is slow", count: 3 };

it("renders the empty state collapsed", () => {
  const html = renderToStaticMarkup(<IntakeErrors runs={[run("ok", "2026-10-31T01:00:00Z", [])]} warnings={[]} />);
  expect(html.includes("Errors and warnings")).toBe(true);
  expect(html.includes("No errors in the last 10 runs.")).toBe(true);
  expect(html.includes("open=")).toBe(false);
});

it("renders a failed run with two groups and counts, open", () => {
  const r = run("bad", "2026-10-31T02:00:00Z", [group("Traceback", "ValueError: x", 4, 12, "boom"), group("Timeout", "request timed out", 2, 30, "slow")]);
  const html = renderToStaticMarkup(<IntakeErrors runs={[r]} warnings={[]} />);
  expect(html.includes("open=")).toBe(true);
  expect(html.includes("Agent stopped")).toBe(true);
  expect(html.includes("×4")).toBe(true);
  expect(html.includes("×2")).toBe(true);
  expect(html.includes("first line 12")).toBe(true);
  expect(html.includes("first line 30")).toBe(true);
  expect(html.includes("No errors in the last 10 runs.")).toBe(false);
  expect(html.includes("boom")).toBe(false);
});

it("expands a sample", () => {
  const r = run("bad", "2026-10-31T02:00:00Z", [group("Traceback", "ValueError: x", 4, 12, "boom sample")]);
  expect(renderToStaticMarkup(<IntakeErrors runs={[r]} warnings={[]} expandSamples />).includes("boom sample")).toBe(true);
});

it("shows warnings before runs", () => {
  const r = run("bad", "2026-10-31T02:00:00Z", [group("Traceback", "ValueError: x", 1, 1, "s")]);
  const html = renderToStaticMarkup(<IntakeErrors runs={[r]} warnings={[warning]} />);
  expect(html.indexOf("Index is slow") > -1 && html.indexOf("Index is slow") < html.indexOf("Agent stopped")).toBe(true);
  expect(html.includes("×3")).toBe(true);
});

it("offers Open log on each group", () => {
  const r = run("bad", "2026-10-31T02:00:00Z", [group("Traceback", "ValueError: x", 4, 12, "boom"), group("Timeout", "t", 2, 30, "s")]);
  const html = renderToStaticMarkup(<IntakeErrors runs={[r]} warnings={[]} system="s" />);
  expect(html.split("Open log").length - 1).toBe(2);
});

const page = (start: number, n: number): JobLogPage => ({ stream: "stderr", total_lines: 500, start, truncated: false, lines: Array.from({ length: n }, (_, i) => ({ n: start + i, text: `line ${start + i}` })) });

it("opens centred on the first line and highlights it", async () => {
  expect(logStartFor(100)).toBe(75);
  expect(logStartFor(5)).toBe(1);
  const calls: unknown[][] = [];
  const res = await loadLogPage(async (...a) => { calls.push(a); return page(a[3] as number, 50); }, "sys", "job1", "stderr", logStartFor(100));
  expect(calls[0]).toEqual(["sys", "job1", "stderr", 75, 50]);
  const html = renderToStaticMarkup(<LogLines page={res.page!} highlight={100} />);
  expect(html.includes("intake-log-hit")).toBe(true);
  expect(html.includes("line 100")).toBe(true);
});

it("Earlier and Later move by one page", async () => {
  expect(earlierStart(75)).toBe(25);
  expect(earlierStart(20)).toBe(1);
  expect(laterStart(75)).toBe(125);
  const calls: number[] = [];
  const f = async (_s: string, _j: string, _st: "stdout" | "stderr", start: number) => { calls.push(start); return page(start, 50); };
  await loadLogPage(f, "s", "j", "stderr", earlierStart(75));
  await loadLogPage(f, "s", "j", "stderr", laterStart(75));
  expect(calls).toEqual([25, 125]);
});

it("shows the message and path when the log cannot be read", async () => {
  const res = await loadLogPage(async () => { throw new Error("nope"); }, "s", "job9", "stderr", 1);
  expect(res.error).toBe("The log for this run could not be read");
  const html = renderToStaticMarkup(<LogError jobId="job9" />);
  expect(html.includes("The log for this run could not be read")).toBe(true);
  expect(html.includes("csa-work/ui-jobs/job9/")).toBe(true);
});
