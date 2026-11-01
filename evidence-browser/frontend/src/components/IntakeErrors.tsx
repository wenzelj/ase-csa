import { useState } from "react";
import type { IntakeProblem, IntakeRun, IntakeWarning } from "../types";

const OP_LABEL: Record<string, string> = { ingest: "Ingest new data", intake: "Evidence agent", gap_check: "Check open questions", resolve_gaps: "Resolve evidence and update answers" };

function when(value?: string | null) { if (!value) return "—"; const d = new Date(value); return isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }

function Group({ problem, open }: { problem: IntakeProblem; open: boolean }) {
  const [shown, setShown] = useState(open);
  return <li className="intake-err-group">
    <div className="intake-err-row"><b>{problem.kind}</b><span className="intake-err-sig">{problem.signature}</span><span>×{problem.count}</span><small>first line {problem.first_line}</small>
      <button className="quiet" aria-expanded={shown} onClick={() => setShown(!shown)}>{shown ? "Hide sample" : "Show sample"}</button></div>
    {shown && <pre className="intake-err-sample">{problem.sample}</pre>}
  </li>;
}

export function IntakeErrors({ runs, warnings, expandSamples = false }: { runs: IntakeRun[]; warnings: IntakeWarning[]; expandSamples?: boolean }) {
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
      <ul>{r.problems.map(p => <Group key={`${p.kind}-${p.signature}`} problem={p} open={expandSamples} />)}</ul>
    </article>)}
  </details>;
}
