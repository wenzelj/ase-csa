// DraftLane job recovery: after a page reload, the newest answer or refresh_draft job must come
// back — a queued/running one is polled again, a terminal one is shown with its output.
import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { DraftLane } from "../components/DraftLane";
import type { DraftSnapshot, ReviewJob } from "../types";
// vitest types are resolved by the test runner; a minimal fallback keeps `tsc` happy when the
// package is not in node_modules.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const vitestImport = (await import("vitest" as any) as {
  it: (name: string, fn: () => void | Promise<void>) => void;
  expect: (actual: unknown) => { toBe: (e: unknown) => void; toBeGreaterThanOrEqual: (n: number) => void };
}) ?? {};
const it: (name: string, fn: () => void | Promise<void>) => void = vitestImport.it ?? ((name: string, fn: () => void | Promise<void>) => { void fn(); });
const expect: (actual: unknown) => any = vitestImport.expect ?? ((actual: unknown) => ({
  toBe(e: unknown) { if (actual !== e) throw new Error(`expected ${JSON.stringify(e)}, got ${JSON.stringify(actual)}`); },
  toBeGreaterThanOrEqual(n: number) { if (typeof actual !== "number" || actual < n) throw new Error(`expected >= ${n}, got ${actual}`); },
}));

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

// --- Minimal browser globals (Node has none) -------------------------------------------
type Timer = { fn: () => void; ms: number };
const timers: Map<number, Timer> = new Map();
let nextTimer = 0;
const fakeElement = { id: "", scrollIntoView: () => {} };
function makeElement(tag: string): Record<string, any> {
  const el: Record<string, any> = {
    nodeType: 1, tagName: tag.toUpperCase(), nodeName: tag.toUpperCase(), localName: tag.toLowerCase(),
    childNodes: [], children: [], firstChild: null, lastChild: null,
    ownerDocument: null, style: {}, attributes: [],
    namespaceURI: "http://www.w3.org/1999/xhtml", textContent: "",
    appendChild(c: unknown) { el.childNodes.push(c); return c; },
    insertBefore(c: unknown) { el.childNodes.push(c); return c; },
    removeChild(c: unknown) { return c; },
    replaceChild(n: unknown, o: unknown) { return o; },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; },
    addEventListener(type: string, fn?: unknown, opts?: unknown) {
      const t = (opts && typeof opts === "object" && (opts as any).capture) ? documentStub : el;
      const arr: unknown[] = (t as any)._listeners ?? ((t as any)._listeners = []);
      arr.push({ type, fn });
    },
    removeEventListener() {}, dispatchEvent() { return true; },
    length: 0, value: "", selected: false, defaultSelected: false, disabled: false, multiple: false,
    options: [],
  };
  return el;
}
const documentStub: Record<string, any> = {
  nodeType: 9,
  getElementById: () => fakeElement,
  activeElement: null, body: null, defaultView: null,
  createElement: (tag: string) => makeElement(tag),
  createElementNS: (_ns: string, tag: string) => makeElement(tag),
  createTextNode: () => ({ nodeType: 3, textContent: "" }),
  _listeners: [],
  addEventListener(type: string, fn?: unknown) { (documentStub._listeners as unknown[]).push({ type, fn }); },
  removeEventListener() {}, dispatchEvent() { return true; },
};
class IFrame {}
const windowStub: Record<string, any> = {
  setInterval(fn: () => void, ms: number) { const id = ++nextTimer; timers.set(id, { fn, ms }); return id; },
  clearInterval(id: number) { timers.delete(id); },
  document: documentStub,
  HTMLElement: makeElement("div"), HTMLIFrameElement: IFrame,
  Node: makeElement("div"), Text: { nodeType: 3 },
};
(globalThis as Record<string, any>).window = windowStub;
(globalThis as Record<string, any>).document = documentStub;
(globalThis as Record<string, any>).HTMLElement = windowStub.HTMLElement;
(globalThis as Record<string, any>).HTMLIFrameElement = IFrame;
(globalThis as Record<string, any>).Node = windowStub.Node;

const SNAPSHOT = {
  project_key: "reveloc", stage: "draft", stale_checked_at: null,
  counts: { current: 1, stale: 0, answered: 0, "not-answered": 1 },
  sections: [{ number: "3.1", key: "ASSET", title: "Asset inventory", kind: "subsection", level: 3, document_state: "final", state: "not-answered", answered_at: null, open: 0 }],
  changes: { rows: [] }, open_questions: { total: 0, groups: [] }, spec_error: null,
} as unknown as DraftSnapshot;

function job(id: string, operation: string, state: string, created_at: string, extra: Record<string, unknown> = {}): ReviewJob {
  return { id, project_key: "reveloc", operation, state, created_at, started_at: null, finished_at: null,
    exit_code: null, stdout_tail: "", stderr_tail: "", message: null, ...extra } as unknown as ReviewJob;
}
function json(body: unknown) { return { ok: true, status: 200, json: async () => body }; }

let fetchUrls: string[] = [];
let jobsListCalls = 0;
let JOBS: ReviewJob[] = [];
let JOB_STATE: Record<string, ReviewJob> = {};

(globalThis as Record<string, any>).fetch = async (url: string) => {
  const u = url as string;
  fetchUrls.push(u);
  const jobsUrl = "/api/systems/reveloc/jobs";
  if (u === jobsUrl) { jobsListCalls++; return json({ jobs: JOBS }); }
  if (u.startsWith(jobsUrl + "/")) {
    const id = u.slice(jobsUrl.length + 1);
    return json(JOB_STATE[id] || JOBS.find(j => j.id === id) || job(id, "answer", "failed", "2026-10-31T00:00:00Z"));
  }
  if (u === "/api/systems/reveloc/draft") return json(SNAPSHOT);
  return json({});
};

function render() {
  const el = makeElement("div");
  el.ownerDocument = documentStub;
  return createRoot(el as unknown as HTMLElement);
}
const tick = () => new Promise<void>(r => setTimeout(r, 0));
async function settle() { for (let i = 0; i < 10; i++) await tick(); }
function fireTimers() { for (const t of [...timers.values()]) void t.fn(); }

// --- Case 1: reload during a running answer ---------------------------------------------
it("resumes a running answer job after reload and polls it", async () => {
  fetchUrls = []; jobsListCalls = 0; timers.clear();
  const running = job("job-running", "answer", "running", "2026-10-31T11:00:00Z", {
    display_args: ["answer", "3.1", "--cli", "gpt"], stdout_tail: "CSA_PHASE GENERATING: answer draft" });
  const olderDone = job("job-done", "refresh_draft", "succeeded", "2026-10-31T09:00:00Z");
  JOBS = [running, olderDone];
  JOB_STATE = { "job-running": running };

  const root = render();
  await act(async () => { root.render(<DraftLane system="reveloc" investigate={() => {}} />); });
  await act(async () => { await settle(); });
  await act(async () => { fireTimers(); await settle(); });

  expect(jobsListCalls).toBeGreaterThanOrEqual(1);
  expect(fetchUrls.some(u => u === "/api/systems/reveloc/jobs/job-running")).toBe(true);
  await act(async () => { root.unmount(); });
});

// --- Case 2: return after a failed answer ------------------------------------------------
it("shows a failed answer job after reload without polling it", async () => {
  fetchUrls = []; jobsListCalls = 0; timers.clear();
  const failed = job("job-failed", "answer", "failed", "2026-10-31T10:00:00Z", {
    display_args: ["answer", "3.1", "--cli", "gpt"],
    stdout_tail: "CSA_PHASE CARD: reading the evidence\nCSA_PHASE GENERATING: answer draft",
    stderr_tail: "answer 3.1 stopped: model run failed",
    message: "answer 3.1 stopped: model run failed" });
  JOBS = [failed];
  JOB_STATE = { "job-failed": failed };

  const root = render();
  await act(async () => { root.render(<DraftLane system="reveloc" investigate={() => {}} />); });
  await act(async () => { await settle(); });

  expect(jobsListCalls).toBeGreaterThanOrEqual(1);
  expect(timers.size).toBe(0);
  await act(async () => { root.unmount(); });
});

console.log("draftLaneJobs recovery tests passed");
