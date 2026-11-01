import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IntakeErrors } from "../components/IntakeErrors";
import type { IntakeRun, IntakeWarning } from "../types";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const vt = (await import("vitest" as any)) as { it: (n: string, f: () => void) => void; expect: (a: unknown) => any };
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
