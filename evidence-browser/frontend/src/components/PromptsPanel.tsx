import { useEffect, useState } from "react";
import { fetchPromptHistory, fetchPromptPreview, fetchPrompts, resetPrompt, savePrompt, submitJob } from "../api";
import type { PromptInfo, PromptList, PromptPreview, ReviewJob } from "../types";

// The prompts an answer call is built from: one base prompt and one per kind of block. An edit is saved for this
// project only (csa-work/prompts/answer) and Reset goes back to the shared default.
export function PromptsPanel({ system, cli, busy, onJob }: { system: string; cli: string; busy: boolean; onJob: (job: ReviewJob) => void }) {
  const [list, setList] = useState<PromptList | null>(null); const [open, setOpen] = useState(false);
  const [name, setName] = useState("requirement"); const [text, setText] = useState(""); const [message, setMessage] = useState(""); const [error, setError] = useState("");
  const [section, setSection] = useState(""); const [block, setBlock] = useState(""); const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [versions, setVersions] = useState<{ file: string; text: string }[] | null>(null);

  async function load(keep = name) {
    try {
      const data = await fetchPrompts(system); setList(data);
      const current = data.prompts.find(p => p.name === keep) || data.prompts[0]; setName(current.name); setText(current.text);
      if (!section && data.sections[0]) { setSection(data.sections[0].key); setBlock(data.sections[0].blocks[0]?.id || ""); }
    } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { if (open && !list) void load(); }, [open]);
  useEffect(() => { setList(null); setPreview(null); setMessage(""); setError(""); }, [system]);

  const current: PromptInfo | undefined = list?.prompts.find(p => p.name === name);
  const dirty = !!current && text !== current.text;
  const bytes = new TextEncoder().encode(text).length;
  const sec = list?.sections.find(s => s.key === section);

  function pick(next: string) {
    if (dirty && !confirm("Discard the changes you have not saved?")) return;
    const p = list?.prompts.find(x => x.name === next); if (!p) return;
    setName(next); setText(p.text); setMessage(""); setError(""); setVersions(null);
  }
  async function save() {
    if (!current) return; setError(""); setMessage("");
    try { await savePrompt(system, name, text, current.etag); setMessage("Saved for this project."); await load(name); setPreview(null); }
    catch (e) { setError((e as Error).message); }
  }
  async function reset() {
    if (!current || current.source !== "project" || !confirm("Go back to the shared default? Your version is kept in history.")) return;
    setError(""); try { await resetPrompt(system, name); setMessage("Back to the shared default."); await load(name); setPreview(null); } catch (e) { setError((e as Error).message); }
  }
  async function showHistory() { try { setVersions((await fetchPromptHistory(system, name)).versions); } catch (e) { setError((e as Error).message); } }
  async function show() { setError(""); try { setPreview(await fetchPromptPreview(system, section, block)); } catch (e) { setError((e as Error).message); } }
  async function tryBlock() {
    if (!sec || !block) return; setError("");
    if (dirty && !confirm("The editor has unsaved changes. The run uses the saved prompts. Run anyway?")) return;
    try { onJob(await submitJob(system, "answer", sec.number, { cli, blocks: block })); } catch (e) { setError((e as Error).message); }
  }

  return <section className="decision-desk draft-prompts">
    <header><div><h2>Prompts</h2><p>What each answer call is told. One base prompt for every call, plus one for the kind of block it writes. Changes apply to this project only.</p></div>
      <button className="quiet" onClick={() => setOpen(!open)}>{open ? "Hide" : "Edit prompts"}</button></header>
    {open && list && <div className="prompts-body">
      <ul className="prompts-list">{list.prompts.map(p => <li key={p.name}><button className={p.name === name ? "active" : ""} onClick={() => pick(p.name)}><b>{p.title}</b><small>{p.words} words{p.source === "project" ? " · edited for this project" : ""}</small></button></li>)}</ul>
      <div className="prompts-editor">
        {current && <p className="prompts-use">{current.use}{current.required.length ? ` Must keep: ${current.required.map(r => `{{${r}}}`).join(", ")}.` : ""}</p>}
        <textarea value={text} onChange={e => setText(e.target.value)} spellCheck={false} rows={22} aria-label="Prompt text" />
        <div className="prompts-actions">
          <button onClick={() => void save()} disabled={!dirty || bytes > list.max_bytes}>Save for this project</button>
          <button className="quiet" onClick={() => void reset()} disabled={current?.source !== "project"}>Reset to default</button>
          <button className="quiet" onClick={() => void showHistory()}>History</button>
          <span className={bytes > list.max_bytes ? "prompts-over" : ""}>{bytes.toLocaleString()} / {list.max_bytes.toLocaleString()} bytes</span>
        </div>
        {message && <p className="prompts-ok" role="status">{message}</p>}
        {error && <p className="desk-error" role="alert">{error}</p>}
        {versions && <div className="prompts-history"><b>Earlier versions</b>{versions.length ? versions.map(v => <details key={v.file}><summary>{v.file}</summary><pre>{v.text}</pre><button className="quiet" onClick={() => { setText(v.text); setVersions(null); }}>Use this text in the editor</button></details>) : <p>None yet.</p>}</div>}
        <div className="prompts-preview">
          <h3>See one call</h3>
          <div className="prompts-pick">
            <select value={section} onChange={e => { setSection(e.target.value); setBlock(list.sections.find(s => s.key === e.target.value)?.blocks[0]?.id || ""); setPreview(null); }}>{list.sections.map(s => <option key={s.key} value={s.key}>{s.number} {s.title}</option>)}</select>
            <select value={block} onChange={e => { setBlock(e.target.value); setPreview(null); }}>{sec?.blocks.map(b => <option key={b.id} value={b.id}>{b.id} · {b.kind} · {b.label}</option>)}</select>
            <button className="quiet" onClick={() => void show()}>Show the rules for this call</button>
            <button onClick={() => void tryBlock()} disabled={busy || !block}>Try on this block</button>
          </div>
          {preview && <><p>{preview.words.toLocaleString()} words from {preview.sources.map(s => `${s.name}${s.source === "project" ? " (edited)" : ""}`).join(" + ")}. The agent definition and the card are added to this.</p><pre>{preview.text}</pre></>}
        </div>
      </div>
    </div>}
  </section>;
}
