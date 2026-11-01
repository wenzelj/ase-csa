import { useEffect, useState } from "react";
import { fetchJobLog } from "../api";
import type { IntakeProblem, IntakeRun, IntakeWarning, JobLogPage } from "../types";

export const LOG_PAGE = 50;
export type LogFetcher = (system: string, jobId: string, stream: "stdout" | "stderr", start: number, limit: number) => Promise<JobLogPage>;
export const logStartFor = (firstLine: number) => Math.max(1, firstLine - Math.floor(LOG_PAGE / 2));
export const earlierStart = (start: number) => Math.max(1, start - LOG_PAGE);
export const laterStart = (start: number) => start + LOG_PAGE;
export async function loadLogPage(fetcher: LogFetcher, system: string, jobId: string, stream: "stdout" | "stderr", start: number): Promise<{ page?: JobLogPage; error?: string }> {
  try { return { page: await fetcher(system, jobId, stream, start, LOG_PAGE) }; }
  catch { return { error: "The log for this run could not be read" }; }
}

export function LogLines({ page, highlight }: { page: JobLogPage; highlight: number }) {
  return <pre className="intake-log-lines">{page.lines.map(l => <div key={l.n} className={l.n === highlight ? "intake-log-hit" : undefined}><span className="intake-log-n">{l.n}</span> {l.text}</div>)}</pre>;
}

export function LogError({ jobId }: { jobId: string }) {
  return <p className="intake-log-error">The log for this run could not be read <code>csa-work/ui-jobs/{jobId}/</code></p>;
}

function LogViewer({ system, jobId, problem, fetcher }: { system?: string; jobId: string; problem: IntakeProblem; fetcher: LogFetcher }) {
  const [stream, setStream] = useState<"stdout" | "stderr">(problem.stream || "stderr");
  const [start, setStart] = useState(logStartFor(problem.first_line));
  const [page, setPage] = useState<JobLogPage | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    if (!system) { setFailed(true); return; }
    loadLogPage(fetcher, system, jobId, stream, start).then(r => { if (!live) return; setPage(r.page || null); setFailed(!r.page); });
    return () => { live = false; };
  }, [system, jobId, stream, start, fetcher]);
  const switchTo = (s: "stdout" | "stderr") => { setStream(s); setStart(s === problem.stream ? logStartFor(problem.first_line) : 1); };
  const lastShown = page && page.lines.length ? page.lines[page.lines.length - 1].n : start;
  return <div className="intake-log">
    <div className="intake-log-bar">
      {(["stdout", "stderr"] as const).map(s => <button key={s} className="quiet" aria-pressed={stream === s} onClick={() => switchTo(s)}>{s}</button>)}
      <button className="quiet" disabled={start <= 1} onClick={() => setStart(earlierStart(start))}>Earlier</button>
      <button className="quiet" disabled={!page || lastShown >= page.total_lines} onClick={() => setStart(laterStart(start))}>Later</button>
    </div>
    {failed ? <LogError jobId={jobId} /> : page && <LogLines page={page} highlight={stream === problem.stream ? problem.first_line : -1} />}
  </div>;
}

const OP_LABEL: Record<string, string> = { ingest: "Ingest new data", intake: "Evidence agent", gap_check: "Check open questions", resolve_gaps: "Resolve evidence and update answers" };

function when(value?: string | null) { if (!value) return "—"; const d = new Date(value); return isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }

function Group({ problem, open, system, jobId, fetcher }: { problem: IntakeProblem; open: boolean; system?: string; jobId: string; fetcher: LogFetcher }) {
  const [shown, setShown] = useState(open);
  const [logOpen, setLogOpen] = useState(false);
  return <li className="intake-err-group">
    <div className="intake-err-row"><b>{problem.kind}</b><span className="intake-err-sig">{problem.signature}</span><span>×{problem.count}</span><small>first line {problem.first_line}</small>
      <button className="quiet" aria-expanded={shown} onClick={() => setShown(!shown)}>{shown ? "Hide sample" : "Show sample"}</button>
      <button className="quiet" aria-expanded={logOpen} onClick={() => setLogOpen(!logOpen)}>{logOpen ? "Close log" : "Open log"}</button></div>
    {logOpen && <LogViewer system={system} jobId={jobId} problem={problem} fetcher={fetcher} />}
    {shown && <pre className="intake-err-sample">{problem.sample}</pre>}
  </li>;
}

export function IntakeErrors({ runs, warnings, expandSamples = false, system, fetcher = fetchJobLog }: { runs: IntakeRun[]; warnings: IntakeWarning[]; expandSamples?: boolean; system?: string; fetcher?: LogFetcher }) {
  const failing = runs.filter(r => r.has_problems || r.problems.length > 0)
    .sort((a, b) => (Date.parse(b.started_at || "") || 0) - (Date.parse(a.started_at || "") || 0));
  const any = failing.length > 0 || warnings.length > 0;
  return <details className="intake-errors" open={any}>
    <summary><h2>Errors and warnings</h2></summary>
    {warnings.length > 0 && <ul className="intake-err-warnings">{warnings.map(w => <li key={`${w.step}-${w.code}`} className="intake-warn-line">{w.message} <b>×{w.count}</b></li>)}</ul>}
    {failing.length === 0 && <p className="draft-none">No errors in the last 10 runs.</p>}
    {failing.map(r => <article key={r.id} className="intake-err-run">
      <header><b>{OP_LABEL[r.operation] || r.operation}</b><span>{when(r.started_at)}</span><span className="draft-pill">{r.state}</span></header>
      {r.reason && <p>{r.reason}</p>}
      <ul>{r.problems.map(p => <Group key={`${p.kind}-${p.signature}`} problem={p} open={expandSamples} system={system} jobId={r.id} fetcher={fetcher} />)}</ul>
    </article>)}
  </details>;
}
