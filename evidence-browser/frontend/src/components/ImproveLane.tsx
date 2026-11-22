import { useEffect, useState } from "react";
import { applyImprove, cancelJob, discardImprove, fetchImprove, fetchImproveSection, fetchJob, submitJob } from "../api";
import { AGENT_CLIS, rememberedAgentCli, rememberAgentCli } from "../agentClis";
import type { ImproveDetail, ImproveSection, ImproveSnapshot, ReviewJob } from "../types";
import { Empty, Loading } from "./ui";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
type ImportedRatingStatus = { assessment_status?: string; quality_status?: string; quality_error?: string };
type ImportedReadiness = { provenance?: string; source_document_hash?: string; rating_status?: ImportedRatingStatus; readiness_reasons?: string[] };
type ImportedSection = ImproveSection & { readiness?: ImportedReadiness; provenance?: string; document_hash?: string; answer_sheet_hash?: string; rating_status?: ImportedRatingStatus };

export function improveStateLabel(state: string): string {
  return ({ "not-started": "Not started", "context-ready": "Context ready", "ready-for-improve": "Ready for Improve", "proposal-ready": "Proposal ready", proposed: "Proposal ready", failed: "Last run failed", interrupted: "Last run interrupted", unavailable: "Unavailable" } as Record<string, string>)[state] || state;
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
    if (operation === "insert_after" || operation === "insert_row") answer = answer.includes(before) ? answer.replace(before, `${before}${after}`) : answer;
    else if (operation === "delete_row") answer = answer.replace(before, "");
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
    answer = operation === "insert_after" || operation === "insert_row" ? answer.replace(before, `${before}${after}`) : operation === "delete_row" ? answer.replace(before, "") : answer.replace(before, after);
  }
  return answer;
}

function rowParts(value: string): string[] { return value.split("|").map(part => part.trim()); }
function sameRow(left: string[], right: string[]): boolean { return left.length === right.length && left.every((cell, index) => cell === right[index]); }

function applyTableEdits(rows: string[][], proposal?: Record<string, unknown> | null): string[][] {
  const edits = (proposal?.edits as Record<string, unknown>[] | undefined) || [];
  let next = rows.map(row => row.slice());
  const cellEdits = edits.filter(edit => !["replace_row", "insert_row", "delete_row"].includes(String(edit.operation || "")) && !(String(edit.operation || "") === "insert_after" && String(edit.before || "").includes("|")));
  next = next.map(row => row.map(cell => applyEdits(cell, { edits: cellEdits })));
  for (const edit of edits) {
    const operation = String(edit.operation || "");
    const before = String(edit.before || "");
    const rowEdit = ["replace_row", "insert_row", "delete_row"].includes(operation) || (operation === "insert_after" && before.includes("|"));
    if (!rowEdit) continue;
    const index = next.findIndex(row => sameRow(row, rowParts(before)));
    if (index < 0) continue;
    if (operation === "delete_row") { next.splice(index, 1); continue; }
    const afterRows = String(edit.after || "").split("\n").filter(row => row.trim()).map(rowParts);
    if (!afterRows.length) continue;
    if (operation === "replace_row") { next.splice(index, 1, afterRows[0]); continue; }
    if (operation === "insert_after" && !sameRow(afterRows[0], rowParts(before))) next.splice(index, 1, afterRows.shift()!);
    if (afterRows.length) next.splice(index + 1, 0, ...afterRows);
  }
  return next;
}

function proposalHasVisibleChange(blocks: { kind?: string; text?: string; rows?: string[][] }[], proposal?: Record<string, unknown> | null): boolean {
  return blocks.some(block => {
    if (block.rows?.length) return JSON.stringify(block.rows) !== JSON.stringify(applyTableEdits(block.rows, proposal));
    return (block.text || "") !== applyEdits(block.text || "", proposal);
  });
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
  const nextRows = applyTableEdits(oldRows, proposal);
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
  const [applying, setApplying] = useState(false);
  const [applyMessage, setApplyMessage] = useState("");
  const [cli, setCli] = useState(rememberedAgentCli());
  const [error, setError] = useState("");

  async function load(preserveSelection = true) {
    try { const next = await fetchImprove(system); setSnapshot(next); const row = preserveSelection && selected ? next.sections.find(item => item.key === selected.key) : undefined; if (row) { setSelected(row); setDetail(await fetchImproveSection(system, row.key)); } else if (!preserveSelection) { setSelected(null); setDetail(null); } }
    catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { setSnapshot(null); setSelected(null); setDetail(null); void load(false); }, [system]);

  async function choose(row: ImproveSection) {
    setSelected(row); setError(""); setApplyMessage("");
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
    setApplying(true);
    setApplyMessage("Applying improvement and re-rating the subsection…");
    setError("");
    try {
      const result = await applyImprove(system, selected.key, cli);
      await load();
      if (result.rating && result.rating.status !== "OK") {
        setError(`Improvement applied. Rating unavailable: ${result.rating.message || result.rating.status}`);
        setApplyMessage("Improvement applied, but the quality rating needs attention.");
      } else {
        setApplyMessage("Improvement applied and the subsection was re-rated.");
      }
    } catch (e) {
      setApplyMessage("");
      setError(`Apply improvement failed: ${(e as Error).message}`);
    } finally {
      setApplying(false);
    }
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
  const selectedImport = selected as ImportedSection;
  const hasProposedChange = proposalHasVisibleChange(reviewBlocks, detail?.proposal);
  return <section className="page improve-page">
    <header className="page-heading"><div><span>Incremental repair · separate from Draft answers</span><h1>Improve answers</h1><p>Inspect the answer already in the document, address named gaps and preserve supported content. Improve never rebuilds a subsection from a fresh card.</p></div><label><span>Agent for improvement</span><select value={cli} onChange={e => setCli(e.target.value)} disabled={running}>{AGENT_CLIS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>{onBack && <button className="quiet" onClick={onBack}>Back to workspace</button>}</header>
    {!selected && error && <p className="desk-error" role="alert">{error}</p>}
    {!selected && job && <div className={`draft-job draft-job-${job.state}`} role="status"><div><b>Improve proposal</b><span>{running ? "Finding a bounded improvement…" : job.state === "succeeded" ? "Proposal ready" : `Stopped: ${job.state}`}</span></div>{running && <button className="quiet" onClick={() => void cancelJob(system, job.id)}>Cancel</button>}</div>}
    <div className={`improve-layout${selected ? " improve-layout-focus" : " improve-layout-landing"}`}><section className="decision-desk"><header><div><h2>Answered subsections</h2><p>{snapshot.eligible_count} eligible · {snapshot.proposal_count} proposal(s) ready</p></div><button className="quiet" onClick={() => void load()}>Refresh</button></header><table className="draft-table"><thead><tr><th>Section</th><th>Improve state</th><th>Quality rating</th><th>Controlled assessment rating</th></tr></thead><tbody>{snapshot.sections.map(row => { const imported = String(row.state) === "answered-imported"; const data = row as ImportedSection; const readiness = data.readiness; const ratingStatus = readiness?.rating_status || data.rating_status; return <tr key={row.key} className={selected?.key === row.key ? "draft-focus" : ""}><td><button className="table-link" disabled={!row.eligible} onClick={() => void choose(row)}><b>{row.number}</b> {row.title}{imported && <small>Imported · {readiness?.provenance || data.provenance || row.improve.provenance || "document"}{readiness?.source_document_hash ? ` · ${readiness.source_document_hash}` : ""}</small>}<small>{row.key}</small></button></td><td>{row.eligible ? improveStateLabel(row.improve.state) : row.improve.reason}</td><td>{row.rating?.latest?.toFixed?.(1) || "—"}{imported && <small>{ratingStatus?.quality_status === "rated" ? "Quality rated" : "Quality unrated"}</small>}</td><td>{imported ? (ratingStatus?.assessment_status === "resolved" ? "Present" : "Missing") : "—"}</td></tr>; })}</tbody></table></section>
      {selected && <section className="decision-desk improve-detail"><header><div className="improve-detail-heading"><button className="quiet improve-back" onClick={() => { setSelected(null); setDetail(null); setError(""); setApplyMessage(""); }}>Back to subsections</button><div><h2>{`${selected.number} ${selected.title}`}</h2><p>{improveStateLabel(selected.improve.state)}</p></div></div><span>{detail?.proposal && <><button className="quiet" disabled={applying} onClick={() => void discard()}>Discard</button><button disabled={applying || !hasProposedChange} onClick={() => void apply()}>{applying ? "Applying…" : hasProposedChange ? "Apply improvement" : "No change to apply"}</button></>}</span><button disabled={running || applying} onClick={() => void findImprovement()}>Find improvement with {AGENT_CLIS.find(c => c.id === cli)?.label || cli}</button></header>{error && <p className="desk-error improve-detail-error" role="alert">{error}</p>}{job && <div className={`draft-job draft-job-${job.state}`} role="status"><div><b>Improve proposal</b><span>{running ? "Finding a bounded improvement…" : job.state === "succeeded" ? "Proposal ready" : `Stopped: ${job.state}`}</span></div>{running && <button className="quiet" onClick={() => void cancelJob(system, job.id)}>Cancel</button>}</div>}{applying && <div className="improve-apply-status improve-apply-working" role="status" aria-live="polite"><span className="improve-spinner" aria-hidden="true" />{applyMessage}</div>}{!applying && applyMessage && <div className="improve-apply-status improve-apply-complete" role="status" aria-live="polite">{applyMessage}</div>}{detail?.proposal && !hasProposedChange && <p className="improve-no-change-note" role="status">No document change is proposed. Generate a new improvement or discard this proposal.</p>}{detail?.status === "UNAVAILABLE" && <Empty title="Not available" text={detail.message || "No answer is present."} />}{detail?.status === "OK" && <><div className="improve-comparison"><header><div><h3>Review the answer change</h3><p>Each question and subsection detail is separated below. Green text is proposed; red text is removed.</p></div><span className={hasProposedChange ? "improve-change-count" : "improve-no-change"}>{hasProposedChange ? "Document change proposed" : "No document change proposed"}</span></header><div className="improve-review-blocks">{reviewBlocks.map((block, index) => <ReviewBlock key={index} block={block} proposal={detail.proposal} />)}</div><small className="improve-answer-meta">{detail.current?.provenance || selectedImport.readiness?.provenance || "legacy/unknown"} · {detail.current?.document_hash || selectedImport.readiness?.source_document_hash || "no document hash"}</small></div><div className="improve-evidence"><h3>Quality guidance</h3>{detail.rating_summary?.latest != null && <p><b>Latest quality rating: {detail.rating_summary.latest.toFixed(1)}</b> · average history {detail.rating_summary.average.toFixed(1)}</p>}{detail.rating_findings?.length ? <ul>{detail.rating_findings.map(item => <li key={item.id}><b>{item.id}</b>: {item.reason}{item.improve?.length ? <ul>{item.improve.map(tip => <li key={tip}>{tip}</li>)}</ul> : null}</li>)}</ul> : <p>No rating findings recorded.</p>}{detail.reader_review && <details><summary>Reader review</summary><pre>{detail.reader_review}</pre></details>}{detail.gap_searches?.length ? <details><summary>Evidence searches</summary><ul>{detail.gap_searches.map((item, i) => <li key={`${item.question}-${i}`}>{item.question}: {item.verdict || item.error || "searched"}</li>)}</ul></details> : null}<small>{detail.evidence?.supporting_ids?.join(", ") || "No supporting evidence listed"}</small></div>{detail.proposal && <div className="improve-proposal"><h3>Pending proposal</h3><pre>{JSON.stringify(detail.proposal, null, 2)}</pre></div>}</>}</section>}
    </div>
  </section>;
}
