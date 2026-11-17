import { useEffect, useState } from "react";
import { applyImprove, cancelJob, discardImprove, fetchImprove, fetchImproveSection, fetchJob, submitJob } from "../api";
import { AGENT_CLIS, rememberedAgentCli, rememberAgentCli } from "../agentClis";
import type { ImproveDetail, ImproveSection, ImproveSnapshot, ReviewJob } from "../types";
import { Empty, Loading } from "./ui";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

export function improveStateLabel(state: string): string {
  return ({ "not-started": "Not started", "context-ready": "Context ready", "proposal-ready": "Proposal ready", proposed: "Proposal ready", failed: "Last run failed", interrupted: "Last run interrupted", unavailable: "Unavailable" } as Record<string, string>)[state] || state;
}

function when(value?: string | null) { if (!value) return "—"; const date = new Date(value); return isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }

type DiffKind = "same" | "removed" | "added";
type DiffPart = { text: string; kind: DiffKind };

function proposedAnswer(current: string, proposal?: Record<string, unknown> | null): string {
  let answer = current;
  for (const edit of (proposal?.edits as Record<string, unknown>[] | undefined) || []) {
    const operation = String(edit.operation || "");
    const before = String(edit.before || "");
    const after = String(edit.after || "");
    if (!before || operation === "keep") continue;
    if (operation === "insert_after") answer = answer.includes(before) ? answer.replace(before, `${before}${after}`) : answer;
    else answer = answer.includes(before) ? answer.replace(before, after) : answer;
  }
  return answer;
}

function applyEdits(text: string, proposal?: Record<string, unknown> | null): string {
  let answer = text;
  for (const edit of (proposal?.edits as Record<string, unknown>[] | undefined) || []) {
    const operation = String(edit.operation || "");
    const before = String(edit.before || "");
    const after = String(edit.after || "");
    if (!before || operation === "keep" || !answer.includes(before)) continue;
    answer = operation === "insert_after" ? answer.replace(before, `${before}${after}`) : answer.replace(before, after);
  }
  return answer;
}

function diffParts(oldText: string, newText: string): { old: DiffPart[]; next: DiffPart[] } {
  const oldTokens = oldText.match(/\s+|[^\s]+/g) || [];
  const newTokens = newText.match(/\s+|[^\s]+/g) || [];
  const rows = oldTokens.length + 1, cols = newTokens.length + 1;
  const dp = Array.from({ length: rows }, () => new Array<number>(cols).fill(0));
  for (let i = oldTokens.length - 1; i >= 0; i--) for (let j = newTokens.length - 1; j >= 0; j--) dp[i][j] = oldTokens[i] === newTokens[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const old: DiffPart[] = [], next: DiffPart[] = [];
  let i = 0, j = 0;
  while (i < oldTokens.length || j < newTokens.length) {
    if (i < oldTokens.length && j < newTokens.length && oldTokens[i] === newTokens[j]) { old.push({ text: oldTokens[i++], kind: "same" }); next.push({ text: newTokens[j++], kind: "same" }); }
    else if (j < newTokens.length && (i === oldTokens.length || dp[i][j + 1] >= dp[i + 1][j])) next.push({ text: newTokens[j++], kind: "added" });
    else old.push({ text: oldTokens[i++], kind: "removed" });
  }
  return { old, next };
}

function DiffText({ parts }: { parts: DiffPart[] }) { return <>{parts.map((part, index) => part.kind === "same" ? <span key={index}>{part.text}</span> : <mark key={index} className={`improve-diff-${part.kind}`}>{part.text}</mark>)}</>; }

function ReviewBlock({ block, proposal }: { block: { kind?: string; text?: string; rows?: string[][] }; proposal?: Record<string, unknown> | null }) {
  const oldRows = block.rows || [];
  const nextRows = oldRows.map(row => row.map(cell => applyEdits(cell, proposal)));
  const oldText = block.text || "";
  const nextText = oldRows.length ? nextRows.map(row => row.join(" | ")).join("\n") : applyEdits(oldText, proposal);
  const changed = oldText !== nextText || JSON.stringify(oldRows) !== JSON.stringify(nextRows);
  return <article className="improve-review-block">
    <div className="improve-block-heading"><span>{block.kind === "table" ? "Question set" : "Subsection detail"}</span>{changed && <b>Changed</b>}</div>
    <div className="improve-diff-grid">
      <div><h4>Current answer</h4>{oldRows.length ? <table className="improve-answer-table"><tbody>{oldRows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci}><DiffText parts={diffParts(cell, nextRows[ri]?.[ci] || cell).old} /></td>)}</tr>)}</tbody></table> : <div className="improve-answer"><DiffText parts={diffParts(oldText, nextText).old} /></div>}</div>
      <div><h4>New answer</h4>{oldRows.length ? <table className="improve-answer-table"><tbody>{nextRows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci}><DiffText parts={diffParts(oldRows[ri]?.[ci] || "", cell).next} /></td>)}</tr>)}</tbody></table> : <div className="improve-answer"><DiffText parts={diffParts(oldText, nextText).next} /></div>}</div>
    </div>
  </article>;
}

export function ImproveLane({ system, onBack }: { system: string; onBack?: () => void }) {
  const [snapshot, setSnapshot] = useState<ImproveSnapshot | null>(null);
  const [selected, setSelected] = useState<ImproveSection | null>(null);
  const [detail, setDetail] = useState<ImproveDetail | null>(null);
  const [job, setJob] = useState<ReviewJob | null>(null);
  const [cli, setCli] = useState(rememberedAgentCli());
  const [error, setError] = useState("");

  async function load() {
    try { const next = await fetchImprove(system); setSnapshot(next); const row = selected ? next.sections.find(item => item.key === selected.key) : next.sections.find(item => item.eligible); if (row) { setSelected(row); setDetail(await fetchImproveSection(system, row.key)); } }
    catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { setSnapshot(null); setSelected(null); setDetail(null); void load(); }, [system]);

  async function choose(row: ImproveSection) {
    setSelected(row); setError("");
    try { setDetail(await fetchImproveSection(system, row.key)); } catch (e) { setError((e as Error).message); }
  }
  async function findImprovement() {
    if (!selected) return;
    setError("");
    try {
      const started = await submitJob(system, "improve", selected.key, { cli }); setJob(started);
      const poll = async () => { const current = await fetchJob(system, started.id); setJob(current); if (TERMINAL.has(current.state)) { await load(); } else window.setTimeout(poll, 1500); };
      window.setTimeout(poll, 500);
    } catch (e) { setError((e as Error).message); }
  }
  async function apply() {
    if (!selected || !detail?.proposal || !window.confirm("Apply this bounded improvement to the working document?")) return;
    try { await applyImprove(system, selected.key); await load(); } catch (e) { setError((e as Error).message); }
  }
  async function discard() {
    if (!selected || !detail?.proposal) return;
    try { await discardImprove(system, selected.key); await load(); } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { rememberAgentCli(cli); }, [cli]);

  if (!snapshot) return <section className="page improve-page">{error ? <div className="desk-error" role="alert">{error}</div> : <Loading />}</section>;
  if (snapshot.stage !== "draft") return <section className="page improve-page"><Empty title="Improve is currently draft-stage only" text="V1 tracked-change integration is a separate future lane." /></section>;
  const running = !!job && !TERMINAL.has(job.state);
  const currentText = detail?.current?.text || "";
  const nextText = proposedAnswer(currentText, detail?.proposal);
  const diff = diffParts(currentText, nextText);
  const reviewBlocks = detail?.current?.blocks?.length ? detail.current.blocks : [{ kind: "paragraph", text: currentText }];
  return <section className="page improve-page">
    <header className="page-heading"><div><span>Incremental repair · separate from Draft answers</span><h1>Improve answers</h1><p>Inspect the answer already in the document, address named gaps and preserve supported content. Improve never rebuilds a subsection from a fresh card.</p></div><label><span>Agent for improvement</span><select value={cli} onChange={e => setCli(e.target.value)} disabled={running}>{AGENT_CLIS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>{onBack && <button className="quiet" onClick={onBack}>Back to workspace</button>}</header>
    {error && <p className="desk-error" role="alert">{error}</p>}
    {job && <div className={`draft-job draft-job-${job.state}`} role="status"><div><b>Improve proposal</b><span>{running ? "Finding a bounded improvement…" : job.state === "succeeded" ? "Proposal ready" : `Stopped: ${job.state}`}</span></div>{running && <button className="quiet" onClick={() => void cancelJob(system, job.id)}>Cancel</button>}</div>}
    <div className="improve-layout"><section className="decision-desk"><header><div><h2>Answered subsections</h2><p>{snapshot.eligible_count} eligible · {snapshot.proposal_count} proposal(s) ready</p></div><button className="quiet" onClick={() => void load()}>Refresh</button></header><table className="draft-table"><thead><tr><th>Section</th><th>Improve state</th><th>Rating</th></tr></thead><tbody>{snapshot.sections.map(row => <tr key={row.key} className={selected?.key === row.key ? "draft-focus" : ""}><td><button className="table-link" disabled={!row.eligible} onClick={() => void choose(row)}><b>{row.number}</b> {row.title}<small>{row.key}</small></button></td><td>{row.eligible ? improveStateLabel(row.improve.state) : row.improve.reason}</td><td>{row.rating?.latest?.toFixed?.(1) || "—"}</td></tr>)}</tbody></table></section>
      <section className="decision-desk improve-detail"><header><div><h2>{selected ? `${selected.number} ${selected.title}` : "Choose a subsection"}</h2><p>{selected ? improveStateLabel(selected.improve.state) : "Only existing answers can be improved."}</p></div><span>{detail?.proposal && <><button className="quiet" onClick={() => void discard()}>Discard</button><button onClick={() => void apply()}>Apply improvement</button></>}</span><button disabled={!selected || running} onClick={() => void findImprovement()}>Find improvement with {AGENT_CLIS.find(c => c.id === cli)?.label || cli}</button></header>{detail?.status === "UNAVAILABLE" && <Empty title="Not available" text={detail.message || "No answer is present."} />}{detail?.status === "OK" && <><div className="improve-comparison"><header><div><h3>Review the answer change</h3><p>Each question and subsection detail is separated below. Green text is proposed; red text is removed.</p></div><span className={nextText === currentText ? "improve-no-change" : "improve-change-count"}>{nextText === currentText ? "No text change" : "Text changed"}</span></header><div className="improve-review-blocks">{reviewBlocks.map((block, index) => <ReviewBlock key={index} block={block} proposal={detail.proposal} />)}</div><small className="improve-answer-meta">{detail.current?.provenance || "legacy/unknown"} · {detail.current?.document_hash || "no document hash"}</small></div><div className="improve-evidence"><h3>Previous gaps and evidence</h3>{detail.findings?.length ? <ul>{detail.findings.map(item => <li key={item}>{item}</li>)}</ul> : <p>No previous findings recorded.</p>}<small>{detail.evidence?.supporting_ids?.join(", ") || "No supporting evidence listed"}</small></div>{detail.proposal && <div className="improve-proposal"><h3>Pending proposal</h3><pre>{JSON.stringify(detail.proposal, null, 2)}</pre></div>}</>}</section></div>
  </section>;
}
