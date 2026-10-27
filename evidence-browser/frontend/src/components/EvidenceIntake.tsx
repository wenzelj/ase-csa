import { useEffect, useRef, useState } from "react";
import { api, cancelJob, fetchIntake, fetchJob, reviewEvidence, submitJob } from "../api";
import { AGENT_CLIS, rememberedAgentCli, rememberAgentCli } from "../agentClis";
import type { IntakeCandidate, IntakeEvidenceRow, IntakeFile, IntakeSnapshot, ReviewJob } from "../types";
import { deriveIntakeSteps, resumableJob, type StepKey } from "./intakeSteps";

const TERMINAL = ["succeeded", "failed", "cancelled", "interrupted"];
const OP_LABEL: Record<string, string> = { ingest: "Ingest new data", intake: "Evidence agent", gap_check: "Check open questions", resolve_gaps: "Resolve evidence and update answers" };
const VERDICT: Record<string, string> = { ANSWERED: "Answered", CANDIDATES: "Possible answer found", NOT_FOUND: "Not found" };

function when(value?: string | null) { if (!value) return "—"; const d = new Date(value); return isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }
function name(path: string) { return path.split("/").pop() || path; }

type Props = {
  system: string; draftStage: boolean; refreshKey: number;
  openEvidence: (row: IntakeEvidenceRow) => void; writeFact: (candidate: IntakeCandidate) => void;
  openSection: (key: string) => void;
};

export function EvidenceIntake({ system, draftStage, refreshKey, openEvidence, writeFact, openSection }: Props) {
  const [snap, setSnap] = useState<IntakeSnapshot | null>(null); const [job, setJob] = useState<ReviewJob | null>(null);
  const [error, setError] = useState(""); const [cli, setCli] = useState(rememberedAgentCli()); const [showLog, setShowLog] = useState(false);
  const [onlyFound, setOnlyFound] = useState(true);
  const poll = useRef<number | undefined>(undefined);

  async function load() {
    try { setSnap(await fetchIntake(system)); }
    catch (e) {
      const message = (e as Error).message;
      setError(message === "Not Found" ? "The evidence workspace server is older than this page. Stop it (Ctrl+C in its Terminal) and run csa browse again." : message);
    }
  }
  function watch(id: string) {
    window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const current = await fetchJob(system, id); setJob(current);
        if (TERMINAL.includes(current.state)) { window.clearInterval(poll.current); await load(); }
      } catch (e) { window.clearInterval(poll.current); setError((e as Error).message); }
    }, 2000);
  }
  async function resume() {
    try { const live = resumableJob((await api<{ jobs: ReviewJob[] }>(`/api/systems/${system}/jobs`)).jobs); if (live) { setJob(live); watch(live.id); } }
    catch { /* no job list: nothing to resume */ }
  }
  useEffect(() => { setSnap(null); setJob(null); void load(); void resume(); return () => window.clearInterval(poll.current); }, [system]);
  useEffect(() => { if (refreshKey) void load(); }, [refreshKey]);
  useEffect(() => { rememberAgentCli(cli); }, [cli]);

  async function run(operation: string, options: Record<string, string | boolean> = {}) {
    setError(""); setShowLog(true);
    try {
      const started = await submitJob(system, operation, undefined, options); setJob(started); watch(started.id);
    } catch (e) { setError((e as Error).message); }
  }
  async function notAnAnswer(c: IntakeCandidate) {
    setError("");
    try { await reviewEvidence(system, c.evidence_id, "rejected", `read for ${c.dr_id}: does not answer the question`); await load(); }
    catch (e) { setError((e as Error).message); }
  }

  if (!snap) return <section className="page draft-page intake-page">{error ? <div className="desk-error" role="alert">{error}</div> : <div className="loading"><span /><strong>Reading what came in…</strong></div>}</section>;

  const { steps, next, busy } = deriveIntakeSteps(snap, job);
  const running = !!job && !TERMINAL.includes(job.state);
  const rec = snap.intake;
  const questions = (snap.gap_check?.questions || []).filter(q => !onlyFound || q.verdict !== "NOT_FOUND");
  const files: IntakeFile[] = rec ? [...rec.added, ...rec.changed] : [];
  const action = (key: StepKey) => ({
    ingest: <button onClick={() => void run("ingest")} disabled={busy}>Ingest new data</button>,
    documents: <span className="intake-action"><select value={cli} onChange={e => setCli(e.target.value)} disabled={busy} aria-label="Agent for evidence intake">{AGENT_CLIS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select><button onClick={() => void run("intake", { cli })} disabled={busy || !rec}>Run the evidence agent</button></span>,
    gaps: <button onClick={() => void run("gap_check")} disabled={busy}>Check open questions</button>,
    settle: <span className="intake-action"><select value={cli} onChange={e => setCli(e.target.value)} disabled={busy} aria-label="Agent for evidence settlement">{AGENT_CLIS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select><button onClick={() => void run("resolve_gaps", { cli })} disabled={busy || !snap.candidates.length}>Resolve and update answers</button></span>, use: null,
  })[key];

  return <section className="page draft-page intake-page">
    <header className="page-heading"><div><span>Evidence intake</span><h1>Bring new data in and use it</h1><p>New files go into the index first. The evidence agent records what the sources state, checks open questions against the matrix and index, settles each finding from its source, and updates the affected answers. The final step can change the working document through the normal framework pipeline.</p></div></header>

    <ol className="intake-steps">{steps.map((s, i) => <li key={s.key} className={`intake-step intake-${s.status}${s.key === next ? " intake-next" : ""}`}>
      <span className="intake-num">{i + 1}</span><div><b>{s.title}</b><small>{s.detail || " "}</small></div>{action(s.key)}
    </li>)}</ol>

    <div className="draft-counts">
      <div className="draft-count"><strong>{snap.matrix.live ?? snap.matrix.rows}</strong><span>Evidence rows{snap.matrix.rejected ? ` (${snap.matrix.rejected} rejected not counted)` : ""}</span></div>
      <div className="draft-count"><strong>{snap.matrix.by_status.VERIFIED || 0}</strong><span>Verified</span></div>
      <div className="draft-count draft-stale"><strong>{snap.candidates.length}</strong><span>To settle</span></div>
      <div className="draft-count"><strong>{snap.graph.nodes} / {snap.graph.edges}</strong><span>Graph nodes / links</span></div>
      <div className="draft-count"><strong>{snap.stale}</strong><span>Stale answers</span></div>
    </div>

    {snap.sync && !snap.sync.ok && <div className="intake-warn" role="alert"><b>{snap.sync.failed ? "The host files did not rebuild" : "The host files are older than the evidence"}</b><p>{snap.sync.failed ? `${snap.sync.last?.hosts_index || "Graph sync failed"}. ` : ""}Hosts, links, flows and per-host evidence shown elsewhere in the workspace may be out of date. Run Ingest new data{snap.sync.failed ? " once the error is fixed" : ""}.</p></div>}
    {error && <p className="desk-error" role="alert">{error}</p>}
    {job && <div className={`draft-job draft-job-${job.state}`} role="status"><div><b>{OP_LABEL[job.operation] || job.operation}</b><span>{running ? "Running…" : job.state === "succeeded" ? "Done" : `Stopped: ${job.state}`}</span></div><div className="draft-job-buttons"><button className="quiet" onClick={() => setShowLog(!showLog)}>{showLog ? "Hide output" : "Show output"}</button>{running && <button className="quiet" onClick={() => void cancelJob(system, job.id).then(() => fetchJob(system, job.id)).then(setJob)}>Stop</button>}</div>{showLog && <pre>{[job.stdout_tail, job.stderr_tail].filter(Boolean).join("\n") || "No output yet."}</pre>}</div>}

    <section className="decision-desk"><header><div><h2>1 · What came in</h2><p>{rec ? `Last ingest that brought something in: ${when(rec.built_at_utc)}.` : "Run Ingest new data after adding files to the project's discovery folders."}{snap.nothing_new_since ? ` The index was refreshed since then with nothing new.` : ""}</p></div></header>
      {rec && rec.unreadable.length > 0 && <div className="intake-warn" role="note"><b>Not readable: supply a text or PDF copy</b><ul>{rec.unreadable.map(f => <li key={f.rel_path}>{name(f.rel_path)} <small>{f.reason}</small></li>)}</ul></div>}
      {files.length ? <table className="draft-table"><thead><tr><th>File</th><th>Change</th><th>Index</th></tr></thead><tbody>{files.map(f => <tr key={f.rel_path}><td>{name(f.rel_path)}<small>{f.rel_path}</small></td><td>{rec!.added.includes(f) ? "New" : "Changed"}</td><td>{f.status === "indexed" ? "Readable" : f.status}<small>{f.reason}</small></td></tr>)}</tbody></table> : <p className="draft-none">{rec ? "Only removals in the last intake." : "Nothing ingested yet."}</p>}
      {rec && rec.removed.length > 0 && <p className="draft-none">Removed from the index: {rec.removed.map(name).join(", ")}</p>}
    </section>

    {((snap.refresh?.recheck.length || 0) + (snap.refresh?.retired.length || 0) + (snap.hosts?.to_classify.length || 0)) > 0 && <section className="decision-desk"><header><div><h2>Keeping the evidence true</h2><p>What the last ingest found about evidence already recorded. Re-check rows are handled by the evidence agent (step 2); hosts to classify need a role, site and scope in the project's roles.csv or an inventory.</p></div></header>
      {!!snap.refresh?.recheck.length && <><h3>To re-check ({snap.refresh.recheck.length})</h3><table className="draft-table"><thead><tr><th>ID</th><th>Why</th><th>Claim</th></tr></thead><tbody>{snap.refresh.recheck.map(r => <tr key={r.evidence_id}><td>{r.evidence_id}</td><td>{r.why}<small>{name(r.file)}</small></td><td>{r.claim}</td></tr>)}</tbody></table></>}
      {!!snap.refresh?.retired.length && <details className="intake-summary"><summary>Retired by the last ingest ({snap.refresh.retired.length})</summary><ul>{snap.refresh.retired.map(r => <li key={r.evidence_id}>{r.evidence_id}: {r.reason}</li>)}</ul></details>}
      {!!snap.hosts?.to_classify.length && <><h3>Hosts named only in documents ({snap.hosts.to_classify.length})</h3><table className="draft-table"><thead><tr><th>Host</th><th>Address</th><th>Evidence</th></tr></thead><tbody>{snap.hosts.to_classify.map(h => <tr key={h.host}><td>{h.host}</td><td>{h.ips || "—"}</td><td>{h.evidence_ids.split(";").join(", ")}</td></tr>)}</tbody></table></>}
      {!!snap.hosts?.unnamed_addresses && <p className="draft-none">{snap.hosts.unnamed_addresses} addresses are still seen only by IP (hosts/addresses.csv).</p>}
    </section>}

    <section className="decision-desk"><header><div><h2>2 · New evidence</h2><p>Rows added to the evidence matrix since that ingest.</p></div></header>
      {snap.matrix.added_since_intake.length ? <table className="draft-table"><thead><tr><th>ID</th><th>Status</th><th>Claim</th><th /></tr></thead><tbody>{snap.matrix.added_since_intake.map(r => <tr key={r.evidence_id}><td>{r.evidence_id}</td><td><span className="draft-pill">{r.status}</span></td><td>{r.claim}<small>{r.source_title}</small></td><td><button className="quiet" onClick={() => openEvidence(r)}>Open source</button></td></tr>)}</tbody></table> : <p className="draft-none">No new rows yet.</p>}
      {snap.agent_summary && <details className="intake-summary"><summary>Evidence agent summary ({when(snap.agent_summary.modified_at)})</summary><pre>{snap.agent_summary.text}</pre></details>}
    </section>

    <section className="decision-desk"><header><div><h2>3 · Open questions</h2><p>{snap.gap_check ? `Checked ${when(snap.gap_check.checked_at)}.` : "Not checked yet."}</p></div><label className="draft-check"><input type="checkbox" checked={onlyFound} onChange={e => setOnlyFound(e.target.checked)} /> Only questions with something found</label></header>
      {questions.length ? <table className="draft-table"><thead><tr><th>Section</th><th>Question</th><th>Result</th><th>Evidence</th></tr></thead><tbody>{questions.map(q => <tr key={q.dr_id}><td><b>{q.number}</b><small>{q.dr_id}</small></td><td>{q.text}</td><td><span className={`draft-pill intake-${q.verdict.toLowerCase()}`}>{VERDICT[q.verdict] || q.verdict}</span></td><td>{q.evidence_ids.join(", ") || "—"}</td></tr>)}</tbody></table> : <p className="draft-none">{snap.gap_check ? "Nothing found for the open questions." : "Run Check open questions."}</p>}
    </section>

    <section className="decision-desk"><header><div><h2>4 · Settle what was found</h2><p>The framework can read every candidate in its original source, record supported facts or scoped gaps, and rerun the affected answers. The individual controls remain available for recovery or manual review.</p></div></header>
      {snap.candidates.length ? <div className="intake-cards">{snap.candidates.map(c => <article key={c.evidence_id} className="intake-card">
        <header><b>{c.dr_id}</b><span>{c.evidence_id}</span></header>
        <p className="intake-question">{(c.question || "").replace(/^DR-[^:]+:\s*/, "")}</p>
        <blockquote>{c.evidence_excerpt}</blockquote>
        <small>{c.source_title}{c.page_or_location ? ` · ${c.page_or_location}` : ""}</small>
        <footer><button className="quiet" onClick={() => openEvidence(c)}>Open source</button><button className="quiet" onClick={() => void notAnAnswer(c)} disabled={busy}>Not an answer</button><button onClick={() => writeFact(c)} disabled={busy}>Write the fact</button></footer>
      </article>)}</div> : <p className="draft-none">Nothing to settle.</p>}
    </section>

    <section className="decision-desk"><header><div><h2>5 · Use it in the document</h2><p>{draftStage ? "These subsections have new evidence for an open question. Answer them again on Draft answers." : "These subsections have new evidence for an open question. Author them on the Assessment page."}</p></div></header>
      {snap.gap_check?.affected.length ? <table className="draft-table"><thead><tr><th>Subsection</th><th>Answered</th><th>To settle</th><th /></tr></thead><tbody>{snap.gap_check.affected.map(a => <tr key={a.key}><td><b>{a.number}</b> {a.title}<small>{a.key}</small></td><td>{a.answered}</td><td>{a.candidates}</td><td><button onClick={() => openSection(a.key)}>{draftStage ? "Open in Draft answers" : "Open in Assessment"}</button></td></tr>)}</tbody></table> : <p className="draft-none">Nothing new to answer yet.</p>}
    </section>
  </section>;
}
