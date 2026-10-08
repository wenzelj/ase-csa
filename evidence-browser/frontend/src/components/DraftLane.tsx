import { useEffect, useRef, useState } from "react";
import { cancelJob, fetchDraft, fetchJob, submitJob } from "../api";
import type { DraftSection, DraftSnapshot, ReviewJob } from "../types";
import { Empty } from "./ui";

const TERMINAL = ["succeeded", "failed", "cancelled", "interrupted"];
const CLIS = [{ id: "claude", label: "Claude" }, { id: "codex", label: "Codex" }, { id: "evo", label: "Evo (local)" }];
const STATE_LABEL: Record<string, string> = { current: "Current", stale: "Evidence changed", answered: "Answered", "not-answered": "Not answered" };
const OP_LABEL: Record<string, string> = { ingest: "Ingest new data", stale: "Check for stale answers", answer: "Answer", refresh_draft: "Refresh stale answers", freeze: "Freeze at V1" };

function remembered(): string { try { return localStorage.getItem("csa-draft-cli") || "claude"; } catch { return "claude"; } }
function when(value?: string | null) { if (!value) return "—"; const d = new Date(value); return isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }

export function DraftLane({ system, focus = "", investigate }: { system: string; focus?: string; investigate: (query: string) => void }) {
  const [snap, setSnap] = useState<DraftSnapshot | null>(null); const [job, setJob] = useState<ReviewJob | null>(null);
  const [error, setError] = useState(""); const [cli, setCli] = useState(remembered()); const [fresh, setFresh] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(false); const [showLog, setShowLog] = useState(false);
  const poll = useRef<number | undefined>(undefined);

  async function load() {
    try { setSnap(await fetchDraft(system)); }
    catch (e) {
      const message = (e as Error).message;
      setError(message === "Not Found" ? "The evidence workspace server is older than this page and has no draft route yet. Stop it (Ctrl+C in its Terminal) and run csa browse again." : message);
    }
  }
  useEffect(() => { setSnap(null); setJob(null); void load(); return () => window.clearInterval(poll.current); }, [system]);
  useEffect(() => { if (!focus) return; const el = document.getElementById(`draft-row-${focus}`); el?.scrollIntoView({ block: "center" }); }, [focus, snap]);
  useEffect(() => { try { localStorage.setItem("csa-draft-cli", cli); } catch { /* per-viewer convenience only */ } }, [cli]);

  const running = !!job && !TERMINAL.includes(job.state);
  async function run(operation: string, target?: string, options: Record<string, string | boolean> = {}) {
    setError(""); setShowLog(true);
    try {
      const started = await submitJob(system, operation, target, options); setJob(started);
      window.clearInterval(poll.current);
      poll.current = window.setInterval(async () => {
        try {
          const current = await fetchJob(system, started.id); setJob(current);
          if (TERMINAL.includes(current.state)) { window.clearInterval(poll.current); await load(); }
        } catch (e) { window.clearInterval(poll.current); setError((e as Error).message); }
      }, 2000);
    } catch (e) { setError((e as Error).message); }
  }
  function answer(row: DraftSection) { void run("answer", row.number || row.key, { cli, ...(fresh ? { fresh: true } : {}) }); }
  function freeze() { if (confirm("Freeze this assessment at V1?\n\nA baseline copy of the working document is saved and the project switches to the V1 change lane (tracked changes, review, cleanup). The draft lane stops for this project.")) void run("freeze", "v1"); }

  if (!snap) return <section className="page draft-page">{error ? <div className="desk-error" role="alert">{error}</div> : <div className="loading"><span /><strong>Reading the draft state…</strong></div>}</section>;
  if (snap.stage !== "draft") return <section className="page draft-page"><Empty title="This assessment is at V1" text="Changes now go through the V1 change lane: open the Assessment page to author, review in Word and clean up." /></section>;

  const counts = snap.counts || {}; const stale = counts.stale || 0;
  const rows = snap.sections.filter(r => !onlyOpen || r.state === "stale" || r.state === "not-answered");
  const args = (job as (ReviewJob & { display_args?: string[] }) | null)?.display_args || [];
  const jobTarget = job?.operation === "answer" ? args.filter(a => !a.startsWith("-") && a !== "answer")[0] || "" : "";

  return <section className="page draft-page">
    <header className="page-heading draft-heading">
      <div><span>Draft lane · before V1</span><h1>Draft answers</h1><p>Index new data, then answer each subsection from the evidence. Every answer goes straight into the working document as plain text. No change files, review or cleanup until the document reaches V1.</p></div>
      <div className="draft-model"><label><span>Model for answers</span><select value={cli} onChange={e => setCli(e.target.value)} disabled={running}>{CLIS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label><label className="draft-check"><input type="checkbox" checked={fresh} onChange={e => setFresh(e.target.checked)} /> Ask fresh (ignore the saved answer)</label></div>
    </header>

    <div className="draft-actions">
      <button onClick={() => void run("ingest")} disabled={running}><b>1 · Ingest new data</b><small>Index new files, update the evidence matrix, hosts and graph</small></button>
      <button onClick={() => void run("stale")} disabled={running}><b>2 · Check for stale answers</b><small>{snap.stale_checked_at ? `Last checked ${when(snap.stale_checked_at)}` : "Not checked yet"} · no model</small></button>
      <button onClick={() => void run("refresh_draft", undefined, { cli })} disabled={running || !stale}><b>3 · Refresh stale answers{stale ? ` (${stale})` : ""}</b><small>{stale ? `Answer again with ${CLIS.find(c => c.id === cli)?.label}` : "Nothing is stale"}</small></button>
    </div>

    <div className="draft-counts">{(["current", "stale", "answered", "not-answered"] as const).map(k => <div key={k} className={`draft-count draft-${k}`}><strong>{counts[k] || 0}</strong><span>{STATE_LABEL[k]}</span></div>)}<div className="draft-count"><strong>{snap.open_questions.total}</strong><span>Open questions</span></div></div>

    {error && <p className="desk-error" role="alert">{error}</p>}
    {job && <div className={`draft-job draft-job-${job.state}`} role="status"><div><b>{OP_LABEL[job.operation] || job.operation}{jobTarget ? ` ${jobTarget}` : ""}</b><span>{running ? (job.operation === "answer" || job.operation === "refresh_draft" ? "Running — the agent works in its own Terminal window" : "Running…") : job.state === "succeeded" ? "Done" : `Stopped: ${job.state}`}</span></div><div className="draft-job-buttons"><button className="quiet" onClick={() => setShowLog(!showLog)}>{showLog ? "Hide output" : "Show output"}</button>{running && <button className="quiet" onClick={() => void cancelJob(system, job.id)}>Cancel</button>}</div>{showLog && <pre>{(job.stdout_tail || "") + (job.stderr_tail ? "\n" + job.stderr_tail : "") || job.message || "Waiting for output…"}</pre>}</div>}
    {snap.spec_error && <p className="desk-error">Section list unavailable: {snap.spec_error}</p>}

    <section className="decision-desk draft-desk"><header><div><h2>Subsections</h2><p>Answer one subsection at a time. A subsection with unaccepted tracked changes is refused until you accept or reject them in Word.</p></div><label className="draft-check"><input type="checkbox" checked={onlyOpen} onChange={e => setOnlyOpen(e.target.checked)} /> Only what needs an answer</label></header>
      <table className="draft-table"><thead><tr><th>Section</th><th>State</th><th>Last answered</th><th>Open</th><th /></tr></thead><tbody>
        {rows.map(row => <tr key={row.key} id={`draft-row-${row.key}`} className={focus && (focus === row.key || focus === row.number) ? "draft-focus" : ""}>
          <td><b>{row.number}</b> {row.title}<small>{row.key}</small></td>
          <td><span className={`draft-pill draft-${row.state}`}>{STATE_LABEL[row.state] || row.state}</span></td>
          <td>{when(row.answered_at)}</td><td>{row.open || "—"}</td>
          <td><button onClick={() => answer(row)} disabled={running}>{row.state === "not-answered" ? "Answer" : "Answer again"}</button></td>
        </tr>)}
        {!rows.length && <tr><td colSpan={5}>Nothing to show.</td></tr>}
      </tbody></table>
    </section>

    <div className="draft-lower">
      <section className="decision-desk"><header><div><h2>Recent changes</h2><p>What each answer run wrote into the document.</p></div></header>
        {snap.changes.rows.length ? <table className="draft-table"><thead><tr><th>When</th><th>Subsection</th><th>Change</th><th>Open</th></tr></thead><tbody>{snap.changes.rows.map((r, i) => <tr key={i}><td>{r.day.slice(5)} {r.time}</td><td>{r.subsection}</td><td>{r.change}</td><td>{r.open}</td></tr>)}</tbody></table> : <p className="draft-none">No draft runs yet.</p>}
      </section>
      <section className="decision-desk"><header><div><h2>Open questions</h2><p>What the evidence does not answer yet. These feed Discovery Required.</p></div></header>
        {snap.open_questions.groups.length ? <div className="draft-questions">{snap.open_questions.groups.map(g => <details key={g.title} open={snap.open_questions.groups.length <= 3}><summary>{g.title} <span>{g.items.length}</span></summary><ul>{g.items.map((q, i) => <li key={i}><span>{q}</span><button className="quiet" onClick={() => investigate(q.replace(/^\[[BC]\d+\]\s*/, ""))}>Trace</button></li>)}</ul></details>)}</div> : <p className="draft-none">No open questions.</p>}
      </section>
    </div>

    <footer className="draft-freeze"><div><b>Reached V1?</b><span>Freezing saves a baseline copy and switches this project to the V1 change lane (tracked changes, review in Word, cleanup).</span></div><button className="quiet" onClick={freeze} disabled={running}>Freeze at V1…</button></footer>
  </section>;
}
