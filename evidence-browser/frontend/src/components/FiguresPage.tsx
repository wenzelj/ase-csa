import { useEffect, useMemo, useState, type ReactElement } from "react";
import { api, fetchJob, submitJob } from "../api";
import type { ReviewJob } from "../types";
import "./figures.css";

/* CSA figures: where the working document needs a figure, the brief (what the figure must show, tied to the
 * section's words and the evidence), the figure drawn now from the current evidence, the fit check against the
 * section's text, and the figure's place in the document. Save writes csa-work/figures/<KEY>; "Put in document"
 * runs `csa figure KEY --place` as a job (tracked change, approve in Word); "Reword with agent" runs the wording
 * agent, whose wording the framework checks before it is used. "Refresh figures" creates and redraws every figure
 * from the latest evidence; the figure design agent designs, builds or reviews a figure (csa figure KEY --design). */

type Req = { id: string; text: string; current_state: string; rating: string };
type Saved = { at?: string; drawn?: string; hash: string; fit?: Record<string, number>; gaps?: number; placed?: { at: string; hash: string; drawing?: string }; docx?: string | null } | null;
type Row = { key: string; number: string; title: string; level: number; status: string; reason: string; profile: string | null;
  archetype: string | null; question?: string; must_show?: string[]; caption?: string; requirements: Req[]; hosts_in_text: string[];
  slot: { placeholder: boolean; caption: string | null } | null; saved: Saved };
type Refreshed = { key: string; number: string; title: string; action: string; placement?: string; message?: string };
type Listing = { state: string; reason?: string; document?: string; rows: Row[]; counts?: Record<string, number>; gaps?: number;
  last_refresh?: { at: string; results: Refreshed[] } | null; refreshed?: Refreshed[] };
type AgentNote = { text: string; at: string };
type Rel = { consumer: string; provider: string; order: number; state: string; side: string; side_reason: string; evidence: string[]; text: string };
type Text = { text: string; by: string };
type Item = { id: string; what: string; status: string; provider?: string; evidence: string[]; section_says: string | null; include: boolean; requirements: string[] };
type Gap = { id: string; what: string; why: string };
type Brief = { purpose: Text; caption: Text; source: Text; items: Item[]; gaps: Gap[]; question?: string; requirements: string[] };
type Check = { level: "ok" | "note" | "flag"; kind: string; text: string; evidence: string[] };
type Detail = { state: string; reason?: string; row: Row; brief: Brief; problems: string[]; fit: { checks: Check[]; counts: Record<string, number> };
  relations: Rel[]; svg: string | null; hash: string | null; print_svg?: string | null;
  print?: { width_mm: number; height_mm: number; fits_page: boolean; min_text_pt: number } | null; notes: string[]; nodes?: number; lines?: number; saved: Saved;
  freshness: "current" | "changed" | "not-saved"; placement: "not-placed" | "placed" | "out-of-date";
  agent?: { design?: AgentNote; review?: AgentNote; build?: AgentNote } };

const STATUS: Record<string, { label: string; tone: string }> = {
  needed: { label: "Figure needed", tone: "need" }, helpful: { label: "Figure helps", tone: "help" },
  placed: { label: "In the document", tone: "done" }, "not-built": { label: "Kind not built yet", tone: "wait" },
  "not-useful": { label: "No figure", tone: "none" },
};
const KIND: Record<string, string> = { A: "System overview", B: "Service dependency", C: "Zones and conduits", D: "Access path", E: "Numbered flow" };
const SIDE: Record<string, string> = { it: "IT (enterprise)", ot: "OT-resident", internet: "Internet", unknown: "Not captured" };
const BY: Record<string, string> = { framework: "framework", agent: "agent, checked", you: "you" };
const ITEM: Record<string, string> = { shown: "Drawn", absent: "Shown as a gap box", gap: "Not captured" };
const FILTERS: { id: string; label: string; match: (s: string) => boolean }[] = [
  { id: "all", label: "All sections", match: () => true },
  { id: "need", label: "Need a figure", match: s => s === "needed" || s === "helpful" || s === "placed" },
  { id: "wait", label: "Not built yet", match: s => s === "not-built" },
  { id: "none", label: "No figure", match: s => s === "not-useful" },
];
const when = (s?: string) => s ? new Date(s).toLocaleString("en-AU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const DONE = ["succeeded", "failed", "cancelled", "interrupted"];

export default function FiguresPage({ system, openEvidenceId }: { system: string; openEvidenceId?: (id: string) => void }) {
  const [list, setList] = useState<Listing | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("need");
  const [key, setKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState("");
  const [job, setJob] = useState<ReviewJob | null>(null);
  const [fit, setFit] = useState(true);
  const [showRefresh, setShowRefresh] = useState(false);

  const loadList = () => api<Listing>(`/api/systems/${system}/figures`).then(l => {
    setList(l);
    setKey(k => k ?? (l.rows.find(r => r.status === "needed") || l.rows[0])?.key ?? null);
  }).catch(e => setError(String(e.message || e)));
  const loadDetail = (k: string) => api<Detail>(`/api/systems/${system}/figures/${k}`).then(setDetail).catch(e => setError(String(e.message || e)));
  useEffect(() => { setList(null); setKey(null); setDetail(null); setError(""); setJob(null); loadList(); }, [system]);
  useEffect(() => { if (key) { setDetail(null); setError(""); loadDetail(key); } }, [system, key]);
  useEffect(() => {                                           // follow a running job, then reload
    if (!job || DONE.includes(job.state)) return;
    const t = setTimeout(async () => {
      try {
        const j = await fetchJob(system, job.id); setJob(j);
        if (DONE.includes(j.state)) { setBusy(""); if (key) await loadDetail(key); await loadList(); }
      } catch (e: any) { setError(String(e.message || e)); setBusy(""); }
    }, 1500);
    return () => clearTimeout(t);
  }, [job?.id, job?.state]);

  const rows = useMemo(() => (list?.rows || []).filter(r => FILTERS.find(f => f.id === filter)!.match(r.status)), [list, filter]);

  async function post(path: string, body?: unknown, what = "") {
    if (!key) return;
    setBusy(what); setError("");
    try {
      const d = await api<Detail>(`/api/systems/${system}/figures/${key}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}) });
      setDetail(d);
      if (d.problems?.length) setError("Not saved: " + d.problems.join("; "));
      await loadList();
    } catch (e: any) { setError(String(e.message || e)); } finally { setBusy(""); }
  }
  async function refreshAll() {
    setBusy("refresh"); setError("");
    try {
      const l = await api<Listing>(`/api/systems/${system}/figures/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      setList(l); setShowRefresh(true);
      if (key) await loadDetail(key);
    } catch (e: any) { setError(String(e.message || e)); } finally { setBusy(""); }
  }
  async function run(operation: string, what: string, options: Record<string, string> = {}) {
    if (!key) return;
    setBusy(what); setError("");
    try {
      const j = await submitJob(system, operation, key, options); setJob(j);
      if (DONE.includes(j.state)) { setBusy(""); await loadDetail(key); await loadList(); }      // finished at once
    } catch (e: any) { setError(String(e.message || e)); setBusy(""); }
  }

  if (error && !list) return <div className="fg"><div className="fg-msg">{error}</div></div>;
  if (!list) return <div className="fg"><p className="fg-muted">Reading the working document…</p></div>;
  if (list.state !== "ready") return <div className="fg"><div className="fg-msg">{list.reason}</div></div>;
  const c = list.counts || {};

  return (
    <div className="fg">
      <header className="fg-head">
        <div>
          <h2>CSA figures</h2>
          <p>Where <b>{list.document}</b> needs a figure, what it must show, and the figure drawn from the current evidence.</p>
        </div>
        <div className="fg-counts">
          <span className="need">{(c.needed || 0) + (c.helpful || 0)} need a figure</span>
          <span className="done">{c.placed || 0} in the document</span>
          <span className="wait">{c["not-built"] || 0} kind not built yet</span>
          <span className="none">{c["not-useful"] || 0} no figure</span>
          {!!list.gaps && <span className="gap">{list.gaps} gap{list.gaps === 1 ? "" : "s"} to Discovery Required</span>}
        </div>
        <div className="fg-refresh">
          <button className="primary" disabled={!!busy} onClick={refreshAll}
            title="Draws every figure the document needs from the latest evidence: creates the ones never saved and redraws the ones that changed. The document is not changed.">
            {busy === "refresh" ? "Drawing from the latest evidence…" : "Refresh figures from the latest evidence"}</button>
          {list.last_refresh && <button className="fg-link" onClick={() => setShowRefresh(!showRefresh)}>
            Last refreshed {when(list.last_refresh.at)}{showRefresh ? " ▴" : " ▾"}</button>}
        </div>
      </header>
      {showRefresh && list.last_refresh && <RefreshSummary r={list.last_refresh} open={k => { setKey(k); setFilter("all"); }} />}
      {error && <div className="fg-msg">{error}<button onClick={() => setError("")}>×</button></div>}
      <div className="fg-body">
        <nav className="fg-list" aria-label="Sections">
          <div className="fg-filters">
            {FILTERS.map(f => <button key={f.id} className={f.id === filter ? "on" : ""} onClick={() => setFilter(f.id)}>{f.label}</button>)}
          </div>
          {rows.map(r => (
            <button key={r.key} className={`fg-item ${r.key === key ? "on" : ""}`} onClick={() => setKey(r.key)}>
              <span className="fg-num">{r.number}</span>
              <span className="fg-title">{r.title}{r.saved && <small>Saved {when(r.saved.at)}{r.saved.fit?.flag ? ` · ${r.saved.fit.flag} to check` : ""}{r.saved.placed ? " · placed" : ""}</small>}</span>
              <span className={`fg-pill ${STATUS[r.status]?.tone}`}>{STATUS[r.status]?.label || r.status}</span>
            </button>
          ))}
          {!rows.length && <p className="fg-muted">No sections in this group.</p>}
        </nav>
        <section className="fg-detail">
          {!detail ? <p className="fg-muted">{key ? "Drawing from the current evidence…" : "Choose a section."}</p>
            : <Panel d={detail} busy={busy} job={job} fit={fit} setFit={setFit} openEvidenceId={openEvidenceId}
                save={() => post("save", {}, "save")} edit={b => post("brief", b, "brief")}
                system={system} place={drawing => run("figure_place", "place", { drawing })} reword={cli => run("figure_wording", "agent", cli ? { cli } : {})}
                designer={(mode, cli) => run("figure_design", "design-" + mode, { mode, cli })} />}
        </section>
      </div>
    </div>
  );
}

const DRAWING_KEY = "csa-figure-drawing";
const readDrawing = (): "picture" | "word" => { try { return localStorage.getItem(DRAWING_KEY) === "word" ? "word" : "picture"; } catch { return "picture"; } };

const ACTION: Record<string, string> = { created: "Created", redrawn: "Redrawn", unchanged: "Unchanged", "not-built": "Kind not built yet", error: "Error" };

function RefreshSummary({ r, open }: { r: { at: string; results: Refreshed[] }; open: (k: string) => void }) {
  const n = (a: string) => r.results.filter(x => x.action === a).length;
  const stale = r.results.filter(x => x.placement === "out-of-date");
  return (
    <div className="fg-box fg-refreshbox">
      <h4>Refreshed {when(r.at)}: {n("created")} created, {n("redrawn")} redrawn, {n("unchanged")} unchanged{n("error") ? `, ${n("error")} failed` : ""}</h4>
      {stale.length > 0 && <p className="fg-warn">{stale.length} figure{stale.length === 1 ? " is" : "s are"} in the document but changed: open {stale.length === 1 ? "it" : "each"} and choose Replace in document.</p>}
      <table className="fg-table"><tbody>{r.results.map(x => (
        <tr key={x.key}><td>{x.number}</td><td><button className="fg-link" onClick={() => open(x.key)}>{x.title}</button></td>
          <td><span className={`fg-act ${x.action}`}>{ACTION[x.action] || x.action}</span></td>
          <td>{x.placement === "out-of-date" ? "In the document, out of date" : x.placement === "placed" ? "In the document" : x.message || ""}</td></tr>))}
      </tbody></table>
    </div>
  );
}

/* The agent's markdown, shown plainly: headings, bullets and paragraphs. */
function Md({ text }: { text: string }) {
  const out: ReactElement[] = []; let list: string[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={out.length}>{list.map((l, i) => <li key={i}>{l}</li>)}</ul>); list = []; } };
  text.split("\n").forEach(line => {
    const t = line.trimEnd();
    if (/^\s*[-*] /.test(t)) { list.push(t.replace(/^\s*[-*] /, "")); return; }
    flush();
    if (/^#{1,6} /.test(t)) out.push(<h5 key={out.length}>{t.replace(/^#+ /, "")}</h5>);
    else if (t.startsWith("```")) return;
    else if (t) out.push(<p key={out.length}>{t}</p>);
  });
  flush();
  return <div className="fg-md">{out}</div>;
}

function AgentBox({ d, busy, run }: { d: Detail; busy: string; run: (mode: string, cli: string) => void }) {
  const [cli, setCli] = useState("claude");
  const [confirm, setConfirm] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const a = d.agent || {};
  const built = !!d.svg;
  useEffect(() => { setConfirm(false); setOpen(null); }, [d.row.key]);
  const note = (mode: "design" | "review" | "build", label: string) => a[mode] && (
    <div className="fg-agentnote">
      <button className="fg-link" onClick={() => setOpen(open === mode ? null : mode)}>{label} ({when(a[mode]!.at)}) {open === mode ? "▴" : "▾"}</button>
      {open === mode && <Md text={a[mode]!.text} />}
    </div>);
  return (
    <div className="fg-box fg-agent">
      <div className="fg-boxhead"><h4>Figure design agent</h4>
        <span className="fg-tools">
          <select value={cli} onChange={e => setCli(e.target.value)} aria-label="Agent CLI"><option>claude</option><option>codex</option><option>evo</option></select>
          {!built && <button disabled={!!busy} onClick={() => run("design", cli)}>{busy === "design-design" ? "Agent designing…" : a.design ? "Design again" : "Design this figure"}</button>}
          {!built && a.design && !confirm && <button className="primary" disabled={!!busy} onClick={() => setConfirm(true)}>{busy === "design-build" ? "Agent building…" : "Build from this design"}</button>}
          {built && <button disabled={!!busy} onClick={() => run("review", cli)}>{busy === "design-review" ? "Agent reviewing…" : "Review with agent"}</button>}
        </span>
      </div>
      <p className="fg-muted">{built
        ? "The agent checks this figure against the design rules (IT, boundary and OT layers, one icon per role, one line per function, readable on A4) and lists each problem with its fix."
        : "This section has no figure the framework can draw yet. The agent works out whether a figure answers the section's question, what the evidence can show, and how to draw it, and writes a design. After you read the design, it can build the new kind of figure into the framework."}
        {" "}It runs in its own window; this page updates when it finishes.</p>
      {confirm && <div className="fg-confirm">
        <span>Building changes the framework: the figure profile, the code that reads the evidence, and tests. It never changes the document.</span>
        <button className="primary" disabled={!!busy} onClick={() => { setConfirm(false); run("build", cli); }}>Build now</button>
        <button onClick={() => setConfirm(false)}>Cancel</button></div>}
      {note("design", "The design")}
      {note("build", "Build report")}
      {note("review", "Review")}
    </div>
  );
}

function Panel({ d, busy, job, fit, setFit, openEvidenceId, save, edit, place, reword, designer, system }: {
  d: Detail; busy: string; job: ReviewJob | null; fit: boolean; setFit: (b: boolean) => void; openEvidenceId?: (id: string) => void;
  save: () => void; edit: (b: Record<string, unknown>) => void; place: (drawing: string) => void; reword: (cli: string) => void;
  designer: (mode: string, cli: string) => void; system: string }) {
  const r = d.row, b = d.brief;
  const [draft, setDraft] = useState<{ purpose: string; caption: string } | null>(null);
  const [cli, setCli] = useState("claude");
  const [view, setView] = useState<"print" | "screen">("print");
  const [drawing, setDrawingState] = useState<"picture" | "word">(readDrawing);
  const setDrawing = (v: "picture" | "word") => { setDrawingState(v); try { localStorage.setItem(DRAWING_KEY, v); } catch { /* per-browser only */ } };
  const placedAs = d.saved?.placed?.drawing === "word" ? "word" : "picture";
  const canPlace = d.freshness === "current" && (d.placement !== "placed" || placedAs !== drawing);
  const fileUrl = (name: string) => `/api/systems/${system}/figures/${r.key}/file/${name}`;
  useEffect(() => { setDraft(null); }, [r.key]);
  const ev = (id: string) => /^E-\d+$/.test(id) && openEvidenceId
    ? <button key={id} className="fg-ev" onClick={() => openEvidenceId(id)}>{id}</button> : <span key={id} className="fg-ev plain">{id}</span>;
  const flags = d.fit.checks.filter(c => c.level === "flag"), notes = d.fit.checks.filter(c => c.level === "note");
  const jobRunning = job && !DONE.includes(job.state);
  return (
    <>
      <div className="fg-dhead">
        <div>
          <h3>{r.number} {r.title}</h3>
          <span className={`fg-pill ${STATUS[r.status]?.tone}`}>{STATUS[r.status]?.label}</span>
          {r.archetype && <span className="fg-kind">{KIND[r.archetype] || r.archetype}</span>}
        </div>
      </div>
      <p className="fg-reason">{r.reason}</p>

      {r.requirements.length > 0 && <div className="fg-box">
        <h4>What the section asks</h4>
        <ul>{r.requirements.map(q => <li key={q.id}><b>{q.id}</b> {q.text} {q.rating && <span className="fg-rating">{q.rating}</span>}</li>)}</ul>
      </div>}

      {d.svg && <div className="fg-box brief">
        <div className="fg-boxhead"><h4>Brief: what the figure must show</h4>
          {!draft && <span className="fg-tools">
            <button onClick={() => setDraft({ purpose: b.purpose.text, caption: b.caption.text })}>Edit wording</button>
            <select value={cli} onChange={e => setCli(e.target.value)} aria-label="Agent CLI"><option>claude</option><option>codex</option><option>evo</option></select>
            <button disabled={!!busy} onClick={() => reword(cli)}>{busy === "agent" ? "Agent working…" : "Reword with agent"}</button>
          </span>}
        </div>
        {draft ? <div className="fg-edit">
          <label>Purpose<textarea value={draft.purpose} onChange={e => setDraft({ ...draft, purpose: e.target.value })} rows={2} /></label>
          <label>Caption<textarea value={draft.caption} onChange={e => setDraft({ ...draft, caption: e.target.value })} rows={2} /></label>
          <span className="fg-tools"><button className="primary" disabled={!!busy} onClick={() => { edit(draft); setDraft(null); }}>Check and keep</button>
            <button onClick={() => setDraft(null)}>Cancel</button></span>
          <small className="fg-muted">The wording may only name hosts, addresses and numbers the figure holds.</small>
        </div> : <dl className="fg-words">
          <dt>Purpose</dt><dd>{b.purpose.text} <small>({BY[b.purpose.by] || b.purpose.by})</small></dd>
          <dt>Caption</dt><dd>{b.caption.text} <small>({BY[b.caption.by] || b.caption.by})</small></dd>
          <dt>Source</dt><dd>{b.source.text}</dd>
        </dl>}
        <table className="fg-table items"><tbody>{b.items.map(i => (
          <tr key={i.id} className={i.include ? "" : "out"}>
            <td><input type="checkbox" checked={i.include} disabled={!!busy || !i.provider} title={i.provider ? "Draw this in the figure" : "Always drawn"}
              onChange={e => edit({ include: { [i.id]: e.target.checked } })} /></td>
            <td><span className={`fg-st ${i.status}`}>{ITEM[i.status] || i.status}</span></td>
            <td>{i.what}{i.section_says && <div className="fg-says">The section says: “{i.section_says}”</div>}</td>
            <td className="fg-evs">{i.evidence.slice(0, 6).map(ev)}{i.evidence.length > 6 && <small> +{i.evidence.length - 6}</small>}</td>
          </tr>))}</tbody></table>
        {b.gaps.length > 0 && <div className="fg-gaps"><b>Not captured: these go to Discovery Required when the figure is saved</b>
          <ul>{b.gaps.map(g => <li key={g.id}>{g.what}</li>)}</ul></div>}
      </div>}

      {d.svg && <>
        <div className="fg-figbar">
          <span className={`fg-fresh ${d.freshness}`}>
            {d.freshness === "current" ? `Saved ${when(d.saved?.drawn || d.saved?.at)} and still matches the evidence`
              : d.freshness === "changed" ? `Saved ${when(d.saved?.drawn || d.saved?.at)}, but the evidence or the brief has changed since`
              : "Drawn now from the evidence, not saved yet"}
          </span>
          <span className={`fg-fresh ${d.placement === "placed" ? "current" : d.placement === "out-of-date" ? "changed" : "not-saved"}`}>
            {d.placement === "placed" ? `In the document as ${placedAs === "word" ? "a Word drawing" : "a picture"} (tracked)`
              : d.placement === "out-of-date" ? "In the document, out of date" : "Not in the document"}
          </span>
          <span className="fg-tools">
            {d.print_svg && <span className="fg-seg">
              <button className={view === "print" ? "on" : ""} onClick={() => setView("print")}>As printed</button>
              <button className={view === "screen" ? "on" : ""} onClick={() => setView("screen")}>Screen view</button></span>}
            {view === "screen" && <button onClick={() => setFit(!fit)}>{fit ? "Actual size" : "Fit to width"}</button>}
            <button className="primary" disabled={!!busy || d.freshness === "current"} onClick={save}>
              {busy === "save" ? "Saving…" : d.freshness === "changed" ? "Save the new version" : d.freshness === "current" ? "Saved" : "Save figure"}
            </button>
            <button className="primary" disabled={!!busy || !canPlace} onClick={() => place(drawing)}
              title="Inserts the figure, caption and source as a tracked change. Accept or reject it in Word.">
              {busy === "place" ? "Putting in document…" : d.placement === "not-placed" ? "Put in document" : "Replace in document"}
            </button>
          </span>
        </div>
        <div className="fg-drawopt">
          <span className="fg-label">Drawing in the document</span>
          <span className="fg-seg">
            <button className={drawing === "picture" ? "on" : ""} onClick={() => setDrawing("picture")}>Picture</button>
            <button className={drawing === "word" ? "on" : ""} onClick={() => setDrawing("word")}>Word drawing (editable)</button>
          </span>
          <small className="fg-muted">{drawing === "word"
            ? "Every zone, card, icon, line and label is a Word shape in one group: anyone can move, recolour or retype it in Word. Lines are not attached to the cards, so move a line with its card. The picture is kept as a fallback for older readers."
            : "The figure goes in as one high-resolution picture. Change it here and put it in again."}</small>
          {d.saved?.docx && d.freshness === "current" && <span className="fg-files">Download:
            <a href={fileUrl("figure.docx")} download>Word file (editable drawing)</a>
            <a href={fileUrl("figure-print.svg")} download>SVG</a>
            <a href={fileUrl("figure.png")} download>PNG</a></span>}
        </div>
        {jobRunning && <div className="fg-note">Running: {job!.operation.replace("figure_", "")} ({job!.state})…</div>}
        {job && DONE.includes(job.state) && job.state !== "succeeded" && <div className="fg-msg">The job {job.state}: {(job.stderr_tail || job.stdout_tail || job.message || "").slice(-400)}</div>}
        {view === "print" && d.print_svg
          ? <div className="fg-paper"><div className="fg-sheet" dangerouslySetInnerHTML={{ __html: d.print_svg }} />
              {d.print && <small className="fg-muted">In the document: {Math.round(d.print.width_mm)} × {Math.round(d.print.height_mm)} mm at the text width; smallest text {d.print.min_text_pt} pt.</small>}</div>
          : <div className={`fg-drawing ${fit ? "fit" : ""}`} dangerouslySetInnerHTML={{ __html: d.svg }} />}
        <p className="fg-caption">Figure: {b.caption.text}</p>
      </>}
      {!d.svg && r.status === "not-built" && <div className="fg-note">This section needs {r.archetype && KIND[r.archetype] ? (/^[AEIOU]/.test(KIND[r.archetype]) ? "an " : "a ") + KIND[r.archetype].toLowerCase() : "a"} figure. Drawing that kind is not built yet, so nothing is drawn.</div>}
      {!d.svg && jobRunning && <div className="fg-note">Running: {job!.operation.replace("figure_", "")} ({job!.state})…</div>}
      {!d.svg && job && DONE.includes(job.state) && job.state !== "succeeded" && <div className="fg-msg">The job {job.state}: {(job.stderr_tail || job.stdout_tail || job.message || "").slice(-400)}</div>}
      <AgentBox d={d} busy={busy} run={designer} />

      {d.svg && <div className="fg-box">
        <h4>Fit check: does the figure say what the section says?</h4>
        {!flags.length && <p className="fg-ok">Nothing in the section's text contradicts the figure.</p>}
        {flags.map((c, i) => <div key={i} className="fg-check flag"><b>Check</b> {c.text} {c.evidence.slice(0, 4).map(ev)}</div>)}
        {notes.map((c, i) => <div key={i} className="fg-check note">{c.text}</div>)}
      </div>}

      {d.relations.length > 0 && <div className="fg-box wide">
        <h4>Every line in the figure, with its evidence</h4>
        <table className="fg-table">
          <thead><tr><th>Vital host</th><th>Takes it from</th><th>Order</th><th>In use</th><th>Provider sits in</th><th>Evidence</th></tr></thead>
          <tbody>{d.relations.map((x, i) => (
            <tr key={i} title={x.text}>
              <td>{x.consumer}</td><td>{x.provider}</td><td>{x.order}</td><td>{x.state === "active" ? "Yes" : "Configured, not in use"}</td>
              <td title={x.side_reason}><span className={`fg-side ${x.side}`}>{SIDE[x.side] || x.side}</span></td>
              <td>{x.evidence.map(ev)}</td>
            </tr>))}</tbody>
        </table>
      </div>}
    </>
  );
}
