import { useCallback, useEffect, useState } from "react";
import { authorArtifactUrl, cancelJob, fetchAuthorJob, fetchAuthorSetup, fetchLatestAuthor, submitAuthor } from "../api";
import type { AuthorEvidence, AuthorOutcome, AuthorSetup, ReviewJob } from "../types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
function evidenceLabel(status: string): string {
  const value = status.toUpperCase();
  if (value === "VERIFIED" || value === "INFERRED" || value === "CONFLICTING") return value;
  if (value === "NOT_FOUND" || !value) return "MISSING";
  return "UNSUPPORTED";
}

type Props = {
  system: string;
  section: string;
  openEvidence: (row: AuthorEvidence) => void;
  onProposalReady: () => void;
};

export function AuthorPanel({ system, section, openEvidence, onProposalReady }: Props) {
  const [setup, setSetup] = useState<AuthorSetup | null>(null);
  const [job, setJob] = useState<ReviewJob | null>(null);
  const [outcome, setOutcome] = useState<AuthorOutcome | null>(null);
  const [cards, setCards] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const current = await fetchAuthorSetup(system, section);
      setSetup(current);
      try {
        const latest = await fetchLatestAuthor(system, section);
        setJob(latest.job); setOutcome(latest.outcome);
      } catch { setJob(null); setOutcome(null); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Author setup failed"); }
  }, [system, section]);

  useEffect(() => { setSetup(null); setJob(null); setOutcome(null); void load(); }, [load]);
  useEffect(() => {
    if (!job || TERMINAL.has(job.state)) return;
    const timer = window.setTimeout(async () => {
      try {
        const result = await fetchAuthorJob(system, section, job.id);
        setJob(result.job); setOutcome(result.outcome);
        if (TERMINAL.has(result.job.state)) {
          setSetup(await fetchAuthorSetup(system, section));
          if (result.outcome.routed_to_editor && result.outcome.current) onProposalReady();
        }
      } catch (reason) { setError(reason instanceof Error ? reason.message : "Author job status failed"); }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [job?.id, job?.state, system, section, onProposalReady]);

  const start = async () => {
    setError(""); setOutcome(null);
    try { const result = await submitAuthor(system, section, cards); setJob(result.job); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Author run could not start"); }
  };
  const stop = async () => {
    if (!job) return;
    try { await cancelJob(system, job.id); setJob({ ...job, state: "cancelled" }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Author run could not be stopped"); }
  };
  const running = Boolean(job && !TERMINAL.has(job.state));

  return <section className="author-panel" aria-label="AI author workflow">
    <header><div><span>Evidence-grounded drafting</span><h3>AI Author</h3></div><span className="author-no-apply">Proposal only · no apply</span></header>
    {!setup ? <p>{error || "Loading author setup…"}</p> : <>
      <div className="author-context">
        <div><small>System</small><strong>{setup.project_key}</strong></div>
        <div><small>Section</small><strong>{setup.visible_number} · {setup.stable_key}</strong></div>
        <div><small>Registered route</small><strong>{cards ? setup.model_route.answer : setup.model_route.author}</strong></div>
        <div><small>Existing proposal</small><strong>{setup.existing_proposal.exists ? `${setup.existing_proposal.file} · ${setup.existing_proposal.validation}` : "None"}</strong></div>
      </div>
      <label className="author-card-toggle"><input type="checkbox" checked={cards} onChange={event => setCards(event.target.checked)} />Build a section card and answer sheet first</label>
      {cards && <div className="author-cards"><strong>Selected card questions</strong>{setup.selected_cards.length ? <ul>{setup.selected_cards.map(card => <li key={card.id}><b>{card.id}</b>{card.question}</li>)}</ul> : <p>The framework will generate the section card when the run starts.</p>}</div>}
      <ol className="author-stages">{(outcome?.stages || setup.stages).map(stage => <li key={stage.key} className={`author-stage-${stage.state.toLowerCase().replaceAll("_", "-")}`}><i /><span><strong>{stage.label}</strong><small>{stage.state}</small></span></li>)}</ol>
      <div className="author-artifacts"><strong>Run artifacts</strong><div>{setup.artifacts.map(item => item.exists ? <a key={item.key} href={authorArtifactUrl(system, section, item.key)} target="_blank" rel="noreferrer">{item.label}</a> : <span key={item.key}>{item.label} · pending</span>)}</div></div>
      <div className="author-evidence"><header><strong>Evidence set</strong><span>{setup.evidence.length} claim{setup.evidence.length === 1 ? "" : "s"}</span></header>{setup.evidence.length ? setup.evidence.map(row => { const label = evidenceLabel(row.status); return <button key={row.evidence_id} type="button" onClick={() => openEvidence(row)}><b>{row.evidence_id}</b><span>{row.claim || row.question}</span><em className={`author-evidence-${label.toLowerCase()}`}>{label}</em></button>; }) : <p>No section evidence is currently selected. The run may return an incomplete-evidence state.</p>}</div>
      {outcome && <div className={`author-outcome author-outcome-${outcome.state.toLowerCase()}`} role="status"><strong>{outcome.state}</strong>{!outcome.current && <p>This result is stale for the current document or section inputs.</p>}{outcome.non_success_reasons.map((reason, index) => <p key={index}>{reason}</p>)}{outcome.warnings.map((warning, index) => <p key={`warning-${index}`}>{warning}</p>)}</div>}
      {error && <p className="rv-error" role="alert">{error}</p>}
      <footer><button type="button" disabled={running} onClick={start}>{setup.prior_runs ? "Retry authoring" : "Run authoring"}</button>{running && <button type="button" className="quiet" onClick={stop}>Stop</button>}{outcome?.routed_to_editor && outcome.current && <><button type="button" className="quiet" onClick={() => document.querySelector(".inspector-proposal")?.scrollIntoView({ behavior: "smooth" })}>Edit proposal</button><button type="button" className="quiet" onClick={() => document.querySelector(".proposal-actions")?.scrollIntoView({ behavior: "smooth" })}>Validate proposal</button></>}</footer>
    </>}
  </section>;
}
