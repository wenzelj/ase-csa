import { FormEvent, useEffect, useState } from "react";

type System = { key: string; label: string; project_key: string; available: boolean };
type Summary = {
  label: string; project_key: string; built_at_utc?: string; index_complete: boolean;
  captures: number; current_captures: number; files_by_status: Record<string, number>;
  evidence_rows: number; families: string[];
  coverage: { host: string; families: Record<string, number> }[];
};
type EvidenceRow = Record<string, string>;
type FileRow = {
  file_id: number; rel_path: string; host?: string; ext: string; size: number;
  status: string; reason?: string; source_class: string; current: number;
};
type IndexHit = {
  file_id?: number; source_title: string; source_version: string; page_or_location: string;
  evidence_excerpt: string; rel_path: string; host?: string; source_class: string; superseded: boolean;
};
type SearchStage = { kind: "matrix" | "index"; verdict?: string; matches?: EvidenceRow[]; results?: IndexHit[]; count?: number };
type SearchResponse = { query: string; stages: SearchStage[] };
type TableInfo = { table: string; format: string; rows: number; hosts: number; columns: string[] };
type Preview = {
  kind: string; name: string; rel_path: string; lines?: { number: number; text: string }[];
  highlight?: [number, number]; rows?: string[][]; row_start?: number; highlight_row?: number;
  sheet?: string; sheets?: string[]; pdf_url?: string; raw_url?: string; reason?: string;
};
type Draft = {
  csa_area: string; question: string; claim: string; status: string; source_title: string;
  source_version: string; section: string; page_or_location: string; evidence_excerpt: string;
  inference_reason: string; confidence: string; gap_or_action: string; review_state: string;
};
type View = "overview" | "evidence" | "files" | "tables";

const EMPTY_DRAFT: Draft = {
  csa_area: "", question: "", claim: "", status: "VERIFIED", source_title: "",
  source_version: "", section: "", page_or_location: "", evidence_excerpt: "",
  inference_reason: "", confidence: "high", gap_or_action: "", review_state: "pending",
};

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message || `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data as T;
}

function formatBytes(bytes: number) {
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(1)} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function Status({ value }: { value?: string }) {
  const name = (value || "unknown").toLowerCase().replaceAll("_", " ");
  return <span className={`status status-${name.replaceAll(" ", "-")}`}>{name}</span>;
}

export default function App() {
  const initial = new URLSearchParams(location.search).get("system") || "iamps";
  const [systems, setSystems] = useState<System[]>([]);
  const [system, setSystem] = useState(initial);
  const [view, setView] = useState<View>("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [evidenceRows, setEvidenceRows] = useState<EvidenceRow[]>([]);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [fileTotal, setFileTotal] = useState(0);
  const [fileFacets, setFileFacets] = useState<{ statuses: string[]; extensions: string[]; source_classes: string[] }>({ statuses: [], extensions: [], source_classes: [] });
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftResult, setDraftResult] = useState<Record<string, unknown> | null>(null);
  const [sourceChoices, setSourceChoices] = useState<{ row: EvidenceRow; files: FileRow[] } | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[] | null>(null);
  const [fileFilter, setFileFilter] = useState("");
  const [fileStatus, setFileStatus] = useState("");
  const [fileExt, setFileExt] = useState("");
  const [fileClass, setFileClass] = useState("");
  const [includeHistory, setIncludeHistory] = useState(false);

  useEffect(() => { api<{ systems: System[] }>("/api/systems").then(x => setSystems(x.systems)).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    history.replaceState(null, "", `?system=${system}`);
    setError(""); setSearch(null); setPreview(null); setDraft(null);
    Promise.all([
      api<Summary>(`/api/systems/${system}/summary`),
      api<{ rows: EvidenceRow[] }>(`/api/systems/${system}/evidence?limit=250`),
      api<{ files: FileRow[]; total: number; facets: typeof fileFacets }>(`/api/systems/${system}/files?limit=500`),
      api<{ tables: TableInfo[] }>(`/api/systems/${system}/tables`),
    ]).then(([s, e, f, t]) => { setSummary(s); setEvidenceRows(e.rows); setFiles(f.files); setFileTotal(f.total); setFileFacets(f.facets); setTables(t.tables); })
      .catch(e => setError(e.message));
  }, [system]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ limit: "500", all_captures: String(includeHistory), include_archive: String(includeHistory) });
      if (fileFilter) params.set("q", fileFilter);
      if (fileStatus) params.set("status", fileStatus);
      if (fileExt) params.set("ext", fileExt);
      if (fileClass) params.set("source_class", fileClass);
      api<{ files: FileRow[]; total: number; facets: typeof fileFacets }>(`/api/systems/${system}/files?${params}`)
        .then(x => { setFiles(x.files); setFileTotal(x.total); setFileFacets(x.facets); }).catch(e => setError(e.message));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [includeHistory, system, fileFilter, fileStatus, fileExt, fileClass]);

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (!searchText.trim()) return;
    setBusy(true); setError(""); setPreview(null); setDraft(null);
    try {
      const result = await api<SearchResponse>(`/api/systems/${system}/search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchText }),
      });
      setSearch(result); setView("overview");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function openFile(fileId: number, anchor = "") {
    setError("");
    try {
      const result = await api<Preview>(`/api/systems/${system}/files/${fileId}/preview?anchor=${encodeURIComponent(anchor)}`);
      setPreview(result); setPreviewOpen(true);
    } catch (e) { setError((e as Error).message); }
  }

  async function openEvidence(row: EvidenceRow) {
    try {
      const result = await api<{ sources: FileRow[]; state: string }>(`/api/systems/${system}/evidence/${row.evidence_id}/sources`);
      if (result.sources.length === 1) await openFile(result.sources[0].file_id, row.page_or_location);
      else if (!result.sources.length) setError("The cited source is not available in this discovery index.");
      else setSourceChoices({ row, files: result.sources });
    } catch (e) { setError((e as Error).message); }
  }

  function prepareEvidence(hit: IndexHit) {
    setDraft({ ...EMPTY_DRAFT, question: search?.query || "", source_title: hit.source_title,
      source_version: hit.source_version, page_or_location: hit.page_or_location,
      evidence_excerpt: hit.evidence_excerpt });
    setDraftResult(null);
  }

  async function validateDraft() {
    if (!draft) return;
    setError(""); setDraftResult(null);
    try {
      const result = await api<Record<string, unknown>>(`/api/systems/${system}/evidence-drafts/validate`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
      });
      setDraftResult(result);
    } catch (e) { setError((e as Error).message); }
  }

  async function commitDraft() {
    if (!draft || !draftResult || !confirm("Add this reviewed row to the append-only evidence matrix?")) return;
    try {
      const result = await api<Record<string, unknown>>(`/api/systems/${system}/evidence-drafts/commit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft, confirmed: true }),
      });
      setDraftResult(result);
      const refreshed = await api<{ rows: EvidenceRow[] }>(`/api/systems/${system}/evidence?limit=250`);
      setEvidenceRows(refreshed.rows);
    } catch (e) { setError((e as Error).message); }
  }

  async function openTable(name: string) {
    try {
      const result = await api<{ results: { row: Record<string, unknown> }[] }>(`/api/systems/${system}/tables?table=${encodeURIComponent(name)}&limit=100`);
      setTableRows(result.results.map(x => x.row));
    } catch (e) { setError((e as Error).message); }
  }

  const matrixStage = search?.stages.find(stage => stage.kind === "matrix");
  const indexStage = search?.stages.find(stage => stage.kind === "index");

  return <div className="shell">
    <header className="masthead">
      <div className="product-mark"><span className="mark-lines" aria-hidden="true" /><div><b>CSA evidence</b><span>Source workspace</span></div></div>
      <label className="system-picker">System<select value={system} onChange={e => setSystem(e.target.value)}>
        {systems.map(item => <option key={item.key} value={item.key} disabled={!item.available}>{item.label}</option>)}
      </select></label>
      <form className="global-search" onSubmit={submitSearch}>
        <input value={searchText} onChange={e => setSearchText(e.target.value)} placeholder="Search a host, service, setting or document" aria-label="Search evidence and captured data" />
        <button disabled={busy}>{busy ? "Searching…" : "Search evidence"}</button>
      </form>
    </header>

    <aside className="rail" aria-label="Workspace sections">
      {(["overview", "evidence", "files", "tables"] as View[]).map(item =>
        <button key={item} className={view === item ? "active" : ""} onClick={() => { setView(item); setSearch(null); }}>
          {item === "files" ? "Data library" : item[0].toUpperCase() + item.slice(1)}
        </button>)}
      <div className="rail-note"><span className={summary?.index_complete ? "lamp good" : "lamp"} />
        {summary?.index_complete ? "Index ready" : "Index incomplete"}<small>{summary?.built_at_utc?.replace("T", " ").replace("Z", " UTC")}</small></div>
    </aside>

    <main className="workspace">
      {error && <div className="error" role="alert"><b>Could not complete that action.</b><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
      {search ? <SearchDesk matrix={matrixStage} index={indexStage} openFile={openFile} openEvidence={openEvidence} prepareEvidence={prepareEvidence} /> :
       view === "overview" ? <Overview summary={summary} /> :
       view === "evidence" ? <EvidenceLedger rows={evidenceRows} openEvidence={openEvidence} /> :
       view === "files" ? <DataLibrary files={files} total={fileTotal} facets={fileFacets} filter={fileFilter} setFilter={setFileFilter} status={fileStatus} setStatus={setFileStatus} ext={fileExt} setExt={setFileExt} sourceClass={fileClass} setSourceClass={setFileClass} history={includeHistory} setHistory={setIncludeHistory} openFile={openFile} /> :
       <Tables tables={tables} rows={tableRows} openTable={openTable} />}
    </main>

    {preview && <SourceReader preview={preview} open={previewOpen} close={() => setPreviewOpen(false)} />}
    {draft && <DraftPanel draft={draft} setDraft={setDraft} result={draftResult} validate={validateDraft} commit={commitDraft} close={() => setDraft(null)} />}
    {sourceChoices && <SourceChooser row={sourceChoices.row} files={sourceChoices.files} close={() => setSourceChoices(null)} choose={file => { setSourceChoices(null); openFile(file.file_id, sourceChoices.row.page_or_location); }} />}
  </div>;
}

function Overview({ summary }: { summary: Summary | null }) {
  if (!summary) return <Loading />;
  return <section className="page">
    <div className="page-heading"><div><h1>What this assessment can see</h1><p>Current capture coverage by host and evidence family. A blank cell means the index has no current file classified for that area.</p></div>
      <dl className="context-strip"><div><dt>Current captures</dt><dd>{summary.current_captures}</dd></div><div><dt>Evidence rows</dt><dd>{summary.evidence_rows}</dd></div><div><dt>Indexed files</dt><dd>{summary.files_by_status.indexed || 0}</dd></div></dl></div>
    <div className="coverage-wrap"><table className="coverage"><thead><tr><th>Host or source</th>{summary.families.map(f => <th key={f}>{f}</th>)}</tr></thead>
      <tbody>{summary.coverage.map(row => <tr key={row.host}><th>{row.host}</th>{summary.families.map(f => <td key={f} className={row.families[f] ? "has-data" : ""}>{row.families[f] || ""}</td>)}</tr>)}</tbody></table></div>
    <div className="index-ledger"><h2>Index ledger</h2>{Object.entries(summary.files_by_status).map(([key, value]) => <div key={key}><Status value={key} /><span>{value.toLocaleString()} files</span></div>)}</div>
  </section>;
}

function SearchDesk({ matrix, index, openFile, openEvidence, prepareEvidence }: {
  matrix?: SearchStage; index?: SearchStage; openFile: (id: number, anchor?: string) => void;
  openEvidence: (row: EvidenceRow) => void; prepareEvidence: (hit: IndexHit) => void;
}) {
  return <section className="page search-page">
    <div className="page-heading"><div><h1>Search path</h1><p>The matrix was checked first. Captured data is searched only when the matrix does not settle the question.</p></div></div>
    <div className="search-thread">
      <div className="stage"><div className="stage-marker">1</div><div className="stage-body"><div className="stage-title"><h2>Evidence matrix</h2><Status value={matrix?.verdict} /></div>
        {!matrix?.matches?.length ? <p className="empty">No matrix row answered this search.</p> : matrix.matches.map(row => <button className="evidence-row" key={row.evidence_id} onClick={() => openEvidence(row)}>
          <span className="evidence-id">{row.evidence_id}</span><Status value={row.status} /><strong>{row.claim}</strong><small>{row.source_title} · {row.page_or_location}</small></button>)}</div></div>
      <div className={`stage ${index ? "" : "muted"}`}><div className="stage-marker">2</div><div className="stage-body"><div className="stage-title"><h2>Discovery index</h2>{index ? <span>{index.results?.length || 0} results</span> : <span>Not searched</span>}</div>
        {!index ? <p className="empty">The matrix likely answers the question, so the framework stopped here.</p> : !index.results?.length ? <p className="empty">No indexed source matched. Check the data library for unindexed file types and capture gaps.</p> : index.results.map((hit, i) => <article className="index-result" key={`${hit.rel_path}-${i}`}>
          <div><span className="result-source">{hit.host || "Document source"}</span>{hit.superseded && <Status value="superseded" />}</div>
          <p>{hit.evidence_excerpt}</p><small>{hit.rel_path}<br />{hit.page_or_location}</small>
          <div className="row-actions"><button disabled={!hit.file_id} onClick={() => hit.file_id && openFile(hit.file_id, hit.page_or_location)}>Read source</button><button className="quiet" onClick={() => prepareEvidence(hit)}>Prepare evidence row</button></div>
        </article>)}</div></div>
    </div>
  </section>;
}

function EvidenceLedger({ rows, openEvidence }: { rows: EvidenceRow[]; openEvidence: (row: EvidenceRow) => void }) {
  const [query, setQuery] = useState("");
  const visible = rows.filter(row => !query || `${row.evidence_id} ${row.claim} ${row.question} ${row.source_title}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="page"><div className="page-heading"><div><h1>Evidence ledger</h1><p>Atomic claims in the append-only matrix. Open a row to trace it back to its indexed source.</p></div><input className="filter" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter evidence" /></div>
    <div className="ledger-head"><span>Evidence</span><span>Status</span><span>Claim and source</span></div>
    <div className="ledger">{visible.map(row => <button key={row.evidence_id} onClick={() => openEvidence(row)}><span className="evidence-id">{row.evidence_id}</span><span><Status value={row.status} /><Status value={row.review_state} /></span><span><strong>{row.claim}</strong><small>{row.source_title} · {row.page_or_location}</small></span></button>)}</div>
  </section>;
}

function DataLibrary({ files, total, facets, filter, setFilter, status, setStatus, ext, setExt, sourceClass, setSourceClass, history, setHistory, openFile }: { files: FileRow[]; total: number; facets: { statuses: string[]; extensions: string[]; source_classes: string[] }; filter: string; setFilter: (v: string) => void; status: string; setStatus: (v: string) => void; ext: string; setExt: (v: string) => void; sourceClass: string; setSourceClass: (v: string) => void; history: boolean; setHistory: (v: boolean) => void; openFile: (id: number) => void }) {
  return <section className="page"><div className="page-heading"><div><h1>Data library</h1><p>Files known to the discovery index, including material that could not be searched.</p></div><div className="file-controls"><input className="filter" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter path or host" /><label><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)} /> Include superseded and archived</label></div></div>
    <div className="facet-bar"><label>Index state<select value={status} onChange={e => setStatus(e.target.value)}><option value="">All states</option>{facets.statuses.map(x => <option key={x}>{x}</option>)}</select></label><label>File type<select value={ext} onChange={e => setExt(e.target.value)}><option value="">All types</option>{facets.extensions.map(x => <option key={x}>{x || "plain text"}</option>)}</select></label><label>Source class<select value={sourceClass} onChange={e => setSourceClass(e.target.value)}><option value="">All classes</option>{facets.source_classes.map(x => <option key={x}>{x}</option>)}</select></label><span>Showing {files.length.toLocaleString()} of {total.toLocaleString()}</span></div>
    <div className="file-list"><div className="file-head"><span>Source</span><span>Type</span><span>Index state</span><span>Size</span></div>{files.map(file => <button key={file.file_id} onClick={() => openFile(file.file_id)}><span><strong>{file.rel_path.split("/").at(-1)}</strong><small>{file.host || "Project document"}<br />{file.rel_path}</small></span><code>{file.ext || "text"}</code><span><Status value={file.status} /><small>{file.reason}</small></span><span>{formatBytes(file.size)}</span></button>)}</div>
  </section>;
}

function Tables({ tables, rows, openTable }: { tables: TableInfo[]; rows: Record<string, unknown>[] | null; openTable: (name: string) => void }) {
  const columns = rows?.length ? Object.keys(rows[0]) : [];
  return <section className="page"><div className="page-heading"><div><h1>Structured tables</h1><p>Cross-host views extracted from repeated discovery files. Host counts expose the coverage boundary of each table.</p></div></div>
    <div className="table-browser"><div className="table-index">{tables.map(t => <button key={t.table} onClick={() => openTable(t.table)}><strong>{t.table.replaceAll("_", " ")}</strong><span>{t.rows.toLocaleString()} rows · {t.hosts} hosts</span><small>{t.columns.slice(0, 5).join(", ")}</small></button>)}</div>
      <div className="table-data">{!rows ? <p className="empty">Choose a table to inspect its first 100 rows.</p> : !rows.length ? <p className="empty">This table has no rows in the current scope.</p> : <div className="grid-scroll"><table><thead><tr>{columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(c => <td key={c}>{String(row[c] ?? "")}</td>)}</tr>)}</tbody></table></div>}</div></div>
  </section>;
}

function SourceReader({ preview, open, close }: { preview: Preview; open: boolean; close: () => void }) {
  return <aside className={`reader ${open ? "open" : ""}`} aria-label="Source reader"><div className="reader-head"><div><strong>{preview.name}</strong><small>{preview.rel_path}</small></div><button onClick={close} aria-label="Close source reader">×</button></div>
    <div className="reader-tools">{preview.pdf_url && <a href={preview.pdf_url} target="_blank">Open rendered original</a>}{preview.raw_url && <a href={preview.raw_url} target="_blank">Open original</a>}</div>
    <div className="reader-body">{preview.kind === "image" && preview.raw_url ? <img src={preview.raw_url} alt={preview.name} /> : preview.rows ? <table className="sheet"><tbody>{preview.rows.map((row, i) => <tr className={preview.row_start && i + preview.row_start === preview.highlight_row ? "highlight" : ""} key={i}><th>{(preview.row_start || 1) + i}</th>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table> : preview.lines ? <div className="source-lines">{preview.lines.map(line => <div key={line.number} className={preview.highlight && line.number >= preview.highlight[0] && line.number <= preview.highlight[1] ? "highlight" : ""}><span>{line.number}</span><code>{line.text || " "}</code></div>)}</div> : <div className="unsupported"><h2>Preview unavailable</h2><p>{preview.reason || "This binary format cannot be safely rendered in the browser."}</p>{preview.raw_url && <a href={preview.raw_url} target="_blank">Open original file</a>}</div>}</div>
  </aside>;
}

function DraftPanel({ draft, setDraft, result, validate, commit, close }: { draft: Draft; setDraft: (d: Draft) => void; result: Record<string, unknown> | null; validate: () => void; commit: () => void; close: () => void }) {
  const set = (key: keyof Draft, value: string) => setDraft({ ...draft, [key]: value });
  return <div className="scrim"><section className="draft-panel" role="dialog" aria-modal="true" aria-labelledby="draft-title"><header><div><h2 id="draft-title">Prepare evidence row</h2><p>Review the source wording, then state one reusable claim.</p></div><button onClick={close} aria-label="Close evidence draft">×</button></header>
    <div className="draft-grid"><label>CSA area<input value={draft.csa_area} onChange={e => set("csa_area", e.target.value)} placeholder="network_and_connectivity" /></label><label>Status<select value={draft.status} onChange={e => set("status", e.target.value)}>{["VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND"].map(x => <option key={x}>{x}</option>)}</select></label>
      <label className="wide">Question<input value={draft.question} onChange={e => set("question", e.target.value)} /></label><label className="wide">Atomic claim<textarea value={draft.claim} onChange={e => set("claim", e.target.value)} rows={3} /></label>
      <label className="wide">Source title<input value={draft.source_title} onChange={e => set("source_title", e.target.value)} /></label><label>Source version<input value={draft.source_version} onChange={e => set("source_version", e.target.value)} /></label><label>Location<input value={draft.page_or_location} onChange={e => set("page_or_location", e.target.value)} /></label>
      <label className="wide">Exact supporting excerpt<textarea value={draft.evidence_excerpt} onChange={e => set("evidence_excerpt", e.target.value)} rows={4} /></label><label>Confidence<select value={draft.confidence} onChange={e => set("confidence", e.target.value)}>{["", "high", "medium", "low"].map(x => <option key={x} value={x}>{x || "Not set"}</option>)}</select></label><label>Section<input value={draft.section} onChange={e => set("section", e.target.value)} /></label>
      <label className="wide">Inference reason<input value={draft.inference_reason} onChange={e => set("inference_reason", e.target.value)} /></label><label className="wide">Gap or action<input value={draft.gap_or_action} onChange={e => set("gap_or_action", e.target.value)} /></label></div>
    {result && <pre className="validation-result">{JSON.stringify(result, null, 2)}</pre>}
    <footer><button className="quiet" onClick={close}>Cancel</button><button onClick={validate}>Validate draft</button><button className="commit" disabled={!result || result.status !== "DRY_RUN"} onClick={commit}>Add to evidence matrix</button></footer>
  </section></div>;
}

function SourceChooser({ row, files, choose, close }: { row: EvidenceRow; files: FileRow[]; choose: (file: FileRow) => void; close: () => void }) {
  return <div className="scrim"><section className="source-chooser" role="dialog" aria-modal="true" aria-labelledby="source-choice-title">
    <header><div><h2 id="source-choice-title">Choose the cited source</h2><p>{row.evidence_id} names files found in more than one capture. Select the source you want to inspect.</p></div><button onClick={close} aria-label="Close source choices">×</button></header>
    <div>{files.map(file => <button key={file.file_id} onClick={() => choose(file)}><strong>{file.rel_path.split("/").at(-1)}</strong><span>{file.host || "Project document"}</span><small>{file.rel_path}</small></button>)}</div>
  </section></div>;
}

function Loading() { return <div className="loading">Reading the evidence index…</div>; }
