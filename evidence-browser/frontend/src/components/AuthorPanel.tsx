import { useCallback, useEffect, useState } from "react";
import { authorArtifactUrl, cancelJob, fetchAuthorJob, fetchAuthorSetup, fetchLatestAuthor, submitAuthor } from "../api";
import type { AuthorEvidence, AuthorOutcome, AuthorSetup, ReviewJob, WriterPolicy } from "../types";

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
  const [legacy, setLegacy] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [checkAnswers, setCheckAnswers] = useState(false);
  const [writerPolicy, setWriterPolicy] = useState<WriterPolicy>("auto");
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
    try { const result = await submitAuthor(system, section, { legacy, fresh, check_answers: checkAnswers, writer_policy: writerPolicy }); setJob(result.job); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Author run could not start"); }
  };
  const stop = async () => {
    if (!job) return;
    try { await cancelJob(system, job.id); setJob({ ...job, state: "cancelled" }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Author run could not be stopped"); }
  };
  const running = Boolean(job && !TERMINAL.has(job.state));
  const view = outcome || setup!;
  const metric = (key: string, suffix = "") => `${view?.run_metrics[key] ?? 0}${suffix}`;

  return <section className="author-panel" aria-label="AI author workflow">
    <header><div><span>Evidence-grounded drafting</span><h3>AI Author</h3></div><span className="author-no-apply">Proposal only · no apply</span></header>
    {!setup ? <p>{error || "Loading author setup…"}</p> : <>
      <div className="author-context">
        <div><small>System</small><strong>{setup.project_key}</strong></div>
        <div><small>Section</small><strong>{setup.visible_number} · {setup.stable_key}</strong></div>
        <div><small>Authoring route</small><strong>{outcome?.actual_route === "legacy" || legacy ? setup.model_route.legacy : setup.model_route.cards}</strong></div>
        <div><small>Existing proposal</small><strong>{setup.existing_proposal.exists ? `${setup.existing_proposal.file} · ${setup.existing_proposal.validation}` : "None"}</strong></div>
      </div>
      <details className="author-options"><summary>Authoring controls</summary><div>
        <label><input type="checkbox" checked={legacy} onChange={event => setLegacy(event.target.checked)} />Use legacy author workflow</label>
        <label><input type="checkbox" checked={fresh} disabled={legacy} onChange={event => setFresh(event.target.checked)} />Generate every answer again</label>
        <label><input type="checkbox" checked={checkAnswers} disabled={legacy} onChange={event => setCheckAnswers(event.target.checked)} />Run an advisory answer check</label>
        <label>Writer decision<select value={writerPolicy} onChange={event => setWriterPolicy(event.target.value as WriterPolicy)}><option value="auto">Let validation decide</option><option value="force">Always run writer</option><option value="skip">Skip writer</option></select></label>
      </div></details>
      {!legacy && <div className="author-cards"><strong>Questions this section must answer</strong>{setup.selected_cards.length ? <ul>{setup.selected_cards.map(card => <li key={card.id}><b>{card.id}</b>{card.question}</li>)}</ul> : <p>The framework will prepare the questions when the run starts.</p>}</div>}
      <ol className="author-stages">{view.stages.map(stage => <li key={stage.key} className={`author-stage-${stage.state.toLowerCase().replaceAll("_", "-")}`}><i /><span><strong>{stage.label}</strong><small>{stage.state}</small><p>{stage.reason}</p></span></li>)}</ol>
      <section className="author-reuse" aria-label="Answer reuse decisions"><header><div><strong>Answer reuse</strong><p>The framework decides which answers remain trustworthy.</p></div><b className={`cache-${view.cache_status.toLowerCase()}`}>{view.cache_status}</b></header>{view.question_decisions.length ? <div>{view.question_decisions.map(row => <article key={row.question_id}><code>{row.question_id}</code><span><strong>{row.question}</strong><small>{row.reason}</small></span><em>{row.decision}</em></article>)}</div> : <p>The question card has not been prepared.</p>}</section>
      <section className="author-facts" aria-label="Established facts"><header><div><strong>Facts already established</strong><p>Reusable conclusions remain connected to the section and evidence that established them.</p></div><span>{view.established_facts.length}</span></header>{view.established_facts.length ? view.established_facts.map((fact, index) => <article key={`${fact.origin_section}-${fact.question_id}-${index}`} className={fact.validation_state}><i /><div><strong>{fact.fact}</strong><small>From {fact.origin_section}, question {fact.question_id}{fact.basis ? ` · ${fact.basis}` : ""}</small><div>{fact.sources.map(source => <button key={source.evidence_id} type="button" onClick={() => openEvidence({ evidence_id: source.evidence_id, status: source.status, review_state: fact.validation_state, question: fact.question_id, claim: fact.fact, source_title: source.source_title, page_or_location: source.page_or_location })}><b>{source.evidence_id}</b><span>{source.source_title || "Source unavailable"}{source.page_or_location ? `, ${source.page_or_location}` : ""}</span></button>)}</div></div><em>{fact.reuse_status}</em></article>) : <p>No prior section facts are required for these questions.</p>}</section>
      <dl className="author-run-summary"><div><dt>Elapsed</dt><dd>{metric("total_seconds", "s")}</dd></div><div><dt>Evidence read</dt><dd>{metric("read_kb", " KB")}</dd></div><div><dt>Commands</dt><dd>{metric("commands")}</dd></div><div><dt>Model tokens</dt><dd>{metric("tokens")}</dd></div><div><dt>Writer</dt><dd>{view.writer_decision.state}</dd><small>{view.writer_decision.reason}</small></div><div><dt>Rules</dt><dd>{view.rules_digest.sha256 ? view.rules_digest.sha256.slice(0, 8) : "Unavailable"}</dd><small>{view.rules_digest.bytes} bytes</small></div></dl>
      {(view.autofixes.length > 0 || (outcome?.artifact_changes.length ?? 0) > 0) && <section className="author-audit"><strong>What the run changed</strong>{view.autofixes.map((fix, index) => <p key={`${fix.code}-${index}`}><b>{fix.code}</b>{fix.edit_id && <code>{fix.edit_id}</code>}<span>{fix.message}</span></p>)}{outcome?.artifact_changes.map(change => <p key={change.key}><b>{change.change}</b><code>{change.label}</code></p>)}</section>}
      <div className="author-artifacts"><strong>Run artifacts</strong><div>{setup.artifacts.map(item => item.exists ? <a key={item.key} href={authorArtifactUrl(system, section, item.key)} target="_blank" rel="noreferrer">{item.label}</a> : <span key={item.key}>{item.label} · pending</span>)}</div></div>
      <div className="author-evidence"><header><strong>Evidence set</strong><span>{setup.evidence.length} claim{setup.evidence.length === 1 ? "" : "s"}</span></header>{setup.evidence.length ? setup.evidence.map(row => { const label = evidenceLabel(row.status); return <button key={row.evidence_id} type="button" onClick={() => openEvidence(row)}><b>{row.evidence_id}</b><span>{row.claim || row.question}</span><em className={`author-evidence-${label.toLowerCase()}`}>{label}</em></button>; }) : <p>No section evidence is currently selected. The run may return an incomplete-evidence state.</p>}</div>
      {outcome && <div className={`author-outcome author-outcome-${outcome.state.toLowerCase()}`} role="status"><strong>{outcome.state}</strong>{!outcome.current && <p>This result is stale for the current document or section inputs.</p>}{outcome.non_success_reasons.map((reason, index) => <p key={index}>{reason}</p>)}{outcome.warnings.map((warning, index) => <p key={`warning-${index}`}>{warning}</p>)}</div>}
      {error && <p className="rv-error" role="alert">{error}</p>}
      <footer><button type="button" disabled={running || setup.lock_state.locked} onClick={start}>{setup.prior_runs ? "Retry authoring" : "Run authoring"}</button>{setup.lock_state.locked && <span role="status">{setup.lock_state.detail}</span>}{running && <button type="button" className="quiet" onClick={stop}>Stop</button>}{outcome?.routed_to_editor && outcome.current && <><button type="button" className="quiet" onClick={() => document.querySelector(".inspector-proposal")?.scrollIntoView({ behavior: "smooth" })}>Edit proposal</button><button type="button" className="quiet" onClick={() => document.querySelector(".proposal-actions")?.scrollIntoView({ behavior: "smooth" })}>Validate proposal</button></>}</footer>
    </>}
  </section>;
}
